"""Tests for agent-level access control (migration 012)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from stronghold.security.access_control import check_agent_access, is_agent_visible
from stronghold.types.auth import AuthContext, IdentityKind


def _auth(
    user_id: str = "anon",
    kind: IdentityKind = IdentityKind.USER,
    org_id: str = "org-1",
) -> AuthContext:
    return AuthContext(
        user_id=user_id, username=user_id, roles=frozenset(),
        org_id=org_id, team_id="", kind=kind, auth_method="test",
    )


def test_public_agent_allows_any_user():
    check_agent_access("ranger", "public", {}, _auth("random-user"))


def test_restricted_empty_grant_denies_all():
    with pytest.raises(HTTPException) as exc_info:
        check_agent_access("ranger-elite", "restricted", {}, _auth("random-user"))
    assert exc_info.value.status_code == 403


def test_restricted_user_in_grant_allowed():
    check_agent_access("ranger-elite", "restricted", {"users": ["scott"]}, _auth("scott"))


def test_restricted_service_account_in_grant_allowed():
    check_agent_access(
        "ranger-elite", "restricted",
        {"service_accounts": ["coinswarm-svc"]},
        _auth("coinswarm-svc", kind=IdentityKind.SERVICE_ACCOUNT),
    )


def test_restricted_wrong_user_denied():
    with pytest.raises(HTTPException):
        check_agent_access("ranger-elite", "restricted", {"users": ["scott"]}, _auth("hacker"))


def test_restricted_system_always_allowed():
    check_agent_access("ranger-elite", "restricted", {}, _auth("system", kind=IdentityKind.SYSTEM))


def test_restricted_org_in_grant_allowed():
    check_agent_access("ranger-elite", "restricted", {"orgs": ["trusted-corp"]}, _auth("x", org_id="trusted-corp"))


def test_restricted_wrong_org_denied():
    with pytest.raises(HTTPException):
        check_agent_access("ranger-elite", "restricted", {"orgs": ["trusted-corp"]}, _auth("x", org_id="untrusted"))


def test_public_visible_to_all():
    assert is_agent_visible("public", {}, _auth("anyone")) is True


def test_restricted_hidden_from_non_allowlisted():
    assert is_agent_visible("restricted", {"users": ["scott"]}, _auth("hacker")) is False


def test_restricted_visible_to_allowlisted():
    assert is_agent_visible("restricted", {"users": ["scott"]}, _auth("scott")) is True


def test_restricted_visible_to_system():
    assert is_agent_visible("restricted", {}, _auth("system", kind=IdentityKind.SYSTEM)) is True
