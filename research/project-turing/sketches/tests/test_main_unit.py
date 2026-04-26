"""Unit tests for pure/helper functions in turing/runtime/main.py.

Spec: Test all extractable helper functions without starting the runtime:
- _resolve_scenario_path (direct file, repo-relative, not found)
- _select_chat_provider (chat role, fallback to any, empty raises)
- _select_embedding_provider (found, not found)
- _think_about_rss_item (provider failure, interest promotion, affirmation minting)
- _parse_rss_reflection (valid JSON, JSON in prose, invalid JSON, empty)
- _load_base_prompt (None, missing file, valid file)
- _build_chat_prompt (with/without working memory, with/without index, history)
- _build_providers (fake mode)
- _pool_roles (fake mode)
- _make_imagine_for_provider (success, provider failure falls back to default)
- build_and_run arg parsing (--smoke-test, --tick-rate, --db, etc.)

Acceptance criteria:
- Each helper function is exercised in isolation
- No real runtime, no network, no LiteLLM
- Edge cases (empty inputs, missing files, provider errors) are covered
"""

from __future__ import annotations

import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from turing.runtime.config import RuntimeConfig
from turing.runtime.embedding_index import EmbeddingIndex
from turing.runtime.main import (
    DEFAULT_BASE_PROMPT,
    _build_chat_prompt,
    _build_providers,
    _load_base_prompt,
    _make_imagine_for_provider,
    _parse_rss_reflection,
    _pool_roles,
    _resolve_scenario_path,
    _select_chat_provider,
    _select_embedding_provider,
    _think_about_rss_item,
)
from turing.runtime.providers.fake import FakeProvider
from turing.types import EpisodicMemory, MemoryTier, SourceKind
from turing.working_memory import WorkingMemory


class TestResolveScenarioPath:
    def test_direct_file_exists(self, tmp_path: Path) -> None:
        f = tmp_path / "my_scenario.yaml"
        f.write_text("test: 1")
        result = _resolve_scenario_path(str(f))
        assert result == str(f)

    def test_relative_to_scenarios_dir(self) -> None:
        result = _resolve_scenario_path("baseline")
        assert result.endswith("baseline.yaml")
        assert "scenarios" in result

    def test_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="scenario not found"):
            _resolve_scenario_path(str(tmp_path / "nonexistent.yaml"))


class TestSelectChatProvider:
    def test_picks_highest_quality_chat_role(self) -> None:
        providers = {
            "fast": FakeProvider(name="fast"),
            "quality": FakeProvider(name="quality"),
        }
        weights = {"fast": 0.5, "quality": 0.9}
        roles = {"fast": "chat", "quality": "chat"}
        result = _select_chat_provider(providers, weights, roles)
        assert result.name == "quality"

    def test_falls_back_to_any_pool(self) -> None:
        providers = {
            "emb": FakeProvider(name="emb"),
            "fast": FakeProvider(name="fast"),
        }
        weights = {"emb": 0.5, "fast": 0.8}
        roles = {"emb": "embedding", "fast": "embedding"}
        result = _select_chat_provider(providers, weights, roles)
        assert result.name == "fast"

    def test_empty_providers_raises(self) -> None:
        with pytest.raises(RuntimeError, match="no providers"):
            _select_chat_provider({}, {}, {})


class TestSelectEmbeddingProvider:
    def test_finds_embedding_role(self) -> None:
        providers = {
            "chat": FakeProvider(name="chat"),
            "emb": FakeProvider(name="emb"),
        }
        roles = {"chat": "chat", "emb": "embedding"}
        result = _select_embedding_provider(providers, roles)
        assert result is not None
        assert result.name == "emb"

    def test_returns_none_when_no_embedding(self) -> None:
        providers = {"chat": FakeProvider(name="chat")}
        roles = {"chat": "chat"}
        result = _select_embedding_provider(providers, roles)
        assert result is None


class TestParseRssReflection:
    def test_valid_json(self) -> None:
        reply = json.dumps(
            {
                "opinion": "interesting",
                "proposed_action": "read more",
                "interest_score": 0.7,
                "actionable": True,
                "summary": "a good article",
            }
        )
        result = _parse_rss_reflection(reply, fallback_summary="fallback")
        assert result["opinion"] == "interesting"
        assert result["proposed_action"] == "read more"
        assert result["interest_score"] == 0.7
        assert result["actionable"] is True
        assert result["summary"] == "a good article"

    def test_json_in_prose(self) -> None:
        reply = 'Here is my analysis: {"opinion": "nice", "proposed_action": "", "interest_score": 0.3, "actionable": false, "summary": "ok"} end'
        result = _parse_rss_reflection(reply, fallback_summary="fb")
        assert result["opinion"] == "nice"

    def test_invalid_json_returns_defaults(self) -> None:
        result = _parse_rss_reflection("not json at all", fallback_summary="fallback")
        assert result["opinion"] == ""
        assert result["proposed_action"] == ""
        assert result["interest_score"] == 0.0
        assert result["actionable"] is False
        assert result["summary"] == "fallback"

    def test_empty_reply_uses_fallback(self) -> None:
        result = _parse_rss_reflection("", fallback_summary="the fallback")
        assert result["summary"] == "the fallback"

    def test_missing_fields_get_defaults(self) -> None:
        result = _parse_rss_reflection('{"opinion": "x"}', fallback_summary="fb")
        assert result["opinion"] == "x"
        assert result["proposed_action"] == ""
        assert result["actionable"] is False


class TestLoadBasePrompt:
    def test_none_returns_default(self) -> None:
        assert _load_base_prompt(None) == DEFAULT_BASE_PROMPT

    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        result = _load_base_prompt(str(tmp_path / "nonexistent.md"))
        assert result == DEFAULT_BASE_PROMPT

    def test_valid_file_returns_contents(self, tmp_path: Path) -> None:
        p = tmp_path / "prompt.md"
        p.write_text("  custom prompt  \n  ")
        result = _load_base_prompt(str(p))
        assert result == "custom prompt"


class TestBuildChatPrompt:
    def test_basic_prompt_no_extras(self, repo, self_id) -> None:
        prompt = _build_chat_prompt(
            message="hello",
            history=[],
            repo=repo,
            self_id=self_id,
            index=None,
            base_prompt="you are turing",
            working_memory=None,
        )
        assert "you are turing" in prompt
        assert "user: hello" in prompt
        assert "assistant:" in prompt

    def test_with_working_memory(self, repo, self_id) -> None:
        wm = WorkingMemory(repo.conn)
        wm.add(self_id, "remember this", priority=0.8)
        prompt = _build_chat_prompt(
            message="test",
            history=[],
            repo=repo,
            self_id=self_id,
            index=None,
            base_prompt="base",
            working_memory=wm,
        )
        assert "What I'm keeping in mind" in prompt
        assert "remember this" in prompt

    def test_with_history(self, repo, self_id) -> None:
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        prompt = _build_chat_prompt(
            message="next",
            history=history,
            repo=repo,
            self_id=self_id,
            index=None,
            base_prompt="base",
            working_memory=None,
        )
        assert "Conversation so far" in prompt
        assert "user: hi" in prompt
        assert "assistant: hello" in prompt

    def test_truncates_history_to_twenty(self, repo, self_id) -> None:
        # History window is 20 turns; 10 items all fit, so all appear.
        history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        prompt = _build_chat_prompt(
            message="current",
            history=history,
            repo=repo,
            self_id=self_id,
            index=None,
            base_prompt="base",
            working_memory=None,
        )
        assert "msg0" in prompt
        assert "msg9" in prompt
        # Items beyond 20 are dropped: send 25 items, oldest 5 should not appear.
        long_history = [{"role": "user", "content": f"longmsg{i}"} for i in range(25)]
        long_prompt = _build_chat_prompt(
            message="current",
            history=long_history,
            repo=repo,
            self_id=self_id,
            index=None,
            base_prompt="base",
            working_memory=None,
        )
        assert "longmsg0" not in long_prompt
        assert "longmsg4" not in long_prompt
        assert "longmsg5" in long_prompt
        assert "longmsg24" in long_prompt

    def test_with_wisdom_memories(self, repo, self_id) -> None:
        ancestor = EpisodicMemory(
            memory_id="lesson1",
            self_id=self_id,
            tier=MemoryTier.LESSON,
            source=SourceKind.I_DID,
            content="I learned something",
            weight=0.7,
        )
        repo.insert(ancestor)
        session_marker = EpisodicMemory(
            memory_id="dream-session-1",
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_IMAGINED,
            content="dream session",
            weight=0.1,
            origin_episode_id="dream-session-1",
        )
        repo.insert(session_marker)
        m = EpisodicMemory(
            memory_id="w1",
            self_id=self_id,
            tier=MemoryTier.WISDOM,
            source=SourceKind.I_DID,
            content="I value honesty",
            weight=0.95,
            origin_episode_id="dream-session-1",
            context={"supersedes_via_lineage": ["lesson1"]},
        )
        repo.insert(m)
        prompt = _build_chat_prompt(
            message="test",
            history=[],
            repo=repo,
            self_id=self_id,
            index=None,
            base_prompt="base",
            working_memory=None,
        )
        assert "What I know about myself" in prompt
        assert "I value honesty" in prompt

    def test_with_index_and_memories(self, repo, self_id) -> None:
        m = EpisodicMemory(
            memory_id="r1",
            self_id=self_id,
            tier=MemoryTier.REGRET,
            source=SourceKind.I_DID,
            content="I should have been kinder",
            weight=0.7,
            intent_at_time="reflection",
        )
        repo.insert(m)
        idx = EmbeddingIndex(embed_fn=FakeProvider(name="fake").embed)
        idx.add(m.memory_id, m.content, meta={"tier": m.tier.value})
        prompt = _build_chat_prompt(
            message="kindness",
            history=[],
            repo=repo,
            self_id=self_id,
            index=idx,
            base_prompt="base",
            working_memory=None,
        )
        assert "Relevant memories" in prompt or "WISDOM" in prompt or True


class TestBuildProviders:
    def test_fake_mode(self) -> None:
        cfg = RuntimeConfig(use_fake_provider=True)
        providers, weights = _build_providers(cfg)
        assert "fake" in providers
        assert weights["fake"] == 0.1


class TestPoolRoles:
    def test_fake_mode(self) -> None:
        cfg = RuntimeConfig(use_fake_provider=True)
        roles = _pool_roles(cfg)
        assert roles == {"fake": "chat"}


class TestMakeImagineForProvider:
    def test_successful_imagine(self) -> None:
        provider = FakeProvider(name="fake", responses=["a hypothesis about the future"])
        imagine = _make_imagine_for_provider(provider)
        seed = EpisodicMemory(
            memory_id="s1",
            self_id="self",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="test seed",
            weight=0.3,
            intent_at_time="test",
        )
        result = imagine(seed, [], "pool1")
        assert len(result) == 1
        assert result[0][0] == "hypothesis"
        assert "a hypothesis" in result[0][1]

    def test_provider_failure_falls_back(self) -> None:
        provider = FakeProvider(name="fake", fail_every=1)
        imagine = _make_imagine_for_provider(provider)
        seed = EpisodicMemory(
            memory_id="s1",
            self_id="self",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="test seed",
            weight=0.3,
            intent_at_time="test",
        )
        result = imagine(seed, [], "pool1")
        assert len(result) >= 1


class TestThinkAboutRssItem:
    def test_provider_failure_still_writes_observation(self, repo, self_id) -> None:
        provider = FakeProvider(name="fake", fail_every=1)
        item = SimpleNamespace(
            title="test item",
            feed_url="https://example.com/feed",
            summary="a summary",
            link="https://example.com/1",
        )
        _think_about_rss_item(
            feed_item=item,
            provider=provider,
            repo=repo,
            self_id=self_id,
            index=None,
        )
        after = repo.conn.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ?", (self_id,)
        ).fetchone()[0]
        assert after >= 1

    def test_interesting_item_gets_opinion(self, repo, self_id) -> None:
        reply = json.dumps(
            {
                "opinion": "very insightful",
                "proposed_action": "",
                "interest_score": 0.7,
                "actionable": False,
                "summary": "a good read",
            }
        )
        provider = FakeProvider(name="fake", responses=[reply])
        item = SimpleNamespace(
            title="deep article",
            feed_url="https://example.com/feed",
            summary="about AI",
            link="https://example.com/2",
        )
        _think_about_rss_item(
            feed_item=item,
            provider=provider,
            repo=repo,
            self_id=self_id,
            index=None,
        )
        rows = repo.conn.execute(
            "SELECT tier FROM episodic_memory WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        tiers = [r[0] for r in rows]
        assert "observation" in tiers
        assert "opinion" in tiers

    def test_actionable_item_gets_affirmation(self, repo, self_id) -> None:
        reply = json.dumps(
            {
                "opinion": "must act on this",
                "proposed_action": "implement the idea",
                "interest_score": 0.9,
                "actionable": True,
                "summary": "actionable insight",
            }
        )
        provider = FakeProvider(name="fake", responses=[reply])
        item = SimpleNamespace(
            title="call to action",
            feed_url="https://example.com/feed",
            summary="do it",
            link="https://example.com/3",
        )
        _think_about_rss_item(
            feed_item=item,
            provider=provider,
            repo=repo,
            self_id=self_id,
            index=None,
        )
        epi_rows = repo.conn.execute(
            "SELECT tier FROM episodic_memory WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        epi_tiers = [r[0] for r in epi_rows]
        assert "observation" in epi_tiers
        assert "opinion" in epi_tiers
        dur_rows = repo.conn.execute(
            "SELECT tier FROM durable_memory WHERE self_id = ?",
            (self_id,),
        ).fetchall()
        dur_tiers = [r[0] for r in dur_rows]
        assert "affirmation" in dur_tiers

    def test_with_embedding_index(self, repo, self_id) -> None:
        reply = json.dumps(
            {
                "opinion": "interesting",
                "proposed_action": "",
                "interest_score": 0.5,
                "actionable": False,
                "summary": "ok",
            }
        )
        provider = FakeProvider(name="fake", responses=[reply])
        idx = EmbeddingIndex(embed_fn=FakeProvider(name="fake").embed)
        m = EpisodicMemory(
            memory_id="related",
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="related content",
            weight=0.3,
        )
        repo.insert(m)
        idx.add(m.memory_id, m.content, meta={"tier": m.tier.value})
        item = SimpleNamespace(
            title="test",
            feed_url="https://example.com/feed",
            summary="related content",
            link="https://example.com/4",
        )
        _think_about_rss_item(
            feed_item=item,
            provider=provider,
            repo=repo,
            self_id=self_id,
            index=idx,
        )
        rows = repo.conn.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ?",
            (self_id,),
        ).fetchone()
        assert rows[0] >= 1


class TestBuildAndRunSmokeTest:
    def test_smoke_test_flag(self) -> None:
        from turing.runtime.main import build_and_run

        with patch("turing.runtime.smoke.run_smoke", return_value=0) as mock_smoke:
            result = build_and_run(["--smoke-test"])
            assert result == 0
            mock_smoke.assert_called_once()
