"""Make `turing` importable from the sketches directory."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SKETCHES = Path(__file__).resolve().parent.parent
if str(_SKETCHES) not in sys.path:
    sys.path.insert(0, str(_SKETCHES))

from turing.repo import Repo  # noqa: E402
from turing.self_identity import bootstrap_self_id  # noqa: E402


@pytest.fixture
def repo() -> Repo:
    return Repo(None)


@pytest.fixture
def self_id(repo: Repo) -> str:
    return bootstrap_self_id(repo.conn)
