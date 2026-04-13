# Stronghold — Secure Agent Governance Platform
# Multi-stage build for minimal production image

FROM python:3.12.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
# Mason's workspace validation depends on the dev quality tools existing
# in the runtime image: pytest, ruff, mypy, and bandit.
RUN pip install --no-cache-dir --prefix=/install ".[dev]"

FROM python:3.12.11-slim

# Mason needs git to create branches, worktrees, commit, push
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Create non-root user for runtime
RUN groupadd --gid 1000 stronghold && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash stronghold

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ src/
COPY agents/ agents/
COPY tests/ tests/
COPY migrations/ migrations/
COPY config/ config/
COPY pyproject.toml .

# Remove uvloop — it requires socketpair() which fails in unprivileged containers
RUN pip uninstall -y uvloop 2>/dev/null; true

# Workspace directory for Mason worktrees
RUN mkdir -p /workspace && chown 1000:1000 /workspace

# Ensure app files are readable by non-root user
RUN chown -R 1000:1000 /app

USER 1000:1000

EXPOSE 8100

CMD ["uvicorn", "stronghold.api.app:create_app", "--host", "0.0.0.0", "--port", "8100", "--factory"]
