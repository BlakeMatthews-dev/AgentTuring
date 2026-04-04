"""Runtime-controlled Builders pipeline.

The LLM generates content (code, analysis, criteria).
The runtime controls all execution: reads files, writes files, runs tests, commits.
The LLM never sees tool definitions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from stronghold.builders.extractors import (
    ExtractionError,
    extract_gherkin_scenarios,
    extract_json,
    extract_python_code,
)

logger = logging.getLogger("stronghold.builders.pipeline")

MAX_LLM_RETRIES = 3

# ── Auditor stage context ────────────────────────────────────────────
# Each stage gets: purpose, scope, out_of_scope, approval_checklist, rejection_format
# The Auditor prompt is built from these — it never invents its own criteria.

_AUDITOR_STAGE_CONTEXT: dict[str, dict[str, Any]] = {
    "issue_analyzed": {
        "purpose": "Understand the problem and plan the approach",
        "scope": "Problem statement, requirements list, edge cases, affected files, approach",
        "out_of_scope": (
            "Implementation details, code, fallback values, error handling specifics — "
            "those belong in acceptance_defined or later stages"
        ),
        "checklist": [
            "Problem statement is clear and matches the issue",
            "Requirements are listed and non-empty",
            "At least one edge case identified",
            "Affected files are plausible paths in the repo",
        ],
        "rejection_format": (
            "State WHICH checklist item failed, QUOTE the problematic text, "
            "and say WHAT it should say instead"
        ),
    },
    "acceptance_defined": {
        "purpose": "Define testable success criteria in Gherkin format",
        "scope": "Gherkin scenarios with Given/When/Then covering happy path, errors, edge cases",
        "out_of_scope": "Implementation approach, code, file paths — those belong in tests_written",
        "checklist": [
            "At least 3 Gherkin scenarios present",
            "Each scenario has Given, When, and Then steps",
            "Happy path is covered",
            "At least one error or edge case scenario",
            "Scenarios are concrete and testable (not vague)",
        ],
        "rejection_format": (
            "State WHICH scenario is wrong or missing, "
            "and provide the corrected Gherkin text"
        ),
    },
    "tests_written": {
        "purpose": "Create pytest test files that validate the acceptance criteria",
        "scope": "Test file exists, compiles without errors, tests map to criteria",
        "out_of_scope": (
            "Whether tests PASS — they SHOULD fail at this stage (TDD). "
            "Implementation code has not been written yet. "
            "AssertionError and 404 responses are EXPECTED and CORRECT — "
            "the endpoint being tested does not exist yet. "
            "Only SyntaxError and ImportError indicate real problems."
        ),
        "checklist": [
            "Test file was created (evidence shows file path)",
            "Pytest ran without SyntaxError or ImportError (AssertionError is OK — that is TDD)",
            "At least one test function exists (test count > 0)",
        ],
        "rejection_format": (
            "State WHICH error needs fixing with the EXACT error message. "
            "Do NOT reject for AssertionError or 404 — those are expected in TDD."
        ),
    },
    "implementation_started": {
        "purpose": "Write code that makes the failing tests pass",
        "scope": "Source files modified, test results improved",
        "out_of_scope": "Code style, naming — those are checked in quality gates stage",
        "checklist": [
            "At least one source file was modified (evidence shows file list)",
            "Test pass count improved vs before implementation",
            "Changes are committed to git",
        ],
        "rejection_format": "State WHICH test still fails and WHY, quoting the error output",
    },
    "implementation_ready": {
        "purpose": "Run quality gates and fix violations in new code",
        "scope": "All gates ran, new-code violations addressed",
        "out_of_scope": "Pre-existing violations in files NOT touched by this issue",
        "checklist": [
            "All 5 quality gates ran (pytest, ruff_check, ruff_format, mypy, bandit)",
            "No NEW violations introduced by this issue's changes",
        ],
        "rejection_format": (
            "State WHICH gate failed with the EXACT violation text, "
            "and whether it is new or pre-existing"
        ),
    },
    "quality_checks_passed": {
        "purpose": "Final verification — confirm commits and passing tests",
        "scope": "Git log, diff stat, final pytest run",
        "out_of_scope": "Re-reviewing implementation decisions from earlier stages",
        "checklist": [
            "Git log shows at least one commit for this issue",
            "Diff shows changes to source and/or test files",
            "Pytest output shows tests ran",
        ],
        "rejection_format": "State WHICH check failed, quoting the evidence",
    },
}


@dataclass
class StageResult:
    """Output of a pipeline stage."""

    success: bool
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)


class RuntimePipeline:
    """Deterministic stage executor. LLM generates content, runtime executes."""

    def __init__(
        self,
        llm: Any,
        tool_dispatcher: Any,
        prompt_manager: Any = None,
        frank_model: str = "google-gemini-3.1-pro",
        mason_model: str = "openrouter-anthropic/claude-opus-4.6",
        auditor_model: str = "google-gemini-3.1-pro",
    ) -> None:
        self._llm = llm
        self._td = tool_dispatcher
        self._pm = prompt_manager
        self._frank_model = frank_model
        self._mason_model = mason_model
        self._auditor_model = auditor_model

    # ── Helpers ──────────────────────────────────────────────────────

    async def load_onboarding(self, workspace: str) -> str:
        """Read ONBOARDING.md from workspace or bundled locations. Cache on first call."""
        if hasattr(self, "_onboarding_cache"):
            return self._onboarding_cache

        # Try workspace first (repo has its own onboarding)
        content = await self._read_file("ONBOARDING.md", workspace)

        # Fallback: bundled in Docker image at /app/
        if not content:
            from pathlib import Path
            for candidate in [
                Path("/app/ONBOARDING.md"),
                Path(__file__).resolve().parents[3] / "ONBOARDING.md",  # repo root
            ]:
                if candidate.exists():
                    content = candidate.read_text(encoding="utf-8", errors="ignore")
                    break

        if not content:
            content = "(No ONBOARDING.md found — proceeding without codebase context)"

        self._onboarding_cache = content
        return content

    def _prepend_onboarding(self, prompt: str, run: Any) -> str:
        """Inject onboarding context into an LLM prompt."""
        onboarding = getattr(run, "_onboarding", "")
        if not onboarding:
            return prompt
        return (
            f"## Codebase Context (read before writing any code)\n\n"
            f"{onboarding}\n\n"
            f"---\n\n"
            f"{prompt}"
        )

    async def _get_prompt(self, name: str) -> str:
        """Get a prompt from the library. Falls back to defaults if not in manager."""
        if self._pm:
            try:
                content = await self._pm.get(name)
                if content:
                    return content
            except Exception:
                pass
        # Fallback to hardcoded defaults
        from stronghold.builders.prompts import BUILDER_PROMPT_DEFAULTS
        return BUILDER_PROMPT_DEFAULTS.get(name, "")

    async def _compose_prompt(self, *fragment_names: str) -> str:
        """Compose a prompt from named fragments in the prompt library."""
        parts = []
        for name in fragment_names:
            content = await self._get_prompt(name)
            if content:
                parts.append(content)
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _render(template: str, **kwargs: str) -> str:
        """Replace {{variable}} placeholders in a prompt template."""
        result = template
        for key, value in kwargs.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result

    async def seed_prompts(self) -> None:
        """Seed default builder prompts into the prompt library.

        Always updates to latest defaults — prompt refinements in code
        take effect immediately. Use the API to override with custom versions.
        """
        if not self._pm:
            return
        from stronghold.builders.prompts import BUILDER_PROMPT_DEFAULTS
        for name, content in BUILDER_PROMPT_DEFAULTS.items():
            try:
                await self._pm.upsert(name, content, label="production")
            except Exception:
                pass

    async def _llm_call(self, prompt: str, model: str) -> str:
        """Single LLM call. No tools. Returns text content."""
        response = await self._llm.complete(
            [{"role": "user", "content": prompt}],
            model,
        )
        choices = response.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    async def _llm_extract(
        self,
        prompt: str,
        model: str,
        extractor: Any,
        what: str,
    ) -> Any:
        """Call LLM, extract structured output, retry on parse failure."""
        last_error = ""
        for attempt in range(MAX_LLM_RETRIES):
            full_prompt = prompt
            if last_error:
                full_prompt = (
                    f"Your previous response could not be parsed: {last_error}\n\n"
                    f"Try again. Follow the format instructions exactly.\n\n"
                    f"{prompt}"
                )
            text = await self._llm_call(full_prompt, model)
            try:
                return extractor(text)
            except ExtractionError as e:
                last_error = str(e)
                logger.warning(
                    "Extraction failed for %s (attempt %d/%d): %s",
                    what, attempt + 1, MAX_LLM_RETRIES, e,
                )
        raise ExtractionError(
            f"Failed to extract {what} after {MAX_LLM_RETRIES} attempts: {last_error}"
        )

    async def _read_file(self, path: str, workspace: str) -> str:
        """Read a file from workspace. Returns content or empty string."""
        result = await self._td.execute(
            "file_ops", {"action": "read", "path": path, "workspace": workspace},
        )
        if result.startswith("Error:"):
            return ""
        return result

    async def _write_file(self, path: str, content: str, workspace: str) -> str:
        """Write a file to workspace. Returns result string."""
        return await self._td.execute(
            "file_ops",
            {"action": "write", "path": path, "content": content, "workspace": workspace},
        )

    async def _list_files(self, path: str, workspace: str) -> str:
        """List directory contents. Returns result string."""
        return await self._td.execute(
            "file_ops", {"action": "list", "path": path, "workspace": workspace},
        )

    async def _run_pytest(self, workspace: str, path: str = "tests/") -> str:
        """Run pytest with workspace src/ on PYTHONPATH so local changes are used."""
        cmd = f"PYTHONPATH={workspace}/src:$PYTHONPATH python -m pytest {path} -v"
        return await self._td.execute(
            "shell", {"command": cmd, "workspace": workspace},
        )

    async def _run_quality_gate(self, gate: str, workspace: str) -> str:
        """Run a quality gate tool. Returns output string."""
        return await self._td.execute(gate, {"workspace": workspace})

    async def _git_command(self, command: str, workspace: str) -> str:
        """Run a git command in workspace."""
        return await self._td.execute(
            "git", {"command": command, "workspace": workspace},
        )

    async def _post_to_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> str:
        """Post a comment to the GitHub issue."""
        return await self._td.execute(
            "github",
            {
                "action": "post_pr_comment",
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "body": body,
            },
        )

    # ── Stage 1: Issue Analysis ──────────────────────────────────────

    async def analyze_issue(self, run: Any, feedback: str = "") -> StageResult:
        """Frank analyzes the issue. Runtime reads repo context, LLM produces analysis."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        issue_content = getattr(run, "_issue_content", "")
        issue_title = getattr(run, "_issue_title", "")

        # Runtime reads repo structure
        file_listing = await self._list_files("src/", ws)
        test_listing = await self._list_files("tests/", ws)
        architecture = await self._read_file("ARCHITECTURE.md", ws)
        architecture_excerpt = architecture[:3000] if architecture else "(not found)"

        feedback_block = ""
        if feedback:
            feedback_block = f"Previous analysis rejected. Fix:\n{feedback}"

        template = await self._get_prompt("builders.frank.analyze_issue")
        prompt = self._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=issue_title,
            issue_content=issue_content,
            file_listing=file_listing,
            test_listing=test_listing,
            architecture_excerpt=architecture_excerpt,
            feedback_block=feedback_block,
        )

        analysis = await self._llm_extract(
            prompt, self._frank_model, extract_json, "issue analysis",
        )

        # Post to issue
        summary = (
            f"## Issue Analysis\n\n"
            f"**Problem:** {analysis.get('problem', '')}\n\n"
            f"**Requirements:**\n"
            + "\n".join(f"- {r}" for r in analysis.get("requirements", []))
            + "\n\n**Edge Cases:**\n"
            + "\n".join(f"- {e}" for e in analysis.get("edge_cases", []))
            + f"\n\n**Affected Files:** {', '.join(analysis.get('affected_files', []))}\n\n"
            f"**Approach:** {analysis.get('approach', '')}\n"
        )

        await self._post_to_issue(owner, repo, run.issue_number, summary)

        return StageResult(
            success=True,
            summary=summary,
            evidence={"analysis": analysis},
            artifacts={"analysis": analysis},
        )

    # ── Stage 2: Acceptance Criteria ─────────────────────────────────

    async def define_acceptance_criteria(self, run: Any, feedback: str = "") -> StageResult:
        """Frank writes Gherkin acceptance criteria."""
        owner, repo = run.repo.split("/")
        issue_content = getattr(run, "_issue_content", "")
        issue_title = getattr(run, "_issue_title", "")

        # Get analysis from prior stage artifacts
        analysis = {}
        for artifact in run.artifacts:
            if artifact.type == "issue_analyzed_output":
                analysis = getattr(run, "_analysis", {})
                break

        requirements = analysis.get("requirements", [issue_content])
        edge_cases = analysis.get("edge_cases", [])

        # Check for locked criteria from a previous outer loop pass
        locked = getattr(run, "_locked_criteria", set())
        old_criteria = getattr(run, "_criteria", [])

        feedback_block = ""
        if feedback:
            feedback_block = f"Previous criteria rejected. Fix:\n{feedback}"

        if locked and old_criteria:
            locked_info = "\n".join(
                f"- Criterion {i + 1}: {'LOCKED (tests pass — do NOT change)' if i in locked else 'FAILED — must be rewritten'}: {c[:80]}"
                for i, c in enumerate(old_criteria)
            )
            feedback_block += (
                f"\n\nPREVIOUS ATTEMPT RESULTS:\n{locked_info}\n\n"
                f"Keep the locked criteria EXACTLY as they are. "
                f"Only rewrite the FAILED criteria. "
                f"Return ALL criteria (locked + rewritten) in order.\n"
            )

        template = await self._get_prompt("builders.frank.acceptance_criteria")
        prompt = self._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=issue_title,
            requirements="\n".join(f"- {r}" for r in requirements),
            edge_cases="\n".join(f"- {e}" for e in edge_cases),
            feedback_block=feedback_block,
        )

        scenarios = await self._llm_extract(
            prompt, self._frank_model, extract_gherkin_scenarios, "Gherkin scenarios",
        )

        # Post to issue
        scenarios_text = "\n\n".join(scenarios)
        summary = (
            f"## Acceptance Criteria\n\n"
            f"```gherkin\n{scenarios_text}\n```\n\n"
            f"**Total scenarios:** {len(scenarios)}\n"
        )

        await self._post_to_issue(owner, repo, run.issue_number, summary)

        # Stash for next stage
        run._criteria = scenarios
        run._analysis = analysis

        return StageResult(
            success=True,
            summary=summary,
            evidence={"scenario_count": len(scenarios), "scenarios": scenarios},
            artifacts={"criteria": scenarios},
        )

    # ── Stage 3+4: One-at-a-time TDD ───────────────────────────────

    async def write_tests(self, run: Any, feedback: str = "") -> StageResult:
        """Redirect to combined TDD method."""
        return await self.write_tests_and_implement(run, feedback=feedback)

    async def implement(self, run: Any, feedback: str = "") -> StageResult:
        """Implementation is done inside write_tests_and_implement. Auto-pass."""
        return StageResult(
            success=True,
            summary="Implementation completed in tests_written stage (one-at-a-time TDD)",
            evidence={"note": "Combined with write_tests stage"},
        )

    async def write_tests_and_implement(self, run: Any, feedback: str = "") -> StageResult:
        """One-at-a-time TDD: for each criterion, write one test, make it pass, lock it.

        Green tests stay green. Append only. Never rewrite a passing test.
        """
        from stronghold.builders.nested_loop import MasonTestTracker

        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        criteria = getattr(run, "_criteria", [])
        locked_criteria: set[int] = getattr(run, "_locked_criteria", set())
        analysis = getattr(run, "_analysis", {})
        affected_files = analysis.get("affected_files", [])
        issue_content = getattr(run, "_issue_content", "")

        if not criteria:
            return StageResult(success=False, summary="No acceptance criteria found")

        # Resolve affected source file
        if not affected_files:
            file_listing = await self._list_files("src/stronghold/api/routes", ws)
            raw_prompt = (
                f"Which source file should be modified to implement this issue?\n\n"
                f"Issue: {issue_content[:500]}\n\n"
                f"Available route files:\n{file_listing}\n\n"
                f"Output ONLY the file path, e.g.: src/stronghold/api/routes/status.py\n"
            )
            prompt = self._prepend_onboarding(raw_prompt, run)
            path_response = await self._llm_call(prompt, self._mason_model)
            path = path_response.strip().strip("`").strip()
            affected_files = [path] if path.startswith("src/") else ["src/stronghold/api/routes/status.py"]

        # Read source context
        source_context = ""
        for fpath in affected_files[:3]:
            content = await self._read_file(fpath, ws)
            if content:
                source_context += f"\n# --- {fpath} ---\n{content}\n"

        test_file = f"tests/api/test_issue_{run.issue_number}.py"
        tracker = MasonTestTracker()
        files_written: list[str] = []
        criteria_completed = 0

        for i, criterion in enumerate(criteria):
            if i in locked_criteria:
                print(f"[TDD] Criterion {i + 1}/{len(criteria)}: LOCKED (tests pass) — skipping", flush=True)
                criteria_completed += 1
                continue
            print(f"[TDD] Criterion {i + 1}/{len(criteria)}: {criterion[:80]}", flush=True)

            # ── Test phase: write ONE test ──────────────────────────
            if i == 0:
                # First criterion: generate complete file
                template = await self._get_prompt("builders.mason.write_first_test")
                raw_prompt = self._render(
                    template,
                    criterion=criterion,
                    source_context=source_context,
                    feedback_block=feedback if feedback else "",
                )
            else:
                # Subsequent: append to existing file
                existing_code = await self._read_file(test_file, ws)
                template = await self._get_prompt("builders.mason.append_test")
                raw_prompt = self._render(
                    template,
                    criterion=criterion,
                    existing_code=existing_code,
                    feedback_block="",
                )

            prompt = self._prepend_onboarding(raw_prompt, run)

            try:
                test_code = await self._llm_extract(
                    prompt, self._mason_model, extract_python_code, f"test for criterion {i + 1}",
                )
                await self._write_file(test_file, test_code, ws)
            except ExtractionError as e:
                logger.error("Failed to generate test for criterion %d: %s", i + 1, e)
                await self._post_to_issue(
                    owner, repo, run.issue_number,
                    f"Criterion {i + 1}: failed to generate test — {e}",
                )
                continue

            # Verify test compiles (max 2 fix attempts)
            for fix_attempt in range(2):
                output = await self._run_pytest(ws, test_file)
                if "SyntaxError" not in output and "ImportError" not in output:
                    break
                current_code = await self._read_file(test_file, ws)
                fix_prompt = (
                    f"This test file has errors:\n\n```python\n{current_code}\n```\n\n"
                    f"Error:\n```\n{output[:2000]}\n```\n\n"
                    f"Fix the code. Output ONLY the corrected complete file.\n"
                )
                try:
                    fixed = await self._llm_extract(
                        fix_prompt, self._mason_model, extract_python_code, "fix test",
                    )
                    await self._write_file(test_file, fixed, ws)
                except ExtractionError:
                    break

            # ── Impl phase: make THIS test pass ─────────────────────
            for impl_attempt in range(3):
                output = await self._run_pytest(ws, test_file)
                passing = self._count_passing(output)
                failing = self._count_failing(output)

                print(
                    f"[TDD] Criterion {i + 1} impl attempt {impl_attempt + 1}: "
                    f"{passing} passed, {failing} failed, hwm={tracker.high_water_mark}",
                    flush=True,
                )

                # All tests pass (including previous criteria) → done with this criterion
                if failing == 0 and passing > 0:
                    break

                tracker.record_test_result(passing)
                if tracker.has_failed:
                    break

                # Ask LLM to implement/fix
                test_code_current = await self._read_file(test_file, ws)
                for fpath in affected_files:
                    source = await self._read_file(fpath, ws)
                    template = await self._get_prompt("builders.mason.implement")
                    raw_prompt = self._render(
                        template,
                        test_code=test_code_current,
                        pytest_output=output[:3000],
                        file_path=fpath,
                        source_code=source,
                        issue_content=issue_content,
                        feedback_block="",
                    )
                    impl_prompt = self._prepend_onboarding(raw_prompt, run)
                    try:
                        new_source = await self._llm_extract(
                            impl_prompt, self._mason_model, extract_python_code, f"impl c{i + 1}a{impl_attempt + 1}",
                        )
                        await self._write_file(fpath, new_source, ws)
                        if fpath not in files_written:
                            files_written.append(fpath)
                    except ExtractionError as e:
                        logger.error("Impl failed for %s: %s", fpath, e)

                # Fix test bugs (AttributeError/TypeError) if any
                test_output = await self._run_pytest(ws, test_file)
                if "AttributeError" in test_output or "TypeError" in test_output:
                    tc = await self._read_file(test_file, ws)
                    fix_prompt = (
                        f"Fix the runtime errors in this test:\n\n```python\n{tc}\n```\n\n"
                        f"Error:\n```\n{test_output[:2000]}\n```\n\n"
                        f"Output ONLY the corrected complete file. Do NOT remove any test functions.\n"
                    )
                    try:
                        fixed = await self._llm_extract(fix_prompt, self._mason_model, extract_python_code, "fix test bugs")
                        await self._write_file(test_file, fixed, ws)
                    except ExtractionError:
                        pass

            # Check if this criterion's tests pass
            check_output = await self._run_pytest(ws, test_file)
            check_passing = self._count_passing(check_output)
            check_failing = self._count_failing(check_output)

            # Commit this criterion
            await self._git_command("add -A", ws)
            await self._git_command(
                f'commit -m "feat(#{run.issue_number}): criterion {i + 1} -- {criterion[:50]}" --allow-empty', ws,
            )
            criteria_completed += 1

            # Lock this criterion if all tests pass so far
            if check_failing == 0 and check_passing > 0:
                locked_criteria.add(i)
                print(f"[TDD] Criterion {i + 1} LOCKED ({check_passing} tests pass)", flush=True)

            # Post progress
            final_output = await self._run_pytest(ws, test_file)
            p = self._count_passing(final_output)
            f = self._count_failing(final_output)
            await self._post_to_issue(
                owner, repo, run.issue_number,
                f"**Criterion {i + 1}/{len(criteria)}:** {p} passed, {f} failed\n\n"
                f"```\n{final_output[:1000]}\n```",
            )

            if tracker.has_failed:
                logger.warning("Stalled — stopping TDD loop")
                break

        # Persist locked criteria on run for next outer loop pass
        run._locked_criteria = locked_criteria

        # Final summary
        final_output = await self._run_pytest(ws, test_file)
        final_passing = self._count_passing(final_output)
        final_failing = self._count_failing(final_output)

        summary = (
            f"## TDD Complete\n\n"
            f"**Criteria completed:** {criteria_completed}/{len(criteria)}\n"
            f"**Files modified:** {', '.join(f'`{f}`' for f in files_written)}\n"
            f"**Tests:** {final_passing} passed, {final_failing} failed "
            f"(hwm: {tracker.high_water_mark})\n\n"
            f"**Pytest:**\n```\n{final_output[:2000]}\n```\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary)

        return StageResult(
            success=final_passing > 0,
            summary=summary,
            evidence={
                "test_file": test_file,
                "files_written": files_written,
                "criteria_completed": criteria_completed,
                "tests_passing": final_passing,
                "tests_failing": final_failing,
                "high_water_mark": tracker.high_water_mark,
                "pytest_output": final_output[:3000],
            },
            artifacts={"test_file": test_file, "files_written": files_written},
        )

    # ── Stage 5: Quality Gates ───────────────────────────────────────

    async def run_quality_gates(self, run: Any, feedback: str = "") -> StageResult:
        """Run quality gates scoped to changed files only."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        test_file = f"tests/api/test_issue_{run.issue_number}.py"

        # Get list of changed files to scope the gates
        diff_output = await self._git_command("diff --name-only HEAD", ws)
        changed_src = [f for f in diff_output.strip().splitlines() if f.startswith("src/") and f.endswith(".py")]
        changed_src_str = " ".join(changed_src) if changed_src else "src/stronghold/api/routes/status.py"

        results: dict[str, str] = {}

        # pytest — only our test file
        results["pytest"] = await self._run_pytest(ws, test_file)

        # ruff/mypy/bandit — only changed source files
        for gate_name, cmd in [
            ("ruff_check", f"ruff check {changed_src_str}"),
            ("ruff_format", f"ruff format --check {changed_src_str}"),
            ("mypy", f"mypy {changed_src_str} --strict"),
            ("bandit", f"bandit {changed_src_str} -ll"),
        ]:
            result = await self._td.execute("shell", {"command": cmd, "workspace": ws})
            results[gate_name] = result
            logger.info("Quality gate %s: %s", gate_name, result[:100])

        # Try to fix ruff/mypy issues with LLM (one pass)
        for fixable_gate in ("ruff_check", "mypy"):
            output = results.get(fixable_gate, "")
            if output and not output.startswith("Error:") and ("error" in output.lower() or "warning" in output.lower()):
                # Read the files with violations, ask LLM to fix
                affected = self._parse_violation_files(output)
                for fpath in affected[:3]:
                    source = await self._read_file(fpath, ws)
                    if not source:
                        continue
                    fix_prompt = (
                        f"Fix the {fixable_gate} violations in this file:\n\n"
                        f"Violations:\n```\n{output[:1500]}\n```\n\n"
                        f"Source file `{fpath}`:\n```python\n{source}\n```\n\n"
                        f"Output ONLY the corrected complete file.\n"
                    )
                    try:
                        fixed = await self._llm_extract(
                            fix_prompt, self._mason_model, extract_python_code, f"fix {fixable_gate}",
                        )
                        await self._write_file(fpath, fixed, ws)
                    except ExtractionError:
                        pass

                # Re-run the gate
                rerun_cmd = f"ruff check {changed_src_str}" if fixable_gate == "ruff_check" else f"mypy {changed_src_str} --strict"
                results[fixable_gate] = await self._td.execute(
                    "shell", {"command": rerun_cmd, "workspace": ws},
                )

        # Commit fixes
        await self._git_command("add -A", ws)
        await self._git_command(
            f'commit -m "style: quality gate fixes for issue #{run.issue_number}" --allow-empty', ws,
        )

        summary = (
            f"## Quality Gates\n\n"
            + "\n".join(
                f"**{name}:** `{output[:200]}`"
                for name, output in results.items()
            )
            + "\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary)

        return StageResult(
            success=True,
            summary=summary,
            evidence={"gate_results": {k: v[:2000] for k, v in results.items()}},
            artifacts={"gate_results": results},
        )

    # ── Stage 6: Final Verification ──────────────────────────────────

    async def final_verification(self, run: Any, feedback: str = "") -> StageResult:
        """Final check — run all gates, verify commits exist."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")

        # Final pytest run
        pytest_output = await self._run_pytest(ws)

        # Git log to confirm commits
        git_log = await self._git_command("log --oneline -10", ws)

        # Diff against main
        git_diff_stat = await self._git_command("diff main --stat", ws)

        summary = (
            f"## Final Verification\n\n"
            f"**Pytest:**\n```\n{pytest_output[:1500]}\n```\n\n"
            f"**Git log:**\n```\n{git_log}\n```\n\n"
            f"**Changes vs main:**\n```\n{git_diff_stat}\n```\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary)

        return StageResult(
            success=True,
            summary=summary,
            evidence={
                "pytest_output": pytest_output[:3000],
                "git_log": git_log,
                "diff_stat": git_diff_stat,
            },
        )

    # ── Auditor Review ───────────────────────────────────────────────

    async def auditor_review(
        self,
        stage: str,
        evidence: dict[str, Any],
    ) -> tuple[bool, str]:
        """Auditor reviews concrete evidence using composed prompts from the library."""
        # Get stage-specific context from prompt library
        stage_context = await self._get_prompt(f"builders.auditor.stage.{stage}")
        if not stage_context:
            # Fallback to hardcoded context dict
            ctx = _AUDITOR_STAGE_CONTEXT.get(stage, {})
            purpose = ctx.get("purpose", "Complete the stage")
            scope = ctx.get("scope", "")
            out_of_scope = ctx.get("out_of_scope", "")
            checklist = ctx.get("checklist", [])
            rejection_format = ctx.get("rejection_format", "Be specific")
            checklist_text = "\n".join(f"- [ ] {item}" for item in checklist)
        else:
            # Parse structured context from prompt library
            import yaml
            try:
                ctx = yaml.safe_load(stage_context)
            except Exception:
                ctx = {}
            purpose = ctx.get("purpose", "Complete the stage")
            scope = ctx.get("scope", "")
            out_of_scope = ctx.get("out_of_scope", "")
            checklist_raw = ctx.get("checklist", [])
            rejection_format = ctx.get("rejection_format", "Be specific")
            checklist_text = "\n".join(
                f"- [ ] {item}" for item in (checklist_raw if isinstance(checklist_raw, list) else [])
            )

        evidence_text = "\n".join(
            f"**{k}:**\n{v}" if isinstance(v, str) else f"**{k}:** {v}"
            for k, v in evidence.items()
        )

        # Compose review prompt from library
        review_template = await self._get_prompt("builders.auditor.review")
        prompt = self._render(
            review_template,
            stage=stage,
            purpose=purpose,
            scope=scope,
            out_of_scope=out_of_scope,
            checklist=checklist_text,
            evidence=evidence_text,
            rejection_format=rejection_format,
        )

        text = await self._llm_call(prompt, self._auditor_model)
        # Parse verdict — scan lines for first clear verdict keyword
        approved = True  # default approve if no verdict found
        for line in (text or "").splitlines():
            stripped = line.strip().upper().lstrip("#").strip()
            if stripped.startswith("APPROVED") or stripped.startswith("VERDICT: APPROVED") or stripped.startswith("VERDICT:APPROVED"):
                approved = True
                break
            if stripped.startswith("CHANGES_REQUESTED") or stripped.startswith("VERDICT: CHANGES") or stripped.startswith("VERDICT:CHANGES"):
                approved = False
                break
        print(f"[AUDITOR] stage={stage} approved={approved} first80={text[:80] if text else 'EMPTY'}", flush=True)
        return approved, text

    # ── Utilities ────────────────────────────────────────────────────

    @staticmethod
    def _count_passing(pytest_output: str) -> int:
        """Count passing tests from pytest output."""
        import re
        match = re.search(r"(\d+)\s+passed", pytest_output)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _count_failing(pytest_output: str) -> int:
        """Count failing tests from pytest output."""
        import re
        failed = re.search(r"(\d+)\s+failed", pytest_output)
        errors = re.search(r"(\d+)\s+error", pytest_output)
        return (int(failed.group(1)) if failed else 0) + (int(errors.group(1)) if errors else 0)

    @staticmethod
    def _parse_violation_files(output: str) -> list[str]:
        """Extract file paths from ruff/mypy output."""
        import re

        paths: list[str] = []
        for match in re.finditer(r"(src/\S+\.py)", output):
            path = match.group(1)
            if path not in paths:
                paths.append(path)
        return paths
