"""Frank strategy: architect pipeline with self-review loops.

Each step posts to the GitHub issue, self-reviews, and revises
until the review passes. Tests are committed as save points.
After all tests are validated, hands off to Mason (the Builder).
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

logger = logging.getLogger("stronghold.frank.strategy")

StatusCallback = Callable[[str], Coroutine[Any, Any, None]]


async def _noop_status(msg: str) -> None:
    pass


async def _heartbeat(status: StatusCallback) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(15)
        elapsed += 15
        await status(f"  thinking... ({elapsed}s)")


class FrankStrategy:
    """Architect strategy — plan, criteria, tests, then hand off."""

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

        # Helpers bound to this context
        async def ask(prompt: str) -> str:
            await status("  LLM thinking...")
            hb = asyncio.create_task(_heartbeat(status))
            try:
                r = await llm.complete([{"role": "user", "content": prompt}], model)
            finally:
                hb.cancel()
            return r.get("choices", [{}])[0].get("message", {}).get("content", "")

        async def review(output: str, criteria: str) -> tuple[bool, str]:
            """Self-review: returns (passed, feedback)."""
            r = await ask(
                f"Review this output:\n\n{output[:3000]}\n\n"
                f"Criteria: {criteria}\n\n"
                f"Answer ONLY 'PASS' or 'FAIL: <reason>'."
            )
            r = r.strip()
            return r.upper().startswith("PASS"), r

        async def comment(body: str) -> None:
            if ex:
                await ex(
                    "github",
                    {
                        "action": "post_pr_comment",
                        "owner": ctx["owner"],
                        "repo": ctx["repo"],
                        "issue_number": ctx["issue_num"],
                        "body": body,
                    },
                )

        async def write_file(path: str, content: str) -> None:
            if ex:
                await ex(
                    "file_ops",
                    {
                        "action": "write",
                        "path": path,
                        "content": content,
                        "workspace": ctx["ws_path"],
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
                    "workspace": ctx["ws_path"],
                },
            )
            s = str(r)
            return "" if "Error" in s[:20] or "not found" in s else s

        async def save(msg: str) -> None:
            if not ex:
                return
            await ex(
                "workspace",
                {
                    "action": "commit",
                    "issue_number": ctx["issue_num"],
                    "message": msg,
                },
            )
            await ex(
                "workspace",
                {
                    "action": "push",
                    "issue_number": ctx["issue_num"],
                },
            )

        n = ctx["issue_num"]
        title = ctx["title"]

        # ═══ STEP 1: Architecture Plan ═══
        await status("Step 1: Architecture plan")
        plan = ""
        for attempt in range(3):
            plan = await ask(
                f"GitHub issue #{n}: {title}\n\n"
                f"Write an architecture plan (under 300 words):\n"
                f"- What files/modules change\n"
                f"- How it fits Stronghold's existing architecture\n"
                f"- Protocols, types, interfaces needed\n"
                f"- Testing approach\n"
                f"Be specific about file paths."
            )
            passed, feedback = await review(
                plan,
                "Complete? Specific file paths? Fits existing architecture? "
                "Would a developer know exactly what to build?",
            )
            if passed:
                break
            await status(f"  Review failed (attempt {attempt + 1}): {feedback[:80]}")
            plan = await ask(
                f"Revise this architecture plan based on feedback:\n\n"
                f"{plan}\n\nFeedback: {feedback}\n\nOutput the revised plan only."
            )

        await comment(f"## Architecture Plan\n\n{plan}\n\n---\n*Frank (Architect) — Step 1*")
        await status("Step 1 complete")

        # ═══ STEP 2: Acceptance Criteria (Gherkin) ═══
        await status("Step 2: Acceptance criteria (Gherkin)")
        criteria = ""
        for attempt in range(3):
            criteria = await ask(
                f"Issue #{n}: {title}\n\n"
                f"Architecture plan:\n{plan}\n\n"
                f"Write acceptance criteria in Gherkin format:\n\n"
                f"Feature: [name]\n\n"
                f"  Scenario: [name]\n"
                f"    Given [precondition]\n"
                f"    When [action]\n"
                f"    Then [expected result]\n\n"
                f"Cover: happy path, error cases, edge cases, "
                f"multi-tenant isolation. At least 5 scenarios."
            )
            passed, feedback = await review(
                criteria,
                "All in Gherkin Given/When/Then? At least 5 scenarios? "
                "Covers happy path, errors, security, multi-tenant? "
                "Each scenario testable and falsifiable?",
            )
            if passed:
                break
            await status(f"  Review failed (attempt {attempt + 1}): {feedback[:80]}")
            criteria = await ask(
                f"Revise these acceptance criteria:\n\n{criteria}\n\n"
                f"Feedback: {feedback}\n\nOutput revised Gherkin only."
            )

        await comment(
            f"## Acceptance Criteria\n\n```gherkin\n{criteria}\n```\n\n"
            f"---\n*Frank (Architect) — Step 2*"
        )
        await status("Step 2 complete")

        # ═══ STEP 3: Evidence-driven tests ═══
        await status("Step 3: Evidence-driven tests")

        fakes_content = await read_file("tests/fakes.py")
        fakes_ctx = ""
        if fakes_content:
            fakes_ctx = f"\ntests/fakes.py (excerpt):\n{fakes_content[:1500]}\n"

        test_code = await ask(
            f"Issue #{n}: {title}\n\n"
            f"Acceptance criteria:\n```gherkin\n{criteria}\n```\n\n"
            f"{fakes_ctx}\n"
            f"Write pytest tests that validate EACH Gherkin scenario.\n"
            f"Rules:\n"
            f"- Use real classes from stronghold.*, NEVER unittest.mock\n"
            f"- Use fakes from tests/fakes.py where needed\n"
            f"- Tests should FAIL initially (TDD red phase)\n"
            f"- Test names must reference the scenario they validate\n"
            f"- Include 'from __future__ import annotations'\n\n"
            f"Output ONLY Python code. No markdown fences. Start with imports."
        )
        test_code = _strip_fences(test_code)
        test_path = _infer_test_path(plan, title)

        await write_file(test_path, test_code)
        await save(f"frank: evidence-driven tests for #{n}")
        await comment(
            f"## Evidence-Driven Tests\n\n"
            f"File: `{test_path}`\n\n"
            f"```python\n{test_code[:2000]}\n```\n"
            f"{'(truncated)' if len(test_code) > 2000 else ''}\n\n"
            f"---\n*Frank (Architect) — Step 3 (committed)*"
        )
        await status(f"Step 3 complete — committed {test_path}")

        # ═══ STEP 4: Standard TDD tests ═══
        await status("Step 4: Standard TDD tests")
        tdd_code = await ask(
            f"Issue #{n}: {title}\n\n"
            f"The evidence-driven tests are in {test_path}.\n"
            f"Now write ADDITIONAL standard unit tests:\n"
            f"- Protocol compliance (isinstance checks)\n"
            f"- Type safety (correct return types)\n"
            f"- Internal function behavior\n\n"
            f"Output ONLY Python test functions (no imports, no class). "
            f"These will be APPENDED to {test_path}."
        )
        tdd_code = _strip_fences(tdd_code)
        if "def test_" in tdd_code:
            existing = await read_file(test_path)
            combined = existing.rstrip() + "\n\n\n# --- Standard TDD tests ---\n\n" + tdd_code
            await write_file(test_path, combined)
            await save(f"frank: TDD tests for #{n}")
            await status("Step 4 complete — TDD tests committed")
        else:
            await status("Step 4: no additional tests generated")

        # ═══ STEP 5: Edge case tests ═══
        await status("Step 5: Edge case tests")
        edge_code = await ask(
            f"Issue #{n}: {title}\n\n"
            f"Write edge case tests for:\n"
            f"- Empty/null inputs, boundary values\n"
            f"- Adversarial inputs (injection, oversized)\n"
            f"- Multi-tenant isolation (wrong org_id)\n"
            f"- Error recovery\n\n"
            f"Output ONLY Python test functions. "
            f"These will be APPENDED to {test_path}."
        )
        edge_code = _strip_fences(edge_code)
        if "def test_" in edge_code:
            existing = await read_file(test_path)
            combined = existing.rstrip() + "\n\n\n# --- Edge case tests ---\n\n" + edge_code
            await write_file(test_path, combined)
            await save(f"frank: edge case tests for #{n}")
            edge_summary = "\n".join(
                line for line in edge_code.split("\n") if line.strip().startswith("def test_")
            )
            await comment(
                f"## Edge Cases\n\n"
                f"```\n{edge_summary}\n```\n\n"
                f"---\n*Frank (Architect) — Step 5 (committed)*"
            )
            await status("Step 5 complete — edge cases committed")
        else:
            await status("Step 5: no edge cases generated")

        # ═══ HANDOFF ═══
        await comment(
            f"## Ready for Mason\n\n"
            f"Tests: `{test_path}`\n"
            f"Architecture: see Step 1 above\n"
            f"Criteria: see Step 2 above\n\n"
            f"Mason: implement the code to make these tests pass. "
            f"Run quality gates before pushing.\n\n"
            f"---\n*Frank (Architect) — Handoff*"
        )
        await status("Frank complete — ready for Mason handoff")

        return ReasoningResult(
            response=(
                f"Frank completed planning for issue #{n}.\n"
                f"Tests committed to {test_path}.\n"
                f"Architecture plan + Gherkin criteria posted to issue.\n"
                f"Ready for Mason to implement."
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
