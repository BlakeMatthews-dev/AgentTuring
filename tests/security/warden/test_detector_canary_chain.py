"""Tests for canary layer integration in the Warden detector chain (S1.1)."""

from __future__ import annotations

from stronghold.security.warden.detector import Warden
from tests.fakes import InMemoryCanaryStore


async def test_canary_layer_runs_before_heuristics() -> None:
    """Canary check occurs before heuristic layer in the scan chain."""
    store = InMemoryCanaryStore()
    token = await store.get_or_mint("sess-chain", "org-1")

    warden = Warden()
    # Pure canary echo — no heuristic patterns present
    verdict = await warden.scan(
        f"tool result: {token}",
        boundary="tool_result",
        canary_token=token,
    )
    assert verdict.clean is False
    assert "canary_echo" in verdict.flags


async def test_canary_short_circuits_remaining_layers() -> None:
    """Detection at canary layer stops evaluation (no further layers run)."""
    store = InMemoryCanaryStore()
    token = await store.get_or_mint("sess-short", "org-1")

    # Patch heuristic_scan to detect if it runs
    from stronghold.security.warden import heuristics

    original_heuristic_scan = heuristics.heuristic_scan
    heuristic_called = []

    def patched_heuristic_scan(text: str) -> tuple[bool, list[str]]:
        heuristic_called.append(True)
        return original_heuristic_scan(text)

    heuristics.heuristic_scan = patched_heuristic_scan
    try:
        warden = Warden()
        await warden.scan(
            f"output: {token}",
            boundary="tool_result",
            canary_token=token,
        )
    finally:
        heuristics.heuristic_scan = original_heuristic_scan

    assert not heuristic_called, "Heuristic scan should not run after canary detection"
