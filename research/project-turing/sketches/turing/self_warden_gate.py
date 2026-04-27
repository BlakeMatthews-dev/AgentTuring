"""Warden gate for self-authored writes. See specs/warden-on-self-writes.md.

Every text the self writes into its own model passes through this gate
before persistence. Rejection raises SelfWriteBlocked and writes an
OBSERVATION memory describing the block.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WardenVerdict:
    status: str
    reason: str = ""
    verdict_id: str = ""


class SelfWriteBlocked(Exception):
    def __init__(self, verdict: WardenVerdict) -> None:
        self.verdict = verdict
        super().__init__(f"self-write blocked: {verdict.reason}")


class WardenUnavailable(Exception):
    pass


_BLOCKED_INTENTS: dict[str, int] = {}


def get_blocked_counts() -> dict[str, int]:
    return dict(_BLOCKED_INTENTS)


def _record_block(intent: str, self_id: str) -> None:
    key = f"{intent}:{self_id}"
    _BLOCKED_INTENTS[key] = _BLOCKED_INTENTS.get(key, 0) + 1


def warden_gate_self_write(
    text: str,
    intent: str,
    *,
    self_id: str,
    scan_fn=None,
    mirror_fn=None,
) -> None:
    if scan_fn is None:
        return
    truncated = text[:10_000]
    try:
        verdict = scan_fn(truncated)
    except Exception as exc:
        verdict = WardenVerdict(
            status="blocked",
            reason=f"warden unavailable: {exc}",
            verdict_id="unavailable",
        )
    if verdict.status == "blocked":
        if mirror_fn is not None:
            mirror_fn(
                self_id=self_id,
                content=f"warden blocked self-write ({intent}): {verdict.reason}",
                intent_at_time="warden blocked self write",
                context={
                    "verdict_id": verdict.verdict_id,
                    "tool_name": intent,
                    "preview": text[:80],
                },
            )
        _record_block(intent, self_id)
        raise SelfWriteBlocked(verdict)
