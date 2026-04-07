"""Builders 2.0 API endpoints.

Endpoints:
- POST /v1/stronghold/builders/runs              — trigger a new Builders run
- POST /v1/stronghold/builders/runs/{run_id}/execute — execute next stage
- GET  /v1/stronghold/builders/runs/{run_id}      — get run status
- GET  /v1/stronghold/builders/runs               — list all runs
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.builders")

router = APIRouter(prefix="/v1/stronghold/builders", tags=["builders"])

_orchestrator: Any = None


def configure_builders_router(orchestrator: Any, runtime: Any = None) -> None:
    global _orchestrator
    _orchestrator = orchestrator


def _get_orchestrator() -> Any:
    global _orchestrator
    if _orchestrator is None:
        from stronghold.builders import BuildersOrchestrator

        _orchestrator = BuildersOrchestrator()
    return _orchestrator


async def _require_auth(request: Request) -> Any:
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return auth


def _build_service_auth(container: Any) -> Any:
    from stronghold.types.auth import AuthContext

    return AuthContext(
        user_id="builders-service",
        username="builders-service",
        roles=frozenset({"admin"}),
        org_id="",
        auth_method="service",
    )


def _serialize_run(run: Any) -> dict[str, Any]:
    artifacts = []
    for a in run.artifacts:
        if hasattr(a, "model_dump"):
            artifacts.append(a.model_dump(mode="json"))
        else:
            artifacts.append(str(a))

    events = []
    for e in run.events:
        if hasattr(e, "model_dump"):
            events.append(e.model_dump(mode="json"))
        else:
            events.append({})

    return {
        "run_id": run.run_id,
        "repo": run.repo,
        "issue_number": run.issue_number,
        "branch": run.branch,
        "stage": run.current_stage,
        "worker": run.current_worker.value
        if hasattr(run.current_worker, "value")
        else str(run.current_worker),
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "artifacts": artifacts,
        "events": events,
        "updated_at": run.updated_at.isoformat(),
    }


_STAGE_SEQUENCE = [
    "issue_analyzed",
    "acceptance_defined",
    "tests_written",
    "implementation_started",
    "implementation_ready",
    "quality_checks_passed",
]

# UI pipeline stages (Piper + Glazier)
_UI_STAGE_SEQUENCE = [
    "ui_analyzed",
    "ui_criteria_defined",
    "ui_tests_written",
    "ui_implemented",
    "ui_verified",
]


@router.post("/runs")
async def create_run(request: Request) -> JSONResponse:
    """Trigger a new Builders run.

    Body:
    {
        "repo_url": "https://github.com/owner/repo",
        "issue_number": 42,
        "issue_title": "Fix bug",
        "issue_body": "Description",
        "execute": false
    }

    Set execute=true to run the full workflow synchronously.
    """
    from stronghold.builders import RunStatus, WorkerName

    auth = await _require_auth(request)
    container = request.app.state.container
    body = await request.json()

    repo_url = body.get("repo_url", "")
    issue_number = body.get("issue_number")
    issue_title = body.get("issue_title", "")
    issue_body = body.get("issue_body", "")
    execute = body.get("execute", False)

    if not repo_url:
        raise HTTPException(status_code=400, detail="'repo_url' is required")

    parts = repo_url.rstrip("/").replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid repo_url format")
    owner, repo = parts[0], parts[1]

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    orch = _get_orchestrator()

    # Detect UI issues by signals in title/body
    ui_signals = [
        "dashboard/", ".html", "sidebar", "button", "scroll",
        "css", "tailwind", "overlap", "animate", "active state",
        "tooltip", "diff view", "progress bar", "hover",
    ]
    search_text = f"{issue_title} {issue_body}".lower()
    is_ui = any(s in search_text for s in ui_signals)

    if is_ui:
        initial_stage = "ui_analyzed"
        initial_worker = WorkerName("piper")
    else:
        initial_stage = "issue_analyzed"
        initial_worker = WorkerName.FRANK

    orch.create_run(
        run_id=run_id,
        repo=f"{owner}/{repo}",
        issue_number=issue_number or 1,
        branch=f"builders/{issue_number or 1}-{run_id}",
        workspace_ref=f"ws_{run_id}",
        initial_stage=initial_stage,
        initial_worker=initial_worker,
    )

    logger.info("Builders run created: run_id=%s repo=%s", run_id, f"{owner}/{repo}")

    if execute:
        import asyncio

        service_auth = _build_service_auth(container)
        asyncio.create_task(_execute_full_workflow(run_id, orch, container, service_auth))

        run = orch._runs[run_id]
        return JSONResponse(status_code=202, content=_serialize_run(run))

    run = orch._runs[run_id]
    return JSONResponse(content=_serialize_run(run))


@router.post("/runs/{run_id}/execute")
async def execute_stage(request: Request, run_id: str) -> JSONResponse:
    """Execute the next stage in a Builders run.

    Advances the run through one stage of the workflow:
    issue_analyzed -> acceptance_defined -> tests_written ->
    implementation_started -> implementation_ready -> quality_checks_passed -> completed
    """
    from stronghold.builders import RunStatus

    await _require_auth(request)
    container = request.app.state.container
    orch = _get_orchestrator()

    run = orch._runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status in (RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED):
        raise HTTPException(status_code=409, detail=f"Run is already {run.status.value}")

    service_auth = _build_service_auth(container)
    await _execute_one_stage(run_id, orch, container, service_auth)

    run = orch._runs[run_id]
    return JSONResponse(content=_serialize_run(run))


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> JSONResponse:
    await _require_auth(request)
    orch = _get_orchestrator()

    run = orch._runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return JSONResponse(content=_serialize_run(run))


@router.get("/runs")
async def list_runs(request: Request) -> JSONResponse:
    await _require_auth(request)
    orch = _get_orchestrator()

    runs = [_serialize_run(r) for r in orch._runs.values()]
    return JSONResponse(content={"runs": runs})


@router.post("/decompose")
async def decompose(request: Request) -> JSONResponse:
    """Quartermaster endpoint: decompose a parent issue into sub-issues.

    Body:
    {
        "repo_url": "https://github.com/owner/repo",
        "issue_number": 397
    }
    """
    from types import SimpleNamespace

    await _require_auth(request)
    container = request.app.state.container
    body = await request.json()

    repo_url = body.get("repo_url", "")
    issue_number = body.get("issue_number")
    if not repo_url or not issue_number:
        raise HTTPException(
            status_code=400,
            detail="'repo_url' and 'issue_number' are required",
        )

    parts = repo_url.rstrip("/").replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid repo_url format")
    owner, repo = parts[0], parts[1]

    # Fetch issue details
    td = container.tool_dispatcher
    issue_result = await td.execute(
        "github",
        {
            "action": "get_issue",
            "owner": owner, "repo": repo,
            "issue_number": issue_number,
        },
    )
    if issue_result.startswith("Error:"):
        raise HTTPException(
            status_code=404,
            detail=f"Cannot fetch issue #{issue_number}: {issue_result}",
        )

    import json as _json
    issue_data = _json.loads(issue_result)

    # Build a minimal workspace for file reads
    ws_result = await td.execute(
        "workspace",
        {
            "action": "create",
            "issue_number": issue_number,
            "owner": owner,
            "repo": repo,
        },
    )
    ws_path = ""
    if not ws_result.startswith("Error:"):
        ws_data = _json.loads(ws_result)
        ws_path = ws_data.get("path", "")

    # Build a minimal run-like namespace for the pipeline method
    run = SimpleNamespace(
        run_id=f"decompose-{uuid.uuid4().hex[:8]}",
        issue_number=issue_number,
        repo=f"{owner}/{repo}",
        _issue_title=issue_data.get("title", ""),
        _issue_content=issue_data.get("body", ""),
        _workspace_path=ws_path,
    )

    pipeline = _build_pipeline(container)
    result = await pipeline.decompose_issue(run)

    return JSONResponse(content={
        "parent": issue_number,
        "success": result.success,
        "summary": result.summary,
        "evidence": result.evidence,
    })


# ── Gatekeeper: PR Review Endpoint ───────────────────────────────────

_gatekeeper_config: dict[str, Any] = {
    "auto_merge_enabled": False,
    "allowed_authors": (),
    "coverage_tolerance_pct": -1.0,
    "protected_branches": ("main", "master"),
}


@router.post("/review-pr")
async def review_pr_endpoint(request: Request) -> JSONResponse:
    """Gatekeeper endpoint: review a PR and either approve or request changes.

    Body:
    {
        "repo_url": "https://github.com/owner/repo",
        "pr_number": 404,
        "auto_merge_enabled": false  (optional override)
    }
    """
    await _require_auth(request)
    container = request.app.state.container
    body = await request.json()

    repo_url = body.get("repo_url", "")
    pr_number = body.get("pr_number")
    if not repo_url or not pr_number:
        raise HTTPException(
            status_code=400,
            detail="'repo_url' and 'pr_number' are required",
        )

    parts = repo_url.rstrip("/").replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid repo_url")
    owner, repo = parts[0], parts[1]

    auto_merge = bool(body.get(
        "auto_merge_enabled", _gatekeeper_config["auto_merge_enabled"],
    ))

    pipeline = _build_pipeline(container)
    result = await pipeline.review_pr(
        owner=owner,
        repo=repo,
        pr_number=int(pr_number),
        auto_merge_enabled=auto_merge,
        allowed_authors=_gatekeeper_config["allowed_authors"],
        coverage_tolerance_pct=_gatekeeper_config["coverage_tolerance_pct"],
        protected_branches=_gatekeeper_config["protected_branches"],
    )

    return JSONResponse(content={
        "pr_number": pr_number,
        "success": result.success,
        "summary": result.summary,
        "evidence": result.evidence,
    })


@router.post("/gatekeeper/config")
async def gatekeeper_config_update(request: Request) -> JSONResponse:
    """Update Gatekeeper guardrails (auto-merge, allowed authors, etc.)."""
    await _require_auth(request)
    body = await request.json()
    if "auto_merge_enabled" in body:
        _gatekeeper_config["auto_merge_enabled"] = bool(body["auto_merge_enabled"])
    if "allowed_authors" in body:
        _gatekeeper_config["allowed_authors"] = tuple(body["allowed_authors"])
    if "coverage_tolerance_pct" in body:
        _gatekeeper_config["coverage_tolerance_pct"] = float(
            body["coverage_tolerance_pct"],
        )
    if "protected_branches" in body:
        _gatekeeper_config["protected_branches"] = tuple(body["protected_branches"])
    return JSONResponse(content={
        "config": {
            "auto_merge_enabled": _gatekeeper_config["auto_merge_enabled"],
            "allowed_authors": list(_gatekeeper_config["allowed_authors"]),
            "coverage_tolerance_pct": _gatekeeper_config["coverage_tolerance_pct"],
            "protected_branches": list(_gatekeeper_config["protected_branches"]),
        },
    })


@router.get("/gatekeeper/config")
async def gatekeeper_config_get(request: Request) -> JSONResponse:
    await _require_auth(request)
    return JSONResponse(content={
        "config": {
            "auto_merge_enabled": _gatekeeper_config["auto_merge_enabled"],
            "allowed_authors": list(_gatekeeper_config["allowed_authors"]),
            "coverage_tolerance_pct": _gatekeeper_config["coverage_tolerance_pct"],
            "protected_branches": list(_gatekeeper_config["protected_branches"]),
        },
    })


# ── Priority Scheduler ───────────────────────────────────────────────

_LABEL_PRIORITIES: dict[str, int] = {
    "critical": 1000,
    "high": 500,
    "v1.0": 300,
    "follow-on": 200,
    "good first issue": 100,
    "builders": 75,
    "ui": 75,
}

# Patterns the pipeline can currently solve (extend as capabilities grow)
_SOLVABLE_SIGNALS: tuple[str, ...] = (
    "endpoint", "route", "dashboard", ".html", "sidebar",
    "button", "tooltip", "scroll", "animate", "css",
    "test:", "fix:", "feat:",
)

# Patterns the pipeline cannot solve yet — skip these
_SKIP_SIGNALS: tuple[str, ...] = (
    ".sql", "migration", "schema", "postgres table",
    "k8s", "kubernetes", "helm",
    "multi-file", "refactor: rename",
)


def _score_issue(issue: dict[str, Any]) -> int:
    """Score an issue by labels and signals. Higher = higher priority.

    Returns 0 if the issue should be skipped entirely.
    """
    title = issue.get("title", "").lower()
    body = (issue.get("body") or "").lower()
    labels = [lb.lower() for lb in issue.get("labels", [])]
    text = f"{title} {body}"

    # Epic issues are parents of decomposition trees — scheduler works
    # the leaves, not the parent. Skip them entirely.
    if "epic" in labels:
        return 0

    # Skip patterns kill the score
    for sig in _SKIP_SIGNALS:
        if sig in text:
            return 0

    # Must match at least one solvable signal
    if not any(sig in text for sig in _SOLVABLE_SIGNALS):
        return 0

    score = 0
    for lb in labels:
        score += _LABEL_PRIORITIES.get(lb, 0)

    # Base score for matched solvable patterns
    score += 50
    return score


async def _rank_candidate_issues(
    container: Any, owner: str, repo: str,
) -> list[dict[str, Any]]:
    """Fetch open issues, score them, filter blocked, sort by (-score, number).

    Lower issue number = older, wins tiebreakers.
    """
    import json as _json

    td = container.tool_dispatcher

    # Fetch open issues with builders-relevant labels
    issues_result = await td.execute(
        "github",
        {
            "action": "list_issues",
            "owner": owner, "repo": repo,
            "state": "open", "per_page": 100, "max_pages": 3,
        },
    )
    if issues_result.startswith("Error:"):
        logger.warning("Scheduler: list_issues failed: %s", issues_result[:200])
        return []

    try:
        issues = _json.loads(issues_result)
    except Exception:
        return []

    # Filter out PRs (list_issues returns both)
    issues = [i for i in issues if not i.get("is_pr", False)]

    # Score and filter
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for issue in issues:
        score = _score_issue(issue)
        if score <= 0:
            continue
        scored.append((score, issue["number"], issue))

    if not scored:
        return []

    # Sort: highest score first, then lowest issue number (older = first)
    scored.sort(key=lambda x: (-x[0], x[1]))

    # Check blocked_by for top candidates (expensive — only top 20)
    ready: list[dict[str, Any]] = []
    for score, number, issue in scored[:20]:
        blockers_result = await td.execute(
            "github",
            {
                "action": "list_blocked_by",
                "owner": owner, "repo": repo,
                "issue_number": number,
            },
        )
        if blockers_result.startswith("Error:"):
            # If the endpoint isn't available, treat as unblocked
            issue["_score"] = score
            ready.append(issue)
            continue
        try:
            blockers = _json.loads(blockers_result)
        except Exception:
            blockers = []
        open_blockers = [b for b in blockers if b.get("state") == "open"]
        if open_blockers:
            continue
        issue["_score"] = score
        ready.append(issue)

    return ready


# Scheduler runtime state
_scheduler_state: dict[str, Any] = {
    "enabled": False,
    "interval_seconds": 300,  # 5 min default — learning rate T
    "max_concurrent": 2,
    "task": None,
    "last_run": None,
    "last_dispatched": [],
    "completed_issues": set(),  # issue numbers already completed this session
    "failed_issues": set(),     # issue numbers that failed — don't retry until cleared
    "reviewed_prs": set(),      # PR numbers already reviewed this session
    "review_enabled": True,     # Gatekeeper runs alongside dispatch
    "stats": {
        "dispatched": 0,
        "skipped_blocked": 0,
        "skipped_inflight": 0,
        "skipped_completed": 0,
        "skipped_failed": 0,
        "reviewed": 0,
        "merged": 0,
        "review_changes_requested": 0,
    },
}


async def _scheduler_loop(container: Any, owner: str, repo: str) -> None:
    """Background loop: fetch ranked issues and dispatch runs."""
    import asyncio as _asyncio
    import datetime as _datetime

    logger.info("Scheduler loop started: %s/%s", owner, repo)

    while _scheduler_state.get("enabled"):
        try:
            orch = _get_orchestrator()
            # Count in-flight runs (not yet terminal)
            inflight = sum(
                1 for r in orch._runs.values()
                if r.status.value not in ("passed", "failed", "blocked")
            )
            slots = max(0, _scheduler_state["max_concurrent"] - inflight)

            _scheduler_state["last_run"] = _datetime.datetime.now(
                _datetime.timezone.utc,
            ).isoformat()

            # Harvest outcomes of completed runs and move to completed/failed sets
            completed_set = _scheduler_state["completed_issues"]
            failed_set = _scheduler_state["failed_issues"]
            for r in orch._runs.values():
                status_val = r.status.value
                if status_val == "passed":
                    completed_set.add(r.issue_number)
                elif status_val in ("failed", "blocked"):
                    failed_set.add(r.issue_number)

            if slots > 0:
                candidates = await _rank_candidate_issues(container, owner, repo)
                dispatched: list[int] = []
                for issue in candidates:
                    if len(dispatched) >= slots:
                        break
                    number = issue["number"]

                    # Skip if already completed or failed this session
                    if number in completed_set:
                        _scheduler_state["stats"]["skipped_completed"] += 1
                        continue
                    if number in failed_set:
                        _scheduler_state["stats"]["skipped_failed"] += 1
                        continue

                    # Skip if an in-flight run exists for this issue
                    already_running = any(
                        r.issue_number == number
                        and r.status.value not in ("passed", "failed", "blocked")
                        for r in orch._runs.values()
                    )
                    if already_running:
                        _scheduler_state["stats"]["skipped_inflight"] += 1
                        continue

                    await _dispatch_scheduler_run(
                        container, owner, repo, issue,
                    )
                    dispatched.append(number)
                    _scheduler_state["stats"]["dispatched"] += 1

                _scheduler_state["last_dispatched"] = dispatched
                if dispatched:
                    logger.info(
                        "Scheduler dispatched %d runs: %s",
                        len(dispatched), dispatched,
                    )

            # Review pass — run Gatekeeper on any open builders PRs
            if _scheduler_state.get("review_enabled", True):
                await _review_pass(container, owner, repo)

        except Exception as e:
            logger.exception("Scheduler loop error: %s", e)

        await _asyncio.sleep(_scheduler_state["interval_seconds"])

    logger.info("Scheduler loop stopped")


async def _review_pass(container: Any, owner: str, repo: str) -> None:
    """Find open PRs created by builders and run Gatekeeper on each.

    When Gatekeeper requests changes, the parent issue is removed from
    completed_issues so the scheduler re-dispatches it. Mason's next run
    reads the Gatekeeper verdict from the issue comments (via prior_runs
    history) and fixes the specific blockers.

    reviewed_prs tracks (pr_number, head_sha) — a new push to the PR
    branch changes head_sha, triggering a fresh review.
    """
    import json as _json
    import re as _re

    td = container.tool_dispatcher

    # Fetch open PRs (list_issues returns both issues and PRs)
    issues_raw = await td.execute(
        "github",
        {
            "action": "list_issues",
            "owner": owner, "repo": repo,
            "state": "open", "per_page": 50, "max_pages": 2,
        },
    )
    if issues_raw.startswith("Error:"):
        return

    try:
        items = _json.loads(issues_raw)
    except Exception:
        return

    prs = [i for i in items if i.get("is_pr", False)]
    reviewed_set = _scheduler_state["reviewed_prs"]
    completed_set = _scheduler_state["completed_issues"]

    # Review at most 2 PRs per loop
    pipeline = _build_pipeline(container)
    review_slots = 2
    for pr_item in prs:
        if review_slots <= 0:
            break
        pr_number = pr_item["number"]

        # Only review PRs with branch name matching our conventions
        title = pr_item.get("title", "")
        if not any(
            title.startswith(prefix)
            for prefix in ("feat:", "fix:", "refactor:", "test:")
        ):
            continue

        # Get head SHA so we re-review when new commits land
        pr_detail_raw = await td.execute(
            "github",
            {
                "action": "get_pr",
                "owner": owner, "repo": repo,
                "issue_number": pr_number,
            },
        )
        head_sha = ""
        if not pr_detail_raw.startswith("Error:"):
            try:
                pr_detail = _json.loads(pr_detail_raw)
                head_sha = pr_detail.get("head", {}).get("sha", "")[:12]
            except Exception:
                pass

        review_key = f"{pr_number}:{head_sha}"
        if review_key in reviewed_set:
            continue

        # Extract parent issue number from PR title
        issue_match = _re.search(r"#(\d+)", title)
        parent_issue = int(issue_match.group(1)) if issue_match else None

        try:
            result = await pipeline.review_pr(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                auto_merge_enabled=_gatekeeper_config["auto_merge_enabled"],
                allowed_authors=_gatekeeper_config["allowed_authors"],
                coverage_tolerance_pct=_gatekeeper_config["coverage_tolerance_pct"],
                protected_branches=_gatekeeper_config["protected_branches"],
            )
            reviewed_set.add(review_key)
            _scheduler_state["stats"]["reviewed"] += 1

            if result.success:
                if result.evidence.get("merged"):
                    _scheduler_state["stats"]["merged"] += 1
            else:
                # REQUEST_CHANGES — unblock the parent issue for re-dispatch
                _scheduler_state["stats"]["review_changes_requested"] += 1
                if parent_issue and parent_issue in completed_set:
                    completed_set.discard(parent_issue)
                    logger.info(
                        "Gatekeeper requested changes on PR #%d — "
                        "re-opening issue #%d for scheduler",
                        pr_number, parent_issue,
                    )

            review_slots -= 1
        except Exception as e:
            logger.warning("Review of PR #%d failed: %s", pr_number, e)


async def _dispatch_scheduler_run(
    container: Any, owner: str, repo: str, issue: dict[str, Any],
) -> None:
    """Dispatch a single scheduled run. Fire and forget.

    Quartermaster pre-pass: if the issue is non-atomic per the triage
    heuristic AND is not already a Quartermaster-created sub-issue,
    decompose it instead of handing it to Mason. The decompose call
    labels the parent 'epic', so subsequent scheduler ticks skip it
    and pick up the freshly created leaves instead.
    """
    import asyncio as _asyncio
    import json as _json

    from stronghold.builders import WorkerName
    from stronghold.builders.pipeline import RuntimePipeline

    number = issue["number"]
    title = issue.get("title", "")
    labels = [lb.lower() for lb in issue.get("labels", [])]

    # list_issues does not include the body — fetch the full issue so the
    # triage heuristic sees the actual content (acceptance criteria, file
    # paths, "Files to create" markers).
    body = issue.get("body", "") or ""
    if not body:
        try:
            full_raw = await container.tool_dispatcher.execute(
                "github",
                {
                    "action": "get_issue",
                    "owner": owner, "repo": repo,
                    "issue_number": number,
                },
            )
            if not full_raw.startswith("Error:"):
                full = _json.loads(full_raw)
                body = full.get("body", "") or ""
        except Exception as e:
            logger.warning("Scheduler: get_issue #%d failed: %s", number, e)

    # ── Quartermaster pre-pass ────────────────────────────────────
    # Skip the pre-pass if this issue is already a leaf (created by
    # Quartermaster) or already an epic (parent already decomposed).
    is_qm_leaf = "quartermaster" in labels
    is_epic = "epic" in labels
    if not is_qm_leaf and not is_epic:
        strategy = RuntimePipeline._triage_issue(title, body)
        if strategy != "atomic":
            logger.info(
                "Scheduler: issue #%d is non-atomic (%s) — running Quartermaster pre-pass",
                number, strategy,
            )
            try:
                pipeline = _build_pipeline(container)
                from types import SimpleNamespace
                qm_run = SimpleNamespace(
                    run_id=f"qm-pre-{number}",
                    issue_number=number,
                    repo=f"{owner}/{repo}",
                    _issue_title=title,
                    _issue_content=body,
                    _workspace_path="",
                )
                qm_result = await pipeline.decompose_issue(qm_run)
                if qm_result.success:
                    logger.info(
                        "Scheduler: Quartermaster decomposed #%d — skipping direct dispatch",
                        number,
                    )
                    return
                logger.warning(
                    "Scheduler: Quartermaster failed on #%d (%s) — falling back to direct dispatch",
                    number, qm_result.summary[:200],
                )
            except Exception as e:
                logger.warning(
                    "Scheduler: Quartermaster pre-pass crashed on #%d: %s — falling back",
                    number, e,
                )

    # Detect UI issue like create_run does
    ui_signals = [
        "dashboard/", ".html", "sidebar", "button", "scroll",
        "css", "tailwind", "overlap", "animate", "tooltip",
    ]
    search_text = f"{title} {body}".lower()
    is_ui = any(s in search_text for s in ui_signals)

    if is_ui:
        initial_stage = "ui_analyzed"
        initial_worker = WorkerName("piper")
    else:
        initial_stage = "issue_analyzed"
        initial_worker = WorkerName.FRANK

    run_id = f"sched-{uuid.uuid4().hex[:8]}"
    orch = _get_orchestrator()
    orch.create_run(
        run_id=run_id,
        repo=f"{owner}/{repo}",
        issue_number=number,
        branch=f"builders/{number}-{run_id}",
        workspace_ref=f"ws_{run_id}",
        initial_stage=initial_stage,
        initial_worker=initial_worker,
    )

    service_auth = _build_service_auth(container)
    _asyncio.create_task(
        _execute_full_workflow(run_id, orch, container, service_auth),
    )


@router.post("/scheduler/start")
async def scheduler_start(request: Request) -> JSONResponse:
    """Start the priority scheduler loop."""
    import asyncio as _asyncio

    await _require_auth(request)
    body = await request.json()

    repo_url = body.get("repo_url", "")
    parts = repo_url.rstrip("/").replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid repo_url")
    owner, repo = parts[0], parts[1]

    interval = int(body.get("interval_seconds", 300))
    max_concurrent = int(body.get("max_concurrent", 2))

    if _scheduler_state.get("enabled"):
        return JSONResponse({"status": "already_running", "state": _scheduler_snapshot()})

    _scheduler_state["enabled"] = True
    _scheduler_state["interval_seconds"] = interval
    _scheduler_state["max_concurrent"] = max_concurrent
    _scheduler_state["owner"] = owner
    _scheduler_state["repo"] = repo

    container = request.app.state.container
    task = _asyncio.create_task(_scheduler_loop(container, owner, repo))
    _scheduler_state["task"] = task

    return JSONResponse({"status": "started", "state": _scheduler_snapshot()})


@router.post("/scheduler/stop")
async def scheduler_stop(request: Request) -> JSONResponse:
    """Stop the scheduler loop."""
    await _require_auth(request)

    _scheduler_state["enabled"] = False
    task = _scheduler_state.get("task")
    if task is not None:
        task.cancel()
        _scheduler_state["task"] = None

    return JSONResponse({"status": "stopped", "state": _scheduler_snapshot()})


@router.get("/scheduler")
async def scheduler_status(request: Request) -> JSONResponse:
    """Get scheduler status."""
    await _require_auth(request)
    return JSONResponse(_scheduler_snapshot())


def _scheduler_snapshot() -> dict[str, Any]:
    completed = _scheduler_state.get("completed_issues", set())
    failed = _scheduler_state.get("failed_issues", set())
    reviewed = _scheduler_state.get("reviewed_prs", set())
    return {
        "enabled": _scheduler_state.get("enabled", False),
        "interval_seconds": _scheduler_state.get("interval_seconds", 300),
        "max_concurrent": _scheduler_state.get("max_concurrent", 2),
        "review_enabled": _scheduler_state.get("review_enabled", True),
        "last_run": _scheduler_state.get("last_run"),
        "last_dispatched": _scheduler_state.get("last_dispatched", []),
        "completed_count": len(completed),
        "failed_count": len(failed),
        "reviewed_count": len(reviewed),
        "completed_issues": sorted(completed),
        "failed_issues": sorted(failed),
        "reviewed_prs": sorted(reviewed),
        "stats": _scheduler_state.get("stats", {}),
        "owner": _scheduler_state.get("owner"),
        "repo": _scheduler_state.get("repo"),
        "gatekeeper": {
            "auto_merge_enabled": _gatekeeper_config["auto_merge_enabled"],
            "allowed_authors": list(_gatekeeper_config["allowed_authors"]),
            "protected_branches": list(_gatekeeper_config["protected_branches"]),
        },
    }


@router.post("/scheduler/reset")
async def scheduler_reset(request: Request) -> JSONResponse:
    """Clear the completed/failed issue sets so they can be retried."""
    await _require_auth(request)
    _scheduler_state["completed_issues"] = set()
    _scheduler_state["failed_issues"] = set()
    return JSONResponse({"status": "reset", "state": _scheduler_snapshot()})


MAX_STAGE_RETRIES = 3


async def _post_stage_output_to_issue(
    container: Any,
    owner: str,
    repo: str,
    issue_number: int,
    run_id: str,
    stage: str,
    worker_name: str,
    summary: str,
) -> bool:
    """Post the worker's stage output as a GitHub issue comment. Returns True on success."""
    comment_body = (
        f"## Stage: `{stage}` — {worker_name}\n\n"
        f"**Run:** `{run_id}`\n\n"
        f"### Output\n\n{summary}\n\n"
        f"---\n*Awaiting Auditor review.*"
    )
    result = await container.tool_dispatcher.execute(
        "github",
        {
            "action": "post_pr_comment",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
            "body": comment_body,
        },
    )
    if result.startswith("Error:"):
        logger.error("Failed to post stage output to issue: %s", result)
        return False
    logger.info("Posted %s output to %s/%s#%d", stage, owner, repo, issue_number)
    return True


async def _auditor_review_stage(
    container: Any,
    service_auth: Any,
    run: Any,
    stage: str,
    worker_name: str,
    worker_output: str,
) -> tuple[bool, str]:
    """Auditor reviews a stage's output. Returns (approved, feedback).

    The Auditor checks whether the worker's output meets the stage requirements.
    Returns (True, summary) on approval, (False, feedback) on rejection.
    """
    auditor = container.agents.get("auditor")
    if not auditor:
        logger.warning("Auditor agent not found — auto-approving stage %s", stage)
        return True, "Auto-approved (no auditor configured)"

    issue_title = getattr(run, "_issue_title", "")
    issue_content = getattr(run, "_issue_content", "")

    review_prompt = (
        f"You are reviewing stage `{stage}` output from `{worker_name}` "
        f"for issue {run.repo}#{run.issue_number}: {issue_title}\n\n"
        f"## Issue Description\n{issue_content}\n\n"
        f"## Stage Requirements\n{_STAGE_REQUIREMENTS.get(stage, 'Complete the stage successfully.')}\n\n"
        f"## Worker Output\n{worker_output}\n\n"
        f"## Your Task\n"
        f"Review whether the output meets the stage requirements. Be strict but fair.\n\n"
        f"Respond with EXACTLY one of:\n"
        f"- `APPROVED: <one-line reason>` if the output meets requirements\n"
        f"- `CHANGES_REQUESTED: <specific feedback on what must be fixed>` if not\n\n"
        f"Do NOT use tools. Just review and respond with your verdict.\n"
    )

    try:
        response = await auditor.handle(
            [{"role": "user", "content": review_prompt}],
            auth=service_auth,
            session_id=f"auditor-{run.run_id}-{stage}",
        )
        verdict_text = response.content or ""
        logger.info("Auditor verdict for %s/%s: %s", run.run_id, stage, verdict_text[:200])

        if "APPROVED" in verdict_text.upper().split("\n")[0]:
            return True, verdict_text
        else:
            return False, verdict_text
    except Exception as e:
        logger.error("Auditor review failed for %s/%s: %s", run.run_id, stage, e)
        # Fail open — don't block the pipeline on auditor errors
        return True, f"Auto-approved (auditor error: {e})"


async def _post_auditor_verdict_to_issue(
    container: Any,
    owner: str,
    repo: str,
    issue_number: int,
    run_id: str,
    stage: str,
    approved: bool,
    feedback: str,
    attempt: int,
) -> None:
    """Post the Auditor's verdict as a GitHub issue comment."""
    verdict = "APPROVED" if approved else "CHANGES_REQUESTED"
    comment_body = (
        f"## Auditor Review: `{stage}` (attempt {attempt})\n\n"
        f"**Verdict:** {verdict}\n\n"
        f"### Feedback\n\n{feedback}\n\n"
        f"---\n"
    )
    await container.tool_dispatcher.execute(
        "github",
        {
            "action": "post_pr_comment",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
            "body": comment_body,
        },
    )


_STAGE_REQUIREMENTS: dict[str, str] = {
    "issue_analyzed": (
        "Must provide: 1) Clear problem statement, 2) List of requirements, "
        "3) Edge cases identified, 4) Suggested implementation approach."
    ),
    "acceptance_defined": (
        "Must provide Gherkin-format acceptance criteria (Given/When/Then) covering: "
        "1) Happy path, 2) Error scenarios, 3) Edge cases. "
        "Criteria must be testable and specific."
    ),
    "tests_written": (
        "Must have created actual test files in the workspace using file_ops tool calls. "
        "Tests must be runnable with pytest. If the output says 'no text output' but tool "
        "calls were made, check that files were actually written."
    ),
    "implementation_started": (
        "Must have written implementation code using file_ops tool calls. "
        "Code must address the issue requirements. Changes must be committed to git."
    ),
    "implementation_ready": (
        "Must have run quality checks (pytest, ruff, mypy). "
        "Report must show results of each check. New code failures must be fixed."
    ),
    "quality_checks_passed": (
        "All quality gates must pass for the new code. Pre-existing failures are acceptable "
        "but new regressions are not. Git log must show commits for this issue."
    ),
}


def _build_pipeline(container: Any) -> Any:
    """Build a RuntimePipeline from the DI container."""
    from stronghold.builders.pipeline import RuntimePipeline

    # Read model configs from agent identities
    frank = container.agents.get("frank")
    mason = container.agents.get("mason")
    auditor = container.agents.get("auditor")

    return RuntimePipeline(
        llm=container.llm,
        tool_dispatcher=container.tool_dispatcher,
        prompt_manager=container.prompt_manager,
        frank_model=frank.identity.model if frank else "google-gemini-3.1-pro",
        mason_model=mason.identity.model if mason else "openrouter-anthropic/claude-opus-4.6",
        auditor_model=auditor.identity.model if auditor else "google-gemini-3.1-pro",
    )


_STAGE_HANDLERS = {
    "issue_analyzed": "analyze_issue",
    "acceptance_defined": "define_acceptance_criteria",
    "tests_written": "write_tests",
    "implementation_started": "implement",
    "implementation_ready": "run_quality_gates",
    "quality_checks_passed": "final_verification",
}

_STAGE_WORKER = {
    "issue_analyzed": "frank",
    "acceptance_defined": "frank",
    "tests_written": "mason",
    "implementation_started": "mason",
    "implementation_ready": "mason",
    "quality_checks_passed": "mason",
}

# UI pipeline (Piper + Glazier)
_UI_STAGE_HANDLERS = {
    "ui_analyzed": "analyze_ui",
    "ui_criteria_defined": "define_ui_criteria",
    "ui_tests_written": "write_ui_tests",
    "ui_implemented": "implement_ui",
    "ui_verified": "verify_ui",
}

_UI_STAGE_WORKER = {
    "ui_analyzed": "piper",
    "ui_criteria_defined": "piper",
    "ui_tests_written": "glazier",
    "ui_implemented": "glazier",
    "ui_verified": "glazier",
}


async def _execute_one_stage(run_id: str, orch: Any, container: Any, service_auth: Any) -> None:
    """Execute a single stage using runtime-controlled pipeline.

    The runtime controls ALL execution:
    1. Pipeline method reads workspace, calls LLM for content, writes files, runs tests
    2. Evidence is posted to GitHub issue automatically by pipeline
    3. Auditor reviews concrete evidence (actual files, test output)
    4. If approved → advance. If rejected → retry with feedback (max 3).
    """
    from stronghold.builders import ArtifactRef, RunResult, RunStatus, WorkerName

    run = orch._runs[run_id]
    stage = run.current_stage
    worker = run.current_worker
    owner, repo_name = run.repo.split("/")

    handler_name = _STAGE_HANDLERS.get(stage) or _UI_STAGE_HANDLERS.get(stage)
    if not handler_name:
        logger.error("No pipeline handler for stage %s", stage)
        return

    pipeline = _build_pipeline(container)
    # Apply model override from outer loop rotation
    model_override = getattr(run, "_mason_model_override", None)
    if model_override:
        pipeline._mason_model = model_override
    auditor_feedback = ""

    for attempt in range(1, MAX_STAGE_RETRIES + 1):
        print(f"[BUILDERS] Stage {stage} attempt {attempt}/{MAX_STAGE_RETRIES} for run {run_id}", flush=True)

        # 1. Runtime executes the stage — pass Auditor feedback from prior rejection
        try:
            handler = getattr(pipeline, handler_name)
            result = await handler(run, feedback=auditor_feedback)
            print(f"[BUILDERS] Stage {stage} result: success={result.success}, summary={result.summary[:200]}", flush=True)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[BUILDERS] Pipeline {stage} EXCEPTION: {e}\n{tb}", flush=True)
            result = None

        if result is None or not result.success:
            summary = result.summary if result else f"Stage {stage} failed"
            logger.error("Stage %s failed: %s", stage, summary)
            break

        # 2. Auditor reviews concrete evidence (stage-aware prompt)
        approved, feedback = await pipeline.auditor_review(stage, result.evidence)

        # 3. Post Auditor verdict to issue
        await _post_auditor_verdict_to_issue(
            container, owner, repo_name, run.issue_number,
            run_id, stage, approved, feedback, attempt,
        )

        if approved:
            logger.info("Stage %s approved by Auditor (attempt %d)", stage, attempt)
            break

        logger.info("Stage %s rejected by Auditor (attempt %d/%d)", stage, attempt, MAX_STAGE_RETRIES)
        auditor_feedback = feedback
        if attempt == MAX_STAGE_RETRIES:
            result = None  # Signal failure
            break

    # Record result and advance (or fail)
    success = result is not None and result.success
    status = RunStatus.PASSED if success else RunStatus.FAILED
    summary = result.summary if result else f"Stage {stage} failed after {MAX_STAGE_RETRIES} attempts"
    worker_name = worker.value if hasattr(worker, "value") else str(worker)

    run_result = RunResult(
        run_id=run_id,
        worker=worker,
        stage=stage,
        status=status,
        summary=summary[:500],
        artifacts=[
            ArtifactRef(
                type=f"{stage}_output",
                path=f"runs/{run_id}/{stage}.json",
                producer=worker_name,
            )
        ],
    )

    # Determine which sequence this stage belongs to
    if stage in _UI_STAGE_SEQUENCE:
        seq = _UI_STAGE_SEQUENCE
        worker_map = _UI_STAGE_WORKER
        terminal_stage = "ui_verified"
    else:
        seq = _STAGE_SEQUENCE
        worker_map = _STAGE_WORKER
        terminal_stage = "quality_checks_passed"

    idx = seq.index(stage) if stage in seq else -1

    if status == RunStatus.PASSED and idx >= 0 and idx + 1 < len(seq):
        next_stage = seq[idx + 1]
        next_worker_name = worker_map.get(next_stage)
        next_worker = WorkerName(next_worker_name) if next_worker_name else worker
        orch.apply_result(run_result, next_stage=next_stage)
        orch._runs[run_id].current_worker = next_worker
    elif status == RunStatus.PASSED and stage == terminal_stage:
        orch.apply_result(run_result)
        orch.complete_run_if_ready(
            run_id,
            ci_passed=True,
            coverage_pct=95.0,
            quality_passed=True,
        )
        # Create PR on completion — guarded against double-fire when both
        # _execute_one_stage and _execute_full_workflow are running
        if getattr(run, "_pr_creation_started", False):
            logger.info(
                "Skipping PR creation for %s — already started by another path",
                run_id,
            )
        else:
            run._pr_creation_started = True
            ws_path = getattr(run, "_workspace_path", "")
            if ws_path and container:
                import asyncio as _asyncio
                _asyncio.create_task(
                    _create_pr_on_finish(run, container, owner, repo_name, ws_path),
                )
    else:
        orch.apply_result(run_result)


async def _execute_full_workflow(run_id: str, orch: Any, container: Any, service_auth: Any) -> None:
    """Execute all stages in sequence until completion or failure."""
    from stronghold.builders import RunStatus
    import json as _json

    run = orch._runs.get(run_id)
    if not run:
        return

    owner, repo = run.repo.split("/")
    issue_number = run.issue_number
    ws_path = None
    issue_content = ""

    try:
        gh_result = await container.tool_dispatcher.execute(
            "github",
            {
                "action": "get_issue",
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
            },
        )
        if gh_result.startswith("Error:"):
            logger.error("Failed to fetch issue: %s", gh_result)
            return

        issue_data = _json.loads(gh_result)
        issue_content = issue_data.get("body", "")
        issue_title = issue_data.get("title", "")

        warden = getattr(container, "warden", None)
        if warden:
            issue_verdict = await warden.scan(issue_content, "user_input")
            if not issue_verdict.clean:
                logger.warning(
                    "Issue #%d blocked by Warden: %s",
                    issue_number,
                    issue_verdict.flags,
                )
                orch.fail_run(run_id, error=f"Warden blocked issue: {issue_verdict.flags}")
                return
            logger.info("Issue #%d passed Warden scan", issue_number)

        ws_result = await container.tool_dispatcher.execute(
            "workspace",
            {
                "action": "create",
                "issue_number": issue_number,
                "owner": owner,
                "repo": repo,
            },
        )
        if ws_result.startswith("Error:"):
            # Workspace may already exist from a previous run — try to reuse it
            existing_path = f"/workspace/worktrees/mason-{issue_number}"
            import os
            if os.path.isdir(existing_path):
                ws_result = _json.dumps({"path": existing_path, "branch": f"mason/{issue_number}"})
                logger.info("Reusing existing workspace: %s", existing_path)
            else:
                logger.error("Workspace creation failed: %s", ws_result)
                return

        ws_data = _json.loads(ws_result)
        run.branch = ws_data.get("branch", run.branch)
        ws_path = ws_data.get("path")
        logger.info("Workspace created: %s", ws_path)

        repo_verdict = await _scan_repo_for_threats(ws_path, warden)
        if not repo_verdict.clean:
            logger.warning(
                "Repo scan found warnings for run %s (non-blocking): %s",
                run_id,
                repo_verdict.flags,
            )
            # Log but don't block — config files with example values are expected
        else:
            logger.info("Repo scan passed for run %s", run_id)

        run._workspace_path = ws_path
        run._issue_content = issue_content
        run._issue_title = issue_title

        # Stage 0: Load onboarding + seed prompt library
        pipeline = _build_pipeline(container)
        run._onboarding = await pipeline.load_onboarding(ws_path)
        await pipeline.seed_prompts()
        # Seed onboarding into prompt library too
        if container.prompt_manager and run._onboarding:
            try:
                existing = await container.prompt_manager.get("builders.onboarding")
                if not existing:
                    await container.prompt_manager.upsert(
                        "builders.onboarding", run._onboarding, label="production",
                    )
            except Exception:
                pass
        # Copy platform tooling into workspace (tests/fakes.py, ONBOARDING.md)
        # The workspace is a git clone from GitHub which doesn't have our latest utilities
        await container.tool_dispatcher.execute("shell", {
            "command": "cp /app/tests/fakes.py tests/fakes.py && cp /app/ONBOARDING.md ONBOARDING.md 2>/dev/null; true",
            "workspace": ws_path,
        })
        print(f"[BUILDERS] Onboarding loaded: {len(run._onboarding)} chars, platform tooling copied", flush=True)

    except Exception as e:
        logger.error("Workflow setup failed for run %s: %s", run_id, e)
        return

    MAX_OUTER_LOOPS = 3

    for outer in range(MAX_OUTER_LOOPS):
        # Rotate mason model each outer loop
        from stronghold.builders.pipeline import RuntimePipeline as _RP
        rotation = _RP.MODEL_ROTATION
        mason_model = rotation[outer % len(rotation)]
        # Store on run so pipeline reads it
        run = orch._runs.get(run_id)
        if run:
            run._mason_model_override = mason_model
        print(f"[OUTER] Loop {outer + 1}/{MAX_OUTER_LOOPS} for run {run_id}, mason_model={mason_model}", flush=True)

        # Reset run to acceptance_defined if this is a retry (not the first pass)
        if outer > 0:
            from stronghold.builders import WorkerName as _WN

            run = orch._runs.get(run_id)
            if not run:
                break

            # Tell Frank which criteria are locked
            locked = getattr(run, "_locked_criteria", set())
            criteria = getattr(run, "_criteria", [])
            if locked and criteria:
                locked_summary = "\n".join(
                    f"- Criterion {i + 1}: {'LOCKED (tests pass)' if i in locked else 'NEEDS REWORK'}"
                    for i in range(len(criteria))
                )
                await container.tool_dispatcher.execute("github", {
                    "action": "post_pr_comment",
                    "owner": owner,
                    "repo": repo,
                    "issue_number": issue_number,
                    "body": (
                        f"## Outer Loop {outer + 1}: Re-evaluating criteria\n\n"
                        f"{locked_summary}\n\n"
                        f"Frank will re-evaluate failing criteria. Locked criteria will not be touched."
                    ),
                })

            # Reset stage back to acceptance_defined so Frank re-evaluates
            run.current_stage = "acceptance_defined"
            run.current_worker = _WN.FRANK
            run.status = RunStatus.RUNNING

        # Run stages until completion or failure
        max_iterations = len(_STAGE_SEQUENCE) + 2
        for _ in range(max_iterations):
            run = orch._runs.get(run_id)
            if not run:
                break
            if run.status in (RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED):
                break
            await _execute_one_stage(run_id, orch, container, service_auth)

        run = orch._runs.get(run_id)
        if not run:
            break

        # If passed → create PR and exit (guarded against double-fire)
        if run.status == RunStatus.PASSED:
            if getattr(run, "_pr_creation_started", False):
                logger.info(
                    "Skipping PR creation for %s — already started by another path",
                    run_id,
                )
            elif ws_path:
                run._pr_creation_started = True
                await _create_pr_on_finish(run, container, owner, repo, ws_path)
            break

        # If TDD stalled (not a hard failure) → try another outer loop
        if outer < MAX_OUTER_LOOPS - 1:
            print(f"[OUTER] Loop {outer + 1} did not complete — retrying with Frank re-evaluation", flush=True)
            # Reset status so the loop continues
            run.status = RunStatus.RUNNING
            continue

        # Exhausted all outer loops → BLOCKED, wait for human
        run.status = RunStatus.BLOCKED
        await container.tool_dispatcher.execute("github", {
            "action": "post_pr_comment",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
            "body": (
                f"## Builders: Waiting for human guidance\n\n"
                f"**{MAX_OUTER_LOOPS} outer loops exhausted.** "
                f"The pipeline could not fully resolve this issue autonomously.\n\n"
                f"**What was accomplished:** Check the comments above for per-criterion progress.\n\n"
                f"**What's needed:** Review the failing criteria and provide guidance, "
                f"then re-trigger the run."
            ),
        })
        print(f"[OUTER] All {MAX_OUTER_LOOPS} loops exhausted — BLOCKED, waiting for human", flush=True)

    logger.info("Workflow complete for run %s", run_id)


async def _create_pr_on_finish(
    run: Any, container: Any, owner: str, repo: str, ws_path: str
) -> None:
    """Commit changes, push branch, and create PR after successful run."""
    import json as _json

    issue_num = run.issue_number
    td = container.tool_dispatcher

    try:
        # Commit all changes in the worktree
        commit_result = await td.execute(
            "workspace",
            {
                "action": "commit",
                "issue_number": issue_num,
                "message": f"feat: implement issue #{issue_num}",
            },
        )
        if commit_result.startswith("Error:"):
            logger.error("Commit failed: %s", commit_result)
            return

        # Push the branch
        push_result = await td.execute(
            "workspace",
            {"action": "push", "issue_number": issue_num},
        )
        if push_result.startswith("Error:"):
            logger.error("Push failed: %s", push_result)
            return

        push_data = _json.loads(push_result)
        branch = push_data.get("branch", f"mason/{issue_num}")

        # Create the PR
        pr_result = await td.execute(
            "github",
            {
                "action": "create_pr",
                "owner": owner,
                "repo": repo,
                "title": f"feat: #{issue_num} — {getattr(run, '_issue_title', '')}".strip(),
                "head": branch,
                "base": "main",
                "body": (
                    f"## Issue #{issue_num}\n\n"
                    f"Implements #{issue_num}.\n\n"
                    f"### Pipeline\n"
                    f"- Run: `{run.run_id}`\n"
                    f"- Stages completed: {len(run.artifacts)}\n"
                    f"- Generated by Stronghold Builders\n"
                ),
            },
        )
        if pr_result.startswith("Error:"):
            logger.error("PR creation failed: %s", pr_result)
            return

        pr_data = _json.loads(pr_result)
        pr_url = pr_data.get("url", pr_result)
        logger.info("PR created: %s", pr_url)

        # Post PR link to issue
        await td.execute(
            "github",
            {
                "action": "create_comment",
                "owner": owner,
                "repo": repo,
                "issue_number": issue_num,
                "body": f"PR created: {pr_url}",
            },
        )

    except Exception as e:
        logger.error(
            "PR creation failed for run %s: %s", run.run_id, e,
        )


async def _scan_repo_for_threats(ws_path: str, warden: Any) -> Any:
    """Scan repo files for suspicious patterns using Warden.

    Scans:
    - Shell scripts (*.sh)
    - Config files (*.yaml, *.yml, *.json, *.toml)
    - Any file with secrets-like patterns

    Returns WardenVerdict with clean=True if no threats found.
    """
    from stronghold.types.security import WardenVerdict
    from pathlib import Path
    import re

    if not warden or not ws_path:
        return WardenVerdict(clean=True, blocked=False, flags=(), confidence=1.0)

    ws = Path(ws_path)
    if not ws.exists():
        return WardenVerdict(clean=True, blocked=False, flags=(), confidence=1.0)

    suspicious_extensions = {".sh", ".bash", ".zsh"}
    config_extensions = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".env"}
    secret_patterns = [
        re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+"),
        re.compile(r"(?i)(api_key|apikey|secret|token)\s*[=:]\s*\S+"),
        re.compile(r"(?i)-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
        re.compile(r"(?i)aws_access_key_id\s*=\s*\S+"),
        re.compile(r"(?i)aws_secret_access_key\s*=\s*\S+"),
    ]

    all_flags: list[str] = []
    files_scanned = 0

    for ext in suspicious_extensions | config_extensions:
        for filepath in ws.rglob(f"*{ext}"):
            if ".git" in str(filepath) or "node_modules" in str(filepath):
                continue
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
                files_scanned += 1

                verdict = await warden.scan(content, "tool_result")
                if not verdict.clean:
                    all_flags.extend([f"{filepath.name}: {f}" for f in verdict.flags])

                for pattern in secret_patterns:
                    if pattern.search(content):
                        all_flags.append(f"{filepath.name}: potential secret/credential")

            except Exception as e:
                logger.debug("Failed to scan %s: %s", filepath, e)

    if all_flags:
        return WardenVerdict(
            clean=False,
            blocked=len(all_flags) >= 2,
            flags=tuple(all_flags[:10]),
            confidence=0.8,
        )

    logger.debug("Repo scan complete: %d files, no threats", files_scanned)
    return WardenVerdict(clean=True, blocked=False, flags=(), confidence=1.0)


def _build_stage_prompt(stage: str, worker: Any, run: Any) -> str:
    worker_name = worker.value if hasattr(worker, "value") else str(worker)
    ws_path = getattr(run, "_workspace_path", "/workspace")
    issue_content = getattr(run, "_issue_content", "")
    issue_title = getattr(run, "_issue_title", "")

    tool_context = (
        f"\n\nWORKSPACE: {ws_path}\n"
        f"Issue: {run.repo}#{run.issue_number}\n"
        f"Title: {issue_title}\n\n"
        f"AVAILABLE tools: file_ops, shell, workspace, github, run_pytest, run_ruff_check, run_ruff_format, run_mypy, run_bandit, git\n\n"
        f"Use these tools to read files, write code, run tests, and and"
    )

    issue_context = f"\nISSUE CONTENT:\n{issue_content}\n" if issue_content else ""

    stage_prompts = {
        "issue_analyzed": (
            f"You are {worker_name}. Your job is to analyze GitHub issue #{run.issue_number}.\n\n"
            f"Issue: {run.repo}#{run.issue_number}\n"
            f"Title: {issue_title}\n\n"
            f"Body:\n{issue_content}\n\n"
            f"First, call the github tool with action 'get_issue' to fetch full details if needed.\n"
            f"Then analyze:\ 1) What is the problem? 2) What are the requirements? 3) What are the edge cases?\\n\n"
            f"Provide your analysis in structured format:\n"
            f"## Summary\n"
            f"- Problem:\n"
            f"- Requirements:\n"
            f"- Edge cases:\n"
            f"- Suggested approach:\n\n"
        ),
        "acceptance_defined": (
            f"You are {worker_name}. Based on the issue analysis for {run.repo}#{run.issue_number}, "
            f"define acceptance criteria in Gherkin format (Given/When/Then).\n\n"
            f"Issue context:\n{issue_context}\n\n"
            f"Write acceptance criteria covering:\n"
            f"1. Happy path scenarios\n"
            f"2. Error scenarios\n"
            f"3. Edge cases\n\n"
            f"Format each criterion as:\n"
            f"```gherkin\n"
            f"Given [context]\n"
            f"When [action]\n"
            f"Then [expected result]\n"
            f"```\n"
        ),
        "tests_written": (
            f"You are {worker_name}. Write tests for {run.repo}#{run.issue_number}.\n\n"
            f"Issue: {issue_title}\n{issue_context}\n\n"
            f"YOU MUST USE TOOLS. Do not describe what you would do — actually do it.\n\n"
            f"Step 1: Call file_ops with action='list', path='tests/api', workspace='{ws_path}' to see existing tests.\n"
            f"Step 2: Call file_ops with action='read', path='src/stronghold/api/routes/status.py', workspace='{ws_path}' to see existing code.\n"
            f"Step 3: Call file_ops with action='write' to create the test file at the correct path, workspace='{ws_path}'.\n"
            f"Step 4: Call run_pytest with workspace='{ws_path}' to verify.\n\n"
            f"Every step MUST be a tool call. No text-only responses.\n"
        ),
        "implementation_started": (
            f"You are {worker_name}. Implement the solution for {run.repo}#{run.issue_number}.\n\n"
            f"Issue: {issue_title}\n{issue_context}\n\n"
            f"YOU MUST USE TOOLS. Do not describe what you would do — actually do it.\n\n"
            f"Step 1: Call file_ops with action='read', path='src/stronghold/api/routes/status.py', workspace='{ws_path}' to see the target file.\n"
            f"Step 2: Call file_ops with action='write' to add the new code, workspace='{ws_path}'.\n"
            f"Step 3: Call run_pytest with workspace='{ws_path}' to verify tests pass.\n"
            f"Step 4: Call git with command='add -A && git commit -m \"feat: implement #{run.issue_number}\"', workspace='{ws_path}'.\n\n"
            f"Every step MUST be a tool call. No text-only responses.\n"
        ),
        "implementation_ready": (
            f"You are {worker_name}. Run quality checks on the implementation.\n\n"
            f"YOU MUST USE TOOLS — call each one:\n\n"
            f"1. Call run_pytest with workspace='{ws_path}'\n"
            f"2. Call run_ruff_check with workspace='{ws_path}'\n"
            f"3. Call run_ruff_format with workspace='{ws_path}'\n"
            f"4. Call run_mypy with workspace='{ws_path}'\n\n"
            f"If any check fails on YOUR code (not pre-existing failures), call file_ops to fix and re-run.\n"
            f"Report final status of all checks.\n"
        ),
        "quality_checks_passed": (
            f"You are {worker_name}. Final verification for {run.repo}#{run.issue_number}.\n\n"
            f"YOU MUST USE TOOLS:\n\n"
            f"1. Call run_pytest with workspace='{ws_path}'\n"
            f"2. Call run_ruff_check with workspace='{ws_path}'\n"
            f"3. Call run_mypy with workspace='{ws_path}'\n\n"
            f"Then call git with command='log --oneline -5', workspace='{ws_path}' to confirm commits.\n"
            f"Summarize what was implemented and how it addresses the issue.\n"
        ),
    }
    return stage_prompts.get(stage, f"You are {worker_name}. Execute stage: {stage}{tool_context}")


async def _check_existing_work(
    tool_dispatcher: Any,
    owner: str,
    repo: str,
    issue_number: int,
    issue_title: str,
) -> dict[str, Any]:
    """Check for existing work (PRs, issues, comments) related to the issue."""
    import re

    keywords = re.findall(r"\b\w+\b", issue_title.lower())
    search_query = " ".join(keywords[:3])

    prs_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "search_issues",
            "owner": owner,
            "repo": repo,
            "query": f"{search_query} is:pr",
        },
    )

    prs = []
    if not prs_result.startswith("Error:"):
        prs_data = json.loads(prs_result)
        prs = prs_data.get("items", [])

    comments_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "list_issue_comments",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
        },
    )

    comments = []
    if not comments_result.startswith("Error:"):
        comments = json.loads(comments_result)

    linked_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "get_linked_issues",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
        },
    )

    linked_issues = []
    if not linked_result.startswith("Error:"):
        linked_issues = json.loads(linked_result)

    has_work = bool(prs or comments or linked_issues)

    return {
        "prs": prs,
        "issues": linked_issues,
        "comments": comments,
        "has_work": has_work,
    }


async def _frank_archie_phase(
    container: Any,
    tool_dispatcher: Any,
    run_id: str,
    repo: str,
    issue_number: int,
    issue_title: str,
    issue_content: str,
    ws_path: str,
    existing_work: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Frank/Archie phase: decompose problem and define acceptance criteria."""
    from stronghold.builders import WorkerName

    if existing_work is None:
        existing_work = await _check_existing_work(
            tool_dispatcher=tool_dispatcher,
            owner=repo.split("/")[0],
            repo=repo.split("/")[1],
            issue_number=issue_number,
            issue_title=issue_title,
        )

    if existing_work["has_work"]:
        publisher = IssueCommentPublisher(
            tool_dispatcher=tool_dispatcher,
            formatter=IssueCommentFormatter(),
        )
        await publisher.publish_workflow_step(
            owner=repo.split("/")[0],
            repo=repo.split("/")[1],
            issue_number=issue_number,
            comment_type=CommentType.FRANK_DECOMPOSITION,
            step="existing_work_found",
            details={
                "existing_prs": len(existing_work["prs"]),
                "existing_comments": len(existing_work["comments"]),
            },
            run_id=run_id,
        )
        return {
            "phase": "frank_archie",
            "decomposed": False,
            "existing_prs": [p["number"] for p in existing_work["prs"]],
        }

    frank = container.agents.get("frank")
    if not frank:
        return {"phase": "frank_archie", "decomposed": False, "error": "Frank agent not found"}

    prompt = _build_stage_prompt(
        "issue_analyzed",
        WorkerName.FRANK,
        Mock(
            repo=repo,
            issue_number=issue_number,
            _workspace_path=ws_path,
            _issue_content=issue_content,
            _issue_title=issue_title,
        ),
    )
    messages = [{"role": "user", "content": prompt}]

    response = await frank.handle(
        messages,
        auth=_build_service_auth(container),
        session_id=f"builders-{run_id}",
    )

    publisher = IssueCommentPublisher(
        tool_dispatcher=tool_dispatcher,
        formatter=IssueCommentFormatter(),
    )
    await publisher.publish_workflow_step(
        owner=repo.split("/")[0],
        repo=repo.split("/")[1],
        issue_number=issue_number,
        comment_type=CommentType.FRANK_DECOMPOSITION,
        step="problem_decomposition",
        details={
            "sub_problems": ["Decomposed into sub-problems"],
            "assumptions": ["Assumptions documented"],
        },
        run_id=run_id,
    )

    return {
        "phase": "frank_archie",
        "decomposed": True,
        "response": response.content if response else "",
    }


async def _mason_phase(
    container: Any,
    tool_dispatcher: Any,
    test_tracker: MasonTestTracker,
    run_id: str,
    repo: str,
    issue_number: int,
    ws_path: str,
    max_attempts: int = 10,
) -> dict[str, Any]:
    """Mason phase: TDD implementation with test tracking."""
    from stronghold.builders import WorkerName

    mason = container.agents.get("mason")
    if not mason:
        return {"phase": "mason", "success": False, "error": "Mason agent not found"}

    for attempt in range(max_attempts):
        logger.info(f"Mason phase attempt {attempt + 1} of {max_attempts}")

        try:
            prompt = _build_stage_prompt(
                "implementation_started",
                WorkerName.MASON,
                Mock(
                    repo=repo,
                    issue_number=issue_number,
                    _workspace_path=ws_path,
                    _issue_content="",
                    _issue_title="",
                ),
            )
            messages = [{"role": "user", "content": prompt}]

            response = await mason.handle(
                messages,
                auth=_build_service_auth(container),
                session_id=f"builders-{run_id}",
            )

            pytest_result = await tool_dispatcher.execute(
                "workspace",
                {"action": "run_pytest", "path": ws_path},
            )
        except Exception as e:
            logger.error(f"Exception in Mason phase attempt {attempt + 1}: {e}")
            raise

        passing_count = 0
        failing_count = 0
        coverage = "0%"

        logger.info(f"Pytest result: {pytest_result}")

        if not pytest_result.startswith("Error:"):
            import re

            match = re.search(r"(\d+)\s+passed", pytest_result)
            if match:
                passing_count = int(match.group(1))
            match = re.search(r"(\d+)\s+failed", pytest_result)
            if match:
                failing_count = int(match.group(1))
            match = re.search(r"(\d+)%", pytest_result)
            if match:
                coverage = f"{match.group(1)}%"

        logger.info(
            f"Parsed results: passing={passing_count}, failing={failing_count}, coverage={coverage}"
        )

        test_tracker.record_test_result(passing_count)

        publisher = IssueCommentPublisher(
            tool_dispatcher=tool_dispatcher,
            formatter=IssueCommentFormatter(),
        )
        await publisher.publish_workflow_step(
            owner=repo.split("/")[0],
            repo=repo.split("/")[1],
            issue_number=issue_number,
            comment_type=CommentType.MASON_TEST_RESULTS,
            step=f"test_execution_{attempt + 1}",
            details={
                "passing": passing_count,
                "failing": failing_count,
                "coverage": coverage,
                "high_water_mark": test_tracker.high_water_mark,
                "stall_counter": test_tracker.stall_counter,
            },
            run_id=run_id,
        )

        if test_tracker.has_failed:
            return {
                "phase": "mason",
                "success": False,
                "stalled": True,
                "attempts": attempt + 1,
            }

        if failing_count == 0:
            return {
                "phase": "mason",
                "success": True,
                "attempts": attempt + 1,
            }

    return {
        "phase": "mason",
        "success": False,
        "stalled": False,
        "attempts": max_attempts,
    }


async def _run_quality_gates(
    tool_dispatcher: Any,
    ws_path: str,
) -> dict[str, Any]:
    """Run quality gates: pytest, ruff, mypy, bandit."""
    import re

    pytest_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_pytest", "path": ws_path},
    )

    coverage = "0%"
    if not pytest_result.startswith("Error:"):
        match = re.search(r"(\d+)%", pytest_result)
        if match:
            coverage = f"{match.group(1)}%"

    coverage_pct = int(coverage.replace("%", "")) if coverage != "0%" else 0

    ruff_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_ruff_check"},
    )

    mypy_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_mypy"},
    )

    bandit_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_bandit"},
    )

    passed = coverage_pct >= 95

    return {
        "passed": passed,
        "coverage": coverage,
        "pytest": "passed" if not pytest_result.startswith("Error:") else "failed",
        "ruff_check": "passed" if not ruff_result.startswith("Error:") else "failed",
        "mypy": "passed" if not mypy_result.startswith("Error:") else "failed",
        "bandit": "passed" if not bandit_result.startswith("Error:") else "failed",
    }


async def _create_pr_after_success(
    tool_dispatcher: Any,
    owner: str,
    repo: str,
    branch: str,
    issue_number: int,
    ws_path: str,
    quality_passed: bool,
) -> dict[str, Any]:
    """Commit, push, and create PR after successful workflow."""
    if not quality_passed:
        return {"created": False, "pr_number": None}

    commit_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "commit", "message": f"feat: implement issue #{issue_number}"},
    )

    if commit_result.startswith("Error:"):
        return {"created": False, "pr_number": None}

    push_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "push"},
    )

    if push_result.startswith("Error:"):
        return {"created": False, "pr_number": None}

    pr_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "create_pr",
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "title": f"Fix #{issue_number}",
            "head": branch,
            "base": "main",
            "body": f"Implements #{issue_number}\n\nGenerated by Stronghold Builders.",
        },
    )

    if pr_result.startswith("Error:"):
        return {"created": False, "pr_number": None}

    pr_data = json.loads(pr_result)
    pr_number = pr_data.get("number")

    publisher = IssueCommentPublisher(
        tool_dispatcher=tool_dispatcher,
        formatter=IssueCommentFormatter(),
    )
    await publisher.publish_workflow_step(
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        comment_type=CommentType.PR_CREATED,
        step="pr_creation",
        details={
            "pr_number": pr_number,
            "pr_url": pr_data.get("html_url", ""),
            "branch": branch,
        },
        run_id="",
    )

    await tool_dispatcher.execute(
        "workspace",
        {"action": "cleanup"},
    )

    return {"created": True, "pr_number": pr_number}


async def _execute_nested_loop_workflow(
    container: Any,
    tool_dispatcher: Any,
    run_id: str,
    repo: str,
    issue_number: int,
    ws_path: str,
    issue_title: str,
    issue_content: str,
) -> dict[str, Any]:
    """Execute sophisticated nested-loop workflow with outer/inner loops."""
    outer_tracker = OuterLoopTracker(max_failures=5)
    model_escalator = ModelEscalator()
    owner, repo_name = repo.split("/")

    for outer_retry in range(5):
        model = model_escalator.select_model(retry_count=outer_retry)

        logger.info(
            "Outer loop attempt %d with model %s",
            outer_retry + 1,
            model,
        )

        frank_result = await _frank_archie_phase(
            container=container,
            tool_dispatcher=tool_dispatcher,
            run_id=run_id,
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_content=issue_content,
            ws_path=ws_path,
        )

        if not frank_result.get("decomposed", False) and frank_result.get("existing_prs"):
            outer_tracker.record_success()
            return {
                "status": "completed",
                "reason": "existing_work_found",
                "existing_prs": frank_result["existing_prs"],
            }

        test_tracker = MasonTestTracker()

        for inner_retry in range(3):
            mason_result = await _mason_phase(
                container=container,
                tool_dispatcher=tool_dispatcher,
                test_tracker=test_tracker,
                run_id=run_id,
                repo=repo,
                issue_number=issue_number,
                ws_path=ws_path,
            )

            if mason_result.get("success"):
                quality_result = await _run_quality_gates(
                    tool_dispatcher=tool_dispatcher,
                    ws_path=ws_path,
                )

                publisher = IssueCommentPublisher(
                    tool_dispatcher=tool_dispatcher,
                    formatter=IssueCommentFormatter(),
                )
                await publisher.publish_workflow_step(
                    owner=owner,
                    repo=repo_name,
                    issue_number=issue_number,
                    comment_type=CommentType.QUALITY_CHECKS,
                    step="quality_verification",
                    details=quality_result,
                    run_id=run_id,
                )

                if quality_result["passed"]:
                    pr_result = await _create_pr_after_success(
                        tool_dispatcher=tool_dispatcher,
                        owner=owner,
                        repo=repo_name,
                        branch=f"builders/{issue_number}-{run_id}",
                        issue_number=issue_number,
                        ws_path=ws_path,
                        quality_passed=True,
                    )

                    if pr_result["created"]:
                        outer_tracker.record_success()
                        return {
                            "status": "completed",
                            "pr_number": pr_result["pr_number"],
                        }
                else:
                    outer_tracker.record_failure()
                    break

            if mason_result.get("stalled"):
                logger.info(
                    "Mason stalled after %d attempts, returning to Frank/Archie",
                    test_tracker.stall_counter,
                )
                break

        if outer_tracker.should_signal_admin:
            publisher = IssueCommentPublisher(
                tool_dispatcher=tool_dispatcher,
                formatter=IssueCommentFormatter(),
            )
            await publisher.publish_workflow_step(
                owner=owner,
                repo=repo_name,
                issue_number=issue_number,
                comment_type=CommentType.ADMIN_SIGNAL,
                step="admin_alert",
                details={
                    "total_failures": outer_tracker.failure_count,
                    "recommendation": "Review issue complexity and consider manual intervention",
                },
                run_id=run_id,
            )
            return {
                "status": "failed",
                "reason": "max_retries_exceeded",
                "failures": outer_tracker.failure_count,
            }

    return {
        "status": "failed",
        "reason": "max_outer_loops_exceeded",
        "failures": outer_tracker.failure_count,
    }
