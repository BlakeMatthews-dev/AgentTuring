"""Tests for the reward system (rewards.py, chat feedback endpoints)."""

from __future__ import annotations

import json
import sqlite3
import threading
from unittest.mock import MagicMock

from turing.motivation import BacklogItem, Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.rewards import RewardTracker, REWARD_SCHEDULE, DEFAULT_SCHEDULE
from turing.runtime.chat import ChatBridge, make_chat_handler
from http.server import ThreadingHTTPServer


def _make_tracker() -> RewardTracker:
    conn = sqlite3.connect(":memory:")
    return RewardTracker(conn, "test-self")


class TestRewardTracker:
    def test_chat_creation_awards_5(self) -> None:
        rt = _make_tracker()
        pts = rt.award(interface="chat", item_id="m1", event_type="creation")
        assert pts == 5
        assert rt.total_points() == 5

    def test_chat_thumbs_up_awards_10(self) -> None:
        rt = _make_tracker()
        pts = rt.award(interface="chat", item_id="m1", event_type="thumbs_up")
        assert pts == 10

    def test_chat_thumbs_down_deducts_20(self) -> None:
        rt = _make_tracker()
        pts = rt.award(interface="chat", item_id="m1", event_type="thumbs_down")
        assert pts == -20

    def test_blog_thumbs_up_awards_100(self) -> None:
        rt = _make_tracker()
        pts = rt.award(interface="blog", item_id="p1", event_type="thumbs_up")
        assert pts == 100

    def test_blog_thumbs_down_deducts_200(self) -> None:
        rt = _make_tracker()
        pts = rt.award(interface="blog", item_id="p1", event_type="thumbs_down")
        assert pts == -200

    def test_total_points_across_interfaces(self) -> None:
        rt = _make_tracker()
        rt.award(interface="chat", item_id="m1", event_type="creation")
        rt.award(interface="blog", item_id="p1", event_type="creation")
        rt.award(interface="chat", item_id="m1", event_type="thumbs_up")
        assert rt.total_points() == 20

    def test_points_by_interface(self) -> None:
        rt = _make_tracker()
        rt.award(interface="chat", item_id="m1", event_type="creation")
        rt.award(interface="blog", item_id="p1", event_type="thumbs_up")
        by_iface = rt.points_by_interface()
        assert by_iface == {"chat": 5, "blog": 100}

    def test_has_feedback_false_when_none(self) -> None:
        rt = _make_tracker()
        assert rt.has_feedback("m1") is False

    def test_has_feedback_true_after_thumbs_up(self) -> None:
        rt = _make_tracker()
        rt.award(interface="chat", item_id="m1", event_type="thumbs_up")
        assert rt.has_feedback("m1") is True

    def test_has_feedback_true_after_thumbs_down(self) -> None:
        rt = _make_tracker()
        rt.award(interface="chat", item_id="m1", event_type="thumbs_down")
        assert rt.has_feedback("m1") is True

    def test_has_feedback_false_after_only_creation(self) -> None:
        rt = _make_tracker()
        rt.award(interface="chat", item_id="m1", event_type="creation")
        assert rt.has_feedback("m1") is False

    def test_invalid_event_type_raises(self) -> None:
        rt = _make_tracker()
        raised = False
        try:
            rt.award(interface="chat", item_id="m1", event_type="invalid")
        except ValueError:
            raised = True
        assert raised

    def test_unknown_interface_uses_default_schedule(self) -> None:
        rt = _make_tracker()
        pts = rt.award(interface="unknown", item_id="x1", event_type="thumbs_up")
        assert pts == DEFAULT_SCHEDULE["thumbs_up"]

    def test_recent_events(self) -> None:
        rt = _make_tracker()
        rt.award(interface="chat", item_id="m1", event_type="creation")
        rt.award(interface="blog", item_id="p1", event_type="creation")
        events = rt.recent_events(limit=10)
        assert len(events) == 2
        assert events[0]["interface"] == "blog"
        assert events[1]["interface"] == "chat"

    def test_schedule_has_chat_and_default(self) -> None:
        assert "chat" in REWARD_SCHEDULE
        assert REWARD_SCHEDULE["chat"]["creation"] == 5
        assert REWARD_SCHEDULE["chat"]["thumbs_up"] == 10
        assert REWARD_SCHEDULE["chat"]["thumbs_down"] == -20
        assert DEFAULT_SCHEDULE["creation"] == 5
        assert DEFAULT_SCHEDULE["thumbs_up"] == 100
        assert DEFAULT_SCHEDULE["thumbs_down"] == -200
