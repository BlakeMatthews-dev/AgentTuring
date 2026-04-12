"""Camoufox stealth browser fetcher pod — serves POST /fetch.

This is the ELITE-TIER backend. It uses Camoufox (a stealth Firefox fork)
to bypass Cloudflare, DataDome, Akamai, and other anti-bot systems.

This pod is ClusterIP-only — NEVER expose it via NodePort or Ingress.
Access is gated by the Stronghold API's agent-level access control.

Run: uvicorn app:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("camoufox-fetcher")

app = FastAPI(title="camoufox-fetcher", docs_url=None, redoc_url=None)


class FetchRequest(BaseModel):
    url: str
    wait: str = "networkidle"
    timeout_ms: int = 15000


class FetchResponse(BaseModel):
    url: str
    final_url: str
    status: int
    html: str


@app.post("/fetch")
async def fetch(req: FetchRequest) -> FetchResponse:
    from camoufox.async_api import AsyncCamoufox  # noqa: PLC0415

    try:
        async with AsyncCamoufox(headless=True) as browser:
            page = await browser.new_page()
            resp = await page.goto(
                req.url,
                wait_until=req.wait,
                timeout=req.timeout_ms,
            )
            html = await page.content()
            status = resp.status if resp else 0
            final_url = page.url
    except Exception as e:
        logger.error("Fetch failed for %s: %s", req.url, e)
        return FetchResponse(url=req.url, final_url=req.url, status=0, html="")

    logger.info("Fetched %s -> %d (%d chars)", req.url, status, len(html))
    return FetchResponse(url=req.url, final_url=final_url, status=status, html=html)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "engine": "camoufox"}
