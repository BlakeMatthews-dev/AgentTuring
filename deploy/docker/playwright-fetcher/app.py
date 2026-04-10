"""Vanilla Playwright fetcher pod — serves POST /fetch for the browser_fetch tool.

This is the PUBLIC-TIER backend. It uses upstream Playwright + Chromium with
no stealth patches. Sites with anti-bot protection (Cloudflare, DataDome)
will return 403 — that is the intended behavior for non-Elite callers.

Run: uvicorn app:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("playwright-fetcher")

app = FastAPI(title="playwright-fetcher", docs_url=None, redoc_url=None)


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
    from playwright.async_api import async_playwright  # noqa: PLC0415

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                resp = await page.goto(
                    req.url,
                    wait_until=req.wait,
                    timeout=req.timeout_ms,
                )
                html = await page.content()
                status = resp.status if resp else 0
                final_url = page.url
            finally:
                await browser.close()
    except Exception as e:
        logger.error("Fetch failed for %s: %s", req.url, e)
        return FetchResponse(url=req.url, final_url=req.url, status=0, html="")

    logger.info("Fetched %s -> %d (%d chars)", req.url, status, len(html))
    return FetchResponse(url=req.url, final_url=final_url, status=status, html=html)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "engine": "playwright"}
