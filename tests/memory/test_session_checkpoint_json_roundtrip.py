"""Cross-side round-trip: client-written fixture ingests into server store (S1.3/S1.6)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from stronghold.memory.sessions.store import InMemoryCheckpointStore
from stronghold.types.memory import MemoryScope, SessionCheckpoint

FIXTURE = Path("tests/fixtures/checkpoint_sample.md")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Minimal YAML frontmatter parser (avoids adding a yaml dep at test time)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AssertionError("fixture missing frontmatter start marker")
    end = lines.index("---", 1)
    fm: dict[str, Any] = {}
    key: str | None = None
    for line in lines[1:end]:
        if not line.strip():
            continue
        if line.startswith("  - "):
            if key is None:
                raise AssertionError(f"stray list item: {line!r}")
            fm.setdefault(key, []).append(line[4:].strip())
        elif ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            key = k.strip()
            val = v.strip()
            fm[key] = val if val else []
    return fm


async def test_roundtrip_matches_client_fixture() -> None:
    """Client-written fixture decodes into a SessionCheckpoint and round-trips through the store."""
    assert FIXTURE.exists(), f"fixture missing: {FIXTURE}"
    fm = _parse_frontmatter(FIXTURE.read_text(encoding="utf-8"))

    cp = SessionCheckpoint(
        checkpoint_id=str(fm["checkpoint_id"]),
        session_id=str(fm["session_id"]),
        agent_id=fm.get("agent_id") or None,
        user_id=fm.get("user_id") or None,
        org_id=str(fm["org_id"]),
        team_id=fm.get("team_id") or None,
        scope=MemoryScope(fm["scope"]),
        branch=fm.get("branch") or None,
        summary=str(fm["summary"]),
        decisions=tuple(fm.get("decisions", ())),
        remaining=tuple(fm.get("remaining", ())),
        notes=tuple(fm.get("notes", ())),
        failed_approaches=tuple(fm.get("failed_approaches", ())),
        created_at=datetime.fromisoformat(str(fm["created_at"])),
        source=str(fm["source"]),  # type: ignore[arg-type]
    )

    # Server-side round-trip: save, then load, then compare.
    store = InMemoryCheckpointStore()
    cp_id = await store.save(cp)
    loaded = await store.load(cp_id, org_id=cp.org_id)

    assert loaded is not None
    assert loaded.summary == cp.summary
    assert loaded.branch == cp.branch
    assert loaded.decisions == cp.decisions
    assert loaded.source == "claude_code"
    # scope round-trips as the enum, not the string
    assert loaded.scope == MemoryScope.SESSION
