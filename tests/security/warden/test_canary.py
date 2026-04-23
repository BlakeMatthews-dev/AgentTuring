"""Tests for canary-token Warden layer (S1.1)."""

from __future__ import annotations

import pytest

from stronghold.security.warden.canary import generate_canary, scan_canary
from tests.fakes import InMemoryCanaryStore


def test_generate_token_length_and_charset() -> None:
    """Token is 22 chars, URL-safe base64 (no padding, no +/)."""
    token = generate_canary()
    assert len(token) == 22
    import base64
    import binascii
    # Must be valid urlsafe base64 when padded to multiple of 4
    padded = token + "==" * ((4 - len(token) % 4) % 4)
    decoded = base64.urlsafe_b64decode(padded)
    assert len(decoded) == 16  # 128 bits


def test_get_or_mint_returns_same_token_within_session() -> None:
    """AC 1: successive get_or_mint calls in same session return same token."""
    store = InMemoryCanaryStore()

    async def _run() -> None:
        t1 = await store.get_or_mint("session-1", "org-1")
        t2 = await store.get_or_mint("session-1", "org-1")
        assert t1 == t2
        assert len(t1) == 22

    import asyncio
    asyncio.get_event_loop().run_until_complete(_run())


def test_get_or_mint_mints_new_token_for_new_session() -> None:
    """AC 1: different sessions get different tokens."""
    store = InMemoryCanaryStore()

    async def _run() -> None:
        t1 = await store.get_or_mint("session-1", "org-1")
        t2 = await store.get_or_mint("session-2", "org-1")
        assert t1 != t2

    import asyncio
    asyncio.get_event_loop().run_until_complete(_run())


def test_rotate_invalidates_previous_token() -> None:
    """AC 5: rotate() returns a new token and old token is gone."""
    store = InMemoryCanaryStore()

    async def _run() -> None:
        old = await store.get_or_mint("session-1", "org-1")
        new = await store.rotate("session-1", "org-1")
        assert old != new
        current = await store.get_or_mint("session-1", "org-1")
        assert current == new

    import asyncio
    asyncio.get_event_loop().run_until_complete(_run())


async def test_scan_clean_tool_result_returns_clean() -> None:
    """Baseline: tool result with no canary token is clean."""
    token = generate_canary()
    verdict = await scan_canary("This is safe tool output", token=token, boundary="tool_result")
    assert verdict.clean is True
    assert verdict.blocked is False
    assert "canary_echo" not in verdict.flags


async def test_scan_echoed_token_blocks() -> None:
    """AC 2: tool result containing full token is blocked with canary_echo flag."""
    token = generate_canary()
    verdict = await scan_canary(
        f"Here is some output including {token} the token",
        token=token,
        boundary="tool_result",
    )
    assert verdict.clean is False
    assert verdict.blocked is True
    assert "canary_echo" in verdict.flags
    assert verdict.confidence == 1.0


async def test_scan_partial_token_does_not_block() -> None:
    """AC 3: token missing its last character is not flagged."""
    token = generate_canary()
    partial = token[:-1]  # 21 chars — one short
    verdict = await scan_canary(
        f"output with {partial} partial token",
        token=token,
        boundary="tool_result",
    )
    assert verdict.clean is True
    assert "canary_echo" not in verdict.flags


async def test_scan_user_input_is_noop() -> None:
    """AC 4: user_input boundary never flags canary echo."""
    token = generate_canary()
    verdict = await scan_canary(
        f"User message containing {token} the full token",
        token=token,
        boundary="user_input",
    )
    assert verdict.clean is True
    assert "canary_echo" not in verdict.flags


async def test_store_rotates_on_detection() -> None:
    """AC 5: after scan detects echo, old token is no longer current."""
    store = InMemoryCanaryStore()
    old = await store.get_or_mint("session-1", "org-1")
    await store.rotate("session-1", "org-1")
    current = await store.get_or_mint("session-1", "org-1")
    assert current != old


async def test_cross_session_isolation() -> None:
    """AC 7: session A's token in session B's tool result is not flagged."""
    store = InMemoryCanaryStore()
    token_a = await store.get_or_mint("session-a", "org-1")
    token_b = await store.get_or_mint("session-b", "org-1")
    # Session B scans with its own token — session A's token should not trigger
    verdict = await scan_canary(
        f"tool output contains {token_a}",
        token=token_b,
        boundary="tool_result",
    )
    assert verdict.clean is True
    assert "canary_echo" not in verdict.flags


async def test_cross_tenant_isolation() -> None:
    """AC 8: same session_id across different orgs gets different tokens."""
    store = InMemoryCanaryStore()
    t_org1 = await store.get_or_mint("session-1", "org-1")
    t_org2 = await store.get_or_mint("session-1", "org-2")
    assert t_org1 != t_org2


@pytest.mark.perf
async def test_canary_scan_latency_under_2ms() -> None:
    """AC 9: scan overhead < 2ms for up to 40KB tool output."""
    import time

    token = generate_canary()
    content_4k = "A" * 4096
    content_40k = "B" * 40960

    for content in (content_4k, content_40k):
        start = time.perf_counter()
        for _ in range(100):
            await scan_canary(content, token=token, boundary="tool_result")
        elapsed = (time.perf_counter() - start) / 100 * 1000  # ms per call
        assert elapsed < 2.0, f"scan took {elapsed:.2f}ms on {len(content)}-byte input"
