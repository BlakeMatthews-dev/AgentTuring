"""Mason (Builder) strategy: implement code to pass committed tests.

Mason receives a workspace with tests already committed by Frank
(the Architect). Mason's job:
  1. Read the tests
  2. Write implementation code
  3. Run tests — loop until GREEN
  4. Run quality gates — loop until clean
  5. Verify acceptance criteria are met
  6. Push and create PR
"""

from __future__ import annotations

import asyncio
import logging
import re
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


async def _heartbeat(status: StatusCallback) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(15)
        elapsed += 15
        await status(f"  thinking... ({elapsed}s)")


class MasonStrategy:
    """Builder strategy — write code, loop until tests pass."""

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
        status = status_callback or _noop_status
        tool_history: list[dict[str, Any]] = []
        ex = tool_executor

        ctx = _parse_context(messages)
        if not ctx["ws_path"] or not ctx["issue_num"]:
            return ReasoningResult(response="Missing workspace or issue.", done=True)

        n = ctx["issue_num"]
        ws = ctx["ws_path"]

        async def ask(prompt: str) -> str:
            hb = asyncio.create_task(_heartbeat(status))
            try:
                r = await llm.complete([{"role": "user", "content": prompt}], model)
            finally:
                hb.cancel()
            return r.get("choices", [{}])[0].get("message", {}).get("content", "")

        async def read_file(path: str) -> str:
            if not ex:
                return ""
            r = await ex("file_ops", {"action": "read", "path": path, "workspace": ws})
            s = str(r)
            return "" if "Error" in s[:20] or "not found" in s else s

        async def write_file(path: str, content: str) -> None:
            if ex:
                await ex(
                    "file_ops",
                    {
                        "action": "write",
                        "path": path,
                        "content": content,
                        "workspace": ws,
                    },
                )

        async def run_cmd(cmd: str) -> str:
            if not ex:
                return ""
            r = await ex("shell", {"command": cmd, "workspace": ws})
            return str(r)[:3000]

        async def save(msg: str) -> None:
            if not ex:
                return
            await ex("workspace", {"action": "commit", "issue_number": n, "message": msg})
            await ex("workspace", {"action": "push", "issue_number": n})

        async def comment(body: str) -> None:
            if ex:
                await ex(
                    "github",
                    {
                        "action": "post_pr_comment",
                        "owner": ctx["owner"],
                        "repo": ctx["repo"],
                        "issue_number": n,
                        "body": body,
                    },
                )

        # ═══ STEP 1: Read tests ═══
        await status("Step 1: Reading committed tests")

        # Find test files in the workspace
        find_cmd = (
            "find tests/ -name 'test_*.py' -newer .git/HEAD "
            "2>/dev/null || find tests/ -name 'test_*.py' 2>/dev/null"
        )
        test_files_raw = await run_cmd(find_cmd)
        test_files = [f.strip() for f in test_files_raw.split("\n") if f.strip().endswith(".py")][
            :5
        ]

        test_content = ""
        for tf in test_files:
            content = await read_file(tf)
            if content:
                test_content += f"\n=== {tf} ===\n{content[:3000]}\n"

        if not test_content:
            await status("No test files found — running Frank first")
            return ReasoningResult(
                response="No test files found. Run Frank (Architect) first.",
                done=True,
            )

        await status(f"Read {len(test_files)} test file(s)")

        # Read existing source files that tests import
        impl_files: list[str] = []
        for match in re.finditer(r"from stronghold\.(\S+) import", test_content):
            mod_path = match.group(1).replace(".", "/") + ".py"
            impl_files.append(f"src/stronghold/{mod_path}")
        impl_files = list(dict.fromkeys(impl_files))[:10]

        existing_source = ""
        for fp in impl_files:
            content = await read_file(fp)
            if content:
                existing_source += f"\n=== EXISTING: {fp} ===\n{content[:3000]}\n"

        # ═══ STEP 2: Write implementation (loop until tests pass) ═══
        max_attempts = 3
        test_output = ""
        passed = False

        for attempt in range(1, max_attempts + 1):
            await status(f"Step 2: Writing implementation (attempt {attempt}/{max_attempts})")

            prompt = f"Issue #{n}: {ctx['title']}\n\nTests to pass:\n{test_content[:4000]}\n\n"
            if existing_source:
                prompt += (
                    f"Existing source files (PRESERVE all existing code):\n"
                    f"{existing_source[:4000]}\n\n"
                )
            if attempt > 1 and test_output:
                prompt += f"Previous test run FAILED:\n```\n{test_output[:1500]}\n```\n\n"

            prompt += (
                "Write implementation to make the tests pass.\n"
                "For EACH file, output:\n"
                "=== FILE: path/to/file.py ===\n"
                "(complete file content preserving ALL existing code)\n"
                "=== END ===\n\n"
                "Output ONLY file blocks. No explanations."
            )

            impl = await ask(prompt)
            files_written = await _write_file_blocks(impl, ws, ex, tool_history, status)

            if files_written == 0 and attempt == 1:
                await status("No files generated — retrying")
                continue

            if files_written > 0:
                await save(f"mason: implement #{n} (attempt {attempt}, {files_written} files)")

            # Run tests
            await status(f"Step 3: Running tests (attempt {attempt})")
            test_output = await run_cmd(
                f"python -m pytest {' '.join(test_files)} -v --tb=short 2>&1 | tail -40"
            )
            passed = '"passed": true' in test_output
            color = "GREEN" if passed else "RED"
            await status(f"  Tests: {color}")

            if passed:
                break

        # ═══ STEP 4: Quality gates ═══
        await status("Step 4: Quality gates")
        gates_clean = True
        for gate_name, gate_cmd in [
            ("ruff check", "ruff check src/stronghold/ 2>&1 | tail -10"),
            ("mypy", "mypy src/stronghold/ --strict 2>&1 | tail -10"),
        ]:
            await status(f"  Running {gate_name}")
            result = await run_cmd(gate_cmd)
            gate_passed = '"passed": true' in result or "Success" in result
            if not gate_passed:
                gates_clean = False
                await status(f"  {gate_name}: issues found")

        if gates_clean:
            await status("Step 4 complete — all gates clean")

        # ═══ STEP 5: Acceptance criteria check ═══
        await status("Step 5: Verifying acceptance criteria")

        # Read the issue comments to find Frank's Gherkin criteria
        criteria_check = await ask(
            f"The tests for issue #{n} are {'PASSING' if passed else 'FAILING'}.\n\n"
            f"Test output:\n```\n{test_output[:1500]}\n```\n\n"
            f"Based on this test output, are ALL acceptance criteria met?\n"
            f"Answer 'YES' or 'NO: <which criteria are not met>'."
        )
        criteria_met = criteria_check.strip().upper().startswith("YES")
        await status(f"  Acceptance criteria: {'MET' if criteria_met else 'NOT MET'}")

        if not criteria_met and passed:
            await status("  Tests pass but criteria not met — needs more work")

        # ═══ STEP 6: Final push + document ═══
        await status("Step 6: Final push")
        if not passed:
            await save(f"mason: WIP #{n} (tests RED)")

        color = "GREEN" if passed else "RED"
        await comment(
            f"## Mason (Builder) Complete\n\n"
            f"- Tests: **{color}**\n"
            f"- Quality gates: {'clean' if gates_clean else 'issues found'}\n"
            f"- Acceptance criteria: {'MET' if criteria_met else 'NOT MET'}\n"
            f"- Attempts: {attempt}\n\n"
            f"```\n{test_output[:1000]}\n```\n\n"
            f"---\n*Mason (Builder)*"
        )
        await status("Mason complete")

        return ReasoningResult(
            response=(
                f"Mason {'completed' if passed else 'attempted'} issue #{n}. "
                f"Tests: {color}. Gates: {'clean' if gates_clean else 'dirty'}. "
                f"Criteria: {'met' if criteria_met else 'not met'}."
            ),
            done=True,
            tool_history=tool_history,
        )


def _parse_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    ctx: dict[str, Any] = {"ws_path": "", "issue_num": 0, "owner": "", "repo": "", "title": ""}
    for m in messages:
        c = str(m.get("content", ""))
        for line in c.split("\n"):
            s = line.strip()
            if s.startswith("Workspace:"):
                ctx["ws_path"] = s.split(":", 1)[1].strip()
            elif s.startswith("Repository:"):
                parts = s.split(":", 1)[1].strip().split("/")
                if len(parts) == 2:
                    ctx["owner"] = parts[0].strip()
                    ctx["repo"] = parts[1].strip()
            elif "issue #" in s.lower():
                match = re.search(r"#(\d+)", s)
                if match:
                    ctx["issue_num"] = int(match.group(1))
                title_match = re.search(r"#\d+:?\s*(.*)", s)
                if title_match:
                    ctx["title"] = title_match.group(1).strip()
    return ctx


async def _write_file_blocks(
    content: str,
    ws_path: str,
    tool_executor: Any,
    tool_history: list[dict[str, Any]],
    status: StatusCallback,
) -> int:
    files_written = 0
    parts = content.split("=== FILE:")
    for part in parts[1:]:
        lines = part.strip().split("\n")
        if not lines:
            continue
        file_path = lines[0].strip().rstrip("=").strip()
        code_lines: list[str] = []
        in_code = False
        for line in lines[1:]:
            if line.strip() == "=== END ===" or line.startswith("=== FILE:"):
                break
            if line.strip().startswith("```") and not in_code:
                in_code = True
                continue
            if line.strip() == "```" and in_code:
                break
            if not in_code and not line.strip().startswith("```"):
                in_code = True
            if in_code:
                code_lines.append(line)

        if not code_lines or not file_path:
            continue

        file_content = "\n".join(code_lines).rstrip() + "\n"
        await status(f"  Writing {file_path}")
        await tool_executor(
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
                "result": f"wrote {len(file_content)} bytes",
            }
        )
        files_written += 1
        await asyncio.sleep(0.1)

    return files_written
