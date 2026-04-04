"""E2E test fixtures — hits the live Docker stack at localhost:8100."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

STRONGHOLD_URL = os.getenv("STRONGHOLD_URL", "http://localhost:8100")
API_KEY = os.getenv("STRONGHOLD_API_KEY", "sk-stronghold-prod-2026")


def _stack_running() -> bool:
    try:
        r = httpx.get(f"{STRONGHOLD_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


skip_no_stack = pytest.mark.skipif(
    not _stack_running(),
    reason="Docker stack not running (start with: docker compose up -d)",
)


class RetryClient:
    """Async HTTP client that retries on 429 (rate limited)."""

    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        self._base_url = base_url
        self._headers = headers

    async def _retry(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers, timeout=30.0
        ) as c:
            for attempt in range(4):
                resp = await getattr(c, method)(path, **kwargs)
                if resp.status_code != 429:
                    return resp
                wait = int(resp.headers.get("x-ratelimit-reset", "5"))
                await asyncio.sleep(min(wait, 10))
            return resp  # Return last 429 if all retries exhausted

    async def get(self, path: str, **kw: object) -> httpx.Response:
        return await self._retry("get", path, **kw)

    async def post(self, path: str, **kw: object) -> httpx.Response:
        return await self._retry("post", path, **kw)


@pytest.fixture(autouse=True)
def _reset_strikes() -> None:
    """Re-enable and unlock the system user before each test.

    Injection tests trigger strikes which can disable the account,
    causing all subsequent tests to fail with 403.
    """
    if _stack_running():
        headers = {"Authorization": f"Bearer {API_KEY}"}
        for action in ("enable", "unlock"):
            try:
                httpx.post(
                    f"{STRONGHOLD_URL}/v1/stronghold/admin/strikes/system/{action}",
                    headers=headers,
                    timeout=3,
                )
            except Exception:  # noqa: BLE001
                pass


@pytest.fixture
def base_url() -> str:
    return STRONGHOLD_URL


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture
def client() -> RetryClient:
    return RetryClient(
        base_url=STRONGHOLD_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
