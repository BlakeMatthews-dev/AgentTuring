"""Mason strategy: Frank (Architect) then Mason (Builder) in one execution.

Same process, same workspace, same variables. Frank's prompts run first
to plan and write tests, then Mason's prompts run to implement.
No handoff, no file discovery — the test path from Frank flows directly
to Mason as a variable.

Each step is a save point (committed + documented on the issue).
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
    """Single strategy — Frank plans, Mason builds, same execution."""

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
            return ReasoningResult(
                response="Missing workspace or issue.",
                done=True,
            )

        n = ctx["issue_num"]
        ws = ctx["ws_path"]
        title = ctx["title"]

        # ── Shared helpers ──

        async def ask(prompt: str) -> str:
            hb = asyncio.create_task(_heartbeat(status))
            try:
                r = await llm.complete(
                    [{"role": "user", "content": prompt}],
                    model,
                )
            finally:
                hb.cancel()
            return r.get("choices", [{}])[0].get("message", {}).get("content", "")

        async def review(output: str, question: str) -> tuple[bool, str]:
            r = await ask(
                f"Review:\n\n{output[:3000]}\n\n{question}\n\n"
                f"Answer ONLY 'PASS' or 'FAIL: <reason>'."
            )
            return r.strip().upper().startswith("PASS"), r.strip()

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

        async def read_file(path: str) -> str:
            if not ex:
                return ""
            r = await ex(
                "file_ops",
                {
                    "action": "read",
                    "path": path,
                    "workspace": ws,
                },
            )
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
            await ex(
                "workspace",
                {
                    "action": "commit",
                    "issue_number": n,
                    "message": msg,
                },
            )
            await ex(
                "workspace",
                {
                    "action": "push",
                    "issue_number": n,
                },
            )

        # ════════════════════════════════════════════════
        # FRANK (Architect) — planning and tests
        # ════════════════════════════════════════════════

        await status("=== FRANK (Architect) ===")

        # ── Step 1: Architecture Plan ──
        await status("Frank 1/5: Architecture plan")
        plan = ""
        for _ in range(3):
            plan = await ask(
                f"GitHub issue #{n}: {title}\n\n"
                f"Architecture plan (under 300 words):\n"
                f"- What files/modules change\n"
                f"- How it fits Stronghold's architecture\n"
                f"- Protocols, types needed\n"
                f"- Testing approach\n"
                f"Be specific about file paths."
            )
            ok, fb = await review(
                plan,
                "Complete? Specific paths? Implementable?",
            )
            if ok:
                break
            await status(f"  Review: {fb[:60]}")

        await comment(f"## Architecture Plan\n\n{plan}\n\n---\n*Frank*")
        await status("Frank 1/5 done")

        # ── Step 2: Acceptance Criteria (Gherkin) ──
        await status("Frank 2/5: Acceptance criteria")
        criteria = ""
        for _ in range(3):
            criteria = await ask(
                f"Issue #{n}: {title}\n\nPlan:\n{plan}\n\n"
                f"Write acceptance criteria in Gherkin:\n\n"
                f"Feature: ...\n  Scenario: ...\n"
                f"    Given ...\n    When ...\n    Then ...\n\n"
                f"At least 5 scenarios. Cover happy path, errors, "
                f"edge cases, multi-tenant."
            )
            ok, fb = await review(
                criteria,
                "All Gherkin? 5+ scenarios? Testable? Covers errors + security + multi-tenant?",
            )
            if ok:
                break
            await status(f"  Review: {fb[:60]}")

        await comment(f"## Acceptance Criteria\n\n```gherkin\n{criteria}\n```\n\n---\n*Frank*")
        await status("Frank 2/5 done")

        # ── Step 3: Evidence-driven tests ──
        await status("Frank 3/5: Writing tests")
        fakes = await read_file("tests/fakes.py")
        fakes_ctx = f"\ntests/fakes.py (excerpt):\n{fakes[:1500]}\n" if fakes else ""

        test_code = await ask(
            f"Issue #{n}: {title}\n\n"
            f"Criteria:\n```gherkin\n{criteria}\n```\n\n"
            f"{fakes_ctx}\n"
            f"Write pytest tests validating EACH scenario.\n"
            f"- Real classes, NEVER unittest.mock\n"
            f"- Fakes from tests/fakes.py\n"
            f"- Tests should FAIL initially (TDD)\n"
            f"- Include 'from __future__ import annotations'\n\n"
            f"Output ONLY Python code. No fences. Start with imports."
        )
        test_code = _strip_fences(test_code)
        test_path = _infer_test_path(plan, title)

        await write_file(test_path, test_code)
        await save(f"frank: tests for #{n}")
        await comment(
            f"## Tests\n\nFile: `{test_path}`\n\n"
            f"```python\n{test_code[:2000]}\n```\n"
            f"---\n*Frank (committed)*"
        )
        await status(f"Frank 3/5 done — {test_path}")

        # ── Step 4: Edge case tests ──
        await status("Frank 4/5: Edge cases")
        edge_code = await ask(
            f"Issue #{n}: {title}\n\n"
            f"Add edge case tests:\n"
            f"- Empty/null inputs, boundaries\n"
            f"- Adversarial inputs\n"
            f"- Multi-tenant isolation\n"
            f"- Error recovery\n\n"
            f"Output ONLY Python test functions. No imports."
        )
        edge_code = _strip_fences(edge_code)
        if "def test_" in edge_code:
            existing = await read_file(test_path)
            combined = existing.rstrip() + "\n\n\n# --- Edge cases ---\n\n" + edge_code
            await write_file(test_path, combined)
            await save(f"frank: edge cases for #{n}")
            await status("Frank 4/5 done — edge cases committed")
        else:
            await status("Frank 4/5 — no edge cases generated")

        # ── Step 5: Frank posts handoff ──
        await comment(
            f"## Ready for Implementation\n\n"
            f"Tests: `{test_path}`\n"
            f"Criteria: see Gherkin above\n\n---\n*Frank done*"
        )
        await status("Frank 5/5 done")

        # ════════════════════════════════════════════════
        # MASON (Builder) — implementation
        # ════════════════════════════════════════════════

        await status("=== MASON (Builder) ===")

        # ── Read issue comments (human feedback, Auditor reviews, prior runs) ──
        await status("Mason: Reading issue comments")
        issue_comments = ""
        if ex:
            r = await ex(
                "github",
                {
                    "action": "list_pr_comments",
                    "owner": ctx["owner"],
                    "repo": ctx["repo"],
                    "issue_number": n,
                },
            )
            comments_str = str(r)
            if "Error" not in comments_str[:20]:
                import json as _json

                try:
                    comments_list = _json.loads(comments_str)
                    # Filter to non-Mason comments (human + Auditor feedback)
                    human_comments = [
                        c
                        for c in comments_list
                        if isinstance(c, dict)
                        and c.get("user", "") != "Mason"
                        and not c.get("body", "").startswith("## Architecture")
                        and not c.get("body", "").startswith("## Acceptance")
                        and not c.get("body", "").startswith("## Tests")
                        and not c.get("body", "").startswith("## Ready")
                        and not c.get("body", "").startswith("## Results")
                        and not c.get("body", "").startswith("## Cycle")
                        and not c.get("body", "").startswith("## Edge")
                    ]
                    if human_comments:
                        issue_comments = "\n\n".join(
                            f"Comment by {c.get('user', '?')}:\n{c.get('body', '')[:500]}"
                            for c in human_comments[-5:]  # last 5 relevant
                        )
                        await status(f"  Found {len(human_comments)} comment(s)")
                except (ValueError, TypeError):
                    pass

        # ── Step 1: Read tests (we already have them from Frank) ──
        # test_code and test_path are still in scope — no file discovery needed
        await status(f"Mason 1/5: Using tests from {test_path}")

        # Read existing source files that tests import
        existing_source = ""
        for match in re.finditer(
            r"from stronghold\.(\S+) import",
            test_code,
        ):
            mod = match.group(1).replace(".", "/") + ".py"
            fp = f"src/stronghold/{mod}"
            content = await read_file(fp)
            if content:
                existing_source += f"\n=== EXISTING: {fp} ===\n{content[:3000]}\n"

        # ── Outer loop: impl → test → gates → criteria → retry if not met ──
        max_cycles = 3
        test_output = ""
        passed = False
        criteria_met = False
        files_written = 0
        cycle = 0
        criteria_feedback = ""  # accumulates across cycles
        previous_impl = ""  # LLM's last implementation output

        for cycle in range(1, max_cycles + 1):
            await status(f"=== Build cycle {cycle}/{max_cycles} ===")

            # Implement (up to 3 attempts to get tests green)
            for attempt in range(1, 4):
                await status(f"Mason: Implementing (cycle {cycle}, attempt {attempt})")

                prompt = (
                    f"Issue #{n}: {title}\n\nTests to pass:\n```python\n{test_code[:4000]}\n```\n\n"
                )
                if issue_comments:
                    prompt += (
                        f"Reviewer/human comments on this issue:\n"
                        f"{issue_comments}\n\n"
                        f"Address this feedback in your implementation.\n\n"
                    )
                if existing_source:
                    prompt += f"Existing source (PRESERVE all):\n{existing_source[:4000]}\n\n"
                if previous_impl and cycle > 1:
                    prompt += f"Your PREVIOUS implementation:\n{previous_impl[:3000]}\n\n"
                if criteria_feedback:
                    prompt += (
                        f"CRITERIA REVIEW from previous cycle:\n"
                        f"{criteria_feedback}\n\n"
                        f"You MUST address each unmet criterion listed above.\n\n"
                    )
                if attempt > 1 and test_output:
                    prompt += f"Test run FAILED:\n```\n{test_output[:1500]}\n```\n\n"
                prompt += (
                    "Write implementation. For EACH file:\n"
                    "=== FILE: path/to/file.py ===\n"
                    "(complete content preserving existing code)\n"
                    "=== END ===\n\nOutput ONLY file blocks."
                )

                impl = await ask(prompt)
                previous_impl = impl  # save for next cycle's context
                written = await _write_file_blocks(impl, ws, ex, tool_history, status)
                files_written += written
                if written > 0:
                    await save(f"mason: #{n} cycle {cycle} attempt {attempt}")

                await status(f"Mason: Running tests (attempt {attempt})")
                test_output = await run_cmd(
                    f"python -m pytest {test_path} -v --tb=short 2>&1 | tail -30"
                )
                passed = '"passed": true' in test_output
                await status(f"  Tests: {'GREEN' if passed else 'RED'}")
                if passed:
                    break

            # Quality gates
            await status("Mason: Quality gates")
            for gate in ["ruff check src/stronghold/", "mypy src/stronghold/ --strict"]:
                await status(f"  {gate.split()[0]}")
                await run_cmd(f"{gate} 2>&1 | tail -10")

            # Acceptance criteria check
            await status("Mason: Checking acceptance criteria")
            verdict = await ask(
                f"Tests: {'PASSING' if passed else 'FAILING'}.\n\n"
                f"Output:\n```\n{test_output[:1500]}\n```\n\n"
                f"Criteria:\n```gherkin\n{criteria}\n```\n\n"
                f"Is EACH criterion met? 'YES' or 'NO: <which are not met>'"
            )
            criteria_met = verdict.strip().upper().startswith("YES")

            if criteria_met:
                await status("  Criteria: MET")
                break

            # Not met — save feedback and loop
            criteria_feedback = verdict
            await status(f"  Criteria NOT MET: {verdict[:80]}")
            await comment(
                f"## Cycle {cycle}: Criteria Not Met\n\n{verdict}\n\n"
                f"Reviewing previous work and addressing gaps.\n\n---\n*Mason*"
            )
            # Re-read source for next cycle
            existing_source = ""
            for match in re.finditer(r"from stronghold\.(\S+) import", test_code):
                mod = match.group(1).replace(".", "/") + ".py"
                fp = f"src/stronghold/{mod}"
                c = await read_file(fp)
                if c:
                    existing_source += f"\n=== EXISTING: {fp} ===\n{c[:3000]}\n"
            test_output += f"\n\nCRITERIA NOT MET:\n{verdict}"

        # ── Final results ──
        color = "GREEN" if passed else "RED"
        status_word = "COMPLETE" if (passed and criteria_met) else "INCOMPLETE"
        await comment(
            f"## Results: {status_word}\n\n"
            f"- Tests: **{color}**\n"
            f"- Criteria: **{'MET' if criteria_met else 'NOT MET'}**\n"
            f"- Files: {files_written}\n"
            f"- Cycles: {cycle}\n\n"
            f"```\n{test_output[:1000]}\n```\n\n---\n*Mason*"
        )
        await status(f"=== Pipeline {status_word} ===")

        return ReasoningResult(
            response=(
                f"Issue #{n}: Tests {color}, "
                f"criteria {'met' if criteria_met else 'not met'}, "
                f"{files_written} files."
            ),
            done=True,
            tool_history=tool_history,
        )


def _parse_context(messages: list[dict[str, Any]]) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "ws_path": "",
        "issue_num": 0,
        "owner": "",
        "repo": "",
        "title": "",
    }
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
                t = re.search(r"#\d+:?\s*(.*)", s)
                if t:
                    ctx["title"] = t.group(1).strip()
    return ctx


def _strip_fences(code: str) -> str:
    lines = code.strip().split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _infer_test_path(plan: str, title: str) -> str:
    match = re.search(r"tests/\S+\.py", plan)
    if match:
        return match.group(0)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40]
    return f"tests/test_{slug}.py"


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
            if line.strip() == "=== END ===" or (line.startswith("=== FILE:") and in_code):
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
