# Stronghold — Secure Agent Governance Platform
# Multi-stage build for minimal production image

FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ src/
COPY agents/ agents/
COPY tests/ tests/
COPY migrations/ migrations/
COPY config/ config/

# Remove uvloop — it requires socketpair() which fails in unprivileged containers
RUN pip uninstall -y uvloop 2>/dev/null; true

# Non-root user
RUN useradd -r -s /bin/false stronghold
USER stronghold

EXPOSE 8100

CMD ["uvicorn", "stronghold.api.app:create_app", "--host", "0.0.0.0", "--port", "8100", "--factory"]
