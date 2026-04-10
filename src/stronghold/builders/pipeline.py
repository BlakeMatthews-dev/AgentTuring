"""Runtime-controlled Builders pipeline.

The LLM generates content (code, analysis, criteria).
The runtime controls all execution: reads files, writes files, runs tests, commits.
The LLM never sees tool definitions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from stronghold.builders.extractors import (
    ExtractionError,
    extract_gherkin_scenarios,
    extract_json,
    extract_python_code,
)

logger = logging.getLogger("stronghold.builders.pipeline")
tdd_logger = logging.getLogger("stronghold.builders.tdd")
auditor_logger = logging.getLogger("stronghold.builders.auditor")
onboarding_logger = logging.getLogger("stronghold.builders.onboarding")

MAX_LLM_RETRIES = 3


# ── Prior-run signal patterns (module-level so tests can import the
#    source of truth instead of re-declaring local copies) ──────────

# `## Builders Run \`(run|sched)-<hex>\`` — header comment that Mason
# posts at the start of every run. The id prefix is `run-` for manual
# /runs flow and `sched-` for scheduler-dispatched flow. Both must
# match so _fetch_prior_runs sees scheduler-dispatched history.
BUILDERS_RUN_PATTERN = re.compile(
    r"##\s*Builders Run\s*`?((?:run|sched)-[a-f0-9]+)`?"
)

# `## Gatekeeper Verdict on PR #N` — comment that review_pr posts to
# the parent issue when Gatekeeper approves or requests changes on a
# Mason PR. _fetch_prior_runs picks these up so Mason can learn from
# rejections on the next outer-loop attempt.
GATEKEEPER_VERDICT_PATTERN = re.compile(
    r"##\s*Gatekeeper Verdict on PR\s*#(\d+)",
    re.IGNORECASE,
)


# ── Issue type registry for context-aware onboarding ─────────────────


@dataclass
class IssueType:
    """Maps issue signals to onboarding sections. Extensible — just append."""

    name: str
    signals: list[str]       # path patterns, title prefixes, keywords
    sections: list[str]      # ONBOARDING.md section headers to inject
    priority: int = 0        # higher = matched first (most specific wins)


ISSUE_TYPE_REGISTRY: list[IssueType] = [
    IssueType(
        name="ui_dashboard",
        signals=["dashboard/", ".html", "sidebar", "button", "scroll", "css", "tailwind", "overlap", "animate", "active state", "tooltip", "diff view"],
        sections=[
            "Pattern 3: HTML/CSS Structural Tests (UI issues)",
            "Valid Import Paths",
            "Pytest Config",
        ],
        priority=8,
    ),
    IssueType(
        name="test_redis",
        signals=["cache/redis", "redis_pool"],
        sections=[
            "App Factory",
            "Pattern 2: Utility Class Tests (NO FastAPI, NO TestClient)",
            "Testing modules that connect to Redis",
            "Valid Import Paths",
            "Test-Only Issues vs Feature Issues",
        ],
        priority=10,
    ),
    IssueType(
        name="test_utility",
        signals=["cache/", "security/", "memory/", "tools/", "prompts/", "classifier/", "router/selector"],
        sections=[
            "App Factory",
            "Pattern 2: Utility Class Tests (NO FastAPI, NO TestClient)",
            "Valid Import Paths",
            "Test-Only Issues vs Feature Issues",
        ],
        priority=5,
    ),
    IssueType(
        name="test_route",
        signals=["api/routes/", "endpoint", "/v1/"],
        sections=[
            "App Factory",
            "Route Paths in Tests vs Production",
            "Pattern 1: Route Tests (FastAPI + TestClient)",
            "Valid Import Paths",
            "Test-Only Issues vs Feature Issues",
        ],
        priority=5,
    ),
    IssueType(
        name="feature_route",
        signals=["feat:", "fix:", "api/routes/"],
        sections=[
            "App Factory",
            "Route Paths in Tests vs Production",
            "Pattern 1: Route Tests (FastAPI + TestClient)",
            "Valid Import Paths",
            "Build Rules (from CLAUDE.md)",
        ],
        priority=1,
    ),
    IssueType(
        name="feature_general",
        signals=[],  # default fallback
        sections=[
            "App Factory",
            "Pattern 2: Utility Class Tests (NO FastAPI, NO TestClient)",
            "Valid Import Paths",
            "Build Rules (from CLAUDE.md)",
        ],
        priority=0,
    ),
]


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
        "scope": "ruff, mypy, bandit results on changed files",
        "out_of_scope": (
            "Pre-existing violations in files NOT touched by this issue. "
            "Pytest test failures — the TDD stage handles test pass/fail. "
            "Do NOT reject because pytest shows failing tests."
        ),
        "checklist": [
            "Quality gates ran (ruff_check, ruff_format, mypy, bandit)",
            "No NEW ruff/mypy/bandit violations in this issue's changed files",
        ],
        "rejection_format": (
            "State WHICH gate failed with the EXACT violation text, "
            "and whether it is new or pre-existing"
        ),
    },
    "quality_checks_passed": {
        "purpose": "Final verification — confirm commits and tests exist",
        "scope": "Git log, diff stat, final pytest run",
        "out_of_scope": (
            "Re-reviewing implementation decisions from earlier stages. "
            "Test pass/fail counts — the TDD stage already verified tests. "
            "Do NOT reject because some tests fail."
        ),
        "checklist": [
            "Git log shows at least one commit for this issue",
            "Diff shows changes to source and/or test files",
            "Pytest output is present (pytest was invoked, not empty)",
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

    # Model rotation for outer loop — each pass tries the next model
    # Opus first (OpenRouter free tier), then Gemini (no spend cap).
    # NOTE: zhipu-glm-5 returns empty content (reasoning-only model) —
    # unusable as Mason until we handle reasoning_content field.
    MODEL_ROTATION = [
        "openrouter-anthropic/claude-opus-4.6",   # Best, OpenRouter free tier
        "google-gemini-3.1-pro",                   # No spend cap, reliable
        "mistral-large",                           # Fast fallback
    ]

    # Per-model success tracking: {model: {"attempts": N, "criteria_passed": N}}
    _model_stats: dict[str, dict[str, int]] = {}

    @classmethod
    def record_model_result(cls, model: str, criteria_passed: int) -> None:
        """Track how well a model performs for prompt iteration insights."""
        if model not in cls._model_stats:
            cls._model_stats[model] = {"attempts": 0, "criteria_passed": 0}
        cls._model_stats[model]["attempts"] += 1
        cls._model_stats[model]["criteria_passed"] += criteria_passed

    @classmethod
    def get_model_stats(cls) -> dict[str, dict[str, int]]:
        return dict(cls._model_stats)

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

    @staticmethod
    def _detect_issue_type(run: Any) -> IssueType:
        """Match issue signals against registry. Highest priority match wins."""
        title = getattr(run, "_issue_title", "").lower()
        content = getattr(run, "_issue_content", "").lower()
        affected = getattr(run, "_analysis", {}).get("affected_files", [])
        search_text = f"{title} {content} {' '.join(affected)}"

        for itype in sorted(ISSUE_TYPE_REGISTRY, key=lambda t: -t.priority):
            if not itype.signals:
                continue
            if any(signal in search_text for signal in itype.signals):
                return itype

        return min(ISSUE_TYPE_REGISTRY, key=lambda t: t.priority)

    @staticmethod
    def _parse_onboarding_sections(text: str) -> dict[str, str]:
        """Split ONBOARDING.md into sections by ## and ### headers."""
        sections: dict[str, str] = {}
        current_name = ""
        current_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("## ") or line.startswith("### "):
                if current_name:
                    sections[current_name] = "\n".join(current_lines)
                current_name = line.lstrip("#").strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        if current_name:
            sections[current_name] = "\n".join(current_lines)
        return sections

    def _prepend_onboarding(self, prompt: str, run: Any) -> str:
        """Inject ONLY the relevant onboarding sections based on issue type."""
        onboarding = getattr(run, "_onboarding", "")
        if not onboarding:
            return prompt

        sections = self._parse_onboarding_sections(onboarding)
        issue_type = self._detect_issue_type(run)

        # Build focused context from matching sections
        parts: list[str] = []
        for section_name in issue_type.sections:
            for key, content in sections.items():
                if key.startswith(section_name) or section_name in key:
                    parts.append(content)
                    break

        if not parts:
            # Fallback: use full doc if no sections matched
            return f"## Codebase Context\n\n{onboarding}\n\n---\n\n{prompt}"

        context = "\n\n---\n\n".join(parts)
        onboarding_logger.info(
            "[ONBOARDING] issue_type=%s injecting %d sections (%d chars vs %d full)",
            issue_type.name, len(parts), len(context), len(onboarding),
            extra={"run_id": getattr(run, "run_id", "-")},
        )
        return f"## Codebase Context\n\n{context}\n\n---\n\n{prompt}"

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

    async def _llm_call(
        self,
        prompt: str,
        model: str,
        *,
        ctx: Any | None = None,
        trace: Any | None = None,
    ) -> str:
        """Single LLM call. No tools. Returns text content.

        When ``trace`` is provided, wraps the call in a ``llm.complete`` span
        with model/prompt attributes for Phoenix observability.
        """
        if trace is not None and ctx is not None:
            with trace.span("llm.complete") as span:
                span.set_attributes(ctx.to_span_attrs() | {
                    "model_name": model,
                    "model_fallback_chain": list(self.MODEL_ROTATION),
                    "prompt_size_chars": len(prompt),
                })
                span.set_input(prompt[:4000])
                response = await self._llm.complete(
                    [{"role": "user", "content": prompt}],
                    model,
                    fallback_models=self.MODEL_ROTATION,
                )
                choices = response.get("choices", [])
                text = (choices[0].get("message", {}).get("content", "") or "") if choices else ""
                usage = response.get("usage", {}) or {}
                span.set_output(text[:4000])
                span.set_usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    model=model,
                )
                return text

        response = await self._llm.complete(
            [{"role": "user", "content": prompt}],
            model,
            fallback_models=self.MODEL_ROTATION,
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
        *,
        ctx: Any | None = None,
        trace: Any | None = None,
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
            extract_ctx = ctx.with_(extraction_attempt=attempt + 1) if ctx else None
            text = await self._llm_call(full_prompt, model, ctx=extract_ctx, trace=trace)
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
        """Run pytest with workspace src/ taking priority over installed package."""
        # sys.path.insert(0, ...) beats site-packages; PYTHONPATH alone does not
        cmd = (
            f"python -c \"import sys; sys.path.insert(0, '{workspace}/src'); "
            f"import pytest; pytest.main(['{path}', '-v'])\""
        )
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

    async def _fetch_prior_runs(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        exclude_run_id: str = "",
    ) -> list[dict[str, str]]:
        """Fetch prior Builders Run + Gatekeeper Verdict comments.

        Returns a list of dicts with `run_id` and `summary` for each prior
        signal Mason should learn from when re-running this issue:

        1. Prior `## Builders Run` comments — ID can be either
           `run-<hex>` (manual /runs flow) or `sched-<hex>` (scheduler-
           dispatched flow). The previous version of this regex only
           matched `run-`, so scheduler-dispatched runs were silently
           invisible to Frank's prior-history lookup and the
           "learn from prior failures" feedback loop never closed for
           anything the scheduler picked up.

        2. Prior `## Gatekeeper Verdict on PR #N` comments — these
           carry the changes-requested feedback Mason needs to see on
           the next outer loop. Without this, Mason would re-run the
           same issue, produce the same broken PR, and Gatekeeper would
           reject again forever. With this, Mason's analysis sees the
           verdict in its prior-history block and can adjust.

        Excludes the current run if exclude_run_id is set.
        """
        import json as _json

        result = await self._td.execute(
            "github",
            {
                "action": "list_issue_comments",
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
            },
        )
        if result.startswith("Error:"):
            return []

        try:
            comments = _json.loads(result)
        except Exception:
            return []
        if not isinstance(comments, list):
            return []

        prior_runs: list[dict[str, str]] = []

        for comment in comments:
            if not isinstance(comment, dict):
                continue
            body = comment.get("body", "") or ""

            # Builders Run header — accepts both manual and scheduler
            # ID prefixes (see BUILDERS_RUN_PATTERN module docstring).
            run_match = BUILDERS_RUN_PATTERN.search(body)
            if run_match:
                run_id = run_match.group(1)
                if run_id == exclude_run_id:
                    continue
                prior_runs.append({"run_id": run_id, "summary": body})
                continue

            # Gatekeeper verdict — synthesize a stable id from the PR
            # number AND the GitHub comment id so multiple verdicts on
            # the same PR (e.g., three reject cycles) each get a unique
            # entry in prior_runs instead of colliding on the same id.
            gk_match = GATEKEEPER_VERDICT_PATTERN.search(body)
            if gk_match:
                pr_number = gk_match.group(1)
                comment_id = comment.get("id", "x")
                prior_runs.append(
                    {
                        "run_id": f"gatekeeper-pr{pr_number}-{comment_id}",
                        "summary": body,
                    }
                )

        return prior_runs

    async def _post_to_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
        *,
        run: Any = None,
    ) -> str:
        """Post or update the single run comment on the issue.

        First call creates the comment and stashes the ID on the run.
        Subsequent calls edit the same comment, appending new content.
        """
        import json as _json

        comment_id = getattr(run, "_comment_id", None) if run else None

        if comment_id:
            # Edit existing comment — append new section
            old_body = getattr(run, "_comment_body", "")
            new_body = old_body + "\n\n---\n\n" + body
            # Trim if too long (GitHub limit ~65536)
            if len(new_body) > 60000:
                new_body = new_body[-60000:]
            result = await self._td.execute(
                "github",
                {
                    "action": "edit_comment",
                    "owner": owner,
                    "repo": repo,
                    "comment_id": comment_id,
                    "body": new_body,
                },
            )
            if run:
                run._comment_body = new_body
            return result

        # First call — create the comment
        run_id = getattr(run, "run_id", "?") if run else "?"
        header = f"## Builders Run `{run_id}`\n\n"
        full_body = header + body
        result = await self._td.execute(
            "github",
            {
                "action": "post_pr_comment",
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "body": full_body,
            },
        )
        # Stash comment ID for future edits
        if run and not result.startswith("Error:"):
            try:
                data = _json.loads(result)
                run._comment_id = data.get("id")
                run._comment_body = full_body
            except Exception:
                pass
        return result

    # ── Stage 1: Issue Analysis ──────────────────────────────────────

    async def analyze_issue(self, run: Any, feedback: str = "") -> StageResult:
        """Frank analyzes the issue. Runtime reads repo context, LLM produces analysis."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        issue_content = getattr(run, "_issue_content", "")
        issue_title = getattr(run, "_issue_title", "")

        # Runtime reads repo structure — give Frank visibility into the codebase
        file_listing = await self._list_files("src/", ws)
        test_listing = await self._list_files("tests/", ws)
        dashboard_listing = await self._list_files("src/stronghold/dashboard/", ws)
        architecture = await self._read_file("ARCHITECTURE.md", ws)
        architecture_excerpt = architecture[:3000] if architecture else "(not found)"

        # Store listings on run so later stages can use them
        run._file_listing = file_listing
        run._dashboard_listing = dashboard_listing

        # Read prior run history from issue comments
        prior_runs = await self._fetch_prior_runs(
            owner, repo, run.issue_number, exclude_run_id=run.run_id,
        )

        feedback_block = ""
        if feedback:
            feedback_block = f"Previous analysis rejected. Fix:\n{feedback}"

        if prior_runs:
            feedback_block += (
                f"\n\n## Prior Run History\n\n"
                f"This issue has been attempted {len(prior_runs)} time(s) before. "
                f"Learn from prior failures:\n\n"
            )
            for pr in prior_runs[-5:]:  # Last 5 runs
                feedback_block += f"### {pr['run_id']}\n{pr['summary'][:500]}\n\n"

        template = await self._get_prompt("builders.frank.analyze_issue")
        prompt = self._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=issue_title,
            issue_content=issue_content,
            file_listing=file_listing,
            dashboard_listing=dashboard_listing,
            test_listing=test_listing,
            architecture_excerpt=architecture_excerpt,
            feedback_block=feedback_block,
        )

        analysis = await self._llm_extract(
            prompt, self._frank_model, extract_json, "issue analysis",
        )

        # Source-of-truth merge: if the issue body has an explicit
        # '## Files' section (Quartermaster decompositions and well-
        # formed human sub-issues do), trust those over Frank's LLM
        # guess. The LLM tends to hallucinate plausible-but-wrong
        # paths for "create new module" issues, picking an existing
        # file that *sounds* related instead of the actual new module
        # the issue body asks for. Files declared in the body are
        # preferred; LLM-suggested files are appended if they don't
        # collide.
        body_files = self._extract_files_from_issue_body(issue_content)
        if body_files:
            llm_files = analysis.get("affected_files", []) or []
            merged: list[str] = list(body_files)
            for f in llm_files:
                if f and f not in merged:
                    merged.append(f)
            analysis["affected_files"] = merged
            analysis["affected_files_source"] = "issue_body" if not llm_files else "issue_body+llm"
        else:
            analysis.setdefault("affected_files_source", "llm")

        # Post to issue
        summary = (
            f"## Issue Analysis\n\n"
            f"**Problem:** {analysis.get('problem', '')}\n\n"
            f"**Requirements:**\n"
            + "\n".join(f"- {r}" for r in analysis.get("requirements", []))
            + "\n\n**Edge Cases:**\n"
            + "\n".join(f"- {e}" for e in analysis.get("edge_cases", []))
            + f"\n\n**Affected Files** (source: {analysis.get('affected_files_source', 'llm')}):"
            f" {', '.join(analysis.get('affected_files', []))}\n\n"
            f"**Approach:** {analysis.get('approach', '')}\n"
        )

        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

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

        # Add issue-type-aware testing constraints
        issue_type = self._detect_issue_type(run)
        if issue_type.name == "ui_dashboard":
            feedback_block += (
                "\n\nTESTING CONSTRAINT: These criteria will be tested by "
                "reading the HTML file with Python and checking for string "
                "patterns. There is NO browser, NO JavaScript execution. "
                "Criteria MUST be statically verifiable:\n"
                "- GOOD: 'HTML contains a script that references "
                "window.location.pathname'\n"
                "- GOOD: 'HTML contains the class border-emerald-500'\n"
                "- BAD: 'Non-active items should NOT have active "
                "classes' (cannot test without a browser)\n"
                "- BAD: 'Click on nav item and verify it becomes "
                "active' (no browser available)\n"
            )

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

        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

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
        affected_files = list(analysis.get("affected_files", []) or [])
        issue_content = getattr(run, "_issue_content", "")

        if not criteria:
            return StageResult(success=False, summary="No acceptance criteria found")

        # Belt-and-suspenders: even if Frank's analysis didn't carry
        # the files forward, parse the issue body's '## Files' section
        # directly. This catches issues where analyze_issue ran on an
        # older code path or the analysis dict was lost across stages.
        body_files = self._extract_files_from_issue_body(issue_content)
        for bf in body_files:
            if bf and bf not in affected_files:
                affected_files.append(bf)

        # Resolve affected source file
        if not affected_files:
            file_listing = await self._list_files("src/stronghold/api/routes", ws)
            dashboard_listing = getattr(run, "_dashboard_listing", "") or await self._list_files("src/stronghold/dashboard", ws)
            raw_prompt = (
                f"Which source file should be modified to implement this issue?\n\n"
                f"Issue: {issue_content[:500]}\n\n"
                f"Available route files:\n{file_listing}\n\n"
                f"Dashboard files:\n{dashboard_listing}\n\n"
                f"Output ONLY the file path, e.g.: src/stronghold/dashboard/index.html\n"
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

        # Detect rendering model: static HTML vs JS-rendered DOM
        rendering_hint = ""
        for fpath in affected_files[:1]:
            js_signals = await self._td.execute(
                "grep_content",
                {
                    "pattern": r"createElement|innerHTML|appendChild|\.insertAdjacentHTML",
                    "workspace": ws,
                    "glob": fpath,
                    "max_results": 5,
                },
            )
            if js_signals and not js_signals.startswith("Error:"):
                import json as _json
                try:
                    matches = _json.loads(js_signals).get("count", 0)
                except Exception:
                    matches = 0
                if matches > 0:
                    rendering_hint = (
                        "\n## RENDERING MODEL: JavaScript-rendered DOM\n"
                        f"The target file `{fpath}` builds UI elements "
                        "dynamically with JavaScript (createElement, "
                        "innerHTML, appendChild). The HTML markup does "
                        "NOT contain the final DOM.\n\n"
                        "**For tests:** Check the JAVASCRIPT SOURCE "
                        "CODE for the expected changes, not static "
                        "HTML attributes. For example, check that the "
                        "JS sets `.title =` or adds a CSS class, not "
                        "that `title=\"` exists in the HTML.\n\n"
                        "**For implementation:** Modify the JAVASCRIPT "
                        "code that builds the elements, not the static "
                        "HTML markup. Find the createElement/innerHTML "
                        "block and add the fix there.\n"
                    )
                    source_context += rendering_hint

        # Recon: scan for existing test patterns matching the file type
        recon_context = ""
        issue_type = self._detect_issue_type(run)
        if issue_type.name == "ui_dashboard":
            # Find existing dashboard tests to learn the pattern
            existing_tests = await self._td.execute(
                "grep_content",
                {
                    "pattern": "DASHBOARD_DIR|dashboard.*html|read_text",
                    "workspace": ws,
                    "glob": "tests/**/*.py",
                    "max_results": 20,
                },
            )
            if existing_tests and not existing_tests.startswith("Error:"):
                recon_context += (
                    f"\n# --- Existing dashboard test patterns ---\n"
                    f"{existing_tests}\n"
                )
        else:
            # Find existing tests for similar files
            for fpath in affected_files[:1]:
                module_name = fpath.split("/")[-1].replace(".py", "")
                existing_tests = await self._td.execute(
                    "grep_content",
                    {
                        "pattern": f"import.*{module_name}|from.*{module_name}",
                        "workspace": ws,
                        "glob": "tests/**/*.py",
                        "max_results": 10,
                    },
                )
                if existing_tests and not existing_tests.startswith("Error:"):
                    recon_context += (
                        f"\n# --- Existing tests referencing {module_name} ---\n"
                        f"{existing_tests}\n"
                    )

        if recon_context:
            source_context += recon_context

        test_file = f"tests/api/test_issue_{run.issue_number}.py"
        tracker = MasonTestTracker()
        files_written: list[str] = []
        criteria_completed = 0

        # Check if test file already exists from a previous outer loop
        existing_test_code = await self._read_file(test_file, ws)
        has_existing_tests = bool(existing_test_code and "def test_" in existing_test_code)
        if has_existing_tests:
            # Seed tracker with current passing count so hwm starts right
            existing_output = await self._run_pytest(ws, test_file)
            existing_passing = self._count_passing(existing_output)
            if existing_passing > 0:
                tracker.record_test_result(existing_passing)
            tdd_logger.info(
                "[TDD] preserving existing test file (%d passing, %d chars)",
                existing_passing, len(existing_test_code),
                extra={"run_id": run.run_id},
            )

        for i, criterion in enumerate(criteria):
            if i in locked_criteria:
                tdd_logger.info(
                    "[TDD] criterion %d/%d: LOCKED — skipping",
                    i + 1, len(criteria), extra={"run_id": run.run_id},
                )
                criteria_completed += 1
                continue
            tdd_logger.info(
                "[TDD] criterion %d/%d: %s",
                i + 1, len(criteria), criterion[:80],
                extra={"run_id": run.run_id},
            )

            # ── Test phase: write ONE test ──────────────────────────
            if not has_existing_tests and i == 0:
                # First criterion AND no existing file: generate complete file
                template = await self._get_prompt("builders.mason.write_first_test")
                raw_prompt = self._render(
                    template,
                    criterion=criterion,
                    source_context=source_context,
                    feedback_block=feedback if feedback else "",
                )
            else:
                # Append to existing file (whether from this loop or previous)
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
                    run=run,
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

                tdd_logger.info(
                    "[TDD] criterion %d impl attempt %d: %d passed, %d failed, hwm=%d",
                    i + 1, impl_attempt + 1, passing, failing,
                    tracker.high_water_mark, extra={"run_id": run.run_id},
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

            # Auto-format + verify each source file Mason just wrote BEFORE
            # committing. Format must be in the per-criterion commit so the
            # branch we push has properly formatted code, and we now also
            # verify the file is non-empty and parses cleanly to catch the
            # "stub commit" failure mode where extraction succeeds but the
            # file ends up empty/broken.
            stub_files: list[str] = []
            for fpath in (affected_files + [test_file]):
                await self._td.execute(
                    "shell",
                    {
                        "command": f"ruff check --fix --unsafe-fixes {fpath} 2>/dev/null || true",
                        "workspace": ws,
                    },
                )
                await self._td.execute(
                    "shell",
                    {
                        "command": f"ruff format {fpath} 2>/dev/null || true",
                        "workspace": ws,
                    },
                )
                # Sanity check: file exists and isn't a stub
                content = await self._read_file(fpath, ws)
                if not content or len(content.strip()) < 20:
                    stub_files.append(fpath)
                    continue
                # Syntax check via py_compile (cheap, no LLM cost)
                if fpath.endswith(".py"):
                    syntax_check = await self._td.execute(
                        "shell",
                        {
                            "command": (
                                f"python3 -m py_compile {fpath} 2>&1 "
                                f"&& echo OK_SYNTAX || echo FAIL_SYNTAX"
                            ),
                            "workspace": ws,
                        },
                    )
                    if "FAIL_SYNTAX" in syntax_check:
                        stub_files.append(fpath)

            if stub_files:
                logger.warning(
                    "Mason TDD: criterion %d stub/broken files detected: %s — skipping commit",
                    i + 1, stub_files,
                )
                await self._post_to_issue(
                    owner, repo, run.issue_number,
                    f"⚠️ Criterion {i + 1}: skipped commit — stub or broken files: "
                    f"{', '.join(stub_files)}",
                    run=run,
                )
                continue

            # Commit this criterion
            await self._git_command("add -A", ws)
            await self._git_command(
                f'commit -m "feat(#{run.issue_number}): criterion {i + 1} -- {criterion[:50]}" --allow-empty', ws,
            )
            criteria_completed += 1

            # Lock this criterion if all tests pass so far
            if check_failing == 0 and check_passing > 0:
                locked_criteria.add(i)
                tdd_logger.info(
                    "[TDD] criterion %d LOCKED (%d tests pass)",
                    i + 1, check_passing, extra={"run_id": run.run_id},
                )

            # Post progress
            final_output = await self._run_pytest(ws, test_file)
            p = self._count_passing(final_output)
            f = self._count_failing(final_output)
            await self._post_to_issue(
                owner, repo, run.issue_number,
                f"**Criterion {i + 1}/{len(criteria)}:** {p} passed, {f} failed\n\n"
                f"```\n{final_output[:1000]}\n```",
                run=run,
            )

            if tracker.has_failed:
                logger.warning("Stalled — stopping TDD loop")
                break

        # Persist locked criteria on run for next outer loop pass
        run._locked_criteria = locked_criteria

        # Record model performance stats
        RuntimePipeline.record_model_result(self._mason_model, len(locked_criteria))
        tdd_logger.info(
            "[MODEL STATS] %s: %d criteria locked. all stats: %s",
            self._mason_model, len(locked_criteria),
            RuntimePipeline.get_model_stats(), extra={"run_id": run.run_id},
        )

        # Final summary
        final_output = await self._run_pytest(ws, test_file)
        final_passing = self._count_passing(final_output)
        final_failing = self._count_failing(final_output)

        # Self-improve: if we failed, record WHY in ONBOARDING.md for next run
        if final_passing == 0 and final_failing > 0:
            error_snippet = final_output[:500]
            learning = ""
            if "ImportError" in error_snippet or "ModuleNotFoundError" in error_snippet:
                learning = f"\n\n## Learned from issue #{run.issue_number}\n\nImport error encountered: {error_snippet[:200]}\nDo NOT import from these paths.\n"
            elif "AttributeError" in error_snippet:
                learning = f"\n\n## Learned from issue #{run.issue_number}\n\nAttributeError: {error_snippet[:200]}\nCheck the actual API of the class before using methods.\n"
            if learning:
                current_onboarding = await self._read_file("ONBOARDING.md", ws)
                if current_onboarding:
                    await self._write_file("ONBOARDING.md", current_onboarding + learning, ws)
                    onboarding_logger.info(
                        "[ONBOARDING] updated with learning from issue #%d",
                        run.issue_number, extra={"run_id": run.run_id},
                    )

        summary = (
            f"## TDD Complete\n\n"
            f"**Model:** `{self._mason_model}`\n"
            f"**Criteria completed:** {criteria_completed}/{len(criteria)}\n"
            f"**Files modified:** {', '.join(f'`{f}`' for f in files_written)}\n"
            f"**Tests:** {final_passing} passed, {final_failing} failed "
            f"(hwm: {tracker.high_water_mark})\n\n"
            f"**Pytest:**\n```\n{final_output[:2000]}\n```\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

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
        """Run quality gates: mechanical fixes → type inference → checks.

        Pipeline:
        1. Mechanical (zero LLM cost): ruff fix, ruff format, autotyping
        2. Type inference (zero LLM cost): pyrefly infer suggestions
        3. Type checking: mypy --strict
        4. If mypy fails: LLM gets error + pyrefly suggestion + source
        5. Security: bandit
        6. Tests: pytest
        """
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        test_file = f"tests/api/test_issue_{run.issue_number}.py"

        # Scope to changed files (compare against main, not HEAD —
        # Mason already committed during the TDD loop, so HEAD has no
        # unstaged changes. We need the cumulative diff vs base branch.)
        diff_output = await self._git_command(
            "diff --name-only origin/main...HEAD", ws,
        )
        logger.info(
            "[QG] diff vs origin/main returned %d lines",
            len(diff_output.strip().splitlines()),
        )
        changed_src = [
            f for f in diff_output.strip().splitlines()
            if f.startswith("src/") and f.endswith(".py")
        ]
        if not changed_src:
            # Fallback: try diff vs HEAD~10 for safety
            diff_output = await self._git_command(
                "diff --name-only HEAD~10..HEAD", ws,
            )
            changed_src = [
                f for f in diff_output.strip().splitlines()
                if f.startswith("src/") and f.endswith(".py")
            ]
        logger.info("[QG] changed_src: %s", changed_src)
        if not changed_src:
            return StageResult(
                success=True,
                summary="No source changes to gate",
                evidence={"gate_results": {}},
            )
        changed_src_str = " ".join(changed_src)
        logger.info("[QG] running ruff format on: %s", changed_src_str)

        results: dict[str, str] = {}

        # ── Phase 1: Mechanical fixes (zero cost) ──────────────
        await self._td.execute(
            "shell",
            {"command": f"ruff check --fix {changed_src_str}", "workspace": ws},
        )
        await self._td.execute(
            "shell",
            {"command": f"ruff format {changed_src_str}", "workspace": ws},
        )
        # autotyping: add trivial annotations (-> None, -> bool)
        for fpath in changed_src:
            await self._td.execute(
                "shell",
                {"command": f"autotyping {fpath}", "workspace": ws},
            )

        # ── Phase 2: Type inference suggestions (zero cost) ────
        pyrefly_suggestions: dict[str, str] = {}
        for fpath in changed_src:
            suggestion = await self._td.execute(
                "shell",
                {"command": f"pyrefly infer --diff {fpath}", "workspace": ws},
            )
            if suggestion and not suggestion.startswith("Error:"):
                pyrefly_suggestions[fpath] = suggestion

        # ── Phase 3: Check gates ───────────────────────────────
        results["ruff_check"] = await self._td.execute(
            "shell",
            {"command": f"ruff check {changed_src_str}", "workspace": ws},
        )
        results["ruff_format"] = await self._td.execute(
            "shell",
            {"command": f"ruff format --check {changed_src_str}", "workspace": ws},
        )
        results["mypy"] = await self._td.execute(
            "shell",
            {"command": f"mypy {changed_src_str} --strict", "workspace": ws},
        )
        results["bandit"] = await self._td.execute(
            "shell",
            {"command": f"bandit {changed_src_str} -ll", "workspace": ws},
        )
        results["pytest"] = await self._run_pytest(ws, test_file)

        for name, output in results.items():
            logger.info("Quality gate %s: %s", name, output[:100])

        # ── Phase 4: LLM fix for mypy failures ────────────────
        mypy_output = results.get("mypy", "")
        if mypy_output and '"passed": false' in mypy_output:
            for fpath in changed_src[:3]:
                source = await self._read_file(fpath, ws)
                if not source:
                    continue
                suggestion = pyrefly_suggestions.get(fpath, "")
                fix_prompt = (
                    f"Fix the mypy --strict errors in `{fpath}`:\n\n"
                    f"**mypy output:**\n```\n{mypy_output[:1500]}\n```\n\n"
                )
                if suggestion:
                    fix_prompt += (
                        f"**pyrefly type suggestions:**\n"
                        f"```diff\n{suggestion[:1500]}\n```\n\n"
                    )
                fix_prompt += (
                    f"**Source:**\n```python\n{source}\n```\n\n"
                    f"Output ONLY the corrected complete file.\n"
                )
                try:
                    fixed = await self._llm_extract(
                        fix_prompt, self._mason_model,
                        extract_python_code, f"fix mypy {fpath}",
                    )
                    await self._write_file(fpath, fixed, ws)
                except ExtractionError:
                    pass

            # Re-run mypy after fix
            results["mypy"] = await self._td.execute(
                "shell",
                {"command": f"mypy {changed_src_str} --strict", "workspace": ws},
            )

        # Commit all fixes
        await self._git_command("add -A", ws)
        await self._git_command(
            f'commit -m "style: quality gate fixes for issue '
            f'#{run.issue_number}" --allow-empty',
            ws,
        )

        summary = (
            f"## Quality Gates\n\n"
            + "\n".join(
                f"**{name}:** `{output[:200]}`"
                for name, output in results.items()
            )
            + "\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True,
            summary=summary,
            evidence={
                "gate_results": {k: v[:2000] for k, v in results.items()},
                "pyrefly_suggestions": {
                    k: v[:1000] for k, v in pyrefly_suggestions.items()
                },
            },
            artifacts={"gate_results": results},
        )

    # ── Stage 6: Final Verification ──────────────────────────────────

    async def final_verification(self, run: Any, feedback: str = "") -> StageResult:
        """Final check — run issue's tests, verify commits exist."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")

        # Final pytest run — scoped to this issue's tests only (not full repo)
        test_file = f"tests/api/test_issue_{run.issue_number}.py"
        pytest_output = await self._run_pytest(ws, test_file)

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
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True,
            summary=summary,
            evidence={
                "pytest_output": pytest_output[:3000],
                "git_log": git_log,
                "diff_stat": git_diff_stat,
            },
        )

    # ── UI Pipeline Methods (Piper + Glazier) ─────────────────────

    async def analyze_ui(self, run: Any, feedback: str = "") -> StageResult:
        """Piper: analyze HTML file and classify rendering model."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        issue_content = getattr(run, "_issue_content", "")
        issue_title = getattr(run, "_issue_title", "")

        # List dashboard files
        dashboard_listing = await self._list_files(
            "src/stronghold/dashboard", ws,
        )

        # Detect affected file
        template = await self._get_prompt("builders.piper.analyze_ui")
        if not template:
            from stronghold.builders.ui_prompts import PIPER_ANALYZE_UI
            template = PIPER_ANALYZE_UI

        # Read the likely target file
        source_context = ""
        for fname in ["index.html", "agents.html", "quota.html",
                       "prompts.html", "login.html", "profile.html"]:
            if fname.replace(".html", "") in issue_content.lower():
                content = await self._read_file(
                    f"src/stronghold/dashboard/{fname}", ws,
                )
                if content:
                    source_context = (
                        f"# --- src/stronghold/dashboard/{fname}"
                        f" ---\n{content}\n"
                    )
                    break

        if not source_context:
            # Fallback: ask LLM to pick the file
            pick_prompt = (
                f"Which dashboard file for: {issue_title}\n"
                f"Files:\n{dashboard_listing}\n"
                f"Output ONLY the filename."
            )
            fname = await self._llm_call(
                pick_prompt, self._frank_model,
            )
            fname = fname.strip().strip("`").strip()
            content = await self._read_file(
                f"src/stronghold/dashboard/{fname}", ws,
            )
            if content:
                source_context = (
                    f"# --- src/stronghold/dashboard/{fname}"
                    f" ---\n{content}\n"
                )

        # Read prior run history from issue comments
        prior_runs = await self._fetch_prior_runs(
            owner, repo, run.issue_number, exclude_run_id=run.run_id,
        )
        prior_history = ""
        if prior_runs:
            prior_history = (
                f"\n\n## Prior Run History\n\n"
                f"This issue has been attempted {len(prior_runs)} time(s) before. "
                f"Learn from prior failures:\n\n"
            )
            for pr in prior_runs[-5:]:
                prior_history += f"### {pr['run_id']}\n{pr['summary'][:500]}\n\n"

        prompt = self._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=issue_title,
            issue_content=issue_content + prior_history,
            source_context=source_context[:8000],
        )
        prompt = self._prepend_onboarding(prompt, run)

        analysis = await self._llm_extract(
            prompt, self._frank_model,
            extract_json, "UI analysis",
        )

        run._analysis = analysis
        run._rendering_model = analysis.get("rendering_model", "static")

        summary = (
            f"## UI Issue Analysis\n\n"
            f"**Rendering model:** {analysis.get('rendering_model')}\n"
            f"**Requirements:**\n"
            + "\n".join(
                f"- {r}" for r in analysis.get("requirements", [])
            )
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True, summary=summary,
            evidence={"analysis": analysis},
        )

    async def define_ui_criteria(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Piper: write acceptance criteria for UI issue."""
        owner, repo = run.repo.split("/")
        analysis = getattr(run, "_analysis", {})
        rendering_model = getattr(run, "_rendering_model", "static")
        requirements = analysis.get("requirements", [])

        template = await self._get_prompt(
            "builders.piper.ui_acceptance_criteria",
        )
        if not template:
            from stronghold.builders.ui_prompts import (
                PIPER_UI_ACCEPTANCE_CRITERIA,
            )
            template = PIPER_UI_ACCEPTANCE_CRITERIA

        feedback_block = ""
        if feedback:
            feedback_block = (
                f"Previous criteria rejected. Fix:\n{feedback}"
            )

        prompt = self._render(
            template,
            issue_number=str(run.issue_number),
            issue_title=getattr(run, "_issue_title", ""),
            rendering_model=rendering_model,
            requirements="\n".join(f"- {r}" for r in requirements),
            feedback_block=feedback_block,
        )

        scenarios = await self._llm_extract(
            prompt, self._frank_model,
            extract_gherkin_scenarios, "UI Gherkin scenarios",
        )

        run._criteria = scenarios
        scenarios_text = "\n\n".join(scenarios)
        summary = (
            f"## UI Acceptance Criteria\n\n"
            f"**Rendering model:** {rendering_model}\n\n"
            f"```gherkin\n{scenarios_text}\n```\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True, summary=summary,
            evidence={"scenarios": scenarios},
        )

    async def write_ui_tests(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Glazier: write and implement UI tests (TDD)."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        criteria = getattr(run, "_criteria", [])
        rendering_model = getattr(run, "_rendering_model", "static")
        analysis = getattr(run, "_analysis", {})
        issue_content = getattr(run, "_issue_content", "")
        affected_files = analysis.get("affected_files", [])

        if not criteria:
            return StageResult(
                success=False, summary="No acceptance criteria found",
            )

        # Find the target HTML file
        file_path = ""
        for fpath in affected_files:
            if fpath.endswith(".html"):
                file_path = fpath
                break
        if not file_path:
            # Detect from issue content
            for fname in [
                "index.html", "agents.html", "quota.html",
                "prompts.html", "login.html", "profile.html",
            ]:
                if fname.replace(".html", "") in issue_content.lower():
                    file_path = f"src/stronghold/dashboard/{fname}"
                    break
        if not file_path:
            file_path = "src/stronghold/dashboard/index.html"

        source_context = await self._read_file(file_path, ws)
        test_file = f"tests/api/test_issue_{run.issue_number}.py"
        files_written: list[str] = []
        criteria_completed = 0

        for i, criterion in enumerate(criteria):
            if i == 0:
                template = await self._get_prompt(
                    "builders.glazier.write_ui_test",
                )
                if not template:
                    from stronghold.builders.ui_prompts import (
                        GLAZIER_WRITE_UI_TEST,
                    )
                    template = GLAZIER_WRITE_UI_TEST
                raw_prompt = self._render(
                    template,
                    criterion=criterion,
                    file_path=file_path,
                    rendering_model=rendering_model,
                    source_context=source_context[:6000],
                    feedback_block=feedback or "",
                )
            else:
                existing_code = await self._read_file(test_file, ws)
                template = await self._get_prompt(
                    "builders.glazier.append_ui_test",
                )
                if not template:
                    from stronghold.builders.ui_prompts import (
                        GLAZIER_APPEND_UI_TEST,
                    )
                    template = GLAZIER_APPEND_UI_TEST
                raw_prompt = self._render(
                    template,
                    criterion=criterion,
                    rendering_model=rendering_model,
                    existing_code=existing_code,
                    feedback_block="",
                )

            prompt = self._prepend_onboarding(raw_prompt, run)
            try:
                test_code = await self._llm_extract(
                    prompt, self._mason_model,
                    extract_python_code,
                    f"UI test for criterion {i + 1}",
                )
                await self._write_file(test_file, test_code, ws)
            except ExtractionError as e:
                logger.error("UI test gen failed c%d: %s", i + 1, e)
                continue

            # Try to make the test pass (implement)
            for impl_attempt in range(3):
                output = await self._run_pytest(ws, test_file)
                passing = self._count_passing(output)
                failing = self._count_failing(output)

                if failing == 0 and passing > 0:
                    break

                current_source = await self._read_file(file_path, ws)
                current_test = await self._read_file(test_file, ws)

                impl_template = await self._get_prompt(
                    "builders.glazier.implement_ui",
                )
                if not impl_template:
                    from stronghold.builders.ui_prompts import (
                        GLAZIER_IMPLEMENT_UI,
                    )
                    impl_template = GLAZIER_IMPLEMENT_UI

                impl_prompt = self._render(
                    impl_template,
                    test_code=current_test,
                    pytest_output=output[:2000],
                    file_path=file_path,
                    source_code=current_source[:8000],
                    rendering_model=rendering_model,
                    issue_content=issue_content[:500],
                    feedback_block="",
                )

                try:
                    new_html = await self._llm_extract(
                        impl_prompt, self._mason_model,
                        self._extract_html,
                        f"UI impl c{i + 1}a{impl_attempt + 1}",
                    )
                    await self._write_file(file_path, new_html, ws)
                    if file_path not in files_written:
                        files_written.append(file_path)
                except ExtractionError:
                    break

            # Count final state
            final_output = await self._run_pytest(ws, test_file)
            final_passing = self._count_passing(final_output)
            if final_passing > 0:
                criteria_completed += 1

        # Commit changes
        if files_written:
            await self._td.execute(
                "shell",
                {
                    "command": f"git add -A && git commit -m "
                    f"'glazier: UI fix for #{run.issue_number}'",
                    "workspace": ws,
                },
            )

        final_output = await self._run_pytest(ws, test_file)
        final_passing = self._count_passing(final_output)
        final_failing = self._count_failing(final_output)

        summary = (
            f"## UI TDD Complete\n\n"
            f"**Model:** `{self._mason_model}`\n"
            f"**Rendering model:** {rendering_model}\n"
            f"**Criteria completed:** {criteria_completed}"
            f"/{len(criteria)}\n"
            f"**Files modified:** "
            f"{', '.join(f'`{f}`' for f in files_written)}\n"
            f"**Tests:** {final_passing} passed, "
            f"{final_failing} failed\n"
        )
        await self._post_to_issue(
            owner, repo, run.issue_number, summary, run=run,
        )

        return StageResult(
            success=final_passing > 0,
            summary=summary,
            evidence={
                "test_file": test_file,
                "files_written": files_written,
                "criteria_completed": criteria_completed,
                "tests_passing": final_passing,
                "tests_failing": final_failing,
                "rendering_model": rendering_model,
            },
        )

    async def implement_ui(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Glazier: implementation done in write_ui_tests (combined TDD)."""
        return StageResult(
            success=True,
            summary="Implementation completed in ui_tests_written stage",
            evidence={"note": "Combined with write_ui_tests"},
        )

    async def verify_ui(
        self, run: Any, feedback: str = "",
    ) -> StageResult:
        """Glazier: final verification for UI changes."""
        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")

        test_file = f"tests/api/test_issue_{run.issue_number}.py"
        pytest_output = await self._run_pytest(ws, test_file)
        git_log = await self._td.execute(
            "shell", {"command": "git log --oneline -10", "workspace": ws},
        )
        git_diff = await self._td.execute(
            "shell",
            {"command": "git diff main --stat", "workspace": ws},
        )

        summary = (
            f"## UI Final Verification\n\n"
            f"**Pytest:**\n```\n{pytest_output[:1500]}\n```\n\n"
            f"**Git log:**\n```\n{git_log}\n```\n\n"
            f"**Changes:**\n```\n{git_diff}\n```\n"
        )
        await self._post_to_issue(owner, repo, run.issue_number, summary, run=run)

        return StageResult(
            success=True, summary=summary,
            evidence={
                "pytest_output": pytest_output[:3000],
                "git_log": git_log,
                "diff_stat": git_diff,
            },
        )

    @staticmethod
    def _extract_html(text: str) -> str:
        """Extract HTML from LLM response (code block or raw)."""
        # Try to extract from ```html ... ``` block
        import re
        match = re.search(
            r"```(?:html)?\s*\n(.*?)```", text, re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        # If response starts with <!DOCTYPE or <html, use as-is
        stripped = text.strip()
        if stripped.startswith("<!") or stripped.startswith("<html"):
            return stripped
        raise ExtractionError("Could not extract HTML from response")

    # ── Quartermaster: Issue Decomposition ────────────────────────────

    @staticmethod
    def _triage_issue(title: str, body: str) -> str:
        """Classify an issue into a decomposition strategy.

        Returns one of:
        - "atomic"          — single file, no decomposition needed
        - "enumerable:ruff" — work is enumerable from ruff output
        - "enumerable:mypy" — work is enumerable from mypy output
        - "agentic"         — needs LLM-driven planning
        """
        import re as _re

        text = f"{title}\n{body}".lower()

        # Enumerable: tool-driven cleanup
        if "ruff check" in text or "ruff errors" in text or "ruff lint" in text:
            return "enumerable:ruff"
        if "mypy --strict" in text or "mypy errors" in text or "type errors" in text:
            return "enumerable:mypy"

        # Atomic: single file mention with few criteria, no multi-file markers
        path_matches = _re.findall(r"src/stronghold/[\w/]+\.(?:py|html)", text)
        unique_paths = set(path_matches)
        criteria_count = body.count("- [ ]") + body.count("- [x]")

        # Strong multi-file signals — anything with these is NOT atomic
        multi_file_markers = (
            "files to create",
            "files to modify",
            "files to add",
            "## files",
            "new files",
            ".github/workflows/",
        )
        has_multi_file_marker = any(m in text for m in multi_file_markers)

        if (
            len(unique_paths) <= 1
            and criteria_count <= 3
            and not has_multi_file_marker
        ):
            return "atomic"

        # Otherwise, agentic LLM decomposition
        return "agentic"

    async def _enumerable_ruff(
        self, run: Any, ws: str,
    ) -> list[dict[str, Any]]:
        """Run ruff and produce one step per file with errors.

        Writes ruff JSON to a temp file (shell tool truncates stdout at
        3000 chars; ruff output for many errors is much bigger). Then
        reads the file and parses.
        """
        import json as _json
        from collections import defaultdict

        # Write ruff JSON to a temp file in the worktree
        await self._td.execute(
            "shell",
            {
                "command": (
                    "ruff check src/stronghold/ "
                    "--output-format=json --no-fix > .ruff_errors.json 2>&1 || true"
                ),
                "workspace": ws,
            },
        )

        stdout = await self._read_file(".ruff_errors.json", ws)
        if not stdout:
            return []

        # Find the JSON array in stdout (ruff outputs an array of objects)
        try:
            json_start = stdout.find("[")
            json_end = stdout.rfind("]") + 1
            if json_start == -1 or json_end == 0:
                return []
            ruff_errors = _json.loads(stdout[json_start:json_end])
        except Exception:
            return []

        if not ruff_errors:
            return []

        # Group by file
        by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for err in ruff_errors:
            fname = err.get("filename", "")
            if fname.startswith("/"):
                # Make path relative to workspace
                fname = fname.split("/src/stronghold/", 1)[-1]
                fname = "src/stronghold/" + fname
            by_file[fname].append(err)

        # Build steps — one per file
        steps = []
        for fname, errors in sorted(by_file.items()):
            rules = sorted({e.get("code", "?") for e in errors})
            error_lines = []
            for e in errors[:20]:
                code = e.get("code", "?")
                msg = e.get("message", "")
                loc = e.get("location", {})
                line = loc.get("row", 0)
                col = loc.get("column", 0)
                fix_avail = "✓" if e.get("fix") else " "
                error_lines.append(f"  {fix_avail} {code} {fname}:{line}:{col}  {msg}")
            if len(errors) > 20:
                error_lines.append(f"  ... and {len(errors) - 20} more")

            body = (
                f"## Description\n"
                f"Fix all ruff violations in `{fname}`.\n\n"
                f"## Errors ({len(errors)} total)\n"
                f"Rules: {', '.join(rules)}\n\n"
                f"```\n{chr(10).join(error_lines)}\n```\n\n"
                f"## Acceptance Criteria\n"
                f"- [ ] `ruff check {fname}` returns zero errors\n"
                f"- [ ] `ruff format --check {fname}` passes\n"
                f"- [ ] No functional changes (lint/format only)\n\n"
                f"## Implementation Notes\n"
                f"Run `ruff check --fix {fname}` and `ruff format {fname}` "
                f"first to handle auto-fixable items, then manually fix the rest.\n\n"
                f"## Files\n- {fname}"
            )
            steps.append({
                "title": (
                    f"fix: ruff cleanup in "
                    f"{fname.replace('src/stronghold/', '')}"
                ),
                "body": body,
                "depends_on": [],
                "file": fname,
            })

        return steps

    async def _enumerable_mypy(
        self, run: Any, ws: str,
    ) -> list[dict[str, Any]]:
        """Run mypy and produce one step per file with errors."""
        from collections import defaultdict
        import re as _re

        await self._td.execute(
            "shell",
            {
                "command": (
                    "mypy src/stronghold/ --strict --no-error-summary "
                    "> .mypy_errors.txt 2>&1 || true"
                ),
                "workspace": ws,
            },
        )

        stdout = await self._read_file(".mypy_errors.txt", ws)
        if not stdout:
            return []

        # Parse mypy lines: path:line: error: message  [code]
        line_pat = _re.compile(
            r"^(src/stronghold/[^:]+):(\d+):(?:\d+:)?\s*(error|warning):\s*(.+?)(?:\s+\[([^\]]+)\])?$",
            _re.MULTILINE,
        )
        by_file: dict[str, list[dict[str, str]]] = defaultdict(list)
        for m in line_pat.finditer(stdout):
            fname, line, _sev, msg, code = m.groups()
            by_file[fname].append({
                "line": line,
                "message": msg.strip(),
                "code": code or "",
            })

        if not by_file:
            return []

        steps = []
        for fname, errors in sorted(by_file.items()):
            error_lines = "\n".join(
                f"  {e['line']}: {e['message']}"
                + (f"  [{e['code']}]" if e["code"] else "")
                for e in errors[:30]
            )
            if len(errors) > 30:
                error_lines += f"\n  ... and {len(errors) - 30} more"

            body = (
                f"## Description\n"
                f"Fix mypy --strict errors in `{fname}`.\n\n"
                f"## Errors ({len(errors)} total)\n"
                f"```\n{error_lines}\n```\n\n"
                f"## Acceptance Criteria\n"
                f"- [ ] `mypy {fname} --strict` passes with zero errors\n"
                f"- [ ] No type-ignore comments added unless absolutely necessary\n"
                f"- [ ] Existing behavior preserved\n\n"
                f"## Files\n- {fname}"
            )
            steps.append({
                "title": (
                    f"fix: mypy strict in "
                    f"{fname.replace('src/stronghold/', '')}"
                ),
                "body": body,
                "depends_on": [],
                "file": fname,
            })

        return steps

    @staticmethod
    def _needs_further_decomposition(title: str, body: str) -> bool:
        """Heuristic: is this sub-issue still too broad for Mason to solve?

        Signals:
        - Mentions multiple distinct directories under src/stronghold/
        - Mentions "across repo", "whole repo", "all files"
        - Has more than 3 acceptance criteria touching different files
        - Title prefixed with "cleanup", "refactor all", "fix all"
        """
        import re as _re

        text = f"{title}\n{body}".lower()

        # Broad-scope keywords
        broad_keywords = [
            "across repo", "across the repo", "whole repo",
            "all files", "every file", "entire codebase",
        ]
        if any(kw in text for kw in broad_keywords):
            return True

        # Title prefixes indicating wide scope
        broad_prefixes = ("cleanup", "refactor all", "fix all", "migrate all")
        if any(title.lower().strip().startswith(p) for p in broad_prefixes):
            return True

        # Count distinct directories mentioned
        paths = _re.findall(r"src/stronghold/([\w]+(?:/[\w]+)*)", text)
        directories: set[str] = set()
        for p in paths:
            # Take first 2 path segments as "directory"
            parts = p.split("/")
            directories.add("/".join(parts[:2]))
        if len(directories) > 2:
            return True

        return False

    async def decompose_issue(
        self, run: Any, *, depth: int = 0, max_depth: int = 3,
    ) -> StageResult:
        """Quartermaster: decompose a parent issue into sub-issues with dependencies.

        If depth < max_depth, children that are still too broad will be
        recursively decomposed. Parent issues get an 'epic' label so the
        scheduler skips them and works the leaves instead.

        1. Read parent issue + repo context
        2. LLM produces JSON with steps + depends_on (local indices)
        3. For each step: create_issue, then create_sub_issue(parent, child)
        4. After all created: add_blocked_by edges per the depends_on map
        5. For each child still too broad: recurse (up to max_depth)
        6. Label parent as 'epic' so the scheduler skips it
        7. Post a summary comment on the parent issue
        """
        import json as _json

        owner, repo = run.repo.split("/")
        ws = getattr(run, "_workspace_path", "")
        issue_content = getattr(run, "_issue_content", "")
        issue_title = getattr(run, "_issue_title", "")

        # ── Triage: pick the right strategy ──
        strategy = self._triage_issue(issue_title, issue_content)
        logger.info(
            "Quartermaster triage on #%s → %s",
            run.issue_number, strategy,
        )

        plan_summary = ""
        steps: list[dict[str, Any]] = []

        if strategy == "atomic":
            # No decomposition needed — leave the issue for Mason to work directly
            return StageResult(
                success=True,
                summary=(
                    f"Triage: atomic — single-file work order, "
                    f"no decomposition needed."
                ),
                evidence={
                    "parent": run.issue_number,
                    "strategy": "atomic",
                    "depth": depth,
                    "created": [],
                },
            )

        elif strategy == "enumerable:ruff":
            steps = await self._enumerable_ruff(run, ws)
            plan_summary = (
                f"Enumerable ruff decomposition: {len(steps)} files with errors. "
                f"One sub-issue per file."
            )

        elif strategy == "enumerable:mypy":
            steps = await self._enumerable_mypy(run, ws)
            plan_summary = (
                f"Enumerable mypy decomposition: {len(steps)} files with errors. "
                f"One sub-issue per file."
            )

        else:  # agentic
            file_listing = await self._list_files("src/", ws)

            relevant_files = ""
            import re as _re
            mentioned_paths = _re.findall(
                r"(src/stronghold/[\w/]+\.py)", issue_content,
            )
            for path in mentioned_paths[:5]:
                content = await self._read_file(path, ws)
                if content:
                    relevant_files += f"\n# --- {path} ---\n{content[:2000]}\n"

            template = await self._get_prompt("builders.quartermaster.decompose")
            if not template:
                from stronghold.builders.prompts import QUARTERMASTER_DECOMPOSE
                template = QUARTERMASTER_DECOMPOSE

            prompt = self._render(
                template,
                issue_number=str(run.issue_number),
                issue_title=issue_title,
                issue_content=issue_content,
                file_listing=file_listing[:4000],
                relevant_files=relevant_files[:6000],
            )

            plan = await self._llm_extract(
                prompt, self._frank_model, extract_json, "decomposition plan",
            )
            steps = plan.get("steps", [])
            plan_summary = plan.get("summary", "")

        if not steps:
            return StageResult(
                success=False,
                summary=f"Triage: {strategy} produced no steps",
            )

        # Enumerable strategies are uncapped; agentic capped at 25.
        # The cap exists because LLM decompositions tend to either over-split
        # (50 trivial steps) or under-split (3 huge steps); the cap is a
        # heuristic ceiling that says "if you produced more than this, your
        # parent epic is genuinely too broad and a human should split it
        # first." 25 fits real-world v0.9 epics like 'populate priority_tier
        # in 15+ agent.yaml files'; the prior 10 was rejecting them as
        # 'too broad' when they were actually correctly enumerated.
        AGENTIC_CAP = 25
        if strategy == "agentic" and len(steps) > AGENTIC_CAP:
            return StageResult(
                success=False,
                summary=(
                    f"Too many steps ({len(steps)} > {AGENTIC_CAP}) — "
                    f"parent is too broad. Split it into narrower epics first."
                ),
            )

        # Hard safety cap to prevent runaway issue creation
        if len(steps) > 100:
            steps = steps[:100]
            plan_summary += f" (capped at 100 from larger set)"

        # Create all child issues first, recording step index → issue number
        created: list[dict[str, Any]] = []
        for i, step in enumerate(steps):
            title = step.get("title", f"sub-issue {i + 1}")
            body = step.get("body", "")
            body += f"\n\n---\n_Sub-issue of #{run.issue_number}, step {i + 1} of {len(steps)}_"

            result = await self._td.execute(
                "github",
                {
                    "action": "create_issue",
                    "owner": owner, "repo": repo,
                    "title": title, "body": body,
                    "labels": ["builders", "quartermaster"],
                },
            )
            if result.startswith("Error:"):
                logger.error("Failed to create sub-issue %d: %s", i, result)
                return StageResult(
                    success=False,
                    summary=f"Failed to create sub-issue {i + 1}: {result[:200]}",
                )
            try:
                data = _json.loads(result)
            except Exception:
                return StageResult(
                    success=False, summary=f"Bad create_issue response: {result[:200]}",
                )
            created.append({
                "index": i,
                "number": data["number"],
                "title": title,
                "depends_on": step.get("depends_on", []),
            })

        # Link each child as a sub-issue of the parent
        for c in created:
            await self._td.execute(
                "github",
                {
                    "action": "create_sub_issue",
                    "owner": owner, "repo": repo,
                    "issue_number": run.issue_number,
                    "sub_issue_number": c["number"],
                },
            )

        # Add blocked_by edges per depends_on (local index → issue number)
        for c in created:
            for dep_idx in c["depends_on"]:
                if not isinstance(dep_idx, int) or dep_idx >= len(created):
                    continue
                blocker = created[dep_idx]
                await self._td.execute(
                    "github",
                    {
                        "action": "add_blocked_by",
                        "owner": owner, "repo": repo,
                        "issue_number": c["number"],
                        "blocker_issue_number": blocker["number"],
                    },
                )

        # Recurse on children that are still too broad
        recursive_depth = depth + 1
        recurse_counts: list[dict[str, Any]] = []
        if recursive_depth <= max_depth:
            from types import SimpleNamespace

            for c in created:
                # Get the step body that was used to create this child
                step_body = ""
                for i, step in enumerate(steps):
                    if i == c["index"]:
                        step_body = step.get("body", "")
                        break

                if not self._needs_further_decomposition(c["title"], step_body):
                    continue

                logger.info(
                    "Quartermaster recursing on #%d (depth %d)",
                    c["number"], recursive_depth,
                )
                child_run = SimpleNamespace(
                    run_id=f"qm-{recursive_depth}-{c['number']}",
                    issue_number=c["number"],
                    repo=run.repo,
                    _issue_title=c["title"],
                    _issue_content=step_body,
                    _workspace_path=ws,
                )
                child_result = await self.decompose_issue(
                    child_run, depth=recursive_depth, max_depth=max_depth,
                )
                recurse_counts.append({
                    "parent": c["number"],
                    "success": child_result.success,
                    "sub_created": (
                        child_result.evidence.get("created", [])
                        if child_result.success
                        else []
                    ),
                })

        # Label this parent as 'epic' so the scheduler skips it
        await self._td.execute(
            "github",
            {
                "action": "add_labels",
                "owner": owner, "repo": repo,
                "issue_number": run.issue_number,
                "labels": ["epic"],
            },
        )

        # Post summary comment to the parent
        lines = [
            f"## Quartermaster Decomposition (depth {depth}, strategy: {strategy})\n"
        ]
        lines.append(f"{plan_summary}\n")
        lines.append(f"**{len(created)} sub-issues created:**\n")
        for c in created:
            deps = c["depends_on"]
            dep_str = ""
            if deps:
                dep_numbers = [f"#{created[d]['number']}" for d in deps if d < len(created)]
                dep_str = f" _(blocked by {', '.join(dep_numbers)})_"
            # Mark recursed children
            recursed = any(r["parent"] == c["number"] for r in recurse_counts)
            marker = " 🔻 _(further decomposed)_" if recursed else ""
            lines.append(f"- #{c['number']} {c['title']}{dep_str}{marker}")

        if recurse_counts:
            total_leaves = sum(len(r["sub_created"]) for r in recurse_counts)
            lines.append(
                f"\n_Recursed on {len(recurse_counts)} children, "
                f"created {total_leaves} leaf sub-issues._"
            )

        summary_text = "\n".join(lines)

        await self._td.execute(
            "github",
            {
                "action": "post_pr_comment",
                "owner": owner, "repo": repo,
                "issue_number": run.issue_number,
                "body": summary_text,
            },
        )

        return StageResult(
            success=True,
            summary=summary_text,
            evidence={
                "parent": run.issue_number,
                "depth": depth,
                "strategy": strategy,
                "created": [{"number": c["number"], "title": c["title"]} for c in created],
                "dependency_count": sum(len(c["depends_on"]) for c in created),
                "recursed": recurse_counts,
            },
        )

    # ── Gatekeeper: PR Review ────────────────────────────────────────

    async def review_pr(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        auto_merge_enabled: bool = False,
        allowed_authors: tuple[str, ...] = (),
        coverage_tolerance_pct: float = -1.0,
        protected_branches: tuple[str, ...] = ("main", "master"),
    ) -> StageResult:
        """Gatekeeper: review a PR end-to-end and either approve or request changes.

        Phases:
        1. Intake: fetch PR metadata, diff, parent issue
        2. Scope: read full changed files + siblings + callers
        3. Mechanical: ruff, mypy, bandit, pytest on changed files
        4. LLM semantic review: feeds context to Opus, extracts JSON verdict
        5. Act: post review (APPROVE or REQUEST_CHANGES), merge if approved
        """
        import json as _json

        td = self._td

        # ── Phase 1: Intake ────────────────────────────────────────
        pr_raw = await td.execute(
            "github",
            {
                "action": "get_pr",
                "owner": owner, "repo": repo,
                "issue_number": pr_number,
            },
        )
        if pr_raw.startswith("Error:"):
            return StageResult(
                success=False, summary=f"Cannot fetch PR: {pr_raw[:200]}",
            )
        try:
            pr = _json.loads(pr_raw)
        except Exception:
            return StageResult(
                success=False, summary="Bad PR response",
            )

        # Identify parent issue from PR title (pattern: "feat: #NNN —")
        import re as _re
        issue_match = _re.search(r"#(\d+)", pr.get("title", ""))
        parent_issue_number = int(issue_match.group(1)) if issue_match else None
        issue_body = ""
        if parent_issue_number:
            issue_raw = await td.execute(
                "github",
                {
                    "action": "get_issue",
                    "owner": owner, "repo": repo,
                    "issue_number": parent_issue_number,
                },
            )
            if not issue_raw.startswith("Error:"):
                try:
                    issue_body = _json.loads(issue_raw).get("body", "") or ""
                except Exception:
                    issue_body = ""

        # Fetch files changed
        files_raw = await td.execute(
            "github",
            {
                "action": "list_pr_files",
                "owner": owner, "repo": repo,
                "issue_number": pr_number,
            },
        )
        try:
            pr_files = _json.loads(files_raw) if not files_raw.startswith("Error:") else []
        except Exception:
            pr_files = []

        changed_paths = [f["filename"] for f in pr_files if f["filename"].startswith("src/")]
        py_files = [p for p in changed_paths if p.endswith(".py")]

        # ── Phase 2: Scope (need a worktree) ──────────────────────
        # Use workspace tool to ensure we have the PR branch checked out
        ws_result = await td.execute(
            "workspace",
            {
                "action": "create",
                "issue_number": parent_issue_number or pr_number,
                "owner": owner, "repo": repo,
            },
        )
        ws_path = ""
        if not ws_result.startswith("Error:"):
            try:
                ws_path = _json.loads(ws_result).get("path", "")
            except Exception:
                ws_path = ""

        # Checkout the PR head branch in the workspace
        if ws_path and pr.get("head", {}).get("ref"):
            head_ref = pr["head"]["ref"]
            await td.execute(
                "shell",
                {
                    "command": f"git fetch origin {head_ref} && "
                    f"git checkout -B {head_ref} origin/{head_ref}",
                    "workspace": ws_path,
                },
            )

        # Read full changed files
        changed_files_content = ""
        for fpath in changed_paths[:10]:
            content = await self._read_file(fpath, ws_path)
            if content:
                changed_files_content += (
                    f"\n# --- {fpath} ---\n{content[:3000]}\n"
                )

        # Read siblings of new files for parallel structure
        sibling_files_content = ""
        for fpath in changed_paths[:5]:
            # Only for newly added files
            added = any(
                f["filename"] == fpath and f["status"] == "added"
                for f in pr_files
            )
            if not added:
                continue
            import os as _os
            dir_path = _os.path.dirname(fpath)
            if not dir_path:
                continue
            siblings_raw = await td.execute(
                "glob_files",
                {
                    "pattern": f"{dir_path}/*.py",
                    "workspace": ws_path,
                    "max_results": 5,
                },
            )
            if siblings_raw.startswith("Error:"):
                continue
            try:
                siblings_data = _json.loads(siblings_raw)
                sibling_paths = siblings_data.get("files", [])
            except Exception:
                sibling_paths = []
            for sib in sibling_paths[:3]:
                if sib == fpath:
                    continue
                sib_content = await self._read_file(sib, ws_path)
                if sib_content:
                    sibling_files_content += (
                        f"\n# --- {sib} (sibling pattern) ---\n"
                        f"{sib_content[:2000]}\n"
                    )

        # Callers of changed symbols — grep for imports
        callers_content = ""
        for fpath in py_files[:3]:
            module = fpath.replace("src/", "").replace("/", ".").replace(".py", "")
            callers_raw = await td.execute(
                "grep_content",
                {
                    "pattern": f"from {module}|import {module}",
                    "workspace": ws_path,
                    "glob": "**/*.py",
                    "max_results": 10,
                },
            )
            if callers_raw and not callers_raw.startswith("Error:"):
                try:
                    callers_data = _json.loads(callers_raw)
                    matches = callers_data.get("matches", [])
                    for m in matches[:5]:
                        callers_content += (
                            f"- {m['file']}:{m['line']}: {m['content']}\n"
                        )
                except Exception:
                    pass

        # Read CLAUDE.md and ONBOARDING.md
        claude_md = (await self._read_file("CLAUDE.md", ws_path))[:4000]
        onboarding_md = (await self._read_file("ONBOARDING.md", ws_path))[:4000]
        repo_standards = (
            f"## CLAUDE.md\n{claude_md}\n\n## ONBOARDING.md\n{onboarding_md}"
        )

        # ── Phase 3: Mechanical gates ──────────────────────────────
        mechanical_results: dict[str, str] = {}
        if py_files:
            files_str = " ".join(py_files)
            for gate_name, cmd in [
                ("ruff_check", f"ruff check {files_str}"),
                ("ruff_format", f"ruff format --check {files_str}"),
                ("mypy", f"mypy {files_str} --strict"),
                ("bandit", f"bandit {files_str} -ll"),
            ]:
                result = await td.execute(
                    "shell",
                    {"command": cmd, "workspace": ws_path},
                )
                mechanical_results[gate_name] = result[:500]

        mechanical_summary = "\n".join(
            f"{k}: {v[:200]}" for k, v in mechanical_results.items()
        )
        mechanical_pass = all(
            '"passed": true' in v or v.startswith("Error:") or "Success" in v
            for v in mechanical_results.values()
        )

        # ── Coverage check ─────────────────────────────────────────
        coverage_summary = "Coverage check skipped (no baseline available)"
        if py_files and ws_path:
            cov_modules = ",".join(
                f.replace("src/", "").replace("/", ".").replace(".py", "")
                for f in py_files
            )
            cov_result = await td.execute(
                "shell",
                {
                    "command": (
                        f"python -m pytest tests/ -q --cov={cov_modules} "
                        f"--cov-report=term --no-header 2>&1 | tail -20"
                    ),
                    "workspace": ws_path,
                },
            )
            if not cov_result.startswith("Error:"):
                coverage_summary = f"```\n{cov_result[:1500]}\n```"

        # ── Phase 4: LLM semantic review ───────────────────────────
        template = await self._get_prompt("builders.gatekeeper.review_pr")
        if not template:
            from stronghold.builders.prompts import GATEKEEPER_REVIEW_PR
            template = GATEKEEPER_REVIEW_PR

        prompt = self._render(
            template,
            pr_number=str(pr_number),
            pr_title=pr.get("title", ""),
            pr_author=pr.get("user", ""),
            pr_body=(pr.get("body") or "")[:2000],
            base_branch=pr.get("base", {}).get("ref", "main"),
            head_branch=pr.get("head", {}).get("ref", ""),
            files_count=str(pr.get("changed_files", len(pr_files))),
            additions=str(pr.get("additions", 0)),
            deletions=str(pr.get("deletions", 0)),
            issue_number=str(parent_issue_number or ""),
            issue_body=issue_body[:3000],
            mechanical_result=mechanical_summary[:2000],
            coverage_summary=coverage_summary[:1500],
            changed_files=changed_files_content[:15000],
            sibling_files=sibling_files_content[:6000],
            callers=callers_content[:3000],
            repo_standards=repo_standards[:8000],
        )

        verdict = await self._llm_extract(
            prompt, self._mason_model, extract_json, "gatekeeper verdict",
        )

        decision = verdict.get("decision", "request_changes")
        summary = verdict.get("summary", "")
        blockers = verdict.get("blockers", [])
        checked = verdict.get("checked", [])
        suggestions = verdict.get("suggestions", [])

        # Mechanical failures force request_changes
        if not mechanical_pass and decision == "approve":
            decision = "request_changes"
            blockers.append({
                "file": "(multiple)",
                "line": 0,
                "severity": "error",
                "category": "mechanical",
                "message": f"Mechanical gates failed:\n{mechanical_summary[:1000]}",
            })

        # ── Phase 5: Act ───────────────────────────────────────────
        review_body_lines = [
            f"## Gatekeeper Review",
            "",
            f"**Decision:** {decision.upper()}",
            f"**Summary:** {summary}",
            "",
        ]
        if checked:
            review_body_lines.append("### What I checked")
            for c in checked[:20]:
                review_body_lines.append(f"- ✓ {c}")
            review_body_lines.append("")

        if blockers:
            review_body_lines.append("### Blockers")
            for b in blockers[:20]:
                line_ref = f":{b.get('line')}" if b.get("line") else ""
                review_body_lines.append(
                    f"- **{b.get('category', '?')}** "
                    f"`{b.get('file', '?')}{line_ref}` — "
                    f"{b.get('message', '')}"
                )
            review_body_lines.append("")

        if suggestions:
            review_body_lines.append("### Suggestions (non-blocking)")
            for s in suggestions[:10]:
                line_ref = f":{s.get('line')}" if s.get("line") else ""
                review_body_lines.append(
                    f"- `{s.get('file', '?')}{line_ref}` — "
                    f"{s.get('message', '')}"
                )

        review_body = "\n".join(review_body_lines)

        event = "APPROVE" if decision == "approve" else "REQUEST_CHANGES"

        review_result = await td.execute(
            "github",
            {
                "action": "review_pr",
                "owner": owner, "repo": repo,
                "issue_number": pr_number,
                "event": event,
                "body": review_body,
            },
        )

        merged = False
        merge_message = ""
        if decision == "approve" and auto_merge_enabled:
            # Guardrails
            author_ok = (
                not allowed_authors
                or pr.get("user", "") in allowed_authors
            )
            branch_ok = pr.get("base", {}).get("ref") not in protected_branches
            if author_ok and branch_ok:
                merge_raw = await td.execute(
                    "github",
                    {
                        "action": "merge_pr",
                        "owner": owner, "repo": repo,
                        "issue_number": pr_number,
                        "merge_method": "squash",
                        "commit_title": pr.get("title", f"PR #{pr_number}"),
                    },
                )
                if not merge_raw.startswith("Error:"):
                    try:
                        merge_data = _json.loads(merge_raw)
                        merged = bool(merge_data.get("merged", False))
                        merge_message = merge_data.get("message", "")
                    except Exception:
                        pass
            else:
                merge_message = (
                    f"auto_merge guardrails rejected: "
                    f"author_ok={author_ok} branch_ok={branch_ok}"
                )

        # Post verdict to the parent issue (if there is one)
        if parent_issue_number:
            parent_body = (
                f"## Gatekeeper Verdict on PR #{pr_number}\n\n"
                f"**Decision:** {decision.upper()}\n"
                f"{summary}\n"
            )
            if merged:
                parent_body += f"\n**Merged.** {merge_message}\n"
            elif merge_message:
                parent_body += f"\n_{merge_message}_\n"
            await td.execute(
                "github",
                {
                    "action": "post_pr_comment",
                    "owner": owner, "repo": repo,
                    "issue_number": parent_issue_number,
                    "body": parent_body,
                },
            )

        return StageResult(
            success=(decision == "approve"),
            summary=f"{event}: {summary}",
            evidence={
                "pr": pr_number,
                "decision": decision,
                "blockers_count": len(blockers),
                "blockers": blockers[:10],
                "checked_count": len(checked),
                "merged": merged,
                "merge_message": merge_message,
                "mechanical_pass": mechanical_pass,
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
        auditor_logger.info(
            "[AUDITOR] stage=%s approved=%s first80=%s",
            stage, approved, text[:80] if text else "EMPTY",
            extra={"run_id": "-"},
        )
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

    @staticmethod
    def _extract_files_from_issue_body(issue_body: str) -> list[str]:
        """Extract file paths from a Quartermaster-style '## Files' section.

        Quartermaster decompositions and other well-formed sub-issues
        include an explicit list of files that should be created or
        modified, as a markdown bullet list under a '## Files' header
        (sometimes '## Files to create' or '## Files to modify').

        Example issue body fragment::

            ## Files
            - src/stronghold/analytics/suggestions.py
            - src/stronghold/api/routes/optimization.py
            - tests/api/test_optimization.py

        Returns the list of paths in document order, deduplicated.
        Returns [] if no '## Files' section is present.

        This is the source of truth for the implementation pipeline:
        if Quartermaster (or a human author) said the issue requires
        these files, the impl phase must create them. Frank's LLM
        guess at affected_files is secondary and may hallucinate
        existing-but-wrong paths.
        """
        import re

        match = re.search(
            r"^##\s+Files(?:\s+to\s+(?:create|modify|change))?\s*\n"
            r"((?:[ \t]*[-*][ \t]+\S.*\n?)+)",
            issue_body,
            re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            return []

        block = match.group(1)
        paths: list[str] = []
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith(("-", "*")):
                continue
            # Strip the bullet marker, surrounding backticks, and any
            # trailing inline annotation like " (new)" or " — desc".
            entry = line.lstrip("-*").strip().strip("`").strip()
            # Stop at the first whitespace so trailing prose doesn't
            # get glued to the path.
            entry = entry.split()[0] if entry else ""
            entry = entry.strip("`,;")
            if entry and entry not in paths:
                paths.append(entry)
        return paths
