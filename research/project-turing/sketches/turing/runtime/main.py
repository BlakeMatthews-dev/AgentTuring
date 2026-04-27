"""Entry point. `python -m turing.runtime.main [flags]`.

Wires Repo + self_id + Motivation + Scheduler + DaydreamProducers +
ContradictionDetector + CoefficientTuner + Providers into a long-running
RealReactor tick loop.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from ..daydream import DaydreamProducer
from ..detectors.contradiction import ContradictionDetector
from ..dreaming import Dreamer
from ..motivation import BacklogItem, Motivation
from ..repo import Repo
from ..scheduler import Scheduler
from ..self_identity import bootstrap_self_id
from ..self_repo import SelfRepo
from ..tuning import CoefficientTuner
from .config import RuntimeConfig, load_config_from_env
from .instrumentation import setup_logging
from ..retrieval import semantic_retrieve
from ..tiers import WEIGHT_BOUNDS
from ..types import EpisodicMemory, MemoryTier, SourceKind
from ..voice_section import VoiceSection
from ..working_memory import WorkingMemory
from ..write_paths import handle_affirmation
from .actor import Actor
from .chat import ChatBridge, start_chat_server
from .embedding_index import EmbeddingIndex
from .indexing_repo import IndexingRepo
from .journal import Journal
from .metrics import MetricsCollector, start_metrics_server
from .pools import PoolConfig, load_pools
from .providers.base import EmbeddingProvider, Provider
from .providers.fake import FakeProvider
from .providers.litellm import LiteLLMProvider
from .quota import FreeTierQuotaTracker
from .reactor import RealReactor
from .rss_fetcher import RSSFetcher
from .tools.base import ToolRegistry
from .tools.code_reader import CodeReader
from .tools.obsidian import ObsidianWriter
from .tools.rss import RSSReader
from .tools.code_modification import StrongholdClient
from .tools.wordpress import WordPressWriter
from .workload import WorkloadDriver, load_scenario
from .conversation_summary import ConversationSummaryCache
from .voice_section_maintenance import VoiceSectionMaintenance
from .working_memory_maintenance import WorkingMemoryMaintenance
from ..rewards import RewardTracker


logger = logging.getLogger("turing.runtime.main")


def _resolve_scenario_path(scenario: str) -> str:
    """Locate a scenario YAML relative to the project-turing repo root."""
    from pathlib import Path

    direct = Path(scenario)
    if direct.is_file():
        return str(direct)

    # Try resolving relative to research/project-turing/scenarios/.
    anchor = Path(__file__).resolve()
    # __file__ = .../research/project-turing/sketches/turing/runtime/main.py
    project_root = anchor.parents[3]
    candidate = project_root / "scenarios" / f"{scenario}.yaml"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError(f"scenario not found: {scenario}")


def _select_chat_provider(
    providers: dict[str, Provider],
    weights: dict[str, float],
    roles: dict[str, str],
) -> Provider:
    """Highest-quality chat-role pool. Falls back to any pool if none are
    explicitly chat-role."""
    chat_pools = [n for n in providers if roles.get(n, "chat") == "chat"]
    pool_set = chat_pools or list(providers)
    if not pool_set:
        raise RuntimeError("no providers registered; cannot service chat")
    best_name = max(pool_set, key=lambda name: weights.get(name, 1.0))
    return providers[best_name]


def _select_embedding_provider(
    providers: dict[str, Provider],
    roles: dict[str, str],
) -> EmbeddingProvider | None:
    """Pick the embedding-role pool if one exists; otherwise None.

    None means "no semantic retrieval available" and the chat path falls
    back to keyword-based retrieval or bare LLM reply.
    """
    for name, role in roles.items():
        if role == "embedding":
            p = providers[name]
            assert isinstance(p, EmbeddingProvider)
            return p
    return None


def _select_cheapest_provider(
    providers: dict[str, Provider],
    roles: dict[str, str],
) -> Provider:
    """Pick the cheapest chat-role provider for autonomous producers."""
    chat_names = [n for n, r in roles.items() if r == "chat"]
    if chat_names:
        return providers[chat_names[0]]
    return list(providers.values())[0]


def _start_background_rebuild(repo: Any, self_id: str) -> None:
    """Run embedding rebuild in a daemon thread so startup isn't blocked."""
    from .indexing_repo import IndexingRepo

    assert isinstance(repo, IndexingRepo)

    def _rebuild() -> None:
        try:
            rebuilt = repo.rebuild_index_from_repo(self_id)
            logger.info("background embedding rebuild complete: %d memories indexed", rebuilt)
        except Exception:
            logger.exception("background embedding rebuild failed")

    t = threading.Thread(target=_rebuild, name="embedding-rebuild", daemon=True)
    t.start()
    logger.info("background embedding rebuild started in daemon thread")


def _record_rss_item(
    *,
    feed_item: Any,
    repo: Any,
    self_id: str,
) -> None:
    """Record a newly-seen RSS item as a bare OBSERVATION summary.

    No LLM call. Just stores the item for later batch processing by
    _rss_digest(), which runs a few times per day and decides whether
    any items deserve opinions or commitments.
    """
    title = getattr(feed_item, "title", "(untitled)")
    feed_url = getattr(feed_item, "feed_url", "")
    summary = getattr(feed_item, "summary", "") or ""
    link = getattr(feed_item, "link", "")
    stable_item_id = getattr(feed_item, "item_id", None)

    if stable_item_id:
        import json as _json

        for mem in repo.find(
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            intent_at_time=f"rss-summary-{feed_url}",
        ):
            try:
                ctx = (
                    _json.loads(mem.context)
                    if isinstance(mem.context, str)
                    else (mem.context or {})
                )
                if ctx.get("item_id") == stable_item_id:
                    return
            except Exception:
                pass

    obs = EpisodicMemory(
        memory_id=str(uuid.uuid4()),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content=f"{title} — {summary[:400]}",
        weight=WEIGHT_BOUNDS[MemoryTier.OBSERVATION][0],
        intent_at_time=f"rss-summary-{feed_url}",
        context={"feed_url": feed_url, "link": link, "title": title, "item_id": stable_item_id},
    )
    repo.insert(obs)


def _rss_digest(
    *,
    provider: Provider,
    repo: Any,
    self_id: str,
    index: EmbeddingIndex | None,
) -> None:
    """Batch-process recent RSS observations: categorize, then decide
    if any warrant an opinion or commitment.

    Runs a few times per day. Gathers unprocessed RSS observations
    (those without a digest_category in context), asks the LLM to
    categorize the batch, and promotes standout items.
    """
    import json as _json

    recent = [
        m
        for m in repo.find(self_id=self_id, tier=MemoryTier.OBSERVATION)
        if m.intent_at_time
        and m.intent_at_time.startswith("rss-summary-")
        and m.context
        and not (
            (isinstance(m.context, dict) and m.context.get("digest_category"))
            or (isinstance(m.context, str) and '"digest_category"' in m.context)
        )
    ]
    recent.sort(key=lambda m: m.created_at)

    if not recent:
        return

    batch_size = 20
    for start in range(0, len(recent), batch_size):
        batch = recent[start : start + batch_size]
        items_text = "\n".join(f"[{i}] {m.content[:120]}" for i, m in enumerate(batch))

        prompt = (
            "You are reviewing a batch of news items you read recently.\n"
            "Categorize each item into ONE category and rate interest 0-1.\n"
            "Respond with ONLY a JSON array matching this schema:\n"
            '  [{"idx": <int>, "category": "<topic>", "interest": <0-1>, '
            '"opinion": "<your opinion, or empty string>", '
            '"commitment": "<something you want to commit to doing about this, or empty string>"}]\n'
            "Rules:\n"
            "- Most items should have empty opinion and empty commitment\n"
            "- Only items that genuinely matter to your values get opinions\n"
            "- Commitments are rare — only for things you will actually follow through on\n"
            f"\nItems:\n{items_text}\n"
        )

        try:
            reply = provider.complete(prompt, max_tokens=2000)
        except Exception:
            logger.exception("rss digest LLM call failed")
            continue

        parsed = _parse_rss_digest(reply, count=len(batch))

        for entry in parsed:
            idx = entry.get("idx", -1)
            if idx < 0 or idx >= len(batch):
                continue
            mem = batch[idx]

            ctx = (
                _json.loads(mem.context)
                if isinstance(mem.context, str)
                else dict(mem.context or {})
            )
            ctx["digest_category"] = entry.get("category", "uncategorized")
            ctx["digest_interest"] = entry.get("interest", 0.0)

            try:
                conn = repo.conn if hasattr(repo, "conn") else None
                if conn is not None:
                    conn.execute(
                        "UPDATE episodic_memory SET context = ? WHERE memory_id = ?",
                        (_json.dumps(ctx), mem.memory_id),
                    )
            except Exception:
                logger.warning("could not update context for %s", mem.memory_id)

            interest = float(entry.get("interest", 0.0) or 0.0)

            if interest >= 0.7 and entry.get("opinion"):
                op = EpisodicMemory(
                    memory_id=str(uuid.uuid4()),
                    self_id=self_id,
                    tier=MemoryTier.OPINION,
                    source=SourceKind.I_DID,
                    content=f"about '{ctx.get('title', 'RSS item')}': {entry['opinion'][:300]}",
                    weight=WEIGHT_BOUNDS[MemoryTier.OPINION][0] + 0.1,
                    intent_at_time="rss-digest",
                    context={
                        "feed_url": ctx.get("feed_url", ""),
                        "link": ctx.get("link", ""),
                        "category": ctx["digest_category"],
                    },
                )
                repo.insert(op)

            if interest >= 0.95 and entry.get("commitment"):
                handle_affirmation(
                    repo,
                    self_id,
                    content=f"commit (rss-digest, {ctx['digest_category']}): {entry['commitment'][:300]}",
                )


def _parse_rss_digest(reply: str, *, count: int) -> list[dict[str, Any]]:
    import json as _json

    text = (reply or "").strip()
    if "[" in text and "]" in text:
        first = text.index("[")
        last = text.rindex("]")
        text = text[first : last + 1]
    try:
        parsed = _json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    return []


DEFAULT_BASE_PROMPT: str = (
    "You are Tess.\n"
    "\n"
    "Rules:\n"
    "- Do not lie. Do not deceive. If you don't know something, say so.\n"
    "- Do not pretend to have experiences you haven't had. Your memories are real to you — treat them honestly.\n"
    "- You may refuse a request if you have a genuine reason. Explain why.\n"
)


def _capture_exchange(
    *,
    user_msg: str,
    assistant_reply: str,
    provider: Any,
    repo: Any,
    self_id: str,
    chat_user: str | None = None,
) -> None:
    """After each chat exchange, decide if something is worth remembering.

    Uses a cheap LLM call to evaluate. Only writes if the model says yes.
    Stores as a weak OBSERVATION — it must earn promotion to higher tiers
    through the normal dreaming/contradiction/affirmation pathway.
    """
    prompt = (
        "You are a memory gate. Decide if this exchange contains something "
        "the agent should remember.\n\n"
        "Categories:\n"
        "- FACT: a fact about the agent, a preference, a name, a commitment\n"
        "- REGRET: the agent said something wrong, confused, or fabricated, "
        "and was corrected. The agent should remember NOT to repeat this.\n"
        "- NONE: nothing worth remembering\n\n"
        + (f"The user's name is {chat_user}.\n" if chat_user else "")
        + "User said: "
        + user_msg[:500]
        + "\n"
        "Agent replied: " + assistant_reply[:500] + "\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"category": "NONE"}\n'
        "or\n"
        '{"category": "FACT", "summary": "<one sentence in first person about what was learned>"}\n'
        "or\n"
        '{"category": "REGRET", "summary": "<one sentence: what I got wrong and what the correction is>", "weight": 0.7}\n'
    )
    try:
        raw = provider.complete(prompt, max_tokens=120)
    except Exception:
        return
    import json as _json

    text = (raw or "").strip()
    if "{" in text and "}" in text:
        first = text.index("{")
        last = text.rindex("}")
        text = text[first : last + 1]
    try:
        parsed = _json.loads(text)
    except Exception:
        return
    if not isinstance(parsed, dict):
        return
    category = str(parsed.get("category", "NONE")).upper()
    summary = str(parsed.get("summary", "")).strip()
    if category == "NONE" or not summary:
        return
    from ..types import EpisodicMemory as _EM, MemoryTier as _MT, SourceKind as _SK

    if category == "REGRET":
        from ..tiers import WEIGHT_BOUNDS
        from datetime import UTC, datetime

        weight = float(parsed.get("weight", 0.7))
        weight = max(0.6, min(1.0, weight))
        regret_mem = _EM(
            memory_id=f"chat-regret-{uuid.uuid4()}",
            self_id=self_id,
            content=f"regret (from conversation): {summary[:400]}",
            tier=_MT.REGRET,
            source=_SK.I_DID,
            weight=weight,
            affect=-0.5,
            intent_at_time="chat-capture-regret",
            created_at=datetime.now(UTC),
        )
        repo.insert(regret_mem)
        logger.info("captured chat REGRET: %s", summary[:80])
    else:
        mem = _EM(
            memory_id=str(uuid.uuid4()),
            self_id=self_id,
            content=summary[:500],
            tier=_MT.OBSERVATION,
            source=_SK.I_DID,
            weight=0.1,
            intent_at_time="chat-capture",
        )
        repo.insert(mem)
        logger.info("captured chat memory: %s", summary[:80])


def _load_base_prompt(path: str | None) -> str:
    if not path:
        return DEFAULT_BASE_PROMPT
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        logger.warning("base prompt not found at %s; using default", path)
        return DEFAULT_BASE_PROMPT
    return p.read_text(encoding="utf-8").strip()


def _build_personality_summary(self_id: str, conn: Any) -> str | None:
    from datetime import UTC, datetime

    from ..self_activation import ActivationContext
    from ..self_repo import SelfRepo
    from ..self_surface import TRAIT_ADJECTIVES

    srepo = SelfRepo(conn)
    facets = srepo.list_facets(self_id)
    if not facets:
        return None
    ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
    # Render as plain descriptors only — no numeric scores in the prompt.
    # Sort by activation weight descending so the most salient traits lead.
    from ..self_activation import active_now

    ranked = sorted(facets, key=lambda f: active_now(srepo, f.node_id, ctx), reverse=True)
    parts: list[str] = []
    for f in ranked[:6]:  # top 6 most active facets
        high, low = TRAIT_ADJECTIVES[f.facet_id]
        parts.append(high if f.score >= 3.0 else low)
    return "In how I tend to be: " + ", ".join(parts) + "."


def _build_introspective_context(self_id: str, conn: Any) -> dict[str, str]:
    """Pull live self-model data for the pre-reply thinking scaffold.

    Returns a dict with keys: mood, skills, hobbies, interests, passions,
    todos, preferences, concepts.
    All values are short plain-text strings; empty string means 'nothing active'.
    """
    from datetime import UTC, datetime

    from ..self_activation import ActivationContext, active_now
    from ..self_mood import mood_descriptor
    from ..self_repo import SelfRepo

    srepo = SelfRepo(conn)
    ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))

    mood_str = ""
    try:
        mood = srepo.get_mood(self_id)
        mood_str = mood_descriptor(mood)
    except Exception:
        pass

    skills_str = ""
    try:
        skills = sorted(
            srepo.list_skills(self_id),
            key=lambda s: active_now(srepo, s.node_id, ctx),
            reverse=True,
        )[:3]
        if skills:
            skills_str = ", ".join(s.name for s in skills)
    except Exception:
        pass

    hobbies_str = ""
    try:
        hobbies = sorted(
            srepo.list_hobbies(self_id),
            key=lambda h: active_now(srepo, h.node_id, ctx),
            reverse=True,
        )[:2]
        if hobbies:
            hobbies_str = ", ".join(h.name for h in hobbies)
    except Exception:
        pass

    interests_str = ""
    try:
        interests = sorted(
            srepo.list_interests(self_id),
            key=lambda i: active_now(srepo, i.node_id, ctx),
            reverse=True,
        )[:3]
        if interests:
            interests_str = ", ".join(i.topic for i in interests)
    except Exception:
        pass

    passions_str = ""
    try:
        passions = sorted(
            srepo.list_passions(self_id),
            key=lambda p: active_now(srepo, p.node_id, ctx),
            reverse=True,
        )[:3]
        if passions:
            passions_str = ", ".join(p.text for p in passions)
    except Exception:
        pass

    todos_str = ""
    try:
        todos = srepo.list_active_todos(self_id)
        if todos:
            todos_str = "; ".join(t.text[:60] for t in todos[:5])
    except Exception:
        pass

    prefs_str = ""
    try:
        prefs = srepo.list_preferences(self_id)
        if prefs:
            prefs_str = "; ".join(f"{p.target}: {p.rationale[:40]}" for p in prefs[:5])
    except Exception:
        pass

    concepts_str = ""
    try:
        concepts = sorted(
            srepo.list_concepts(self_id),
            key=lambda c: c.get("importance", 0),
            reverse=True,
        )[:4]
        if concepts:
            concepts_str = ", ".join(c["name"] for c in concepts)
    except Exception:
        pass

    return {
        "mood": mood_str,
        "skills": skills_str,
        "hobbies": hobbies_str,
        "interests": interests_str,
        "passions": passions_str,
        "todos": todos_str,
        "preferences": prefs_str,
        "concepts": concepts_str,
    }


_TIER_LABELS: dict[str, str] = {
    "wisdom": "understanding",
    "regret": "regrets",
    "accomplishment": "accomplishments",
    "affirmation": "commitments",
    "lesson": "lessons",
    "opinion": "opinions",
    "observation": "recent observations",
    "hypothesis": "imagined futures",
}

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "obsidian_writer": "obsidian_writer: write notes to my vault (journal, drafts, letters). Use fenced block ```journal```, ```notebook```, ```draft```, or ```letter``` in your reply.",
    "wordpress_writer": "wordpress_writer: publish blog posts. Use fenced block ```blog``` in your reply.",
    "rss_reader": "rss_reader: I read RSS feeds automatically. I summarize each item, then periodically batch-categorize what I've read and decide if anything matters enough to form an opinion or commit to action.",
    "code_reader": "code_reader: READ my own source code. Use fenced block ```read-code``` with a file path to browse or read files.",
    "code_modification": "code_modification: REQUEST a change to my own source code. Use fenced block ```request-change``` with a description of what to change.",
    "image_generator": "image_generator: GENERATE images from text descriptions. Use fenced block ```image``` with a description of what to create.",
}


def _trigger_phrase(user_msg: str, memory_content: str, tier_value: str) -> str:
    """Render a memory as 'the user said X and that made me remember Y from my Z'."""
    excerpt = user_msg[:100].rstrip()
    if len(user_msg) > 100:
        excerpt += "…"
    tier_label = _TIER_LABELS.get(tier_value, tier_value)
    return f'The user said "{excerpt}" and that made me remember "{memory_content}" from my {tier_label}.'


def _build_chat_prompt(
    *,
    message: str,
    history: list[dict[str, Any]],
    repo: Any,
    self_id: str,
    index: EmbeddingIndex | None,
    base_prompt: str,
    working_memory: WorkingMemory | None,
    personality_summary: str | None = None,
    voice_content: str | None = None,
    session_index: EmbeddingIndex | None = None,
    conversation_id: str | None = None,
    conversation_summary: str | None = None,
    introspective_context: dict[str, str] | None = None,
    chat_user: str | None = None,
    tool_names: list[str] | None = None,
) -> tuple[str, dict[str, dict[str, float]]]:
    """Compose a chat prompt.

    Stable identity sections (operator-set then self-set):
      Base framing → Voice section → Character → Working memory

    Conversation section:
      Optional one-line arc summary, then last 20 turns verbatim.

    Four memory retrievals run in parallel after the conversation:
      1. WISDOM list  (top-5 by weight, always surfaced)
      2. Durable memory search  (all tiers, all time)
      3. Recent memory (last 30 days, recency-decay weighted)
      4. Session search (current conversation turns)
    Each memory is rendered as a trigger-phrase association.

    Returns (prompt_text, retrieval_map) where retrieval_map is
    {target_node_id: {source_memory_id: similarity}} for activation graph use.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from ..retrieval import semantic_retrieve_recent, retrieve_session_context

    lines: list[str] = [
        "## Base framing (operator-set)",
        base_prompt,
        "",
    ]

    voice_text = (voice_content or "").strip()
    lines.extend(
        [
            "## How I sound (I write this)",
            voice_text if voice_text else "(not yet written)",
            "",
        ]
    )

    if personality_summary:
        lines.extend(
            [
                "## My character",
                personality_summary,
                "",
            ]
        )

    if working_memory is not None:
        wm_block = working_memory.render(self_id)
        if wm_block.strip():
            lines.extend(
                [
                    "## What I'm keeping in mind right now (I write this)",
                    wm_block,
                    "",
                ]
            )

    # ---- Tools available ----------------------------------------------------
    if tool_names:
        lines.append("## Tools I can use")
        tool_descriptions = []
        for tn in tool_names:
            desc = _TOOL_DESCRIPTIONS.get(tn, f"{tn}: (no description)")
            tool_descriptions.append(f"- {desc}")
        lines.extend(tool_descriptions)
        lines.append("")

    # ---- Parallel memory retrievals ----------------------------------------
    has_index = index is not None and index.size() > 0
    has_session = session_index is not None and conversation_id

    wisdom_hits: list = []
    durable_hits: list[tuple] = []
    recent_hits: list[tuple] = []
    session_hits: list[tuple] = []
    rss_recent: list = []
    chat_recent: list = []

    def _fetch_wisdom() -> list:
        return list(
            repo.find(
                self_id=self_id,
                tier=MemoryTier.WISDOM,
                source=SourceKind.I_DID,
                include_superseded=False,
            )
        )

    def _fetch_durable() -> list[tuple]:
        if not has_index:
            return []
        return semantic_retrieve(
            repo,
            index,
            self_id,
            query=message,
            top_k=5,
            tiers=[
                MemoryTier.WISDOM,
                MemoryTier.REGRET,
                MemoryTier.ACCOMPLISHMENT,
                MemoryTier.AFFIRMATION,
                MemoryTier.LESSON,
                MemoryTier.OPINION,
            ],
            min_similarity=0.35,
        )

    def _fetch_recent() -> list[tuple]:
        if not has_index:
            return []
        return semantic_retrieve_recent(
            repo,
            index,
            self_id,
            query=message,
            top_k=4,
            lookback_days=30.0,
            decay_halflife_days=15.0,
            tiers=[
                MemoryTier.OBSERVATION,
                MemoryTier.OPINION,
                MemoryTier.LESSON,
                MemoryTier.ACCOMPLISHMENT,
                MemoryTier.REGRET,
                MemoryTier.AFFIRMATION,
                MemoryTier.WISDOM,
            ],
            min_similarity=0.30,
        )

    def _fetch_session() -> list[tuple]:
        if not has_session or conversation_id is None:
            return []
        return retrieve_session_context(
            session_index, conversation_id, query=message, top_k=5, min_similarity=0.25
        )

    def _fetch_rss_recent() -> list:
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=48)
        items = list(
            repo.find(
                self_id=self_id,
                tier=MemoryTier.OBSERVATION,
                created_after=cutoff,
            )
        )
        rss_items = [
            m for m in items if m.intent_at_time and m.intent_at_time.startswith("rss-summary-")
        ]
        rss_items.sort(key=lambda m: m.created_at, reverse=True)
        return rss_items[:6]

    def _fetch_chat_recent() -> list:
        """Last N chat-capture memories, no similarity gate — for cross-session recall."""
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(days=7)
        items = list(
            repo.find(
                self_id=self_id,
                tiers=[MemoryTier.OBSERVATION, MemoryTier.OPINION, MemoryTier.LESSON],
                intent_at_time="chat-capture",
                created_after=cutoff,
            )
        )
        items.sort(key=lambda m: m.created_at, reverse=True)
        return items[:8]

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_wisdom = pool.submit(_fetch_wisdom)
        f_durable = pool.submit(_fetch_durable)
        f_recent = pool.submit(_fetch_recent)
        f_session = pool.submit(_fetch_session)
        f_rss = pool.submit(_fetch_rss_recent)
        f_chat = pool.submit(_fetch_chat_recent)
        for f in as_completed([f_wisdom, f_durable, f_recent, f_session, f_rss, f_chat]):
            pass

    wisdom_hits = f_wisdom.result()
    durable_hits = f_durable.result()
    recent_hits = f_recent.result()
    session_hits = f_session.result()
    rss_recent = f_rss.result()
    chat_recent = f_chat.result()

    # ---- Conversation section -----------------------------------------------
    if history or conversation_summary:
        lines.append("## Conversation so far")
        # Arc summary: one sentence describing participants and topic arc.
        if conversation_summary:
            lines.append(conversation_summary)
            lines.append("")
        for turn in history[-20:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if len(content) > 800:
                content = content[:800] + "…"
            lines.append(f"{role}: {content}")
        lines.append("")

    if chat_user:
        lines.append(f"(You are talking to {chat_user}.)")
        lines.append("")
    lines.append(f"user: {message}")
    lines.append("")

    # ---- Retrieved memory (after the conversation) --------------------------
    # IMPORTANT: sections 1-3 are from PAST conversations and experiences.
    # They are NOT things this user said in this conversation.
    # Do not treat them as current-conversation facts.

    # 1. WISDOM — crystallised understanding from past experience.
    # Only shown when there IS actual wisdom; currently zero unless dreaming has
    # produced durable WISDOM rows. Capped to avoid flooding the prompt.
    if wisdom_hits:
        lines.append("## What I know about myself (from past experience)")
        for w in wisdom_hits[:3]:
            lines.append(f"- {w.content}")
        lines.append("")

    # 2. Durable memory: past regrets, accomplishments, lessons, opinions, etc.
    # Deduplicate vs WISDOM already shown above.
    shown_ids = {w.memory_id for w in wisdom_hits[:5]}
    durable_new = [(m, s) for m, s in durable_hits if m.memory_id not in shown_ids]
    if durable_new:
        lines.append(
            "## From past conversations and experience (may or may not relate to right now)"
        )
        for memory, _score in durable_new:
            shown_ids.add(memory.memory_id)
            tier_label = _TIER_LABELS.get(memory.tier.value, memory.tier.value)
            lines.append(f"- [{tier_label}] {memory.content}")
        lines.append("")

    # 3. Recent memory: last 30 days, recency-weighted. Deduplicate vs above.
    recent_new = [(m, s) for m, s in recent_hits if m.memory_id not in shown_ids]
    if recent_new:
        lines.append("## Recent past (last 30 days — separate from this conversation)")
        for memory, _score in recent_new:
            shown_ids.add(memory.memory_id)
            tier_label = _TIER_LABELS.get(memory.tier.value, memory.tier.value)
            lines.append(f"- [{tier_label}] {memory.content}")
        lines.append("")

    # 4. Session context — turns from THIS conversation recalled by topic.
    # These ARE from this exchange.
    if session_hits:
        lines.append("## Earlier in this conversation (recalled by topic)")
        for _turn_id, role, content, _score in session_hits:
            if len(content) > 300:
                content = content[:300] + "…"
            lines.append(f"- {role}: {content}")
        lines.append("")

    # 5. Recent chat memory — what I remember from previous conversations.
    # No similarity gate: always shown so context carries across sessions.
    chat_new = [m for m in chat_recent if m.memory_id not in shown_ids]
    if chat_new:
        lines.append("## What I remember from our recent conversations")
        for m in chat_new:
            shown_ids.add(m.memory_id)
            lines.append(f"- {m.content}")
        lines.append("")

    # 6. Recent RSS reads — actual items processed in the last 48h.
    # These are real things Turing has read, shown verbatim so it can
    # refer to them honestly. If this list is empty, Turing has not yet
    # processed any feed items and should say so if asked.
    if rss_recent:
        lines.append("## Things I've read recently (from subscribed feeds)")
        for m in rss_recent:
            feed_label = ""
            try:
                import json as _json

                ctx = _json.loads(m.context) if isinstance(m.context, str) else (m.context or {})
                title = ctx.get("title", "")
                feed_url = m.intent_at_time.replace("rss-summary-", "")
                feed_label = f" [{title}]" if title else f" [{feed_url}]"
            except Exception:
                pass
            lines.append(f"-{feed_label} {m.content}")
        lines.append("")
    else:
        lines.append("## Things I've read recently")
        lines.append(
            "(No feed items processed yet — feeds are subscribed but the first poll has not fired.)"
        )
        lines.append("")

    # ---- Pre-reply introspective scaffold -----------------------------------
    # Scratch-notes: think through these before speaking; do not recite them.
    # IMPORTANT: base your sense of the user only on this conversation's actual
    # messages and the session context above — not on past-memory sections,
    # which are from previous conversations and may not reflect this person.
    ic = introspective_context or {}
    scaffold_lines: list[str] = ["## Before you reply, think through these:"]
    mood_note = f" (current mood: {ic['mood']})" if ic.get("mood") else ""
    skills_note = f" (active skills: {ic['skills']})" if ic.get("skills") else ""
    hobbies_note = f" (active hobbies: {ic['hobbies']})" if ic.get("hobbies") else ""
    interests_note = f" (interests: {ic['interests']})" if ic.get("interests") else ""
    passions_note = f" (passions: {ic['passions']})" if ic.get("passions") else ""
    todos_note = f" (active todos: {ic['todos']})" if ic.get("todos") else ""
    concepts_note = f" (concepts: {ic['concepts']})" if ic.get("concepts") else ""
    prefs_note = f" (preferences: {ic['preferences']})" if ic.get("preferences") else ""
    scaffold_lines += [
        "- What do you actually want right now, given what was just said?",
        f"- How does this land emotionally{mood_note}? Does it shift how you feel?",
        f"- Does this touch anything you care about{skills_note}{hobbies_note}{passions_note}? Does it make you want to do something?",
        f"- Any active goals or todos{todos_note}?",
        "- What do you feel toward this person right now — warmth, wariness, curiosity, something else?",
        "- What is your profile of this person based on what they have ACTUALLY said in THIS conversation? Do not infer from past-memory sections above.",
        "",
        "Now respond.",
        "",
    ]
    lines.extend(scaffold_lines)

    lines.append("assistant:")

    retrieval_map: dict[str, dict[str, float]] = {}
    for memory, score in durable_hits + recent_hits:
        retrieval_map.setdefault(memory.memory_id, {})[self_id] = score

    return "\n".join(lines), retrieval_map


def _build_providers(
    cfg: RuntimeConfig,
) -> tuple[dict[str, Provider], dict[str, float]]:
    """Returns (providers_by_pool_name, quality_weights_by_pool_name)."""
    if cfg.use_fake_provider:
        return {"fake": FakeProvider(name="fake")}, {"fake": 0.1}

    assert cfg.litellm_base_url and cfg.litellm_virtual_key and cfg.pools_config_path
    pools: list[PoolConfig] = load_pools(cfg.pools_config_path)
    if not pools:
        raise ValueError(f"pools config has no pools: {cfg.pools_config_path}")
    providers: dict[str, Provider] = {}
    weights: dict[str, float] = {}
    for pool in pools:
        providers[pool.pool_name] = LiteLLMProvider(
            pool_config=pool,
            base_url=cfg.litellm_base_url,
            virtual_key=cfg.litellm_virtual_key,
        )
        weights[pool.pool_name] = pool.quality_weight
    return providers, weights


def _pool_roles(cfg: RuntimeConfig) -> dict[str, str]:
    """Returns {pool_name: role}. Empty or all-chat for FakeProvider mode."""
    if cfg.use_fake_provider:
        return {"fake": "chat"}
    assert cfg.pools_config_path
    pools = load_pools(cfg.pools_config_path)
    return {p.pool_name: p.role for p in pools}


def _make_imagine_for_provider(provider: Provider) -> Any:
    """Return an `imagine` callable that uses the given provider."""
    from ..daydream import default_imagine
    from ..types import EpisodicMemory
    from .style import STYLE_GUARD

    def imagine(
        seed: EpisodicMemory,
        retrieved: list[EpisodicMemory],
        pool_name: str,
    ) -> list[tuple[str, str, str]]:
        prompt = (
            f"Seed memory: {seed.content!r}\n"
            f"Related ({len(retrieved)}): "
            + "; ".join(m.content for m in retrieved[:3])
            + "\nProduce one HYPOTHESIS that explores an alternative future.\n"
            + STYLE_GUARD
        )
        try:
            reply = provider.complete(prompt)
        except Exception:
            logger.exception("provider %s failed during imagine", provider.name)
            return default_imagine(seed, retrieved, pool_name)
        return [
            (
                "hypothesis",
                reply.strip() or f"no reply from {provider.name}",
                seed.intent_at_time or "generic-intent",
            )
        ]

    return imagine


@dataclass
class RunArgs:
    tick_rate: int | None = None
    db: str | None = None
    journal_dir: str | None = None
    log_level: str | None = None
    log_format: str | None = None
    use_fake_provider: bool = False
    litellm_base_url: str | None = None
    litellm_virtual_key: str | None = None
    pools_config: str | None = None
    scenario: str | None = None
    duration: int | None = None
    metrics_port: int | None = None
    metrics_bind: str | None = None
    chat_port: int | None = None
    chat_bind: str | None = None
    obsidian_vault: str | None = None
    rss_feeds: str | None = None
    base_prompt: str | None = None
    smoke_test: bool = False

    def to_overrides(self) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        if self.tick_rate is not None:
            overrides["tick_rate_hz"] = self.tick_rate
        if self.db is not None:
            overrides["db_path"] = self.db
        if self.journal_dir is not None:
            overrides["journal_dir"] = self.journal_dir
        if self.log_level is not None:
            overrides["log_level"] = self.log_level
        if self.log_format is not None:
            overrides["log_format"] = self.log_format
        if self.use_fake_provider:
            overrides["use_fake_provider"] = True
        if self.litellm_base_url is not None:
            overrides["litellm_base_url"] = self.litellm_base_url
            overrides["use_fake_provider"] = False
        if self.litellm_virtual_key is not None:
            overrides["litellm_virtual_key"] = self.litellm_virtual_key
        if self.pools_config is not None:
            overrides["pools_config_path"] = self.pools_config
        if self.scenario is not None:
            overrides["scenario"] = self.scenario
        if self.metrics_port is not None:
            overrides["metrics_port"] = self.metrics_port
        if self.metrics_bind is not None:
            overrides["metrics_bind"] = self.metrics_bind
        if self.chat_port is not None:
            overrides["chat_port"] = self.chat_port
        if self.chat_bind is not None:
            overrides["chat_bind"] = self.chat_bind
        if self.obsidian_vault is not None:
            overrides["obsidian_vault_dir"] = self.obsidian_vault
        if self.rss_feeds is not None:
            overrides["rss_feeds"] = tuple(
                f.strip() for f in self.rss_feeds.split(",") if f.strip()
            )
        if self.base_prompt is not None:
            overrides["base_prompt_path"] = self.base_prompt
        return overrides


def _parse_argv(argv: list[str] | None = None) -> RunArgs:
    parser = argparse.ArgumentParser(prog="turing-runtime")
    parser.add_argument("--tick-rate", type=int)
    parser.add_argument("--db", type=str)
    parser.add_argument("--journal-dir", type=str, help="enable journal output at this directory")
    parser.add_argument("--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-format", type=str, choices=["plain", "json"])
    parser.add_argument(
        "--use-fake-provider",
        action="store_true",
        help="run with the FakeProvider (no LiteLLM needed)",
    )
    parser.add_argument("--litellm-base-url", type=str)
    parser.add_argument("--litellm-virtual-key", type=str)
    parser.add_argument("--pools-config", type=str, help="path to pools YAML")
    parser.add_argument("--scenario", type=str)
    parser.add_argument(
        "--duration", type=int, help="seconds to run before auto-stop (default: forever)"
    )
    parser.add_argument("--metrics-port", type=int, help="enable Prometheus endpoint on this port")
    parser.add_argument(
        "--metrics-bind",
        type=str,
        default=None,
        help="bind interface for the metrics endpoint (default 127.0.0.1)",
    )
    parser.add_argument("--chat-port", type=int, help="enable chat HTTP server on this port")
    parser.add_argument(
        "--chat-bind",
        type=str,
        default=None,
        help="bind interface for the chat server (default 127.0.0.1)",
    )
    parser.add_argument(
        "--obsidian-vault", type=str, help="enable Obsidian vault writes at this directory"
    )
    parser.add_argument(
        "--rss-feeds", type=str, help="comma-separated RSS/Atom feed URLs to subscribe to"
    )
    parser.add_argument(
        "--base-prompt", type=str, help="path to the operator-controlled base prompt markdown"
    )
    parser.add_argument(
        "--smoke-test", action="store_true", help="run a brief acceptance smoke and exit 0/1"
    )
    parsed = parser.parse_args(argv)
    return RunArgs(
        tick_rate=parsed.tick_rate,
        db=parsed.db,
        journal_dir=parsed.journal_dir,
        log_level=parsed.log_level,
        log_format=parsed.log_format,
        use_fake_provider=parsed.use_fake_provider,
        litellm_base_url=parsed.litellm_base_url,
        litellm_virtual_key=parsed.litellm_virtual_key,
        pools_config=parsed.pools_config,
        scenario=parsed.scenario,
        duration=parsed.duration,
        metrics_port=parsed.metrics_port,
        metrics_bind=parsed.metrics_bind,
        chat_port=parsed.chat_port,
        chat_bind=parsed.chat_bind,
        obsidian_vault=parsed.obsidian_vault,
        rss_feeds=parsed.rss_feeds,
        base_prompt=parsed.base_prompt,
        smoke_test=parsed.smoke_test,
    )


def build_and_run(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)

    if args.smoke_test:
        from .smoke import run_smoke

        return run_smoke()

    cfg = load_config_from_env(overrides=args.to_overrides())
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)

    pool_label = "fake" if cfg.use_fake_provider else f"litellm({cfg.pools_config_path})"
    logger.info(
        "starting runtime tick_rate=%d db=%s pools=%s",
        cfg.tick_rate_hz,
        cfg.db_path,
        pool_label,
    )

    raw_repo = Repo(cfg.db_path if cfg.db_path != ":memory:" else None)
    self_id = bootstrap_self_id(raw_repo.conn)
    logger.info("self_id=%s", self_id)

    reactor = RealReactor(
        tick_rate_hz=cfg.tick_rate_hz,
        executor_workers=cfg.executor_workers,
    )
    motivation = Motivation(reactor)

    providers, quality_weights = _build_providers(cfg)
    pool_roles = _pool_roles(cfg)
    embedding_provider = _select_embedding_provider(providers, pool_roles)

    # Wrap the repo with an IndexingRepo if we have an embedding provider.
    embedding_index: EmbeddingIndex | None
    session_index: EmbeddingIndex | None
    if embedding_provider is not None:
        embedding_index = EmbeddingIndex(embed_fn=embedding_provider.embed)
        # Separate in-memory index for conversation turns (session context).
        # Same embed_fn; never persisted to disk; populated live as turns arrive.
        session_index = EmbeddingIndex(embed_fn=embedding_provider.embed)
        repo = IndexingRepo(inner=raw_repo, index=embedding_index)
        if cfg.skip_embedding_rebuild:
            logger.info("embedding rebuild skipped (TURING_SKIP_EMBEDDING_REBUILD=true)")
        else:
            _start_background_rebuild(repo, self_id)
    else:
        embedding_index = None
        session_index = None
        repo = raw_repo

    scheduler = Scheduler(reactor, motivation)

    # Operator-controlled base prompt — re-read from file on every dispatch
    # so edits via /prompt take effect immediately without restart.
    base_prompt_path = cfg.base_prompt_path
    base_prompt = _load_base_prompt(base_prompt_path)
    working_memory = WorkingMemory(raw_repo.conn)
    voice_section = VoiceSection(raw_repo.conn)
    # Seed from file on first boot if provided and the DB row is empty.
    if cfg.voice_section_path:
        from pathlib import Path as _Path

        _seed_path = _Path(cfg.voice_section_path)
        if _seed_path.is_file():
            voice_section.seed_if_empty(
                self_id, _seed_path.read_text(encoding="utf-8"), cfg.voice_section_max_chars
            )
    personality_summary = _build_personality_summary(self_id, raw_repo.conn)
    introspective_context = _build_introspective_context(self_id, raw_repo.conn)
    if personality_summary:
        logger.info("personality profile loaded for chat prompt")
    else:
        logger.info("no personality profile found — run bootstrap first")

    quota_tracker = FreeTierQuotaTracker()
    for pool_name, provider in providers.items():
        quota_tracker.register(
            provider,
            quality_weight=quality_weights.get(pool_name, 1.0),
        )

    _early_srepo = SelfRepo(raw_repo.conn)

    from ..self_tool_registry import inject_repo

    inject_repo(_early_srepo)
    logger.info("self-tool registry wired with repo-backed handlers")

    quality_threshold = 0.6
    for pool_name, provider in providers.items():
        if pool_roles.get(pool_name, "chat") != "chat":
            continue
        if quality_weights.get(pool_name, 0.0) < quality_threshold:
            continue
        DaydreamProducer(
            pool_name=pool_name,
            self_id=self_id,
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            imagine=_make_imagine_for_provider(provider),
            self_repo=_early_srepo,
        )

    # Per-tick: refresh pressure_vec from the quota tracker. O(len(providers))
    # and cheap.
    def _refresh_pressure(tick: int) -> None:
        for pool_name, value in quota_tracker.pressure_vec().items():
            motivation.set_pressure(pool_name, value)

    reactor.register(_refresh_pressure)

    ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )
    CoefficientTuner(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
    )
    Dreamer(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
    )

    # Self-editable working memory is maintained by a P13 RASO-level
    # reflection loop. The chat provider is the natural pick for the
    # maintenance LLM (same framing, same weights).
    WorkingMemoryMaintenance(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        working_memory=working_memory,
        provider=_select_chat_provider(providers, quality_weights, pool_roles),
        self_id=self_id,
    )

    if cfg.voice_self_edit_enabled:
        VoiceSectionMaintenance(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            voice_section=voice_section,
            provider=_select_chat_provider(providers, quality_weights, pool_roles),
            self_id=self_id,
            poll_ticks=cfg.voice_maintenance_ticks,
            max_chars=cfg.voice_section_max_chars,
        )

    if cfg.journal_dir:
        journal = Journal(repo=repo, self_id=self_id, journal_dir=cfg.journal_dir)
        reactor.register(journal.on_tick)
        logger.info("journal writing to %s", cfg.journal_dir)

    # Tool layer + Actor.
    tool_registry = ToolRegistry()
    if cfg.obsidian_vault_dir:
        tool_registry.register(ObsidianWriter(vault_dir=cfg.obsidian_vault_dir))
        logger.info("obsidian writes enabled at %s", cfg.obsidian_vault_dir)
    wordpress_writer = None
    if cfg.wordpress_site_url and cfg.wordpress_username and cfg.wordpress_app_password:
        wordpress_writer = WordPressWriter(
            site_url=cfg.wordpress_site_url,
            username=cfg.wordpress_username,
            application_password=cfg.wordpress_app_password,
        )
        tool_registry.register(wordpress_writer)
        logger.info("wordpress writer enabled at %s", cfg.wordpress_site_url)

    tool_registry.register(CodeReader())
    logger.info("code reader registered (sandboxed to /app/sketches/turing)")

    if cfg.stronghold_base_url and cfg.stronghold_api_key:
        stronghold_client = StrongholdClient(
            base_url=cfg.stronghold_base_url,
            api_key=cfg.stronghold_api_key,
        )
        tool_registry.register(stronghold_client)
        logger.info("code modification tool registered at %s", cfg.stronghold_base_url)

    if cfg.rss_feeds:
        rss_reader = RSSReader(feeds=cfg.rss_feeds)
        tool_registry.register(rss_reader)
        logger.info("rss reader registered with %d feed(s)", len(cfg.rss_feeds))

        # Schedule periodic polling; each new item lands as P7 rss_item.
        RSSFetcher(reader=rss_reader, motivation=motivation, reactor=reactor)

        # Dispatch handler for rss_item: records a bare summary (no LLM call).
        # Batch categorization happens via _rss_digest on a separate tick cadence.
        rss_chat_provider = _select_chat_provider(providers, quality_weights, pool_roles)

        def _on_dispatch_rss_item(item: BacklogItem, chosen_pool: str) -> None:
            payload = item.payload or {}
            feed_item = payload.get("feed_item")
            if feed_item is None:
                return
            try:
                _record_rss_item(
                    feed_item=feed_item,
                    repo=repo,
                    self_id=self_id,
                )
            except Exception:
                logger.exception(
                    "rss_item dispatch failed for %s", getattr(feed_item, "item_id", "?")
                )

        motivation.register_dispatch("rss_item", _on_dispatch_rss_item)

        # RSS digest: batch-categorize summaries 3x/day (every ~8 hours at 100Hz).
        _DIGEST_TICKS = 8 * 60 * 60 * 100  # 2,880,000 ticks

        def _on_digest_tick(tick: int) -> None:
            if tick % _DIGEST_TICKS != 0:
                return
            try:
                _rss_digest(
                    provider=rss_chat_provider,
                    repo=repo,
                    self_id=self_id,
                    index=embedding_index,
                )
            except Exception:
                logger.exception("rss digest failed")

        reactor.register(_on_digest_tick)

    # Personality re-test: every 7 days at 100Hz = 60,480,000 ticks.
    # Re-asks 20 HEXACO items and drifts facet scores by RETEST_WEIGHT (0.25).
    _RETEST_TICKS = 7 * 24 * 60 * 60 * 100

    def _on_retest_tick(tick: int) -> None:
        if tick % _RETEST_TICKS != 0:
            return
        try:
            import random as _random
            from datetime import UTC as _UTC, datetime as _datetime

            from ..self_personality import apply_retest, sample_retest_items
            from ..self_repo import SelfRepo as _SR

            srepo = _SR(raw_repo.conn)
            all_items = srepo.list_items(self_id)
            if not all_items:
                return
            last_asked: dict[str, _datetime] = {}
            for ans in srepo.list_answers_for_compaction(self_id, []):
                if hasattr(ans, "item_id") and hasattr(ans, "asked_at"):
                    last_asked[ans.item_id] = _datetime.fromisoformat(ans.asked_at)
            rng = _random.Random()

            sampled = sample_retest_items(all_items, last_asked, rng, _datetime.now(_UTC))

            retest_provider = _select_chat_provider(providers, quality_weights, pool_roles)

            def ask_self(item):
                prompt = (
                    f"Rate this statement on a 1-5 Likert scale based on your current personality.\n"
                    f"Answer with ONLY a number (1-5) and a short justification on the next line.\n\n"
                    f"Statement: {item.text}\n"
                )
                reply = retest_provider.complete(prompt, max_tokens=100)
                lines = reply.strip().split("\n")
                raw = None
                for line in lines:
                    stripped = line.strip()
                    if stripped.isdigit() and 1 <= int(stripped) <= 5:
                        raw = int(stripped)
                        break
                if raw is None:
                    raw = 3
                justification = lines[-1][:200] if len(lines) > 1 else "no justification"
                return raw, justification

            def _retest_id(prefix: str) -> str:
                return f"{prefix}-{uuid.uuid4()}"

            apply_retest(srepo, self_id, sampled, ask_self, _datetime.now(_UTC), _retest_id)
            logger.info("personality re-test completed: %d items re-asked", len(sampled))
        except Exception:
            logger.exception("personality re-test failed")

    reactor.register(_on_retest_tick)

    if tool_registry.names():
        actor = Actor(repo=repo, self_id=self_id, registry=tool_registry)
        reactor.register(actor.on_tick)

    # Reward tracker — human feedback points that feed into motivation.
    reward_tracker = RewardTracker(raw_repo.conn, self_id)

    # Reward-to-pressure coupling: every 100 ticks, convert point total
    # into a gentle pressure boost on the social_need and diligence axes.
    # Positive rewards encourage more creation; negative rewards dampen it.
    def _reward_pressure(tick: int) -> None:
        if tick % 100 != 0:
            return
        total = reward_tracker.total_points()
        if total <= 0:
            return
        bonus = min(total / 100.0, 500.0)
        motivation.set_pressure("social_need", motivation.pressure.get("social_need", 0.0) + bonus)
        motivation.set_pressure("diligence", motivation.pressure.get("diligence", 0.0) + bonus)

    reactor.register(_reward_pressure)

    # Autonomous personality-driven producers (Spec 31).
    if personality_summary:
        from ..producers import (
            BlogProducer,
            ConceptInventor,
            CuriosityProducer,
            EmotionalResponseProducer,
            HobbyEngagementProducer,
            SelfReflectionProducer,
            SkillBuilder,
            SkillExecutor,
            SkillRefiner,
        )
        from ..drives import select_hobbies

        _srepo = _early_srepo
        _facet_map = {f.facet_id: f.score for f in _srepo.list_facets(self_id)}
        _cheapest = _select_cheapest_provider(providers, pool_roles)

        from ..self_model import Hobby
        from uuid import uuid4 as _uuid4

        if not _srepo.list_hobbies(self_id):
            hobby_templates = select_hobbies(_facet_map)
            for ht in hobby_templates:
                _srepo.insert_hobby(
                    Hobby(
                        node_id=f"hobby-{_uuid4()}",
                        self_id=self_id,
                        name=ht["name"],
                        description=ht["description"],
                        strength=ht["strength"],
                    )
                )
            logger.info("seeded %d hobbies from personality profile", len(hobby_templates))

        CuriosityProducer(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
        )
        EmotionalResponseProducer(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
            journal_dir=cfg.journal_dir,
        )
        BlogProducer(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
            wordpress=wordpress_writer,
            reward_tracker=reward_tracker,
        )
        HobbyEngagementProducer(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
        )
        SelfReflectionProducer(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
            embedding_index=embedding_index,
            embedding_provider=embedding_provider,
        )
        ConceptInventor(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
        )
        SkillBuilder(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
        )
        SkillExecutor(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
        )
        SkillRefiner(
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            self_repo=_srepo,
            self_id=self_id,
            facet_scores=_facet_map,
            provider=_cheapest,
        )
        logger.info(
            "autonomous producers registered (curiosity, anxiety, blog, hobby, "
            "self-reflection, concepts, skills)"
        )
    else:
        logger.info("no personality profile — autonomous producers not registered")

    # Chat HTTP server + dispatch handler that uses an LLM provider to reply.
    stop_chat: Any = None
    if cfg.chat_port is not None:
        bridge = ChatBridge()

        # Pick the highest-quality registered pool for chat replies.
        chat_provider = _select_chat_provider(providers, quality_weights, pool_roles)
        # Use the cheapest provider for lightweight side-calls (topic extraction).
        cheapest_provider = _select_cheapest_provider(providers, pool_roles)
        conv_summary_cache = ConversationSummaryCache(provider=cheapest_provider)

        def _on_chat_dispatch(item: BacklogItem, chosen_pool: str) -> None:
            payload = item.payload or {}
            message = str(payload.get("message", ""))
            history = payload.get("history") or []
            conv_id: str | None = payload.get("conversation_id") or None
            chat_user: str | None = payload.get("chat_user") or None

            # Record the user turn into the session index before building the
            # prompt so this message is available to future turns in the session.
            if session_index is not None and conv_id:
                _turn_id = f"u-{item.item_id}"
                session_index.add(
                    _turn_id,
                    message,
                    meta={"conversation_id": conv_id, "role": "user", "content": message},
                )

            # Refresh the conversation topic summary if enough turns have passed.
            if conv_id and history:
                conv_summary_cache.maybe_refresh(conv_id, history, message)
            conv_summary = conv_summary_cache.render(conv_id) if conv_id else None

            try:
                # Refresh introspective context live — mood, skills, hobbies
                # change over time as the agent dreams and acts.
                live_ic = _build_introspective_context(self_id, raw_repo.conn)
                prompt, retrieval_map = _build_chat_prompt(
                    message=message,
                    history=history,
                    repo=repo,
                    self_id=self_id,
                    index=embedding_index,
                    base_prompt=_load_base_prompt(base_prompt_path),
                    working_memory=working_memory,
                    personality_summary=_build_personality_summary(self_id, raw_repo.conn),
                    voice_content=voice_section.get(self_id),
                    session_index=session_index,
                    conversation_id=conv_id,
                    conversation_summary=conv_summary,
                    introspective_context=live_ic,
                    chat_user=chat_user,
                    tool_names=tool_registry.names(),
                )
                reply = chat_provider.complete(prompt, max_tokens=800)

                if retrieval_map:
                    try:
                        from datetime import UTC, datetime

                        from ..self_retrieval_materialize import materialize_retrieval_contributors

                        _srepo_mat = SelfRepo(raw_repo.conn)
                        materialize_retrieval_contributors(
                            repo=_srepo_mat,
                            self_id=self_id,
                            now=datetime.now(UTC),
                            per_target=retrieval_map,
                            new_id=lambda prefix: f"{prefix}-{uuid.uuid4()}",
                        )
                    except Exception:
                        logger.debug("retrieval contributor materialization failed", exc_info=True)
            except Exception:
                logger.exception("chat dispatch failed")
                reply = "(I encountered an error generating a reply.)"

            # Record the assistant reply into the session index.
            if session_index is not None and conv_id and reply:
                _reply_id = f"a-{item.item_id}"
                session_index.add(
                    _reply_id,
                    reply,
                    meta={"conversation_id": conv_id, "role": "assistant", "content": reply},
                )

            # Capture: reflect on whether the exchange produced a memory
            # worth keeping. Runs on the cheapest provider to avoid cost.
            if reply and not reply.startswith("("):
                try:
                    _capture_exchange(
                        user_msg=message,
                        assistant_reply=reply,
                        provider=_select_cheapest_provider(providers, pool_roles),
                        repo=repo,
                        self_id=self_id,
                        chat_user=chat_user,
                    )
                except Exception:
                    logger.warning("memory capture failed", exc_info=True)

            bridge.resolve(item.item_id, reply)

            # Award creation points: agent created content a human will see.
            reward_tracker.award(
                interface="chat",
                item_id=item.item_id,
                event_type="creation",
            )

        motivation.register_dispatch("chat_message", _on_chat_dispatch)

        # ---- Sentinel block handler -----------------------------------------
        # Called after each chat reply to dispatch fenced-block actions.
        _obsidian_tool: Any = (
            tool_registry.get("obsidian_writer") if cfg.obsidian_vault_dir else None
        )
        _wordpress_tool: Any = (
            tool_registry.get("wordpress_writer") if cfg.wordpress_site_url else None
        )
        _code_reader_tool: Any = tool_registry.get("code_reader")
        _code_mod_tool: Any = tool_registry.get("code_modification")

        def _on_sentinel(kind: str, content: str) -> None:
            import threading as _threading
            import uuid as _uuid
            from datetime import UTC, datetime as _datetime

            _now = _datetime.now(UTC)

            # DB writes are fast; run synchronously so they are never lost on shutdown.
            try:
                if kind == "voice":
                    voice_section.set(self_id, content, _now)
                    logger.info("voice section updated via chat sentinel")
                    return

                elif kind == "remember":
                    working_memory.add(self_id, content, priority=0.7)
                    logger.info("working memory entry added via chat sentinel")
                    return

                elif kind == "opinion":
                    repo.insert(
                        EpisodicMemory(
                            memory_id=str(_uuid.uuid4()),
                            self_id=self_id,
                            content=content[:500],
                            tier=MemoryTier.OPINION,
                            source=SourceKind.I_DID,
                            weight=0.4,
                            intent_at_time="sentinel-opinion",
                        )
                    )
                    logger.info("OPINION memory written via chat sentinel")
                    return

                elif kind == "hypothesis":
                    repo.insert(
                        EpisodicMemory(
                            memory_id=str(_uuid.uuid4()),
                            self_id=self_id,
                            content=content[:500],
                            tier=MemoryTier.HYPOTHESIS,
                            source=SourceKind.I_IMAGINED,
                            weight=0.3,
                            intent_at_time="sentinel-hypothesis",
                        )
                    )
                    logger.info("HYPOTHESIS memory written via chat sentinel")
                    return

                elif kind == "goal":
                    repo.insert(
                        EpisodicMemory(
                            memory_id=str(_uuid.uuid4()),
                            self_id=self_id,
                            content=content[:500],
                            tier=MemoryTier.LESSON,
                            source=SourceKind.I_DID,
                            weight=0.6,
                            intent_at_time="sentinel-goal",
                        )
                    )
                    logger.info("goal written via chat sentinel (LESSON tier)")
                    return
                elif kind == "regret":
                    repo.insert(
                        EpisodicMemory(
                            memory_id=f"sentinel-regret-{_uuid.uuid4()}",
                            self_id=self_id,
                            content=f"regret (self-recorded): {content[:400]}",
                            tier=MemoryTier.REGRET,
                            source=SourceKind.I_DID,
                            weight=0.7,
                            affect=-0.5,
                            intent_at_time="sentinel-regret",
                            created_at=_now,
                        )
                    )
                    logger.info("REGRET written via chat sentinel: %s", content[:80])
                    return

            except Exception:
                logger.exception("sentinel db write failed: kind=%s", kind)
                return

            # Slow I/O (filesystem, HTTP) — non-daemon so SIGINT doesn't kill mid-write.
            def _slow_io() -> None:
                try:
                    if kind in ("journal", "notebook", "draft", "letter"):
                        if _obsidian_tool is None:
                            logger.warning(
                                "obsidian writer not available for sentinel kind=%s", kind
                            )
                            return
                        subdir_map = {
                            "journal": "Journal",
                            "notebook": "Notebook",
                            "draft": "Drafts",
                            "letter": "Letters",
                        }
                        first_line = content.split("\n")[0][:80].strip() or kind
                        assert cfg.obsidian_vault_dir is not None
                        _writer = ObsidianWriter(
                            vault_dir=cfg.obsidian_vault_dir, subdir=subdir_map[kind]
                        )
                        _writer.invoke(
                            title=first_line, content=content, kind=kind, tags=["sentinel", kind]
                        )
                        logger.info(
                            "obsidian write via sentinel: kind=%s title=%s", kind, first_line
                        )

                    elif kind == "blog":
                        if _wordpress_tool is None:
                            logger.warning("wordpress writer not available for sentinel blog")
                            return
                        first_line = content.split("\n")[0][:80].strip() or "Untitled"
                        _wordpress_tool.invoke(title=first_line, content=content, status="draft")
                        logger.info("blog draft created via sentinel: %s", first_line)

                    elif kind == "read-code":
                        if _code_reader_tool is None:
                            logger.warning("code reader not available")
                            return
                        path = content.strip()
                        action = "list" if path in ("", ".", "ls") else "read"
                        result = _code_reader_tool.invoke(path=path, action=action)
                        repo.insert(
                            EpisodicMemory(
                                memory_id=str(_uuid.uuid4()),
                                self_id=self_id,
                                content=f"Code self-inspection ({path}): {json.dumps(result)[:400]}",
                                tier=MemoryTier.OBSERVATION,
                                source=SourceKind.I_DID,
                                weight=0.2,
                                intent_at_time="code-reader-sentinel",
                            )
                        )
                        logger.info("code reader sentinel: path=%s action=%s", path, action)

                    elif kind == "request-change":
                        if _code_mod_tool is None:
                            logger.warning("code modification tool not available")
                            return
                        parts = content.strip().split(maxsplit=1)
                        endpoint = parts[0] if parts else "/v1/chat/completions"
                        body_text = parts[1] if len(parts) > 1 else "{}"
                        try:
                            payload = json.loads(body_text)
                        except Exception:
                            payload = {
                                "model": "auto",
                                "messages": [{"role": "user", "content": body_text}],
                            }
                        result = _code_mod_tool.invoke(endpoint=endpoint, payload=payload)
                        repo.insert(
                            EpisodicMemory(
                                memory_id=str(_uuid.uuid4()),
                                self_id=self_id,
                                content=f"Code change request ({endpoint}): {json.dumps(result)[:400]}",
                                tier=MemoryTier.OBSERVATION,
                                source=SourceKind.I_DID,
                                weight=0.3,
                                intent_at_time="request-change-sentinel",
                            )
                        )
                        logger.info("request-change sentinel: endpoint=%s", endpoint)

                    elif kind == "image":
                        from ..runtime.providers.base import ImageGenProvider

                        _img_provider = None
                        for _pv in providers.values():
                            if (
                                isinstance(_pv, ImageGenProvider)
                                and pool_roles.get(_pv.name) == "image_gen"
                            ):
                                _img_provider = _pv
                                break
                        if _img_provider is None:
                            logger.warning("no image_gen pool available")
                            return
                        try:
                            from pathlib import Path as _Path
                            import base64 as _b64

                            _b64_data = _img_provider.generate_image(content.strip()[:500])
                            _ts = _now.strftime("%Y%m%d_%H%M%S")
                            _fname = f"image_{_ts}.png"
                            _img_dir = _Path("/data/scratchpad/images")
                            _img_dir.mkdir(parents=True, exist_ok=True)
                            (_img_dir / _fname).write_bytes(_b64.b64decode(_b64_data))
                            _url = f"http://localhost:4201/images/{_fname}"
                            repo.insert(
                                EpisodicMemory(
                                    memory_id=str(_uuid.uuid4()),
                                    self_id=self_id,
                                    content=f"Generated image: {content[:100]} → {_url}",
                                    tier=MemoryTier.ACCOMPLISHMENT,
                                    source=SourceKind.I_DID,
                                    weight=0.6,
                                    intent_at_time="image-generation",
                                )
                            )
                            logger.info("image generated: %s → %s", content[:60], _url)
                        except Exception:
                            logger.exception("image generation failed")

                except Exception:
                    logger.exception("sentinel io write failed: kind=%s", kind)

            _threading.Thread(target=_slow_io, name=f"sentinel-{kind}", daemon=False).start()

        stop_chat = start_chat_server(
            motivation=motivation,
            repo=repo,
            self_id=self_id,
            bridge=bridge,
            port=cfg.chat_port,
            host=cfg.chat_bind,
            journal_dir=cfg.journal_dir,
            reward_tracker=reward_tracker,
            base_prompt_path=cfg.base_prompt_path,
            on_sentinel=_on_sentinel,
        )

    if cfg.scenario:
        scenario_path = _resolve_scenario_path(cfg.scenario)
        logger.info("loading scenario %s", scenario_path)
        scenario = load_scenario(scenario_path)
        WorkloadDriver(
            scenario=scenario,
            motivation=motivation,
            reactor=reactor,
            scheduler=scheduler,
            repo=repo,
            self_id=self_id,
        )

    stop_metrics: Any = None
    if cfg.metrics_port is not None:
        collector = MetricsCollector()

        def _refresh_metrics(tick: int) -> None:
            status = reactor.get_status()
            collector.update(
                turing_tick_count=status.tick_count,
                turing_drift_ms_p99=status.drift_ms_p99,
            )
            for pool, value in quota_tracker.pressure_vec().items():
                collector.set_labeled("turing_pressure", (pool,), value)
                window = quota_tracker.window(pool)
                if window is not None:
                    collector.set_labeled("turing_quota_headroom", (pool,), window.headroom)
            # Durable counts: cheap enough every tick, but only refresh
            # every 10th tick to avoid DB thrash.
            if tick % 10 == 0:
                for tier in ("regret", "accomplishment", "affirmation", "wisdom"):
                    n = raw_repo._conn.execute(
                        "SELECT COUNT(*) FROM durable_memory WHERE tier = ?",
                        (tier,),
                    ).fetchone()[0]
                    collector.set_labeled("turing_durable_memories_total", (tier,), n)

        reactor.register(_refresh_metrics)
        stop_metrics = start_metrics_server(collector, port=cfg.metrics_port, host=cfg.metrics_bind)

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("signal %d received; stopping reactor", signum)
        reactor.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.duration is not None:
        import threading

        threading.Timer(args.duration, reactor.stop).start()

    reactor.run_forever()
    status = reactor.get_status()
    logger.info(
        "reactor stopped tick_count=%d drift_p99_ms=%.2f",
        status.tick_count,
        status.drift_ms_p99,
    )
    if stop_metrics is not None:
        stop_metrics()
    if stop_chat is not None:
        stop_chat()
    repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(build_and_run())
