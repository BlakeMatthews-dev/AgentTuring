"""Conduit — the request pipeline through which all requests flow.

Every request enters Stronghold through the Conduit. It orchestrates:
1. Intent classification (what does the user want?)
2. Ambiguity resolution (is the request clear enough?)
3. Model selection (which LLM should handle this?)
4. Quota pre-check (can we afford this request?)
5. Sufficiency analysis (does the request have enough detail?)
6. Agent dispatch (route to the right specialist)
7. Response formatting (OpenAI-compatible output)

The Conduit never executes tasks directly — it decides and delegates.
When it can't decide, it routes to the Arbiter agent for clarification.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from stronghold.types.model import ModelConfig, ProviderConfig
from stronghold.types.reactor import Event

if TYPE_CHECKING:
    from stronghold.container import Container

logger = logging.getLogger("stronghold.conduit")

# Words that signal consent in response to a data-sharing question.
_CONSENT_AFFIRMATIVE = frozenset(
    {
        "yes",
        "yeah",
        "sure",
        "ok",
        "okay",
        "fine",
        "allow",
        "yep",
        "yup",
        "y",
        "absolutely",
        "go",
    }
)


class Conduit:
    """The request pipeline — all requests flow through here.

    Holds no state except session→agent stickiness mapping.
    All dependencies are accessed through the Container.
    """

    _MAX_STICKY_SESSIONS = 10_000  # Evict oldest entries when exceeded

    def __init__(self, container: Container) -> None:
        self._c = container
        self._session_agents: dict[str, str] = {}
        self._session_consents: dict[str, set[str]] = {}
        self._consent_pending: dict[str, str] = {}
        self._session_lock = asyncio.Lock()

    def _fallback_agent_name(self, preferred: str | None = None) -> str:
        """Resolve a usable agent name even if a configured agent is missing."""
        agents = self._c.agents
        if preferred and preferred in agents:
            return preferred
        if "arbiter" in agents:
            return "arbiter"
        if "default" in agents:
            return "default"
        for name in agents:
            return name
        raise RuntimeError("No agents are loaded in Stronghold")

    def _fallback_agent(self, preferred: str | None = None) -> Any:
        """Resolve an agent object with graceful fallback semantics."""
        name = self._fallback_agent_name(preferred)
        if preferred == "arbiter" and name != "arbiter":
            logger.warning("Arbiter agent missing; falling back to '%s'", name)
        return self._c.agents[name]

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Cheap token estimate for preflight coin-budget checks."""
        chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                chars += len(content)
            elif isinstance(content, list):
                chars += sum(
                    len(str(part.get("text", "")))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
        return max(chars // 4, 1)

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        status_callback: Any = None,
    ) -> dict[str, Any]:
        """Route a request through the pipeline to the right agent.

        This is the ONLY way requests should reach an LLM. Nothing calls
        LiteLLM directly.

        Args:
            auth: AuthContext from the authenticated request. Required.

        Raises:
            TypeError: If auth is None or not an AuthContext instance.
            QuotaExhaustedError: If all providers are at 100%+ usage.
        """
        import time as _time

        from stronghold.types.auth import AuthContext

        if auth is None or not isinstance(auth, AuthContext):
            logger.error(
                "route_request called without valid AuthContext (got %s). "
                "All callers must provide an explicit AuthContext.",
                type(auth).__name__,
            )
            raise TypeError(
                "route_request requires an AuthContext instance — "
                f"got {type(auth).__name__}. "
                "Pass an explicit AuthContext; SYSTEM_AUTH fallback has been removed."
            )

        _start = _time.monotonic()
        c = self._c  # shorthand

        async def _status(msg: str) -> None:
            if status_callback:
                await status_callback(msg)

        # ── 1. Create trace ──
        trace = c.tracer.create_trace(
            user_id=auth.user_id,
            session_id=session_id or "",
            name="route_request",
        )

        # ── 2. Classify intent ──
        await _status("Classifying intent...")
        with trace.span("conduit.classify") as cs:
            if intent_hint and intent_hint in c.config.task_types:
                from stronghold.types.intent import Intent

                user_text = ""
                for m in reversed(messages):
                    if m.get("role") == "user":
                        user_text = str(m.get("content", ""))
                        break
                intent = Intent(
                    task_type=intent_hint,
                    classified_by="hint",
                    user_text=user_text,
                )
                cs.set_output({"task_type": intent_hint, "classified_by": "hint"})
            else:
                intent = await c.classifier.classify(messages, c.config.task_types)
                cs.set_output(
                    {
                        "task_type": intent.task_type,
                        "classified_by": intent.classified_by,
                        "complexity": intent.complexity,
                        "priority": intent.priority,
                    }
                )

            # Check ambiguity
            from stronghold.classifier.engine import is_ambiguous
            from stronghold.classifier.keyword import score_keywords

            raw_scores = score_keywords(intent.user_text, c.config.task_types)
            if is_ambiguous(raw_scores) and not intent_hint:
                arbiter_agent = self._fallback_agent("arbiter")
                response = await arbiter_agent.handle(messages, auth, session_id=session_id)
                return self._build_response(
                    response_id="stronghold-clarify",
                    model=arbiter_agent.identity.name,
                    content=response.content,
                    routing={
                        "intent": {
                            "task_type": "clarify",
                            "scores": raw_scores,
                            "classified_by": "ambiguous",
                        },
                        "agent": arbiter_agent.identity.name,
                        "reason": f"ambiguous: {raw_scores}",
                    },
                )

        trace.update({"task_type": intent.task_type, "classified_by": intent.classified_by})

        # ── 3. Reactor: post-classify event ──
        c.reactor.emit(
            Event(
                "post_classify",
                {
                    "task_type": intent.task_type,
                    "complexity": intent.complexity,
                    "priority": intent.priority,
                    "classified_by": intent.classified_by,
                    "user_id": auth.user_id,
                    "session_id": session_id or "",
                },
            )
        )

        # ── 4. Session stickiness ──
        target_agent_name = c.intent_registry.get_agent_for_intent(intent.task_type)

        if session_id and not target_agent_name and not intent_hint:
            async with self._session_lock:
                sticky_agent = self._session_agents.get(session_id)
                if sticky_agent and sticky_agent in c.agents:
                    target_agent_name = sticky_agent

        # ── 4b. Data sharing consent resolution ──
        if session_id and session_id in self._consent_pending:
            pending_provider = self._consent_pending.pop(session_id)
            user_text = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    user_text = str(m.get("content", "")).strip().lower()
                    break
            first_word = user_text.split()[0] if user_text else ""
            if first_word in _CONSENT_AFFIRMATIVE or user_text in _CONSENT_AFFIRMATIVE:
                if session_id not in self._session_consents:
                    self._session_consents[session_id] = set()
                self._session_consents[session_id].add(pending_provider)
                logger.info(
                    "Data sharing consent granted: session=%s provider=%s",
                    session_id,
                    pending_provider,
                )

        # ── 5. Quota pre-check ──
        _prov_fields = {f.name for f in ProviderConfig.__dataclass_fields__.values()}
        providers_cfg: dict[str, ProviderConfig] = {
            k: ProviderConfig(**{fk: fv for fk, fv in v.items() if fk in _prov_fields})
            if isinstance(v, dict) else v  # type: ignore[arg-type]
            for k, v in c.config.providers.items()
        }

        _any_available = False
        for prov_name, prov_cfg in providers_cfg.items():
            if prov_cfg.status != "active":
                continue
            has_paygo = (
                prov_cfg.overage_cost_per_1k_input > 0 or prov_cfg.overage_cost_per_1k_output > 0
            )
            if has_paygo:
                _any_available = True
                break
            usage_pct = await c.quota_tracker.get_usage_pct(
                prov_name,
                prov_cfg.billing_cycle,
                prov_cfg.free_tokens,
            )
            if usage_pct < 1.0:
                _any_available = True
                break

        if not _any_available:
            from stronghold.types.errors import QuotaExhaustedError

            logger.warning(
                "Quota pre-check: all providers at 100%%+ usage, rejecting (user=%s, task=%s)",
                auth.user_id,
                intent.task_type,
            )
            raise QuotaExhaustedError(
                "All providers are at or above 100% quota usage. "
                "Request rejected to prevent cost overrun. "
                "Try again next billing cycle or contact an admin."
            )

        # ── 5b. Filter data-sharing providers ──
        _consented = self._session_consents.get(session_id or "", set())
        routable_providers: dict[str, ProviderConfig] = {
            k: v for k, v in providers_cfg.items() if not v.data_sharing or k in _consented
        }

        # ── 6. Model selection ──
        agent_display = target_agent_name or "default"
        await _status(f"Routing to {agent_display.title()}...")
        with trace.span("conduit.route") as rs:
            rs.set_input(
                {
                    "task_type": intent.task_type,
                    "agent": target_agent_name or "default",
                }
            )
            _model_fields = {f.name for f in ModelConfig.__dataclass_fields__.values()}
            models: dict[str, ModelConfig] = {
                k: ModelConfig(**{fk: fv for fk, fv in v.items() if fk in _model_fields})
                if isinstance(v, dict) else v  # type: ignore[arg-type]
                for k, v in c.config.models.items()
            }
            providers = routable_providers
            try:
                from stronghold.types.errors import RoutingError

                selection = c.router.select(intent, models, providers, c.config.routing)
                model_to_use = selection.litellm_id
                best = selection.candidates[0] if selection.candidates else None
                rs.set_output(
                    {
                        "model": model_to_use,
                        "provider": selection.provider,
                        "score": selection.score,
                        "quality": best.quality if best else 0.0,
                        "effective_cost": best.effective_cost if best else 0.0,
                        "usage_pct": best.usage_pct if best else 0.0,
                        "tier": best.tier if best else "unknown",
                        "reason": selection.reason,
                        "candidates_count": len(selection.candidates),
                    }
                )
            except RoutingError:
                logger.warning("Router selection failed, using fallback", exc_info=True)
                selection = None
                model_to_use = next(
                    (
                        str(v.get("litellm_id", k)) if isinstance(v, dict) else v.litellm_id
                        for k, v in c.config.models.items()
                    ),
                    "auto",
                )
                rs.set_output({"model": model_to_use, "reason": "fallback"})

        # ── 6b. Data sharing consent check ──
        # If a data-sharing provider would have scored higher, ask consent.
        _ds_unconsented = {
            k
            for k, v in providers_cfg.items()
            if v.data_sharing and v.status == "active" and k not in _consented
        }
        if _ds_unconsented and session_id:
            try:
                full_selection = c.router.select(intent, models, providers_cfg, c.config.routing)
            except Exception:
                full_selection = None

            if (
                full_selection
                and full_selection.provider in _ds_unconsented
                and (selection is None or full_selection.score > selection.score)
            ):
                ds_cfg = providers_cfg[full_selection.provider]
                notice = ds_cfg.data_sharing_notice or (
                    f"The {full_selection.provider} provider shares your API data "
                    "for model training."
                )
                self._consent_pending[session_id] = full_selection.provider

                arbiter_agent = self._fallback_agent("arbiter")
                consent_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Before answering the user's question, ask a brief "
                            "data sharing consent question. Keep it natural and "
                            "conversational.\n\n"
                            f"Provider: {full_selection.provider}\n"
                            f"Notice: {notice}\n\n"
                            "Ask whether they are OK with this provider seeing "
                            "their request data (for better quality/speed), or "
                            "if they prefer a privacy-respecting alternative.\n\n"
                            "Do NOT fulfill the original request yet."
                        ),
                    },
                    *messages,
                ]
                response = await arbiter_agent.handle(
                    consent_messages,
                    auth,
                    session_id=session_id,
                )
                return self._build_response(
                    response_id="stronghold-consent-required",
                    model=arbiter_agent.identity.name,
                    content=response.content,
                    routing={
                        "intent": {
                            "task_type": intent.task_type,
                            "classified_by": "consent_required",
                        },
                        "agent": arbiter_agent.identity.name,
                        "provider": full_selection.provider,
                        "reason": (f"data_sharing_consent_required: {full_selection.provider}"),
                    },
                )

        # ── 7. Sufficiency check ──
        estimated_input_tokens = self._estimate_tokens(messages)
        estimated_output_tokens = max(estimated_input_tokens, 256)
        if getattr(c, "coin_ledger", None):
            await c.coin_ledger.ensure_can_afford(
                org_id=auth.org_id,
                team_id=auth.team_id,
                user_id=auth.user_id,
                model_used=model_to_use,
                provider=selection.provider if selection else "",
                input_tokens=estimated_input_tokens,
                output_tokens=estimated_output_tokens,
            )

        if session_id:
            async with self._session_lock:
                is_sticky_followup = (
                    session_id in self._session_agents
                    and self._session_agents[session_id] == target_agent_name
                )
        else:
            is_sticky_followup = False

        if target_agent_name and target_agent_name in c.agents:
            from stronghold.agents.request_analyzer import (
                analyze_request_sufficiency,
            )

            always_clarify = {"creative"}

            if not is_sticky_followup:
                if intent.task_type in always_clarify:
                    from stronghold.agents.request_analyzer import (
                        MissingDetail,
                        SufficiencyResult,
                    )

                    sufficiency = SufficiencyResult(
                        sufficient=False,
                        confidence=0.0,
                        missing=[
                            MissingDetail(
                                "what",
                                "What kind of content? (e.g., email, story, blog post, poem)",
                            ),
                            MissingDetail(
                                "where",
                                "Who is the audience? (e.g., a client, your team, social media)",
                            ),
                            MissingDetail(
                                "how",
                                "What tone or style? (e.g., formal, casual, persuasive, heartfelt)",
                            ),
                            MissingDetail(
                                "context",
                                "What topic or theme? Any specific points to include?",
                            ),
                        ],
                    )
                else:
                    sufficiency = analyze_request_sufficiency(
                        intent.user_text,
                        task_type=intent.task_type,
                    )
            else:
                sufficiency = None

            if sufficiency and not sufficiency.sufficient:
                missing_qs = "\n".join(f"- {m.question}" for m in sufficiency.missing)
                guided_messages = [
                    {
                        "role": "system",
                        "content": (
                            "The user's request needs more detail before you can proceed. "
                            "Do NOT attempt to fulfill the request yet. Instead, ask the "
                            "following clarifying questions in a friendly, conversational "
                            "way. Frame them as choices where possible.\n\n"
                            f"Missing details:\n{missing_qs}\n\n"
                            "Keep it brief — just ask the questions, don't write the content."
                        ),
                    },
                    *messages,
                ]
                arbiter_agent = self._fallback_agent("arbiter")
                response = await arbiter_agent.handle(
                    guided_messages,
                    auth,
                    session_id=session_id,
                    model_override=model_to_use,
                )

                if session_id and target_agent_name:
                    async with self._session_lock:
                        self._session_agents[session_id] = target_agent_name

                return self._build_response(
                    response_id="stronghold-needs-detail",
                    model=arbiter_agent.identity.name,
                    content=response.content,
                    routing={
                        "intent": {
                            "task_type": intent.task_type,
                            "classified_by": "needs_detail",
                        },
                        "agent": arbiter_agent.identity.name,
                        "reason": (
                            f"insufficient detail: {[m.category for m in sufficiency.missing]}"
                        ),
                        "missing": missing_qs,
                    },
                )

            # Sufficient — filter context and route to specialist
            agent = c.agents[target_agent_name]
            from stronghold.agents.context_filter import extract_task_context

            messages = extract_task_context(messages, task_type=intent.task_type)
        else:
            agent = self._fallback_agent("arbiter")

        # ── 8. Save session stickiness ──
        if session_id and agent.identity.name != "arbiter":
            async with self._session_lock:
                self._session_agents[session_id] = agent.identity.name
                # Evict oldest entries when map grows too large
                if len(self._session_agents) > self._MAX_STICKY_SESSIONS:
                    excess = len(self._session_agents) - self._MAX_STICKY_SESSIONS
                    for old_key in list(self._session_agents)[:excess]:
                        del self._session_agents[old_key]

        # Build fallback model list
        fallback_models: list[str] = []
        if selection and selection.candidates:
            fallback_models = [
                cand.litellm_id
                for cand in selection.candidates[1:4]
                if cand.litellm_id != model_to_use
            ]
        if fallback_models:
            logger.info("Fallback models: %s", fallback_models)
        self._c.llm._fallback_models = fallback_models  # type: ignore[attr-defined]

        # ── 9. Reactor: pre-agent event ──
        c.reactor.emit(
            Event(
                "pre_agent",
                {
                    "agent": agent.identity.name,
                    "model": model_to_use,
                    "task_type": intent.task_type,
                    "user_id": auth.user_id,
                    "session_id": session_id or "",
                },
            )
        )

        # ── 10. Dispatch to agent ──
        await _status(f"{agent.identity.name.title()} is working...")
        try:
            response = await agent.handle(
                messages,
                auth,
                session_id=session_id,
                model_override=model_to_use,
                status_callback=status_callback,
            )
        except Exception:
            logger.exception(
                "Agent dispatch failed: agent=%s model=%s",
                agent.identity.name,
                model_to_use,
            )
            trace.score("dispatch_error", 0.0, "Agent raised an exception")
            trace.end()
            raise

        # ── 11. Finalize trace ──
        _elapsed_ms = round((_time.monotonic() - _start) * 1000)
        _provider = selection.provider if selection else "unknown"
        trace.update(
            {
                "model": model_to_use,
                "provider": _provider,
                "agent": agent.identity.name,
                "intent": intent.task_type,
                "complexity": intent.complexity,
                "priority": intent.priority,
                "total_latency_ms": str(_elapsed_ms),
                "session_id": session_id or "",
                "is_sticky_followup": str(
                    session_id is not None and agent.identity.name != "default"
                ),
            }
        )
        trace.end()

        # ── 12. Reactor: post-response event ──
        c.reactor.emit(
            Event(
                "post_response",
                {
                    "agent": agent.identity.name,
                    "model": model_to_use,
                    "task_type": intent.task_type,
                    "user_id": auth.user_id,
                    "session_id": session_id or "",
                    "content_length": (len(response.content) if response.content else 0),
                },
            )
        )

        return self._build_response(
            response_id=f"stronghold-{intent.task_type}",
            model=model_to_use,
            content=response.content,
            routing={
                "intent": {
                    "task_type": intent.task_type,
                    "complexity": intent.complexity,
                    "priority": intent.priority,
                    "classified_by": intent.classified_by,
                },
                "model": model_to_use,
                "agent": agent.identity.name,
                "reason": selection.reason if selection else "default",
            },
            include_usage=True,
        )

    @staticmethod
    def _build_response(
        *,
        response_id: str,
        model: str,
        content: str,
        routing: dict[str, Any],
        include_usage: bool = False,
    ) -> dict[str, Any]:
        """Build an OpenAI-compatible chat completion response."""
        result: dict[str, Any] = {
            "id": response_id,
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "_routing": routing,
        }
        if include_usage:
            result["usage"] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        else:
            result["usage"] = {}
        return result
