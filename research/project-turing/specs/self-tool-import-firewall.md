# Spec 49 — Self-tool runtime import firewall (G18)

*Block imports of the self-tool registry from non-self modules via an `importlib` meta-path finder. Closes F21.*

**Depends on:** [self-tool-registry.md](./self-tool-registry.md).
**Depended on by:** —

---

## Current state

Spec 28 AC-28.22/23 state self-tools are t0 and NOT routable. The sketch relies on convention — specialist modules don't import `SELF_TOOL_REGISTRY` because they're not expected to. Nothing enforces the boundary structurally.

## Target

An `importlib.abc.MetaPathFinder` installed at process start that inspects import statements. An import of `turing.self_surface.SELF_TOOL_REGISTRY` (or direct access via `turing.self_surface`) from code outside the `turing.self_*` module family raises `ForbiddenImport`.

## Acceptance criteria

### Finder installation

- **AC-49.1.** `SelfToolImportFirewall` is an `importlib.abc.MetaPathFinder`. Installed by `SelfRuntime.__init__()`; uninstalled by `SelfRuntime.close()`. Test install/uninstall cycle.
- **AC-49.2.** Installed at `sys.meta_path[0]` (first priority) so it sees all imports. Test.

### Permission rules

- **AC-49.3.** Imports originating from a module whose dotted name starts with `turing.self_` OR `turing.self_surface` itself (self-referential) OR `turing.self_conduit` OR `turing.self_runtime` are allowed. Test each.
- **AC-49.4.** Imports from `turing.tests.*`, `turing.daydream`, `turing.dreaming`, `turing.chat`, `turing.scheduler`, etc. that try to `from turing.self_surface import SELF_TOOL_REGISTRY` or `from turing.self_tool_registry import ...` raise `ForbiddenImport`. Test one allowed-self module and one blocked-non-self module.
- **AC-49.5.** `import turing.self_surface` followed by attribute access `turing.self_surface.SELF_TOOL_REGISTRY` from a blocked module is also prevented via an `__getattr__` guard on the `self_surface` module. Test.

### Exception shape

- **AC-49.6.** `ForbiddenImport` carries `(calling_module, target_name, rule)`. Test.
- **AC-49.7.** The exception is raised at import time, not at use time — i.e., `from turing.self_surface import SELF_TOOL_REGISTRY` fails on the `from import` line. Test.

### Allow-list override

- **AC-49.8.** Environment variable `TURING_ALLOW_SELF_IMPORTS=module.name,other.module` adds permitted caller modules. Intended for audit tooling (`stronghold self digest`, inspect CLI). Test.
- **AC-49.9.** Production `CONDUIT_MODE = "self"` startup logs a warning if `TURING_ALLOW_SELF_IMPORTS` is non-empty. Test.

### Test-time behavior

- **AC-49.10.** Existing test modules (`turing/tests/test_*.py`) that legitimately need to import self-tool internals go through `SelfRuntime` (they instantiate a runtime and call `runtime.invoke(...)`) rather than importing the registry directly. Tests that currently import `SELF_TOOL_REGISTRY` are updated to go through the runtime. Test.
- **AC-49.11.** `pytest` imports the firewall lazily — the firewall is only installed when a `SelfRuntime` is instantiated. Tests that don't need the firewall don't pay for it. Test.

### Observability

- **AC-49.12.** Counter `turing_forbidden_import_total{caller, target}` increments on each block. Test.
- **AC-49.13.** Startup log lists currently-allowed caller-module patterns. Test.

### Edge cases

- **AC-49.14.** A `__class__` / `__dict__` reflection attack that walks `sys.modules['turing.self_surface']` bypasses the import hook but hits the module-level `__getattr__` guard (AC-49.5). Test.
- **AC-49.15.** Uninstall on shutdown is idempotent (safe to call twice). Test.
- **AC-49.16.** The firewall does not block imports that are not about self-tools; other `turing.*` imports flow normally. Test a specialist module importing `turing.daydream`.

## Implementation

```python
# self_import_firewall.py

_ALLOWED_CALLER_PREFIXES = (
    "turing.self_",
    "turing.self_surface",
    "turing.self_conduit",
    "turing.self_runtime",
)
_PROTECTED_TARGETS = {
    "turing.self_surface": {"SELF_TOOL_REGISTRY"},
    "turing.self_tool_registry": {"SELF_TOOL_REGISTRY", "SelfTool", "register_self_tool"},
}


class ForbiddenImport(ImportError):
    def __init__(self, calling_module: str, target_name: str, rule: str):
        self.calling_module = calling_module
        self.target_name = target_name
        self.rule = rule
        super().__init__(
            f"{calling_module} tried to import {target_name} "
            f"(blocked by {rule})"
        )


class SelfToolImportFirewall(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name not in _PROTECTED_TARGETS:
            return None
        caller = _find_caller_module()
        if caller is None or _is_allowed(caller):
            return None
        raise ForbiddenImport(caller, name, "import firewall")


def _is_allowed(caller: str) -> bool:
    if caller.startswith(_ALLOWED_CALLER_PREFIXES):
        return True
    extra = os.environ.get("TURING_ALLOW_SELF_IMPORTS", "").split(",")
    return caller in {e.strip() for e in extra if e.strip()}


# turing/self_surface.py

def __getattr__(name: str):
    if name == "SELF_TOOL_REGISTRY":
        caller = _find_caller_module()
        if caller is not None and not _is_allowed(caller):
            raise ForbiddenImport(caller, "SELF_TOOL_REGISTRY", "module getattr")
    raise AttributeError(name)
```

## Open questions

- **Q49.1.** Frame-walking to find the caller is fragile under PEP-667 and async contexts. Alternative: lexical-scope hint via a decorator on allowed modules. Fragile-but-sufficient for research.
- **Q49.2.** `TURING_ALLOW_SELF_IMPORTS` is per-process. A safer shape is "allow-list committed to code, not env" — reduces exfil-by-env-var risk.
- **Q49.3.** The firewall blocks imports. It does not block duck-typing (e.g., `getattr(sys.modules['turing.self_surface'], 'SELF_TOOL_REGISTRY')`). The `__getattr__` module guard catches this for attribute access; direct `__dict__` access still works. A determined attacker inside the process can always get there — this defends against accidental imports, not malicious introspection.
