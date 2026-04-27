"""Tests for specs/bootstrap-seed-registry.md: AC-48.6..8."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_signing import (
    BootstrapTamperDetected,
    SeedReused,
    check_bootstrap_signature,
    sign_bootstrap,
    verify_bootstrap_signature,
)


_NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
_SID = "self:abc123"


# --------- AC-48.6 sign + verify roundtrip -----------------------------------


def test_ac_48_6_sign_verify_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-key-123")
    sig = sign_bootstrap(_SID, seed=42, created_at=_NOW, content="hello")
    assert isinstance(sig, str)
    assert len(sig) == 64
    assert verify_bootstrap_signature(
        _SID, seed=42, created_at=_NOW, content="hello", signature=sig
    )


# --------- AC-48.7 tampered content fails ------------------------------------


def test_ac_48_7_tampered_content_returns_false(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-key-123")
    sig = sign_bootstrap(_SID, seed=42, created_at=_NOW, content="original")
    assert not verify_bootstrap_signature(
        _SID, seed=42, created_at=_NOW, content="tampered", signature=sig
    )


def test_ac_48_7_tampered_content_raises(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-key-123")
    sig = sign_bootstrap(_SID, seed=42, created_at=_NOW, content="original")
    with pytest.raises(BootstrapTamperDetected) as exc_info:
        check_bootstrap_signature(_SID, seed=42, created_at=_NOW, content="tampered", signature=sig)
    assert exc_info.value.self_id == _SID


# --------- AC-48.8 wrong key fails -------------------------------------------


def test_ac_48_8_wrong_key_verification_fails(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-key-123")
    sig = sign_bootstrap(_SID, seed=42, created_at=_NOW, content="hello")
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "different-key-456")
    assert not verify_bootstrap_signature(
        _SID, seed=42, created_at=_NOW, content="hello", signature=sig
    )


def test_ac_48_8_wrong_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-key-123")
    sig = sign_bootstrap(_SID, seed=42, created_at=_NOW, content="hello")
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "different-key-456")
    with pytest.raises(BootstrapTamperDetected):
        check_bootstrap_signature(_SID, seed=42, created_at=_NOW, content="hello", signature=sig)


# --------- missing env var ---------------------------------------------------


def test_missing_env_var_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.delenv("OPERATOR_SIGNING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPERATOR_SIGNING_KEY"):
        sign_bootstrap(_SID, seed=1, created_at=_NOW, content="x")


# --------- edge case: seed 0 is legal ----------------------------------------


def test_seed_zero_is_legal(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-key-123")
    sig = sign_bootstrap(_SID, seed=0, created_at=_NOW, content="boot")
    assert verify_bootstrap_signature(_SID, seed=0, created_at=_NOW, content="boot", signature=sig)


# --------- different self_id fails -------------------------------------------


def test_different_self_id_fails(monkeypatch) -> None:
    monkeypatch.setenv("OPERATOR_SIGNING_KEY", "test-key-123")
    sig = sign_bootstrap(_SID, seed=42, created_at=_NOW, content="hello")
    assert not verify_bootstrap_signature(
        "self:other", seed=42, created_at=_NOW, content="hello", signature=sig
    )


# --------- SeedReused exception attributes -----------------------------------


def test_seed_reused_exception_carries_fields() -> None:
    exc = SeedReused(seed=7, existing_self_id="self:xyz")
    assert exc.seed == 7
    assert exc.existing_self_id == "self:xyz"
    assert "7" in str(exc)
    assert "self:xyz" in str(exc)


# --------- BootstrapTamperDetected exception attributes -----------------------


def test_bootstrap_tamper_exception_carries_self_id() -> None:
    exc = BootstrapTamperDetected(_SID)
    assert exc.self_id == _SID
    assert _SID in str(exc)
