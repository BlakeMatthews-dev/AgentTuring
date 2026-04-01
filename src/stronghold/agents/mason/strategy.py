"""Mason strategy: evidence-driven TDD with 8-phase execution pipeline.

Each phase runs a ReAct-style tool loop with an LLM-evaluated exit gate.
The strategy does not advance to the next phase until the gate is satisfied
or max_rounds is exhausted.

Phases are declared in agent.yaml and loaded into AgentIdentity.phases.
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
    from stronghold.types.agent import AgentIdentity

logger = logging.getLogger("stronghold.mason.strategy")

StatusCallback = Callable[[str], Coroutine[Any, Any, None]]


async def _noop_status(msg: str) -> None:
    pass


_GATE_CHECK_PROMPT = (
    "You are evaluating whether a phase exit gate has been satisfied.\n\n"
    "Phase: {phase_name}\n"
    "Exit gate criteria: {exit_gate}\n\n"
    "Work done so far in this phase:\n{work_summary}\n\n"
    "Has the exit gate been fully satisfied? Answer ONLY 'YES' or 'NO', "
    "followed by a one-sentence justification."
)

_PHASE_SYSTEM_PROMPT = (
    "You are in phase **{phase_name}** of the evidence-driven TDD pipeline.\n\n"
    "## Phase description\n{description}\n\n"
    "## Exit gate (what must be true to advance)\n{exit_gate}\n\n"
    "## Round {round_num} of {max_rounds}\n\n"
    "Work toward satisfying the exit gate. Use tools as needed. "
    "When you believe the gate is satisfied, say so explicitly."
)


class MasonStrategy:
    """8-phase evidence-driven TDD pipeline.

    Registered as 'mason' strategy in the factory. Falls back to
    ArtificerStrategy's generic loop if no phases are configured.
    """

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        identity: AgentIdentity | None = None,
        status_callback: StatusCallback | None = None,
        trace: Trace | None = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Execute the phased pipeline."""
        status = status_callback or _noop_status
        all_tool_history: list[dict[str, Any]] = []
        phase_results: list[str] = []

        phases = identity.phases if identity else ()
        if not phases:
            # No phases configured — single-pass fallback
            return await self._single_pass(
                messages,
                model,
                llm,
                tools=tools,
                tool_executor=tool_executor,
                status_callback=status,
                trace=trace,
            )

        await status(f"Starting {len(phases)}-phase pipeline")
        current_messages = list(messages)

        for phase_idx, phase in enumerate(phases):
            phase_name = phase.get("name", f"phase_{phase_idx}")
            description = phase.get("description", "")
            exit_gate = phase.get("exit_gate", "")
            max_rounds = phase.get("max_rounds", 3)

            await status(f"Phase {phase_idx + 1}/{len(phases)}: {phase_name}")
            logger.info("Mason phase %d: %s (max %d rounds)", phase_idx + 1, phase_name, max_rounds)

            phase_work: list[str] = []
            gate_satisfied = False

            for round_num in range(1, max_rounds + 1):
                # Inject phase context
                phase_prompt = _PHASE_SYSTEM_PROMPT.format(
                    phase_name=phase_name,
                    description=description,
                    exit_gate=exit_gate,
                    round_num=round_num,
                    max_rounds=max_rounds,
                )
                round_messages = list(current_messages)
                round_messages.append({"role": "user", "content": phase_prompt})

                # ReAct loop within this round
                tool_history, response_text = await self._react_round(
                    round_messages,
                    model,
                    llm,
                    tools=tools,
                    tool_executor=tool_executor,
                    status=status,
                    trace=trace,
                    span_prefix=f"{phase_name}.r{round_num}",
                )
                all_tool_history.extend(tool_history)
                phase_work.append(response_text)

                # Append the work to conversation memory
                current_messages.append({"role": "assistant", "content": response_text})

                # Check exit gate
                if exit_gate:
                    gate_satisfied = await self._check_exit_gate(
                        phase_name,
                        exit_gate,
                        "\n".join(phase_work),
                        model,
                        llm,
                        trace=trace,
                    )
                    if gate_satisfied:
                        await status(f"Phase {phase_name}: gate satisfied (round {round_num})")
                        logger.info(
                            "Phase %s: exit gate satisfied at round %d",
                            phase_name,
                            round_num,
                        )
                        break

                await asyncio.sleep(1)

            if not gate_satisfied and exit_gate:
                await status(f"Phase {phase_name}: max rounds reached, advancing")
                logger.warning(
                    "Phase %s: exit gate NOT satisfied after %d rounds",
                    phase_name,
                    max_rounds,
                )

            phase_results.append(
                f"## Phase {phase_idx + 1}: {phase_name}\n"
                f"Gate: {'SATISFIED' if gate_satisfied else 'MAX_ROUNDS'}\n"
                f"Rounds: {min(round_num, max_rounds)}/{max_rounds}\n"
                f"{'---'.join(phase_work[-1:])}"
            )

        await status("Pipeline complete")
        return ReasoningResult(
            response="\n\n".join(phase_results),
            done=True,
            tool_history=all_tool_history,
        )

    async def _react_round(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        status: StatusCallback = _noop_status,
        trace: Trace | None = None,
        span_prefix: str = "round",
    ) -> tuple[list[dict[str, Any]], str]:
        """Single ReAct round: LLM call -> tool execution loop -> text response."""
        tool_history: list[dict[str, Any]] = []
        current = list(messages)

        for step in range(15):  # max tool calls per round
            if trace:
                with trace.span(f"{span_prefix}.llm_{step}") as sp:
                    sp.set_input({"model": model, "msgs": len(current)})
                    response = await llm.complete(current, model, tools=tools, tool_choice="auto")
                    usage = response.get("usage", {})
                    sp.set_usage(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        model=model,
                    )
            else:
                response = await llm.complete(current, model, tools=tools, tool_choice="auto")

            choices = response.get("choices", [])
            message = choices[0].get("message", {}) if choices else {}
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                tool_calls = []

            if not tool_calls:
                return tool_history, message.get("content", "")

            current.append(message)
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                await status(f"  {tool_name}...")
                if tool_executor and callable(tool_executor):
                    if trace:
                        with trace.span(f"tool.{tool_name}") as ts:
                            ts.set_input(tool_args)
                            result = await tool_executor(tool_name, tool_args)
                            ts.set_output({"preview": str(result)[:200]})
                    else:
                        result = await tool_executor(tool_name, tool_args)
                else:
                    result = f"Tool '{tool_name}' not available"

                tool_history.append(
                    {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "result": result,
                    }
                )
                current.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": str(result),
                    }
                )

            await asyncio.sleep(0.5)

        return tool_history, "Max tool calls reached in round"

    async def _check_exit_gate(
        self,
        phase_name: str,
        exit_gate: str,
        work_summary: str,
        model: str,
        llm: LLMClient,
        *,
        trace: Trace | None = None,
    ) -> bool:
        """Ask the LLM whether the exit gate has been satisfied."""
        prompt = _GATE_CHECK_PROMPT.format(
            phase_name=phase_name,
            exit_gate=exit_gate,
            work_summary=work_summary[:3000],
        )
        gate_messages = [{"role": "user", "content": prompt}]

        if trace:
            with trace.span(f"{phase_name}.gate_check") as gs:
                gs.set_input({"exit_gate": exit_gate})
                response = await llm.complete(gate_messages, model)
                content = str(
                    response.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                satisfied = content.strip().upper().startswith("YES")
                gs.set_output({"satisfied": satisfied, "response": content[:200]})
        else:
            response = await llm.complete(gate_messages, model)
            content = str(response.get("choices", [{}])[0].get("message", {}).get("content", ""))
            satisfied = content.strip().upper().startswith("YES")

        verdict = "PASS" if satisfied else "FAIL"
        logger.info("Gate check [%s]: %s -> %s", phase_name, exit_gate[:60], verdict)
        return satisfied

    async def _single_pass(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        status_callback: StatusCallback = _noop_status,
        trace: Trace | None = None,
    ) -> ReasoningResult:
        """Fallback: no phases configured, single ReAct loop."""
        await status_callback("No phases configured — single pass")
        tool_history, response = await self._react_round(
            messages,
            model,
            llm,
            tools=tools,
            tool_executor=tool_executor,
            status=status_callback,
            trace=trace,
        )
        return ReasoningResult(
            response=response,
            done=True,
            tool_history=tool_history,
        )
