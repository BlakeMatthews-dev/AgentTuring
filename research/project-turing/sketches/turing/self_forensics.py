"""Forensic tagging context managers for self-writes. See specs/forensic-tagging.md.

Two ContextVars — request_hash and perception_tool_call_id — set at request
pipeline boundaries and read by the memory-mirroring bridge to stamp every
mirror memory's context dict with provenance information.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_request_hash_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_hash", default=None
)
_perception_tool_call_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "perception_tool_call_id", default=None
)


def get_request_hash() -> str | None:
    return _request_hash_var.get()


def get_perception_tool_call_id() -> str | None:
    return _perception_tool_call_id_var.get()


@contextmanager
def request_scope(request_hash: str) -> Iterator[None]:
    if _request_hash_var.get() is not None:
        raise RuntimeError("nested request_scope is forbidden")
    token = _request_hash_var.set(request_hash)
    try:
        yield
    finally:
        _request_hash_var.reset(token)


@contextmanager
def tool_call_scope(tool_call_id: str) -> Iterator[None]:
    token = _perception_tool_call_id_var.set(tool_call_id)
    try:
        yield
    finally:
        _perception_tool_call_id_var.reset(token)
