FROM python:3.12-slim

# Non-root user.
RUN useradd --create-home --shell /bin/bash turing

WORKDIR /app

# Runtime deps only (httpx, PyYAML). respx is test-only.
COPY sketches/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Source tree. Scenarios + pools config live alongside the sketches package.
COPY sketches/ /app/sketches/
COPY scenarios/ /app/scenarios/
COPY config/ /app/config/

WORKDIR /app/sketches
ENV PYTHONPATH=/app/sketches \
    TURING_DB_PATH=/data/turing.db \
    TURING_JOURNAL_DIR=/data/journal \
    TURING_LOG_FORMAT=json \
    TURING_TICK_RATE_HZ=100 \
    TURING_METRICS_PORT=9100 \
    TURING_METRICS_BIND=0.0.0.0 \
    TURING_USE_FAKE_PROVIDER=true \
    TURING_POOLS_CONFIG=/app/config/pools.example.yaml

USER turing

VOLUME ["/data"]
EXPOSE 9100

ENTRYPOINT ["python", "-m", "turing.runtime.main"]
