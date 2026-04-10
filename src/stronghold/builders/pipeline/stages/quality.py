"""Quality gates stage — ruff, mypy, bandit, pytest with LLM-assisted fixes."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("stronghold.builders.pipeline")


async def run_quality_gates(
    run: Any,
    pipeline: Any,
    feedback: str = "",
) -> Any:
    """Run quality gates: mechanical fixes → type inference → checks.

    Note: StageResult imported lazily inside function body to avoid circular.

    Pipeline:
    1. Mechanical (zero LLM cost): ruff fix, ruff format, autotyping
    2. Type inference (zero LLM cost): pyrefly infer suggestions
    3. Type checking: mypy --strict
    4. If mypy fails: LLM gets error + pyrefly suggestion + source
    5. Security: bandit
    6. Tests: pytest
    """
    from stronghold.builders.pipeline import StageResult

    owner, repo = run.repo.split("/")
    ws = getattr(run, "_workspace_path", "")
    test_file = f"tests/api/test_issue_{run.issue_number}.py"

    # Scope to changed files (compare against main, not HEAD —
    # Mason already committed during the TDD loop, so HEAD has no
    # unstaged changes. We need the cumulative diff vs base branch.)
    diff_output = await pipeline._git_command(
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
        diff_output = await pipeline._git_command(
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
    await pipeline._td.execute(
        "shell",
        {"command": f"ruff check --fix {changed_src_str}", "workspace": ws},
    )
    await pipeline._td.execute(
        "shell",
        {"command": f"ruff format {changed_src_str}", "workspace": ws},
    )
    # autotyping: add trivial annotations (-> None, -> bool)
    for fpath in changed_src:
        await pipeline._td.execute(
            "shell",
            {"command": f"autotyping {fpath}", "workspace": ws},
        )

    # ── Phase 2: Type inference suggestions (zero cost) ────
    pyrefly_suggestions: dict[str, str] = {}
    for fpath in changed_src:
        suggestion = await pipeline._td.execute(
            "shell",
            {"command": f"pyrefly infer --diff {fpath}", "workspace": ws},
        )
        if suggestion and not suggestion.startswith("Error:"):
            pyrefly_suggestions[fpath] = suggestion

    # ── Phase 3: Check gates ───────────────────────────────
    results["ruff_check"] = await pipeline._td.execute(
        "shell",
        {"command": f"ruff check {changed_src_str}", "workspace": ws},
    )
    results["ruff_format"] = await pipeline._td.execute(
        "shell",
        {"command": f"ruff format --check {changed_src_str}", "workspace": ws},
    )
    results["mypy"] = await pipeline._td.execute(
        "shell",
        {"command": f"mypy {changed_src_str} --strict", "workspace": ws},
    )
    results["bandit"] = await pipeline._td.execute(
        "shell",
        {"command": f"bandit {changed_src_str} -ll", "workspace": ws},
    )
    results["pytest"] = await pipeline._run_pytest(ws, test_file)

    for name, output in results.items():
        logger.info("Quality gate %s: %s", name, output[:100])

    # ── Phase 4: LLM fix for mypy failures ────────────────
    mypy_output = results.get("mypy", "")
    if mypy_output and '"passed": false' in mypy_output:
        for fpath in changed_src[:3]:
            source = await pipeline._read_file(fpath, ws)
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
                fixed = await pipeline._llm_extract(
                    fix_prompt, pipeline._mason_model,
                    extract_python_code, f"fix mypy {fpath}",
                )
                await pipeline._write_file(fpath, fixed, ws)
            except ExtractionError:
                pass

        # Re-run mypy after fix
        results["mypy"] = await pipeline._td.execute(
            "shell",
            {"command": f"mypy {changed_src_str} --strict", "workspace": ws},
        )

    # Commit all fixes
    await pipeline._git_command("add -A", ws)
    await pipeline._git_command(
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
    await pipeline._post_to_issue(owner, repo, run.issue_number, summary, run=run)

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
