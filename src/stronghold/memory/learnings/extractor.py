"""Learning extractor: pure function that detects fail→succeed patterns.

No database, no network. Takes tool_history, returns learnings.
RCA extraction is the exception — it requires an LLM call.
"""

from __future__ import annotations

import json
import logging

from stronghold.types.memory import Learning, MemoryScope

logger = logging.getLogger("stronghold.extractor")


class ToolCorrectionExtractor:
    """Extracts learnings from tool call histories."""

    def extract_corrections(
        self,
        user_text: str,
        tool_history: list[dict[str, object]],
    ) -> list[Learning]:
        """Extract fail→succeed correction patterns.

        When a tool fails then succeeds with different args in the same request,
        that's a correction worth remembering.
        """
        learnings: list[Learning] = []

        # Group by tool name
        by_tool: dict[str, list[dict[str, object]]] = {}
        for entry in tool_history:
            name = str(entry.get("tool_name", ""))
            if name not in by_tool:
                by_tool[name] = []
            by_tool[name].append(entry)

        for tool_name, calls in by_tool.items():
            if len(calls) < 2:
                continue

            # Look for fail→succeed pattern
            for i in range(len(calls) - 1):
                result_i = str(calls[i].get("result", ""))
                result_next = str(calls[i + 1].get("result", ""))

                is_failure = result_i.startswith("Error") or "error" in result_i.lower()
                is_success = (
                    not result_next.startswith("Error") and "error" not in result_next.lower()
                )

                if is_failure and is_success:
                    args_failed = calls[i].get("arguments", {})
                    args_succeeded = calls[i + 1].get("arguments", {})

                    # Build trigger keywords from user text
                    words = user_text.lower().split()
                    trigger_keys = [w for w in words if len(w) > 2][:5]

                    learning_text = (
                        f"When user says '{user_text[:80]}', "
                        f"tool {tool_name} fails with {args_failed} "
                        f"but succeeds with {args_succeeded}"
                    )

                    learnings.append(
                        Learning(
                            category="tool_correction",
                            trigger_keys=trigger_keys,
                            learning=learning_text,
                            tool_name=tool_name,
                            source_query=user_text[:80],
                            scope=MemoryScope.AGENT,
                        )
                    )

        return learnings

    def extract_positive_patterns(
        self,
        user_text: str,
        tool_history: list[dict[str, object]],
    ) -> list[Learning]:
        """Extract first-try success patterns on ambiguous queries."""
        learnings: list[Learning] = []

        for entry in tool_history:
            result = str(entry.get("result", ""))
            is_success = not result.startswith("Error") and "error" not in result.lower()
            is_round_zero = entry.get("round", 0) == 0

            if is_success and is_round_zero:
                tool_name = str(entry.get("tool_name", ""))
                args = entry.get("arguments", {})
                words = user_text.lower().split()
                trigger_keys = [w for w in words if len(w) > 2][:5]

                learning_text = (
                    f"For '{user_text[:80]}', tool {tool_name} succeeded on first try with {args}"
                )

                learnings.append(
                    Learning(
                        category="positive_pattern",
                        trigger_keys=trigger_keys,
                        learning=learning_text,
                        tool_name=tool_name,
                        source_query=user_text[:80],
                        scope=MemoryScope.AGENT,
                    )
                )

        return learnings


class RCAExtractor:
    """Generates root cause analysis when tool loops exhaust max rounds.

    Unlike ToolCorrectionExtractor (pure function), this requires an LLM
    client to diagnose failures. Same API as Conductor's generate_rca().
    """

    def __init__(self, llm_client: object | None = None, rca_model: str = "") -> None:
        self._llm = llm_client
        self._rca_model = rca_model

    async def extract_rca(
        self,
        user_text: str,
        tool_history: list[dict[str, object]],
    ) -> Learning | None:
        """Diagnose why the tool loop failed.

        Builds a prompt from the failure history and calls a fast/cheap model.
        Returns a Learning with category='rca', or None if no failures or LLM unavailable.
        """
        failures = [
            h
            for h in tool_history
            if str(h.get("result", "")).startswith("Error")
            or "error" in str(h.get("result", ""))[:50].lower()
        ]
        if not failures:
            return None

        failure_summary = []
        for f in failures:
            failure_summary.append(
                f"Tool: {f.get('tool_name')}, "
                f"Args: {json.dumps(f.get('arguments', {}))}, "
                f"Error: {str(f.get('result', ''))[:200]}"
            )

        rca_prompt = (
            "Analyze why this tool execution failed and provide a concise root cause.\n\n"
            f"User request: {user_text[:200]}\n\n"
            f"Failed tool calls:\n" + "\n".join(failure_summary) + "\n\n"
            "Respond in exactly this format:\n"
            "ROOT CAUSE: <one sentence>\n"
            "PREVENTION: <one sentence describing how to avoid this in future>"
        )

        rca_text = await self._call_llm(rca_prompt)
        if not rca_text:
            return None

        words = user_text.lower().split()
        trigger_keys = [w for w in words if len(w) > 2][:5]
        tool_names = list({str(f.get("tool_name", "")) for f in failures})

        return Learning(
            category="rca",
            trigger_keys=trigger_keys,
            learning=rca_text.strip(),
            tool_name="|".join(tool_names),
            source_query=user_text[:200],
            scope=MemoryScope.AGENT,
        )

    async def _call_llm(self, prompt: str) -> str | None:
        """Call the LLM for RCA. Override in subclasses for different backends."""
        if self._llm is None:
            logger.debug("No LLM client configured for RCA — skipping")
            return None

        try:
            from stronghold.protocols.llm import LLMClient

            if isinstance(self._llm, LLMClient):
                result = await self._llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    model=self._rca_model,
                    max_tokens=200,
                    temperature=0.1,
                )
                # Extract content from OpenAI-format response
                choices = result.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    content: str = str(message.get("content", ""))
                    return content
        except Exception as e:
            logger.warning("RCA LLM call failed: %s", e)

        return None
