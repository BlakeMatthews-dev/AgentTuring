"""UI pipeline stages (Piper + Glazier): analyze, criteria, tests, implement, verify."""

from __future__ import annotations

import logging
from typing import Any

from stronghold.builders.extractors import ExtractionError, extract_gherkin_scenarios, extract_python_code

logger = logging.getLogger("stronghold.builders.pipeline")


# Lazy import to avoid circular: used inside function bodies
_StageResult = None


def _get_stage_result() -> type:
    global _StageResult
    if _StageResult is None:
        from stronghold.builders.pipeline import StageResult
        _StageResult = StageResult
    return _StageResult


# ── UI Pipeline Methods (Piper + Glazier) ─────────────────────

async def analyze_ui(run: Any, pipeline: Any = None, feedback: str = "") -> Any:
    """Piper: analyze HTML file and classify rendering model."""
    owner, repo = run.repo.split("/")
    ws = getattr(run, "_workspace_path", "")
    issue_content = getattr(run, "_issue_content", "")
    issue_title = getattr(run, "_issue_title", "")

    # List dashboard files
    dashboard_listing = await pipeline._list_files(
        "src/stronghold/dashboard", ws,
    )

    # Detect affected file
    template = await pipeline._get_prompt("builders.piper.analyze_ui")
    if not template:
        from stronghold.builders.ui_prompts import PIPER_ANALYZE_UI
        template = PIPER_ANALYZE_UI

    # Read the likely target file
    source_context = ""
    for fname in ["index.html", "agents.html", "quota.html",
                   "prompts.html", "login.html", "profile.html"]:
        if fname.replace(".html", "") in issue_content.lower():
            content = await pipeline._read_file(
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
        fname = await pipeline._llm_call(
            pick_prompt, pipeline._frank_model,
        )
        fname = fname.strip().strip("`").strip()
        content = await pipeline._read_file(
            f"src/stronghold/dashboard/{fname}", ws,
        )
        if content:
            source_context = (
                f"# --- src/stronghold/dashboard/{fname}"
                f" ---\n{content}\n"
            )

    # Read prior run history from issue comments
    prior_runs = await pipeline._fetch_prior_runs(
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

    prompt = pipeline._render(
        template,
        issue_number=str(run.issue_number),
        issue_title=issue_title,
        issue_content=issue_content + prior_history,
        source_context=source_context[:8000],
    )
    prompt = pipeline._prepend_onboarding(prompt, run)

    analysis = await pipeline._llm_extract(
        prompt, pipeline._frank_model,
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
    await pipeline._post_to_issue(owner, repo, run.issue_number, summary, run=run)

    return _get_stage_result()(
        success=True, summary=summary,
        evidence={"analysis": analysis},
    )

async def define_ui_criteria(
    run: Any, pipeline: Any = None, feedback: str = "",
) -> Any:
    """Piper: write acceptance criteria for UI issue."""
    owner, repo = run.repo.split("/")
    analysis = getattr(run, "_analysis", {})
    rendering_model = getattr(run, "_rendering_model", "static")
    requirements = analysis.get("requirements", [])

    template = await pipeline._get_prompt(
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

    prompt = pipeline._render(
        template,
        issue_number=str(run.issue_number),
        issue_title=getattr(run, "_issue_title", ""),
        rendering_model=rendering_model,
        requirements="\n".join(f"- {r}" for r in requirements),
        feedback_block=feedback_block,
    )

    scenarios = await pipeline._llm_extract(
        prompt, pipeline._frank_model,
        extract_gherkin_scenarios, "UI Gherkin scenarios",
    )

    run._criteria = scenarios
    scenarios_text = "\n\n".join(scenarios)
    summary = (
        f"## UI Acceptance Criteria\n\n"
        f"**Rendering model:** {rendering_model}\n\n"
        f"```gherkin\n{scenarios_text}\n```\n"
    )
    await pipeline._post_to_issue(owner, repo, run.issue_number, summary, run=run)

    return _get_stage_result()(
        success=True, summary=summary,
        evidence={"scenarios": scenarios},
    )

async def write_ui_tests(
    run: Any, pipeline: Any = None, feedback: str = "",
) -> Any:
    """Glazier: write and implement UI tests (TDD)."""
    owner, repo = run.repo.split("/")
    ws = getattr(run, "_workspace_path", "")
    criteria = getattr(run, "_criteria", [])
    rendering_model = getattr(run, "_rendering_model", "static")
    analysis = getattr(run, "_analysis", {})
    issue_content = getattr(run, "_issue_content", "")
    affected_files = analysis.get("affected_files", [])

    if not criteria:
        return _get_stage_result()(
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

    source_context = await pipeline._read_file(file_path, ws)
    test_file = f"tests/api/test_issue_{run.issue_number}.py"
    files_written: list[str] = []
    criteria_completed = 0

    for i, criterion in enumerate(criteria):
        if i == 0:
            template = await pipeline._get_prompt(
                "builders.glazier.write_ui_test",
            )
            if not template:
                from stronghold.builders.ui_prompts import (
                    GLAZIER_WRITE_UI_TEST,
                )
                template = GLAZIER_WRITE_UI_TEST
            raw_prompt = pipeline._render(
                template,
                criterion=criterion,
                file_path=file_path,
                rendering_model=rendering_model,
                source_context=source_context[:6000],
                feedback_block=feedback or "",
            )
        else:
            existing_code = await pipeline._read_file(test_file, ws)
            template = await pipeline._get_prompt(
                "builders.glazier.append_ui_test",
            )
            if not template:
                from stronghold.builders.ui_prompts import (
                    GLAZIER_APPEND_UI_TEST,
                )
                template = GLAZIER_APPEND_UI_TEST
            raw_prompt = pipeline._render(
                template,
                criterion=criterion,
                rendering_model=rendering_model,
                existing_code=existing_code,
                feedback_block="",
            )

        prompt = pipeline._prepend_onboarding(raw_prompt, run)
        try:
            test_code = await pipeline._llm_extract(
                prompt, pipeline._mason_model,
                extract_python_code,
                f"UI test for criterion {i + 1}",
            )
            await pipeline._write_file(test_file, test_code, ws)
        except ExtractionError as e:
            logger.error("UI test gen failed c%d: %s", i + 1, e)
            continue

        # Try to make the test pass (implement)
        for impl_attempt in range(3):
            output = await pipeline._run_pytest(ws, test_file)
            passing = pipeline._count_passing(output)
            failing = pipeline._count_failing(output)

            if failing == 0 and passing > 0:
                break

            current_source = await pipeline._read_file(file_path, ws)
            current_test = await pipeline._read_file(test_file, ws)

            impl_template = await pipeline._get_prompt(
                "builders.glazier.implement_ui",
            )
            if not impl_template:
                from stronghold.builders.ui_prompts import (
                    GLAZIER_IMPLEMENT_UI,
                )
                impl_template = GLAZIER_IMPLEMENT_UI

            impl_prompt = pipeline._render(
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
                new_html = await pipeline._llm_extract(
                    impl_prompt, pipeline._mason_model,
                    pipeline._extract_html,
                    f"UI impl c{i + 1}a{impl_attempt + 1}",
                )
                await pipeline._write_file(file_path, new_html, ws)
                if file_path not in files_written:
                    files_written.append(file_path)
            except ExtractionError:
                break

        # Count final state
        final_output = await pipeline._run_pytest(ws, test_file)
        final_passing = pipeline._count_passing(final_output)
        if final_passing > 0:
            criteria_completed += 1

    # Commit changes
    if files_written:
        await pipeline._td.execute(
            "shell",
            {
                "command": f"git add -A && git commit -m "
                f"'glazier: UI fix for #{run.issue_number}'",
                "workspace": ws,
            },
        )

    final_output = await pipeline._run_pytest(ws, test_file)
    final_passing = pipeline._count_passing(final_output)
    final_failing = pipeline._count_failing(final_output)

    summary = (
        f"## UI TDD Complete\n\n"
        f"**Model:** `{pipeline._mason_model}`\n"
        f"**Rendering model:** {rendering_model}\n"
        f"**Criteria completed:** {criteria_completed}"
        f"/{len(criteria)}\n"
        f"**Files modified:** "
        f"{', '.join(f'`{f}`' for f in files_written)}\n"
        f"**Tests:** {final_passing} passed, "
        f"{final_failing} failed\n"
    )
    await pipeline._post_to_issue(
        owner, repo, run.issue_number, summary, run=run,
    )

    return _get_stage_result()(
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
    run: Any, pipeline: Any = None, feedback: str = "",
) -> Any:
    """Glazier: implementation done in write_ui_tests (combined TDD)."""
    return _get_stage_result()(
        success=True,
        summary="Implementation completed in ui_tests_written stage",
        evidence={"note": "Combined with write_ui_tests"},
    )

async def verify_ui(
    run: Any, pipeline: Any = None, feedback: str = "",
) -> Any:
    """Glazier: final verification for UI changes."""
    owner, repo = run.repo.split("/")
    ws = getattr(run, "_workspace_path", "")

    test_file = f"tests/api/test_issue_{run.issue_number}.py"
    pytest_output = await pipeline._run_pytest(ws, test_file)
    git_log = await pipeline._td.execute(
        "shell", {"command": "git log --oneline -10", "workspace": ws},
    )
    git_diff = await pipeline._td.execute(
        "shell",
        {"command": "git diff main --stat", "workspace": ws},
    )

    summary = (
        f"## UI Final Verification\n\n"
        f"**Pytest:**\n```\n{pytest_output[:1500]}\n```\n\n"
        f"**Git log:**\n```\n{git_log}\n```\n\n"
        f"**Changes:**\n```\n{git_diff}\n```\n"
    )
    await pipeline._post_to_issue(owner, repo, run.issue_number, summary, run=run)

    return _get_stage_result()(
        success=True, summary=summary,
        evidence={
            "pytest_output": pytest_output[:3000],
            "git_log": git_log,
            "diff_stat": git_diff,
        },
    )

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


def _extract_files_from_issue_body(issue_body: str) -> list[str]:
    from stronghold.builders.pipeline.github_helpers import extract_files_from_issue_body
    return extract_files_from_issue_body(issue_body)

def _count_passing(pytest_output: str) -> int:
    from stronghold.builders.pipeline.pytest_runner import PytestRunner
    return PytestRunner.count_passing(pytest_output)

def _count_failing(pytest_output: str) -> int:
    from stronghold.builders.pipeline.pytest_runner import PytestRunner
    return PytestRunner.count_failing(pytest_output)

def _parse_violation_files(output: str) -> list[str]:
    from stronghold.builders.pipeline.pytest_runner import PytestRunner
    return PytestRunner.parse_violation_files(output)
