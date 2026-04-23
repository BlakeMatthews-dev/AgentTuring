"""Artificer strategy: plan → architect → phase loop (code → check → fix → commit).

This is the real engineering workflow, not a single-shot LLM call.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.artificer")

# Type for async status callback
StatusCallback = Callable[[str], Coroutine[Any, Any, None]]


async def _noop_status(msg: str) -> None:
    pass


_MAX_ARG_BYTES = 32_768
_MAX_RESULT_BYTES = 16_384


class ArtificerStrategy:
    """Multi-phase engineering workflow.

    1. Plan: decompose into phases
    2. For each phase:
       a. Write code (via write_file tool)
       b. Run quality checks (pytest, ruff, mypy, bandit)
       c. If fail: fix and recheck (max 2 retries)
       d. Commit when green
    3. Return summary of all phases
    """

    def __init__(
        self,
        max_phases: int = 5,
        max_retries_per_phase: int = 2,
    ) -> None:
        self.max_phases = max_phases
        self.max_retries = max_retries_per_phase

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        status_callback: StatusCallback | None = None,
        trace: Trace | None = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the full plan-execute workflow — fully traced."""
        tool_history: list[dict[str, Any]] = []
        status = status_callback or _noop_status

        # Phase 1: Plan — traced
        await status("Planning...")
        if trace:
            with trace.span("artificer.plan") as ps:
                ps.set_input({"model": model, "message_count": len(messages)})
                plan = await self._plan(messages, model, llm)
                ps.set_output({"plan_length": len(plan), "plan_lines": plan.count("\n")})
        else:
            plan = await self._plan(messages, model, llm)

        await status(f"Plan complete ({plan.count(chr(10))} lines)")
        logger.info("Artificer plan generated: %d chars", len(plan))

        # Brief pause between plan and execute to avoid rate limits
        await asyncio.sleep(2)

        # Phase 2: Execute each step with tool calls
        results: list[str] = [f"## Plan\n{plan}"]
        current_messages = list(messages)
        current_messages.append({"role": "assistant", "content": plan})

        execute_prompt = (
            "Now execute the plan above. For each step:\n"
            "1. Use write_file to create/modify files\n"
            "2. Use run_pytest to verify tests pass\n"
            "3. Use run_ruff_check and run_mypy to verify code quality\n"
            "4. Use git_commit when a step is complete\n\n"
            "Execute step by step. Start with step 1."
        )
        current_messages.append({"role": "user", "content": execute_prompt})

        await status("Executing plan...")

        for round_num in range(self.max_phases * 3):
            # LLM call — traced
            if trace:
                with trace.span(f"llm_call_{round_num}") as ls:
                    ls.set_input({"model": model, "message_count": len(current_messages)})
                    response = await llm.complete(
                        current_messages,
                        model,
                        tools=tools,
                        tool_choice="auto",
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
                    tool_choice="auto",
                )

            choices = response.get("choices", [])
            choice = choices[0] if choices else {}
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                tool_calls = []

            if not tool_calls:
                content = message.get("content", "")
                results.append(f"\n## Result\n{content}")
                await status("Complete")
                return ReasoningResult(
                    response="\n\n".join(results),
                    done=True,
                    tool_history=tool_history,
                )

            # Execute tool calls — each traced
            current_messages.append(message)

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    logger.warning(
                        "Malformed tool arguments for %s: %s",
                        tool_name,
                        fn.get("arguments", "")[:200],
                    )
                    tool_args = {}

                # Arg size check: reject oversized tool arguments (JSON bomb)
                raw_arg_bytes = len(fn.get("arguments", "{}").encode("utf-8"))
                if raw_arg_bytes > _MAX_ARG_BYTES:
                    logger.warning(
                        "Tool %s arg size %d exceeds %d limit",
                        tool_name,
                        raw_arg_bytes,
                        _MAX_ARG_BYTES,
                    )
                    tool_result = f"Error: tool arguments exceed {_MAX_ARG_BYTES} byte limit"
                    result_str = tool_result
                    tool_history.append(
                        {
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "result": tool_result,
                            "round": round_num,
                        }
                    )
                    current_messages.append(
                        {"role": "tool", "tool_call_id": tc.get("id", ""), "content": result_str}
                    )
                    continue

                # Sentinel pre_call: permission check + schema validation
                sentinel = kwargs.get("sentinel")
                auth = kwargs.get("auth")
                tool_blocked = False
                if sentinel is not None and auth is not None:
                    sentinel_verdict = await sentinel.pre_call(
                        tool_name,
                        tool_args,
                        auth,
                        {},
                    )
                    if not sentinel_verdict.allowed:
                        tool_result = f"Error: Permission denied for tool '{tool_name}'"
                        tool_blocked = True
                    elif sentinel_verdict.repaired_data:
                        tool_args = sentinel_verdict.repaired_data

                await status(f"Running {tool_name}...")
                logger.info("Tool call: %s(%s)", tool_name, list(tool_args.keys()))

                if tool_blocked:
                    pass
                elif tool_executor and callable(tool_executor):
                    if trace:
                        with trace.span(f"tool.{tool_name}") as ts:
                            ts.set_input(tool_args)
                            tool_result = await tool_executor(tool_name, tool_args)
                            result_preview = str(tool_result)[:300]
                            tool_success = (
                                '"passed": true' in result_preview
                                or '"status": "ok"' in result_preview
                                or (
                                    not result_preview.startswith("Error")
                                    and "error" not in result_preview[:50].lower()
                                )
                            )
                            ts.set_output(
                                {
                                    "success": tool_success,
                                    "result_preview": result_preview,
                                }
                            )
                    else:
                        tool_result = await tool_executor(tool_name, tool_args)
                else:
                    tool_result = f"Tool '{tool_name}' not available"

                # Result truncation: cap tool results to prevent context window exhaustion
                result_str = tool_result if isinstance(tool_result, str) else str(tool_result)
                if len(result_str) > _MAX_RESULT_BYTES:
                    result_str = (
                        result_str[:_MAX_RESULT_BYTES]
                        + f"\n[... truncated, {len(str(tool_result)) - _MAX_RESULT_BYTES} bytes omitted]"
                    )

                # Sentinel post_call: Warden scan + PII filter
                if sentinel is not None and auth is not None:
                    result_str = await sentinel.post_call(tool_name, result_str, auth)

                # Log result summary
                result_preview = result_str[:200]
                if '"passed": true' in result_preview or '"status": "ok"' in result_preview:
                    await status(f"{tool_name}: OK")
                elif '"passed": false' in result_preview:
                    await status(f"{tool_name}: FAILED — fixing...")
                elif '"error":' in result_preview and '"status": "failed"' in result_preview:
                    await status(f"{tool_name}: error — retrying...")

                tool_history.append(
                    {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "result": tool_result,
                        "round": round_num,
                    }
                )

                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result_str,
                    }
                )

            # Pause between rounds to avoid rate limits
            await asyncio.sleep(1)

        await status("Max rounds reached")
        return ReasoningResult(
            response="\n\n".join(results) + "\n\nMax rounds reached.",
            done=True,
            tool_history=tool_history,
        )

    async def _plan(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
    ) -> str:
        """Generate a plan by asking the LLM to decompose the task."""
        plan_messages = list(messages)
        plan_messages.append(
            {
                "role": "user",
                "content": (
                    "Before writing any code, create a detailed plan. "
                    "Break the task into numbered phases. For each phase:\n"
                    "- What files to create/modify\n"
                    "- What tests to write\n"
                    "- What the acceptance criteria are\n\n"
                    "Output ONLY the plan, no code yet."
                ),
            }
        )

        response = await llm.complete(plan_messages, model)
        choices = response.get("choices", [])
        choice = choices[0] if choices else {}
        content: str = choice.get("message", {}).get("content", "No plan generated")
        return content
