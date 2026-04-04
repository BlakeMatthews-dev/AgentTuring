"""React strategy: LLM → tool calls → execute → feed back → repeat.

This is the core tool loop, ported from Conductor main.py:486-609.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.strategies.react")


def _find_tool_schema(
    tools: list[dict[str, Any]] | None,
    tool_name: str,
) -> dict[str, Any]:
    """Find the parameter schema for a tool by name."""
    if not tools:
        return {}
    for tool in tools:
        fn = tool.get("function", {})
        if fn.get("name") == tool_name:
            params: dict[str, Any] = fn.get("parameters", {})
            return params
    return {}


class ReactStrategy:
    """ReAct loop: LLM call → tool dispatch → feed back → repeat."""

    def __init__(
        self,
        max_rounds: int = 3,
        force_tool_first: bool = False,
    ) -> None:
        self.max_rounds = max_rounds
        self.force_tool_first = force_tool_first

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        trace: Trace | None = None,
        warden: Any = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the ReAct loop — fully traced if trace is provided."""
        current_messages = list(messages)
        tool_history: list[dict[str, Any]] = []
        total_input_tokens = 0
        total_output_tokens = 0

        tool_choice = "required" if self.force_tool_first else "auto"

        for round_num in range(self.max_rounds + 1):
            # After first tool round, switch to auto
            if round_num > 0:
                tool_choice = "auto"

            # LLM call — traced
            if trace:
                with trace.span(f"llm_call_{round_num}") as ls:
                    ls.set_input({"model": model, "message_count": len(current_messages)})
                    response = await llm.complete(
                        current_messages,
                        model,
                        tools=tools,
                        tool_choice=tool_choice if tools else None,
                    )
                    usage = response.get("usage", {})
                    ls.set_usage(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        model=model,
                    )
            else:
                response = await llm.complete(
                    current_messages,
                    model,
                    tools=tools,
                    tool_choice=tool_choice if tools else None,
                )

            usage = response.get("usage", {})
            total_input_tokens += usage.get("prompt_tokens", 0)
            total_output_tokens += usage.get("completion_tokens", 0)

            choices = response.get("choices", [])
            choice = choices[0] if choices else {}
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                tool_calls = []

            logger.info(
                "React round %d: model=%s tool_calls=%d content_len=%d tools_sent=%d",
                round_num, model, len(tool_calls),
                len(message.get("content", "") or ""),
                len(tools) if tools else 0,
            )

            if not tool_calls or round_num >= self.max_rounds:
                content = message.get("content", "")
                return ReasoningResult(
                    response=content,
                    done=True,
                    tool_history=tool_history,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # Execute tool calls — each traced individually
            current_messages.append(message)

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                # JSON bomb protection: reject args > 32KB
                if len(raw_args) > 32768:
                    logger.warning("Tool args too large for %s: %d bytes", tool_name, len(raw_args))
                    tool_args = {}
                    tool_result = f"Error: Tool arguments too large ({len(raw_args)} bytes)"  # noqa: F841
                else:
                    try:
                        tool_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Malformed tool arguments for %s: %s",
                            tool_name,
                            raw_args[:200],
                        )
                        tool_args = {}

                # Sentinel pre-call: validate + repair tool arguments
                sentinel = kwargs.get("sentinel")
                auth = kwargs.get("auth")
                tool_blocked = False
                if sentinel is not None and auth is not None:
                    tool_schema = _find_tool_schema(tools, tool_name)
                    sentinel_verdict = await sentinel.pre_call(
                        tool_name,
                        tool_args,
                        auth,
                        tool_schema,
                    )
                    if not sentinel_verdict.allowed:
                        tool_result = f"Error: Permission denied for tool '{tool_name}'"
                        tool_blocked = True
                    elif sentinel_verdict.repaired_data:
                        tool_args = sentinel_verdict.repaired_data

                # Execute via provided executor or return error — traced
                if tool_blocked:
                    pass  # tool_result already set from sentinel denial
                elif tool_executor and callable(tool_executor):
                    if trace:
                        with trace.span(f"tool.{tool_name}") as ts:
                            ts.set_input(tool_args)
                            tool_result = await tool_executor(tool_name, tool_args)
                            tool_result_str_preview = str(tool_result)[:300]
                            tool_success = (
                                not tool_result_str_preview.startswith("Error")
                                and "error" not in tool_result_str_preview[:50].lower()
                            )
                            ts.set_output(
                                {
                                    "success": tool_success,
                                    "result_preview": tool_result_str_preview,
                                }
                            )
                    else:
                        tool_result = await tool_executor(tool_name, tool_args)
                else:
                    tool_result = f"Tool '{tool_name}' not available"

                # Tool result size cap: prevent context window / memory exhaustion
                tool_result_str = str(tool_result)
                if len(tool_result_str) > 16384:
                    tool_result_str = (
                        tool_result_str[:16384]
                        + f"\n[... truncated, {len(str(tool_result)) - 16384} bytes omitted]"
                    )

                # Sentinel post-call: Warden scan + PII filter + token optimize
                if sentinel is not None and auth is not None:
                    tool_result_str = await sentinel.post_call(
                        tool_name,
                        tool_result_str,
                        auth,
                    )
                else:
                    # Fallback: always run Warden + PII even without full Sentinel
                    if warden is not None:
                        verdict = await warden.scan(tool_result_str, "tool_result")
                        if not verdict.clean:
                            tool_result_str = (
                                f"[BLOCKED: tool result contained suspicious content: "
                                f"{', '.join(verdict.flags)}]"
                            )
                    # Always redact PII regardless of Sentinel presence
                    from stronghold.security.sentinel.pii_filter import (  # noqa: PLC0415
                        scan_and_redact,
                    )

                    tool_result_str, _ = scan_and_redact(tool_result_str)

                tool_history.append(
                    {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "result": tool_result_str,
                        "round": round_num,
                    }
                )

                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_result_str,
                    }
                )

        return ReasoningResult(
            response="Max tool rounds reached",
            done=True,
            tool_history=tool_history,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )
