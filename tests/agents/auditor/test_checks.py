"""Tests for Auditor PR review checks.

Each check is a pure function operating on diff text — no I/O, no mocks.
"""

from __future__ import annotations

from stronghold.agents.auditor.checks import (
    check_architecture_update,
    check_bundled_changes,
    check_hardcoded_secrets,
    check_missing_tests,
    check_mock_usage,
    check_private_field_access,
    check_production_code_in_test_pr,
    check_protocol_compliance,
    check_type_annotations,
)
from stronghold.types.feedback import Severity, ViolationCategory


# ---------------------------------------------------------------------------
# check_mock_usage
# ---------------------------------------------------------------------------


class TestCheckMockUsage:
    """Mock usage detection in diff lines."""

    def test_detects_unittest_mock_import(self) -> None:
        diff = ["+from unittest.mock import MagicMock, patch"]
        findings = check_mock_usage(diff, file_path="tests/test_foo.py")
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.MOCK_USAGE
        assert findings[0].severity == Severity.HIGH

    def test_detects_async_mock(self) -> None:
        diff = ["+    mock = AsyncMock()"]
        findings = check_mock_usage(diff, file_path="tests/test_bar.py")
        assert len(findings) == 1

    def test_detects_patch_decorator(self) -> None:
        diff = ["+    @patch('some.module.func')"]
        findings = check_mock_usage(diff, file_path="tests/test_baz.py")
        assert len(findings) == 1

    def test_detects_with_patch(self) -> None:
        diff = ['+    with patch("module.sleep", new_callable=AsyncMock):']
        findings = check_mock_usage(diff, file_path="tests/test_qux.py")
        assert len(findings) == 1

    def test_ignores_non_added_lines(self) -> None:
        diff = ["-from unittest.mock import MagicMock", " import os"]
        findings = check_mock_usage(diff, file_path="tests/test_foo.py")
        assert len(findings) == 0

    def test_no_false_positive_on_clean_code(self) -> None:
        diff = ["+from tests.fakes import FakeLLMClient", "+client = FakeLLMClient()"]
        findings = check_mock_usage(diff, file_path="tests/test_foo.py")
        assert len(findings) == 0

    def test_one_finding_per_line(self) -> None:
        # Line contains both MagicMock and AsyncMock — still one finding
        diff = ["+mock = MagicMock() if sync else AsyncMock()"]
        findings = check_mock_usage(diff, file_path="tests/test_foo.py")
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# check_architecture_update
# ---------------------------------------------------------------------------


class TestCheckArchitectureUpdate:
    """Architecture compliance: new modules need ARCHITECTURE.md updates."""

    def test_new_module_without_arch_update(self) -> None:
        files = ["src/stronghold/scheduling/__init__.py", "src/stronghold/scheduling/store.py"]
        findings = check_architecture_update(files)
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.ARCHITECTURE_UPDATE

    def test_new_module_with_arch_update(self) -> None:
        files = [
            "src/stronghold/scheduling/__init__.py",
            "src/stronghold/scheduling/store.py",
            "ARCHITECTURE.md",
        ]
        findings = check_architecture_update(files)
        assert len(findings) == 0

    def test_no_new_module(self) -> None:
        files = ["src/stronghold/router/scorer.py", "tests/routing/test_scorer.py"]
        findings = check_architecture_update(files)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# check_protocol_compliance
# ---------------------------------------------------------------------------


class TestCheckProtocolCompliance:
    """New modules should have corresponding protocols."""

    def test_new_module_without_protocol(self) -> None:
        files = ["src/stronghold/marketplace/__init__.py", "src/stronghold/marketplace/agents.py"]
        findings = check_protocol_compliance(files)
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.PROTOCOL_MISSING

    def test_new_module_with_protocol(self) -> None:
        files = [
            "src/stronghold/marketplace/__init__.py",
            "src/stronghold/protocols/marketplace.py",
        ]
        findings = check_protocol_compliance(files)
        assert len(findings) == 0

    def test_protocol_dir_change_exempt(self) -> None:
        files = ["src/stronghold/protocols/__init__.py"]
        findings = check_protocol_compliance(files)
        assert len(findings) == 0

    def test_types_dir_exempt(self) -> None:
        files = ["src/stronghold/types/__init__.py", "src/stronghold/types/feedback.py"]
        findings = check_protocol_compliance(files)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# check_production_code_in_test_pr
# ---------------------------------------------------------------------------


class TestCheckProductionCodeInTestPR:
    """Test PRs must not modify src/."""

    def test_test_pr_modifying_src(self) -> None:
        files = ["src/stronghold/container.py", "tests/test_container.py"]
        findings = check_production_code_in_test_pr(files, is_test_pr=True)
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.PRODUCTION_CODE_IN_TEST

    def test_test_pr_only_tests(self) -> None:
        files = ["tests/security/test_warden.py", "tests/conftest.py"]
        findings = check_production_code_in_test_pr(files, is_test_pr=True)
        assert len(findings) == 0

    def test_feature_pr_can_modify_src(self) -> None:
        files = ["src/stronghold/router/scorer.py"]
        findings = check_production_code_in_test_pr(files, is_test_pr=False)
        assert len(findings) == 0

    def test_fakes_exempt(self) -> None:
        files = ["tests/fakes.py"]
        findings = check_production_code_in_test_pr(files, is_test_pr=True)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# check_type_annotations
# ---------------------------------------------------------------------------


class TestCheckTypeAnnotations:
    """Any usage in business logic is flagged."""

    def test_any_in_return_type(self) -> None:
        diff = ["+    async def fetch(self) -> Any:"]
        findings = check_type_annotations(diff, file_path="src/stronghold/api/routes.py")
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.TYPE_ANNOTATIONS

    def test_any_in_parameter(self) -> None:
        diff = ["+    def process(self, data: Any) -> None:"]
        findings = check_type_annotations(diff, file_path="src/stronghold/agents/base.py")
        assert len(findings) == 1

    def test_any_in_test_code_exempt(self) -> None:
        diff = ["+    def process(self, data: Any) -> None:"]
        findings = check_type_annotations(diff, file_path="tests/test_base.py")
        assert len(findings) == 0

    def test_noqa_exempt(self) -> None:
        diff = ["+    def walk(self, node: Any) -> None:  # noqa: ANN401"]
        findings = check_type_annotations(diff, file_path="src/stronghold/security/normalize.py")
        assert len(findings) == 0

    def test_type_checking_guard_exempt(self) -> None:
        diff = ["+    if TYPE_CHECKING:"]
        findings = check_type_annotations(diff, file_path="src/stronghold/container.py")
        assert len(findings) == 0

    def test_clean_code_no_findings(self) -> None:
        diff = ["+    def process(self, data: dict[str, str]) -> list[int]:"]
        findings = check_type_annotations(diff, file_path="src/stronghold/router/scorer.py")
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# check_hardcoded_secrets
# ---------------------------------------------------------------------------


class TestCheckHardcodedSecrets:
    """Detect hardcoded secrets in production code."""

    def test_detects_api_key(self) -> None:
        diff = ['+API_KEY = "sk-1234567890abcdefghijklmnopqrst"']
        findings = check_hardcoded_secrets(diff, file_path="src/stronghold/config/loader.py")
        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL

    def test_detects_aws_key(self) -> None:
        diff = ["+aws_key = 'AKIAIOSFODNN7EXAMPLE'"]
        findings = check_hardcoded_secrets(diff, file_path="src/stronghold/config/secrets.py")
        assert len(findings) == 1

    def test_test_code_exempt(self) -> None:
        diff = ['+API_KEY = "sk-1234567890abcdefghijklmnopqrst"']
        findings = check_hardcoded_secrets(diff, file_path="tests/test_auth.py")
        assert len(findings) == 0

    def test_short_values_ok(self) -> None:
        diff = ['+token = "short"']
        findings = check_hardcoded_secrets(diff, file_path="src/stronghold/api/app.py")
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# check_missing_tests
# ---------------------------------------------------------------------------


class TestCheckMissingTests:
    """Feature PRs must include tests."""

    def test_src_changes_without_tests(self) -> None:
        files = ["src/stronghold/router/scorer.py"]
        findings = check_missing_tests(files, is_test_pr=False)
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.MISSING_TESTS

    def test_src_changes_with_tests(self) -> None:
        files = ["src/stronghold/router/scorer.py", "tests/routing/test_scorer.py"]
        findings = check_missing_tests(files, is_test_pr=False)
        assert len(findings) == 0

    def test_test_pr_exempt(self) -> None:
        files = ["tests/routing/test_scorer.py"]
        findings = check_missing_tests(files, is_test_pr=True)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# check_private_field_access
# ---------------------------------------------------------------------------


class TestCheckPrivateFieldAccess:
    """Flag _private field access on external objects in production code."""

    def test_detects_store_private_access(self) -> None:
        diff = ["+        entries = self._store._memories"]
        findings = check_private_field_access(
            diff, file_path="src/stronghold/memory/management.py"
        )
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.PRIVATE_FIELD_ACCESS

    def test_self_private_access_ok(self) -> None:
        diff = ["+        self._cache = {}"]
        findings = check_private_field_access(diff, file_path="src/stronghold/agents/cache.py")
        assert len(findings) == 0

    def test_test_code_exempt(self) -> None:
        diff = ["+        store._memories.clear()"]
        findings = check_private_field_access(diff, file_path="tests/test_store.py")
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# check_bundled_changes
# ---------------------------------------------------------------------------


class TestCheckBundledChanges:
    """Flag PRs touching too many distinct modules."""

    def test_many_modules_flagged(self) -> None:
        files = [
            "src/stronghold/agents/base.py",
            "src/stronghold/security/warden/detector.py",
            "src/stronghold/router/scorer.py",
            "src/stronghold/memory/learnings/store.py",
            "src/stronghold/api/routes/chat.py",
        ]
        findings = check_bundled_changes(files, commit_count=1)
        assert len(findings) == 1
        assert findings[0].category == ViolationCategory.BUNDLED_CHANGES

    def test_focused_pr_ok(self) -> None:
        files = [
            "src/stronghold/security/warden/detector.py",
            "src/stronghold/security/warden/patterns.py",
            "tests/security/test_warden.py",
        ]
        findings = check_bundled_changes(files, commit_count=1)
        assert len(findings) == 0
