"""Tests for specs/self-tool-import-firewall.md: AC-49.1..16."""

from __future__ import annotations

import os
import sys

import pytest

from turing.self_import_firewall import (
    ForbiddenImport,
    SelfToolImportFirewall,
    get_blocked_counts,
    install_firewall,
    uninstall_firewall,
)


class TestInstallUninstall:
    def test_install_adds_to_meta_path(self) -> None:
        fw = install_firewall()
        assert fw in sys.meta_path
        assert sys.meta_path[0] is fw
        uninstall_firewall(fw)

    def test_install_at_position_zero(self) -> None:
        fw = install_firewall()
        assert sys.meta_path[0] is fw
        uninstall_firewall(fw)

    def test_uninstall_removes_from_meta_path(self) -> None:
        fw = install_firewall()
        uninstall_firewall(fw)
        assert fw not in sys.meta_path

    def test_uninstall_idempotent(self) -> None:
        fw = install_firewall()
        uninstall_firewall(fw)
        uninstall_firewall(fw)

    def test_not_installed_by_default(self) -> None:
        firewalls = [x for x in sys.meta_path if isinstance(x, SelfToolImportFirewall)]
        assert len(firewalls) == 0


class TestForbiddenImport:
    def test_carries_fields(self) -> None:
        exc = ForbiddenImport("turing.chat", "turing.self_tool_registry", "import firewall")
        assert exc.calling_module == "turing.chat"
        assert exc.target_name == "turing.self_tool_registry"
        assert exc.rule == "import firewall"
        assert "blocked by" in str(exc)

    def test_is_import_error(self) -> None:
        exc = ForbiddenImport("a", "b", "r")
        assert isinstance(exc, ImportError)


class TestNonProtectedImports:
    def test_other_turing_imports_pass(self) -> None:
        fw = install_firewall()
        try:
            import turing.types

            assert turing.types is not None
        finally:
            uninstall_firewall(fw)

    def test_unrelated_import_passes(self) -> None:
        fw = install_firewall()
        try:
            import json

            assert json is not None
        finally:
            uninstall_firewall(fw)


class TestAllowEnvOverride:
    def test_env_override_allows_blocked_caller(self, monkeypatch) -> None:
        monkeypatch.setenv("TURING_ALLOW_SELF_IMPORTS", "tests.test_self_import_firewall")
        fw = install_firewall()
        try:
            spec = fw.find_spec("turing.self_tool_registry", None, None)
            assert spec is None
        finally:
            uninstall_firewall(fw)

    def test_empty_env_blocks(self, monkeypatch) -> None:
        monkeypatch.setenv("TURING_ALLOW_SELF_IMPORTS", "")
        fw = install_firewall()
        try:
            monkeypatch.setattr(
                "turing.self_import_firewall._get_caller_module",
                lambda: "turing.chat",
            )
            with pytest.raises(ForbiddenImport):
                fw.find_spec("turing.self_tool_registry", None, None)
        finally:
            uninstall_firewall(fw)


class TestBlockedCounts:
    def test_counter_increments(self, monkeypatch) -> None:
        from turing import self_import_firewall as fw_mod

        monkeypatch.setattr(fw_mod, "_get_caller_module", lambda: "turing.evil_caller")
        fw = install_firewall()
        try:
            with pytest.raises(ForbiddenImport):
                fw.find_spec("turing.self_tool_registry", None, None)
            after = get_blocked_counts().get(("turing.evil_caller", "turing.self_tool_registry"), 0)
            assert after >= 1
        finally:
            uninstall_firewall(fw)
