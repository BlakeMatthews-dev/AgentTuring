"""Proactive outbound messaging via OpenWebUI. See specs/proactive-outbound.md."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class OutboundMessage:
    target_user_id: str
    content: str
    conversation_id: str | None = None
    title: str | None = None


OUTBOUND_PRIORITY: int = 25

_DISPATCH_COUNTS: dict[str, int] = {}


def get_dispatch_counts() -> dict[str, int]:
    return dict(_DISPATCH_COUNTS)


def is_outbound_enabled() -> bool:
    return bool(os.environ.get("OPENWEBUI_API_KEY", ""))


def create_outbound_payload(message: OutboundMessage) -> dict:
    payload = {
        "target_user_id": message.target_user_id,
        "content": message.content,
        "priority": OUTBOUND_PRIORITY,
    }
    if message.conversation_id:
        payload["conversation_id"] = message.conversation_id
    if message.title:
        payload["title"] = message.title
    return payload


def validate_outbound(message: OutboundMessage) -> list[str]:
    errors = []
    if not message.target_user_id.strip():
        errors.append("target_user_id is required")
    if not message.content.strip():
        errors.append("content is required")
    return errors


def record_dispatch(message: OutboundMessage, success: bool) -> None:
    key = "success" if success else "failed"
    _DISPATCH_COUNTS[key] = _DISPATCH_COUNTS.get(key, 0) + 1
