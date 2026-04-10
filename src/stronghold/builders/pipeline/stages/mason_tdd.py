"""Mason TDD stage — one-at-a-time test-driven development loop.

For each acceptance criterion: write one test, make it pass, lock it.
Green tests stay green. Append only. Never rewrite a passing test.

This is the largest single stage handler (~430 LOC), extracted from
RuntimePipeline to enable isolated testing.
"""

from __future__ import annotations

import logging
from typing import Any

from stronghold.builders.extractors import ExtractionError, extract_python_code

tdd_logger = logging.getLogger("stronghold.builders.tdd")
onboarding_logger = logging.getLogger("stronghold.builders.onboarding")


async def run_mason_tdd(
    run: Any,
    pipeline: Any,
    feedback: str = "",
) -> Any:
    """One-at-a-time TDD: for each criterion, write one test, make it pass, lock it.

    Green tests stay green. Append only. Never rewrite a passing test.
    """
    from stronghold.builders.nested_loop import MasonTestTracker
    from stronghold.builders.pipeline import RuntimePipeline, StageResult

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
    body_files = pipeline._extract_files_from_issue_body(issue_content)
    for bf in body_files:
        if bf and bf not in affected_files:
            affected_files.append(bf)

    # Resolve affected source file
    if not affected_files:
        file_listing = await pipeline._list_files("src/stronghold/api/routes", ws)
        dashboard_listing = getattr(run, "_dashboard_listing", "") or await pipeline._list_files("src/stronghold/dashboard", ws)
        raw_prompt = (
            f"Which source file should be modified to implement this issue?\n\n"
            f"Issue: {issue_content[:500]}\n\n"
            f"Available route files:\n{file_listing}\n\n"
            f"Dashboard files:\n{dashboard_listing}\n\n"
            f"Output ONLY the file path, e.g.: src/stronghold/dashboard/index.html\n"
        )
        prompt = pipeline._prepend_onboarding(raw_prompt, run)
        path_response = await pipeline._llm_call(prompt, pipeline._mason_model)
        path = path_response.strip().strip("`").strip()
        affected_files = [path] if path.startswith("src/") else ["src/stronghold/api/routes/status.py"]

    # Read source context
    source_context = ""
    for fpath in affected_files[:3]:
        content = await pipeline._read_file(fpath, ws)
        if content:
            source_context += f"\n# --- {fpath} ---\n{content}\n"

    # Detect rendering model: static HTML vs JS-rendered DOM
    rendering_hint = ""
    for fpath in affected_files[:1]:
        js_signals = await pipeline._td.execute(
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
    issue_type = pipeline._detect_issue_type(run)
    if issue_type.name == "ui_dashboard":
        # Find existing dashboard tests to learn the pattern
        existing_tests = await pipeline._td.execute(
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
            existing_tests = await pipeline._td.execute(
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
    existing_test_code = await pipeline._read_file(test_file, ws)
    has_existing_tests = bool(existing_test_code and "def test_" in existing_test_code)
    if has_existing_tests:
        # Seed tracker with current passing count so hwm starts right
        existing_output = await pipeline._run_pytest(ws, test_file)
        existing_passing = pipeline._count_passing(existing_output)
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
            template = await pipeline._get_prompt("builders.mason.write_first_test")
            raw_prompt = pipeline._render(
                template,
                criterion=criterion,
                source_context=source_context,
                feedback_block=feedback if feedback else "",
            )
        else:
            # Append to existing file (whether from this loop or previous)
            existing_code = await pipeline._read_file(test_file, ws)
            template = await pipeline._get_prompt("builders.mason.append_test")
            raw_prompt = pipeline._render(
                template,
                criterion=criterion,
                existing_code=existing_code,
                feedback_block="",
            )

        prompt = pipeline._prepend_onboarding(raw_prompt, run)

        try:
            test_code = await pipeline._llm_extract(
                prompt, pipeline._mason_model, extract_python_code, f"test for criterion {i + 1}",
            )
            await pipeline._write_file(test_file, test_code, ws)
        except ExtractionError as e:
            logger.error("Failed to generate test for criterion %d: %s", i + 1, e)
            await pipeline._post_to_issue(
                owner, repo, run.issue_number,
                f"Criterion {i + 1}: failed to generate test — {e}",
                run=run,
            )
            continue

        # Verify test compiles (max 2 fix attempts)
        for fix_attempt in range(2):
            output = await pipeline._run_pytest(ws, test_file)
            if "SyntaxError" not in output and "ImportError" not in output:
                break
            current_code = await pipeline._read_file(test_file, ws)
            fix_prompt = (
                f"This test file has errors:\n\n```python\n{current_code}\n```\n\n"
                f"Error:\n```\n{output[:2000]}\n```\n\n"
                f"Fix the code. Output ONLY the corrected complete file.\n"
            )
            try:
                fixed = await pipeline._llm_extract(
                    fix_prompt, pipeline._mason_model, extract_python_code, "fix test",
                )
                await pipeline._write_file(test_file, fixed, ws)
            except ExtractionError:
                break

        # ── Impl phase: make THIS test pass ─────────────────────
        for impl_attempt in range(3):
            output = await pipeline._run_pytest(ws, test_file)
            passing = pipeline._count_passing(output)
            failing = pipeline._count_failing(output)

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
            test_code_current = await pipeline._read_file(test_file, ws)
            for fpath in affected_files:
                source = await pipeline._read_file(fpath, ws)
                template = await pipeline._get_prompt("builders.mason.implement")
                raw_prompt = pipeline._render(
                    template,
                    test_code=test_code_current,
                    pytest_output=output[:3000],
                    file_path=fpath,
                    source_code=source,
                    issue_content=issue_content,
                    feedback_block="",
                )
                impl_prompt = pipeline._prepend_onboarding(raw_prompt, run)
                try:
                    new_source = await pipeline._llm_extract(
                        impl_prompt, pipeline._mason_model, extract_python_code, f"impl c{i + 1}a{impl_attempt + 1}",
                    )
                    await pipeline._write_file(fpath, new_source, ws)
                    if fpath not in files_written:
                        files_written.append(fpath)
                except ExtractionError as e:
                    logger.error("Impl failed for %s: %s", fpath, e)

            # Fix test bugs (AttributeError/TypeError) if any
            test_output = await pipeline._run_pytest(ws, test_file)
            if "AttributeError" in test_output or "TypeError" in test_output:
                tc = await pipeline._read_file(test_file, ws)
                fix_prompt = (
                    f"Fix the runtime errors in this test:\n\n```python\n{tc}\n```\n\n"
                    f"Error:\n```\n{test_output[:2000]}\n```\n\n"
                    f"Output ONLY the corrected complete file. Do NOT remove any test functions.\n"
                )
                try:
                    fixed = await pipeline._llm_extract(fix_prompt, pipeline._mason_model, extract_python_code, "fix test bugs")
                    await pipeline._write_file(test_file, fixed, ws)
                except ExtractionError:
                    pass

        # Check if this criterion's tests pass
        check_output = await pipeline._run_pytest(ws, test_file)
        check_passing = pipeline._count_passing(check_output)
        check_failing = pipeline._count_failing(check_output)

        # Auto-format + verify each source file Mason just wrote BEFORE
        # committing. Format must be in the per-criterion commit so the
        # branch we push has properly formatted code, and we now also
        # verify the file is non-empty and parses cleanly to catch the
        # "stub commit" failure mode where extraction succeeds but the
        # file ends up empty/broken.
        stub_files: list[str] = []
        for fpath in (affected_files + [test_file]):
            await pipeline._td.execute(
                "shell",
                {
                    "command": f"ruff check --fix --unsafe-fixes {fpath} 2>/dev/null || true",
                    "workspace": ws,
                },
            )
            await pipeline._td.execute(
                "shell",
                {
                    "command": f"ruff format {fpath} 2>/dev/null || true",
                    "workspace": ws,
                },
            )
            # Sanity check: file exists and isn't a stub
            content = await pipeline._read_file(fpath, ws)
            if not content or len(content.strip()) < 20:
                stub_files.append(fpath)
                continue
            # Syntax check via py_compile (cheap, no LLM cost)
            if fpath.endswith(".py"):
                syntax_check = await pipeline._td.execute(
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
            await pipeline._post_to_issue(
                owner, repo, run.issue_number,
                f"⚠️ Criterion {i + 1}: skipped commit — stub or broken files: "
                f"{', '.join(stub_files)}",
                run=run,
            )
            continue

        # Commit this criterion
        await pipeline._git_command("add -A", ws)
        await pipeline._git_command(
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
        final_output = await pipeline._run_pytest(ws, test_file)
        p = pipeline._count_passing(final_output)
        f = pipeline._count_failing(final_output)
        await pipeline._post_to_issue(
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
    RuntimePipeline.record_model_result(pipeline._mason_model, len(locked_criteria))
    tdd_logger.info(
        "[MODEL STATS] %s: %d criteria locked. all stats: %s",
        pipeline._mason_model, len(locked_criteria),
        RuntimePipeline.get_model_stats(), extra={"run_id": run.run_id},
    )

    # Final summary
    final_output = await pipeline._run_pytest(ws, test_file)
    final_passing = pipeline._count_passing(final_output)
    final_failing = pipeline._count_failing(final_output)

    # Self-improve: if we failed, record WHY in ONBOARDING.md for next run
    if final_passing == 0 and final_failing > 0:
        error_snippet = final_output[:500]
        learning = ""
        if "ImportError" in error_snippet or "ModuleNotFoundError" in error_snippet:
            learning = f"\n\n## Learned from issue #{run.issue_number}\n\nImport error encountered: {error_snippet[:200]}\nDo NOT import from these paths.\n"
        elif "AttributeError" in error_snippet:
            learning = f"\n\n## Learned from issue #{run.issue_number}\n\nAttributeError: {error_snippet[:200]}\nCheck the actual API of the class before using methods.\n"
        if learning:
            current_onboarding = await pipeline._read_file("ONBOARDING.md", ws)
            if current_onboarding:
                await pipeline._write_file("ONBOARDING.md", current_onboarding + learning, ws)
                onboarding_logger.info(
                    "[ONBOARDING] updated with learning from issue #%d",
                    run.issue_number, extra={"run_id": run.run_id},
                )

    summary = (
        f"## TDD Complete\n\n"
        f"**Model:** `{pipeline._mason_model}`\n"
        f"**Criteria completed:** {criteria_completed}/{len(criteria)}\n"
        f"**Files modified:** {', '.join(f'`{f}`' for f in files_written)}\n"
        f"**Tests:** {final_passing} passed, {final_failing} failed "
        f"(hwm: {tracker.high_water_mark})\n\n"
        f"**Pytest:**\n```\n{final_output[:2000]}\n```\n"
    )
    await pipeline._post_to_issue(owner, repo, run.issue_number, summary, run=run)

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
