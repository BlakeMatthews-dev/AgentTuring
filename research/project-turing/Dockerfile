FROM python:3.12-slim

# Non-root user.
RUN useradd --create-home --shell /bin/bash turing

WORKDIR /app

# Runtime deps only (httpx, PyYAML). respx is test-only.
COPY sketches/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Source tree. Scenarios live alongside the sketches package.
COPY sketches/ /app/sketches/
COPY scenarios/ /app/scenarios/

# The runtime looks for scenarios/<name>.yaml relative to the repo root
# (research/project-turing/); inside the container the layout is flattened
# so sketches/turing/ lives under /app/ and scenarios/ sits at /app/.
WORKDIR /app/sketches
ENV PYTHONPATH=/app/sketches \
    TURING_DB_PATH=/data/turing.db \
    TURING_LOG_FORMAT=json \
    TURING_TICK_RATE_HZ=100 \
    TURING_METRICS_PORT=9100

USER turing

VOLUME ["/data"]
EXPOSE 9100

ENTRYPOINT ["python", "-m", "turing.runtime.main"]
