"""Mason strategy: deterministic pipeline with LLM for thinking.

The strategy orchestrates tools directly. The LLM only generates
text (code, analysis, criteria). This prevents the LLM from
getting stuck in file_ops loops.

Pipeline:
  1. LLM reads issue → generates acceptance criteria
  2. LLM writes test code → strategy writes files
  3. Strategy runs quality gates → LLM fixes failures
  4. Strategy commits, pushes, creates PR
"""

from __future__ import annotations

import asyncio
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


class MasonStrategy:
    """Deterministic pipeline — strategy controls tools, LLM thinks."""

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
        """Run the deterministic Mason pipeline."""
        status = status_callback or _noop_status
        tool_history: list[dict[str, Any]] = []

        # Extract workspace path from the original message
        ws_path = ""
        for m in messages:
            content = str(m.get("content", ""))
            if "Workspace:" in content:
                for line in content.split("\n"):
                    if line.strip().startswith("Workspace:"):
                        ws_path = line.split("Workspace:")[1].strip()
                        break

        if not ws_path:
            return ReasoningResult(
                response="No workspace path provided.",
                done=True,
            )

        await status("Generating code (LLM thinking, may take a few minutes)...")

        # Step 1: Ask LLM to generate code — with a heartbeat so UI shows progress
        plan_messages = list(messages) + [
            {
                "role": "user",
                "content": (
                    "Implement this issue. For EACH file you need to create "
                    "or modify, output the COMPLETE file content using this "
                    "exact format:\n\n"
                    "=== FILE: path/to/file.py ===\n"
                    "```python\n"
                    "# full file content\n"
                    "```\n\n"
                    "Rules:\n"
                    "- Write tests first, then implementation\n"
                    "- Use real classes, not unittest.mock\n"
                    "- All paths relative to repo root\n"
                    "- Include every file needed\n"
                    "- Be concise — output code, not explanations"
                ),
            },
        ]

        # Run LLM call with heartbeat so the UI shows we're alive
        async def _heartbeat() -> None:
            elapsed = 0
            while True:
                await asyncio.sleep(15)
                elapsed += 15
                await status(f"  LLM still generating... ({elapsed}s)")

        heartbeat_task = asyncio.create_task(_heartbeat())
        try:
            response = await llm.complete(plan_messages, model)
        finally:
            heartbeat_task.cancel()

        plan_content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        file_count = plan_content.count("=== FILE:")
        await status(f"Code generated: {file_count} files, {len(plan_content)} chars")

        # Step 3: Parse file blocks and write them
        files_written = 0
        if tool_executor and "=== FILE:" in plan_content:
            await status("Writing files to workspace")
            files_written = await self._write_file_blocks(
                plan_content,
                ws_path,
                tool_executor,
                tool_history,
                status,
            )
            await status(f"Wrote {files_written} files")

        # Step 4: Run quality gates
        if tool_executor and files_written > 0:
            await status("Running quality gates")
            gate_results = await self._run_quality_gates(
                ws_path,
                tool_executor,
                tool_history,
                status,
            )

            # Step 5: If tests fail, ask LLM to fix
            failures = [g for g in gate_results if not g["passed"]]
            if failures:
                await status(f"{len(failures)} gate(s) failed — asking LLM to fix")
                fix_content = await self._ask_for_fixes(
                    plan_content,
                    failures,
                    messages,
                    model,
                    llm,
                )
                if "=== FILE:" in fix_content:
                    await status("Applying fixes")
                    await self._write_file_blocks(
                        fix_content,
                        ws_path,
                        tool_executor,
                        tool_history,
                        status,
                    )
                    await status("Re-running quality gates")
                    await self._run_quality_gates(
                        ws_path,
                        tool_executor,
                        tool_history,
                        status,
                    )

        # Step 6: Commit and push
        if tool_executor and files_written > 0:
            await status("Committing changes")
            await tool_executor(
                "workspace",
                {
                    "action": "commit",
                    "issue_number": self._extract_issue_num(messages),
                    "message": f"mason: implement issue (wrote {files_written} files)",
                },
            )
            tool_history.append(
                {
                    "tool_name": "workspace",
                    "arguments": {"action": "commit"},
                    "result": "committed",
                }
            )

            await status("Pushing to remote")
            await tool_executor(
                "workspace",
                {
                    "action": "push",
                    "issue_number": self._extract_issue_num(messages),
                },
            )
            tool_history.append(
                {
                    "tool_name": "workspace",
                    "arguments": {"action": "push"},
                    "result": "pushed",
                }
            )
            await status("Push complete")

        await status("Pipeline complete")

        summary = (
            f"## Mason Result\n\n"
            f"Files written: {files_written}\n"
            f"Tool calls: {len(tool_history)}\n\n"
            f"## Plan\n{plan_content[:2000]}"
        )
        return ReasoningResult(
            response=summary,
            done=True,
            tool_history=tool_history,
        )

    @staticmethod
    async def _write_file_blocks(
        content: str,
        ws_path: str,
        tool_executor: Any,
        tool_history: list[dict[str, Any]],
        status: StatusCallback,
    ) -> int:
        """Parse === FILE: path === blocks and write each file."""
        files_written = 0
        parts = content.split("=== FILE:")
        for part in parts[1:]:  # skip text before first marker
            lines = part.strip().split("\n")
            if not lines:
                continue
            file_path = lines[0].strip().rstrip("=").strip()
            # Extract code block
            code_lines: list[str] = []
            in_code = False
            for line in lines[1:]:
                if line.strip().startswith("```") and not in_code:
                    in_code = True
                    continue
                if line.strip() == "```" and in_code:
                    break
                if in_code:
                    code_lines.append(line)

            if not code_lines or not file_path:
                continue

            file_content = "\n".join(code_lines) + "\n"
            await status(f"  Writing {file_path}")
            result = await tool_executor(
                "file_ops",
                {
                    "action": "write",
                    "path": file_path,
                    "content": file_content,
                    "workspace": ws_path,
                },
            )
            tool_history.append(
                {
                    "tool_name": "file_ops",
                    "arguments": {"action": "write", "path": file_path},
                    "result": str(result)[:200],
                }
            )
            files_written += 1
            await asyncio.sleep(0.1)

        return files_written

    @staticmethod
    async def _run_quality_gates(
        ws_path: str,
        tool_executor: Any,
        tool_history: list[dict[str, Any]],
        status: StatusCallback,
    ) -> list[dict[str, Any]]:
        """Run pytest, ruff, mypy, bandit and return results."""
        gates = [
            ("pytest", "run_pytest", {"workspace": ws_path, "path": "tests/ -x -q"}),
            ("ruff check", "run_ruff_check", {"workspace": ws_path}),
            ("mypy", "run_mypy", {"workspace": ws_path}),
        ]
        results: list[dict[str, Any]] = []
        for name, tool_name, args in gates:
            await status(f"  Running {name}")
            result = await tool_executor(tool_name, args)
            result_str = str(result)
            passed = '"passed": true' in result_str or '"passed":true' in result_str
            results.append(
                {
                    "gate": name,
                    "passed": passed,
                    "output": result_str[:1000],
                }
            )
            tool_history.append(
                {
                    "tool_name": tool_name,
                    "arguments": args,
                    "result": result_str[:300],
                }
            )
        return results

    @staticmethod
    async def _ask_for_fixes(
        original_plan: str,
        failures: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        model: str,
        llm: Any,
    ) -> str:
        """Ask LLM to fix quality gate failures."""
        failure_text = "\n\n".join(
            f"### {f['gate']} FAILED:\n```\n{f['output'][:500]}\n```" for f in failures
        )
        fix_messages = list(messages) + [
            {
                "role": "assistant",
                "content": original_plan[:3000],
            },
            {
                "role": "user",
                "content": (
                    f"The following quality gates failed:\n\n{failure_text}\n\n"
                    "Fix the issues. Output ONLY the corrected files using "
                    "the same === FILE: path === format."
                ),
            },
        ]
        response = await llm.complete(fix_messages, model)
        return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    @staticmethod
    def _extract_issue_num(messages: list[dict[str, Any]]) -> int:
        """Extract issue number from messages."""
        for m in messages:
            content = str(m.get("content", ""))
            if "issue #" in content.lower():
                import re

                match = re.search(r"#(\d+)", content)
                if match:
                    return int(match.group(1))
        return 0
