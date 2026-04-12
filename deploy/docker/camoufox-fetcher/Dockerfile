# Camoufox stealth browser fetcher for Ranger Elite (gated tier).
# DO NOT add NodePort, Ingress, or LoadBalancer to k8s manifests for this image.
# Access is gated by Stronghold's agent-level access control (migration 012).

FROM python:3.12-slim

WORKDIR /app
COPY app.py .

# Install camoufox + playwright (camoufox needs playwright as its control layer)
# plus the FastAPI server deps.
# Pin camoufox version for reproducibility — bump manually when needed.
RUN pip install --no-cache-dir \
    "camoufox>=0.4" \
    playwright \
    fastapi \
    uvicorn[standard]

# Download the Camoufox Firefox build (headless).
RUN camoufox fetch

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
