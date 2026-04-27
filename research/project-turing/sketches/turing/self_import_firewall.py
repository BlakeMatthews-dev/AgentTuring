"""Self-tool runtime import firewall. See specs/self-tool-import-firewall.md.

Blocks imports of SELF_TOOL_REGISTRY from non-self modules via an
importlib.abc.MetaPathFinder. Prevents accidental cross-boundary access.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys
import threading
from types import ModuleType


_BLOCKED_CALLS: dict[tuple[str, str], int] = {}
_block_lock = threading.Lock()


class ForbiddenImport(ImportError):
    def __init__(self, calling_module: str, target_name: str, rule: str):
        self.calling_module = calling_module
        self.target_name = target_name
        self.rule = rule
        super().__init__(f"{calling_module} tried to import {target_name} (blocked by {rule})")


_ALLOWED_CALLER_PREFIXES = (
    "turing.self_",
    "turing.self_surface",
    "turing.self_conduit",
    "turing.self_runtime",
)

_PROTECTED_MODULES = frozenset(
    {
        "turing.self_tool_registry",
    }
)

_PROTECTED_ATTRS = frozenset(
    {
        "SELF_TOOL_REGISTRY",
        "SelfTool",
        "register_self_tool",
    }
)


def _get_caller_module() -> str | None:
    frame = sys._getframe(2)
    return frame.f_globals.get("__name__")


def _is_allowed(caller: str) -> bool:
    if any(caller.startswith(p) for p in _ALLOWED_CALLER_PREFIXES):
        return True
    extra_raw = os.environ.get("TURING_ALLOW_SELF_IMPORTS", "")
    extra = {e.strip() for e in extra_raw.split(",") if e.strip()}
    return caller in extra


def _record_block(caller: str, target: str) -> None:
    with _block_lock:
        key = (caller, target)
        _BLOCKED_CALLS[key] = _BLOCKED_CALLS.get(key, 0) + 1


def get_blocked_counts() -> dict[tuple[str, str], int]:
    with _block_lock:
        return dict(_BLOCKED_CALLS)


class SelfToolImportFirewall(importlib.abc.MetaPathFinder):
    def find_module(self, fullname: str, path=None):
        if fullname not in _PROTECTED_MODULES:
            return None
        caller = _get_caller_module()
        if caller is None or _is_allowed(caller):
            return None
        _record_block(caller, fullname)
        raise ForbiddenImport(caller, fullname, "import firewall")

    def find_spec(self, fullname, path, target=None):
        if fullname not in _PROTECTED_MODULES:
            return None
        caller = _get_caller_module()
        if caller is None or _is_allowed(caller):
            return None
        _record_block(caller, fullname)
        raise ForbiddenImport(caller, fullname, "import firewall")


def install_firewall() -> SelfToolImportFirewall:
    fw = SelfToolImportFirewall()
    sys.meta_path.insert(0, fw)
    return fw


def uninstall_firewall(fw: SelfToolImportFirewall) -> None:
    try:
        sys.meta_path.remove(fw)
    except ValueError:
        pass
