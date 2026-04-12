# Vanilla Playwright fetcher for the Ranger (public tier).
# DO NOT add stealth patches, patchright, or Camoufox to this image.
# Sites with anti-bot protection SHOULD return 403 — that's by design.

FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app
COPY app.py .

RUN pip install --no-cache-dir fastapi uvicorn[standard]

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
