"""Tests for specs/proactive-outbound.md."""

from __future__ import annotations

import pytest

from turing.self_outbound import (
    OUTBOUND_PRIORITY,
    OutboundMessage,
    create_outbound_payload,
    get_dispatch_counts,
    is_outbound_enabled,
    record_dispatch,
    validate_outbound,
)


@pytest.fixture(autouse=True)
def _reset_counts():
    from turing import self_outbound as mod

    mod._DISPATCH_COUNTS.clear()
    yield


def test_outbound_message_creation():
    msg = OutboundMessage(target_user_id="user-1", content="hello")
    assert msg.target_user_id == "user-1"
    assert msg.content == "hello"
    assert msg.conversation_id is None
    assert msg.title is None


def test_outbound_message_with_optional_fields():
    msg = OutboundMessage(
        target_user_id="user-1", content="hello", conversation_id="conv-1", title="Hey"
    )
    assert msg.conversation_id == "conv-1"
    assert msg.title == "Hey"


def test_create_payload_basic():
    msg = OutboundMessage(target_user_id="user-1", content="hello")
    payload = create_outbound_payload(msg)
    assert payload["target_user_id"] == "user-1"
    assert payload["content"] == "hello"
    assert payload["priority"] == OUTBOUND_PRIORITY
    assert "conversation_id" not in payload
    assert "title" not in payload


def test_create_payload_with_conversation():
    msg = OutboundMessage(target_user_id="user-1", content="hello", conversation_id="conv-1")
    payload = create_outbound_payload(msg)
    assert payload["conversation_id"] == "conv-1"


def test_create_payload_with_title():
    msg = OutboundMessage(target_user_id="user-1", content="hello", title="Check this")
    payload = create_outbound_payload(msg)
    assert payload["title"] == "Check this"


def test_validate_valid():
    msg = OutboundMessage(target_user_id="user-1", content="hello")
    assert validate_outbound(msg) == []


def test_validate_empty_target():
    msg = OutboundMessage(target_user_id="  ", content="hello")
    errors = validate_outbound(msg)
    assert len(errors) == 1
    assert "target_user_id" in errors[0]


def test_validate_empty_content():
    msg = OutboundMessage(target_user_id="user-1", content="  ")
    errors = validate_outbound(msg)
    assert len(errors) == 1
    assert "content" in errors[0]


def test_validate_both_empty():
    msg = OutboundMessage(target_user_id="", content="")
    errors = validate_outbound(msg)
    assert len(errors) == 2


def test_is_outbound_enabled_no_key(monkeypatch):
    monkeypatch.delenv("OPENWEBUI_API_KEY", raising=False)
    assert not is_outbound_enabled()


def test_is_outbound_enabled_with_key(monkeypatch):
    monkeypatch.setenv("OPENWEBUI_API_KEY", "test-key")
    assert is_outbound_enabled()


def test_record_dispatch_success():
    msg = OutboundMessage(target_user_id="user-1", content="hello")
    record_dispatch(msg, success=True)
    assert get_dispatch_counts()["success"] == 1


def test_record_dispatch_failure():
    msg = OutboundMessage(target_user_id="user-1", content="hello")
    record_dispatch(msg, success=False)
    assert get_dispatch_counts()["failed"] == 1


def test_record_dispatch_multiple():
    msg = OutboundMessage(target_user_id="user-1", content="hello")
    record_dispatch(msg, True)
    record_dispatch(msg, True)
    record_dispatch(msg, False)
    counts = get_dispatch_counts()
    assert counts["success"] == 2
    assert counts["failed"] == 1


def test_outbound_priority_is_25():
    assert OUTBOUND_PRIORITY == 25
