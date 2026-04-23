"""Tests for SandboxTemplates.

Spec: Template registry for sandbox environments with validation.
AC: 4 default templates registered, register/get/list/list_by_runtime work,
    validate_template checks security constraints, get_security_rules returns rules.
Edge cases: unknown template returns None, validation rejects insecure configs,
            duplicate registration overwrites, empty rules for unknown template.
Contracts: get_template returns SandboxTemplate|None, list_templates returns list,
           validate_template returns bool.
"""

from __future__ import annotations

from stronghold.sandbox.templates import SandboxTemplate, SandboxTemplates


class TestDefaultTemplates:
    def test_four_defaults_registered(self) -> None:
        st = SandboxTemplates()
        templates = st.list_templates()
        assert len(templates) == 4

    def test_python_isolated(self) -> None:
        st = SandboxTemplates()
        t = st.get_template("python-isolated")
        assert t is not None
        assert t.runtime == "python:3.13"
        assert t.network_access is False

    def test_javascript_isolated(self) -> None:
        st = SandboxTemplates()
        t = st.get_template("javascript-isolated")
        assert t is not None
        assert t.runtime == "node:20"

    def test_browser_playwright(self) -> None:
        st = SandboxTemplates()
        t = st.get_template("browser-playwright")
        assert t is not None
        assert t.memory_limit == "512Mi"
        assert t.cpu_limit == "1.0"
        assert t.filesystem_access == "read-only"

    def test_shell_restricted(self) -> None:
        st = SandboxTemplates()
        t = st.get_template("shell-restricted")
        assert t is not None
        assert t.memory_limit == "128Mi"
        assert t.filesystem_access == "read-only"


class TestGetTemplate:
    def test_unknown_returns_none(self) -> None:
        st = SandboxTemplates()
        assert st.get_template("nonexistent") is None


class TestRegisterTemplate:
    def test_register_and_retrieve(self) -> None:
        st = SandboxTemplates()
        custom = SandboxTemplate(name="custom", runtime="python:3.12", description="test")
        st.register_template(custom)
        assert st.get_template("custom") is not None
        assert st.get_template("custom").runtime == "python:3.12"

    def test_overwrite_existing(self) -> None:
        st = SandboxTemplates()
        t1 = SandboxTemplate(name="x", runtime="python:3.11", description="v1")
        t2 = SandboxTemplate(name="x", runtime="python:3.13", description="v2")
        st.register_template(t1)
        st.register_template(t2)
        assert st.get_template("x").description == "v2"


class TestListByRuntime:
    def test_filters_by_runtime(self) -> None:
        st = SandboxTemplates()
        python_templates = st.list_by_runtime("python:3.13")
        assert len(python_templates) == 1
        assert python_templates[0].name == "python-isolated"

    def test_no_match_returns_empty(self) -> None:
        st = SandboxTemplates()
        assert st.list_by_runtime("rust:1.70") == []


class TestGetSecurityRules:
    def test_known_template_returns_rules(self) -> None:
        st = SandboxTemplates()
        rules = st.get_security_rules_for_template("python-isolated")
        assert isinstance(rules, list)

    def test_unknown_template_returns_empty(self) -> None:
        st = SandboxTemplates()
        assert st.get_security_rules_for_template("nonexistent") == []


class TestValidateTemplate:
    def test_network_access_write_fs_passes(self) -> None:
        st = SandboxTemplates()
        t = SandboxTemplate(
            name="test",
            runtime="python:3.13",
            description="test",
            network_access=True,
            filesystem_access="write",
        )
        assert st.validate_template(t) is True

    def test_host_access_fails(self) -> None:
        st = SandboxTemplates()
        t = SandboxTemplate(
            name="test", runtime="python:3.13", description="test", host_access=True
        )
        assert st.validate_template(t) is False

    def test_no_network_no_fs_fails(self) -> None:
        st = SandboxTemplates()
        t = SandboxTemplate(
            name="test",
            runtime="python:3.13",
            description="test",
            network_access=False,
            filesystem_access="none",
        )
        assert st.validate_template(t) is False

    def test_valid_memory_limit(self) -> None:
        st = SandboxTemplates()
        t = SandboxTemplate(
            name="test",
            runtime="python:3.13",
            description="test",
            network_access=True,
            filesystem_access="write",
            memory_limit="1024Mi",
        )
        assert st.validate_template(t) is True
