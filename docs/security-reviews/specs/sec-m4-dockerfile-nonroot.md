# SEC-M4: Dockerfile runs as non-root with a locked-down `/workspace`

## User Story

As a **platform operator**, I want the Stronghold container to run as a
non-root user with a non-world-writable `/workspace`, so that a process
compromise does not grant root inside the container.

## Background

`Dockerfile:34` sets `chmod 777 /workspace` and has no `USER` directive,
so the container runs as root.

## Acceptance Criteria

- AC1: Given the built image, When inspected, Then the final `USER` is non-root (`stronghold`, uid=1000).
- AC2: Given the container runs, When `stat -c '%a' /workspace` is observed, Then the mode is `750`.
- AC3: Given Mason's quality gates (`pytest`, `ruff`, `mypy`, `bandit`, `git`), When run by the non-root user inside `/workspace`, Then they succeed (CI proves this).
- AC4: Given the container starts via `uvicorn`, When bound to `0.0.0.0:8100`, Then the bind succeeds (port is >1024, no CAP_NET_BIND required).

## Test Mapping

| AC  | Test path                                    | Test function                              | Tier     |
|-----|----------------------------------------------|--------------------------------------------|----------|
| AC1 | tests/deploy/test_dockerfile.py              | test_image_runs_as_nonroot                 | critical |
| AC2 | tests/deploy/test_dockerfile.py              | test_workspace_mode_750                    | critical |
| AC3 | `.github/workflows/ci.yml` (existing smoke)  | (runs Mason quality gates against image)   | e2e      |
| AC4 | tests/deploy/test_dockerfile.py              | test_uvicorn_binds_8100                    | happy    |

## Files to Touch

- Modify: `Dockerfile`:
  ```Dockerfile
  RUN useradd -r -u 1000 -m stronghold \
   && mkdir -p /workspace \
   && chown stronghold:stronghold /workspace \
   && chmod 750 /workspace
  USER stronghold
  ```
- Modify: `deploy/` helm charts — ensure `securityContext.runAsNonRoot: true` already aligns.
- New: `tests/deploy/test_dockerfile.py` — uses `docker inspect`/`docker run --rm` against built image; gate with `deploy` marker.

## Rollback

Single-commit Dockerfile revert. Verify Mason worktree creation still works in CI before release.
