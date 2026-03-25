"""Tests that Warden module has no dangerous imports."""

import importlib
import inspect


class TestWardenIsolation:
    def test_no_tool_imports(self) -> None:
        mod = importlib.import_module("stronghold.security.warden.detector")
        source = inspect.getsource(mod)
        assert "stronghold.tools" not in source
        assert "stronghold.skills" not in source

    def test_no_file_io_imports(self) -> None:
        mod = importlib.import_module("stronghold.security.warden.detector")
        source = inspect.getsource(mod)
        assert "open(" not in source
        assert "pathlib" not in source

    def test_scan_returns_verdict_only(self) -> None:
        from stronghold.security.warden.detector import Warden
        from stronghold.types.security import WardenVerdict

        warden = Warden()
        import asyncio

        verdict = asyncio.get_event_loop().run_until_complete(
            warden.scan("hello", "user_input"),
        )
        assert isinstance(verdict, WardenVerdict)
