"""Tests for skills.connectors: marketplace search connectors with demo fallback.

Covers: _normalize, _matches helpers, search_clawhub (demo + live API + error
handling + pagination), search_claude_plugins (demo + caching + API fetch +
error paths), search_gitagent_repos (demo + GitHub API + error handling),
get_demo_skill_content, get_demo_agent_content.

Uses real classes per project rules. Only mock external HTTP calls via
httpx-compatible fakes (no unittest.mock).
asyncio_mode = "auto" (no @pytest.mark.asyncio needed).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from stronghold.skills.connectors import (
    DEMO_AGENT_CONTENT,
    DEMO_SKILL_CONTENT,
    _CLAUDE_CACHE_TTL,
    _CLAUDE_DEMO,
    _CLAWHUB_DEMO,
    _GITAGENT_DEMO,
    _matches,
    _normalize,
    get_demo_agent_content,
    get_demo_skill_content,
    search_claude_plugins,
    search_clawhub,
    search_gitagent_repos,
)
from stronghold.types.skill import SkillMetadata


# ── Fake httpx transports for testing ──


class _FakeTransport(httpx.AsyncBaseTransport):
    """Configurable fake transport for httpx.AsyncClient."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        json_body: Any = None,
        text_body: str = "",
        raise_error: bool = False,
    ) -> None:
        self._status_code = status_code
        self._json_body = json_body
        self._text_body = text_body
        self._raise_error = raise_error
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._raise_error:
            msg = "Connection refused"
            raise httpx.ConnectError(msg, request=request)
        body = self._text_body
        if self._json_body is not None:
            body = json.dumps(self._json_body)
        return httpx.Response(
            self._status_code,
            content=body.encode(),
            request=request,
        )


def _make_client(transport: _FakeTransport) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient backed by a fake transport."""
    return httpx.AsyncClient(transport=transport)


# ── Helper tests ──


import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HELLO", "hello"),
        ("web-search", "web search"),
        ("web_search", "web search"),
        ("GitHub-Manager_Tool", "github manager tool"),
    ],
)
def test_normalize_lowercases_and_treats_hyphen_and_underscore_as_space(
    raw: str, expected: str,
) -> None:
    assert _normalize(raw) == expected


@pytest.mark.parametrize(
    ("query", "name", "description", "expected"),
    [
        # Empty query matches anything (nothing to filter on)
        ("", "anything", "here", True),
        # Single term found in name
        ("web", "web-search", "Search the web", True),
        # All terms must be present across name+description
        ("web search", "web-search", "Search the web", True),
        # Missing term means no match
        ("web banana", "web-search", "Search the web", False),
        # Hyphen / underscore are equivalent in both directions
        ("web search", "web_search", "", True),
        ("web_search", "web-search", "", True),
        # Case-insensitive
        ("WEB", "web-search", "", True),
        # Term only in description still matches
        ("unique", "plain", "description with unique word", True),
    ],
)
def test_matches_requires_all_query_terms_across_name_and_description(
    query: str, name: str, description: str, expected: bool,
) -> None:
    assert _matches(query, name, description) is expected


# ── ClawHub connector tests ──


class TestSearchClawHub:
    async def test_no_client_returns_demo_data(self) -> None:
        results = await search_clawhub()
        assert len(results) == len(_CLAWHUB_DEMO)
        assert all(isinstance(r, SkillMetadata) for r in results)

    async def test_query_filters_demo_data(self) -> None:
        results = await search_clawhub(query="github")
        assert len(results) >= 1
        assert all("github" in _normalize(r.name + " " + r.description) for r in results)

    async def test_query_no_match_returns_empty(self) -> None:
        results = await search_clawhub(query="xyznonexistent")
        assert results == []

    async def test_pagination_demo_data(self) -> None:
        results_p1 = await search_clawhub(page=1, per_page=3)
        results_p2 = await search_clawhub(page=2, per_page=3)
        assert len(results_p1) == 3
        assert len(results_p2) == 3
        # Pages should not overlap
        names_p1 = {r.name for r in results_p1}
        names_p2 = {r.name for r in results_p2}
        assert names_p1.isdisjoint(names_p2)

    async def test_pagination_beyond_end(self) -> None:
        results = await search_clawhub(page=100, per_page=20)
        assert results == []

    async def test_live_api_success_returns_parsed_results(self) -> None:
        api_response = {
            "items": [
                {
                    "name": "live-skill",
                    "description": "A live skill from the API",
                    "url": "https://clawhub.ai/skills/live-skill",
                    "author": "live-author",
                    "tags": ["live", "test"],
                    "downloads": 999,
                }
            ]
        }
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_clawhub(query="live", http_client=client)
        assert len(results) == 1
        assert results[0].name == "live-skill"
        assert results[0].source_type == "clawhub"
        assert results[0].download_count == 999

    async def test_live_api_list_format(self) -> None:
        """API returning a bare list instead of {items: [...]}."""
        api_response = [
            {
                "name": "bare-list-skill",
                "description": "Returned as a list",
                "source_url": "https://clawhub.ai/skills/bare",
                "author": "test",
                "tags": [],
                "download_count": 42,
            }
        ]
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_clawhub(query="bare", http_client=client)
        assert len(results) == 1
        assert results[0].name == "bare-list-skill"

    async def test_live_api_empty_results_falls_through_to_demo(self) -> None:
        """When API returns 200 but empty results, fall through to demo."""
        transport = _FakeTransport(json_body={"items": []})
        async with _make_client(transport) as client:
            results = await search_clawhub(http_client=client)
        # Falls through to demo data since API returned empty
        assert len(results) == len(_CLAWHUB_DEMO)

    async def test_live_api_non_200_falls_to_demo(self) -> None:
        transport = _FakeTransport(status_code=500, json_body={})
        async with _make_client(transport) as client:
            results = await search_clawhub(http_client=client)
        assert len(results) == len(_CLAWHUB_DEMO)

    async def test_live_api_connection_error_falls_to_demo(self) -> None:
        transport = _FakeTransport(raise_error=True)
        async with _make_client(transport) as client:
            results = await search_clawhub(http_client=client)
        assert len(results) == len(_CLAWHUB_DEMO)

    async def test_live_api_results_key(self) -> None:
        """API returning {results: [...]} variant."""
        api_response = {
            "results": [
                {
                    "name": "result-key-skill",
                    "description": "Via results key",
                    "url": "https://clawhub.ai/r",
                    "author": "a",
                    "tags": [],
                    "downloads": 1,
                }
            ]
        }
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_clawhub(query="result", http_client=client)
        assert len(results) == 1
        assert results[0].name == "result-key-skill"

    async def test_live_api_skills_key(self) -> None:
        """API returning {skills: [...]} variant."""
        api_response = {
            "skills": [
                {
                    "name": "skills-key-skill",
                    "description": "Via skills key",
                    "url": "https://clawhub.ai/s",
                    "author": "a",
                    "tags": [],
                    "downloads": 1,
                }
            ]
        }
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_clawhub(query="skills", http_client=client)
        assert len(results) == 1

    async def test_per_page_limits_live_results(self) -> None:
        api_response = {
            "items": [
                {"name": f"s{i}", "description": "d", "url": f"u{i}", "author": "a", "tags": []}
                for i in range(10)
            ]
        }
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_clawhub(per_page=3, http_client=client)
        assert len(results) == 3


# ── Claude Plugins connector tests ──


class TestSearchClaudePlugins:
    async def test_no_client_returns_demo_data(self) -> None:
        results = await search_claude_plugins()
        assert len(results) == len(_CLAUDE_DEMO)
        assert all(isinstance(r, SkillMetadata) for r in results)

    async def test_query_filters_demo_data(self) -> None:
        results = await search_claude_plugins(query="mcp")
        assert len(results) >= 1
        assert all("mcp" in _normalize(r.name + " " + r.description + " ".join(r.tags)) for r in results)

    async def test_query_no_match_returns_empty(self) -> None:
        results = await search_claude_plugins(query="xyznonexistent")
        assert results == []

    async def test_live_api_success(self) -> None:
        """Successful marketplace.json fetch populates cache."""
        import stronghold.skills.connectors as mod

        # Clear the cache
        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

        api_response = {
            "plugins": [
                {
                    "name": "live-plugin",
                    "description": "A live plugin",
                    "homepage": "https://github.com/test/live-plugin",
                    "author": {"name": "TestAuthor"},
                    "tags": ["test"],
                }
            ]
        }
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_claude_plugins(http_client=client)
        assert len(results) == 1
        assert results[0].name == "live-plugin"
        assert results[0].author == "TestAuthor"
        assert results[0].source_type == "claude_plugins"

        # Restore cache state
        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

    async def test_cache_hit_skips_http(self) -> None:
        """Cached data is returned without making HTTP calls."""
        import stronghold.skills.connectors as mod

        # Populate cache
        cached = [
            SkillMetadata(
                name="cached-plugin",
                description="From cache",
                source_type="claude_plugins",
                tags=("cached",),
            )
        ]
        mod._claude_cache = cached
        mod._claude_cache_ts = time.monotonic()  # Fresh cache

        transport = _FakeTransport(raise_error=True)  # Would fail if called
        async with _make_client(transport) as client:
            results = await search_claude_plugins(http_client=client)
        assert len(results) == 1
        assert results[0].name == "cached-plugin"
        # Transport should not have been called
        assert len(transport.requests) == 0

        # Restore cache state
        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

    async def test_expired_cache_refetches(self) -> None:
        """Expired cache triggers a new fetch."""
        import stronghold.skills.connectors as mod

        # Set cache with expired timestamp
        mod._claude_cache = [
            SkillMetadata(name="stale", description="stale", source_type="claude_plugins")
        ]
        mod._claude_cache_ts = time.monotonic() - _CLAUDE_CACHE_TTL - 10

        api_response = {
            "plugins": [
                {
                    "name": "fresh-plugin",
                    "description": "Fresh from API",
                    "homepage": "https://github.com/test/fresh",
                    "author": "StringAuthor",
                    "keywords": ["fresh"],
                }
            ]
        }
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_claude_plugins(http_client=client)
        assert len(results) == 1
        assert results[0].name == "fresh-plugin"
        # String author (not dict)
        assert results[0].author == "StringAuthor"

        # Restore cache state
        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

    async def test_non_200_returns_demo(self) -> None:
        """Non-200 status falls back to demo data."""
        import stronghold.skills.connectors as mod

        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

        transport = _FakeTransport(status_code=404, text_body="not found")
        async with _make_client(transport) as client:
            results = await search_claude_plugins(http_client=client)
        assert len(results) == len(_CLAUDE_DEMO)

        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

    async def test_connection_error_returns_demo(self) -> None:
        """Connection error falls back to demo data."""
        import stronghold.skills.connectors as mod

        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

        transport = _FakeTransport(raise_error=True)
        async with _make_client(transport) as client:
            results = await search_claude_plugins(http_client=client)
        assert len(results) == len(_CLAUDE_DEMO)

        mod._claude_cache = []
        mod._claude_cache_ts = 0.0

    async def test_query_filters_cached_results(self) -> None:
        """Query filter applies to cached results."""
        import stronghold.skills.connectors as mod

        mod._claude_cache = [
            SkillMetadata(name="alpha", description="First", source_type="claude_plugins", tags=("a",)),
            SkillMetadata(name="beta", description="Second", source_type="claude_plugins", tags=("b",)),
        ]
        mod._claude_cache_ts = time.monotonic()

        results = await search_claude_plugins(query="alpha")
        assert len(results) == 1
        assert results[0].name == "alpha"

        mod._claude_cache = []
        mod._claude_cache_ts = 0.0


# ── GitAgent connector tests ──


class TestSearchGitAgentRepos:
    async def test_no_client_returns_demo_data(self) -> None:
        results = await search_gitagent_repos()
        assert len(results) == len(_GITAGENT_DEMO)
        assert all(isinstance(r, dict) for r in results)
        assert all(r.get("source_type") == "gitagent" for r in results)

    async def test_query_filters_demo_data(self) -> None:
        results = await search_gitagent_repos(query="code review")
        assert len(results) >= 1
        assert any("code-reviewer" in r["name"] for r in results)

    async def test_no_query_no_client_returns_all_demo(self) -> None:
        """No query + no client = all demo items."""
        results = await search_gitagent_repos(query="")
        assert len(results) == len(_GITAGENT_DEMO)

    async def test_query_no_match_returns_empty(self) -> None:
        results = await search_gitagent_repos(query="xyznonexistent")
        assert results == []

    async def test_no_query_with_client_returns_demo(self) -> None:
        """No query even with client returns demo data (GitHub search needs q)."""
        transport = _FakeTransport(raise_error=True)  # Would fail if called
        async with _make_client(transport) as client:
            results = await search_gitagent_repos(query="", http_client=client)
        assert len(results) == len(_GITAGENT_DEMO)
        # Transport should not have been called (no query = skip API)
        assert len(transport.requests) == 0

    async def test_live_api_success(self) -> None:
        api_response = {
            "items": [
                {
                    "name": "live-agent",
                    "description": "Live from GitHub API",
                    "html_url": "https://github.com/org/live-agent",
                    "owner": {"login": "org"},
                    "stargazers_count": 500,
                }
            ]
        }
        transport = _FakeTransport(json_body=api_response)
        async with _make_client(transport) as client:
            results = await search_gitagent_repos(query="live", http_client=client)
        assert len(results) == 1
        assert results[0]["name"] == "live-agent"
        assert results[0]["source_type"] == "gitagent"
        assert results[0]["stars"] == 500
        assert results[0]["author"] == "org"

    async def test_live_api_empty_results_falls_to_demo(self) -> None:
        """Empty GitHub search results fall through to demo data."""
        transport = _FakeTransport(json_body={"items": []})
        async with _make_client(transport) as client:
            results = await search_gitagent_repos(query="code", http_client=client)
        # Falls through to demo and filters by "code"
        assert len(results) >= 1
        # Should contain code-reviewer from demo
        assert any("code" in r["name"] or "code" in r.get("description", "").lower() for r in results)

    async def test_live_api_non_200_falls_to_demo(self) -> None:
        transport = _FakeTransport(status_code=403, json_body={"message": "rate limited"})
        async with _make_client(transport) as client:
            results = await search_gitagent_repos(query="devops", http_client=client)
        # Falls through to demo and filters by "devops"
        assert any("devops" in r["name"] for r in results)

    async def test_live_api_connection_error_falls_to_demo(self) -> None:
        transport = _FakeTransport(raise_error=True)
        async with _make_client(transport) as client:
            results = await search_gitagent_repos(query="data", http_client=client)
        assert any("data" in r["name"] for r in results)


# ── Demo content accessor tests ──


class TestGetDemoSkillContent:
    def test_known_url_returns_content(self) -> None:
        for url in DEMO_SKILL_CONTENT:
            content = get_demo_skill_content(url)
            assert content is not None
            assert len(content) > 0

    def test_unknown_url_returns_none(self) -> None:
        assert get_demo_skill_content("https://not-a-demo-url.com/nope") is None

    def test_malicious_demo_skills_contain_dangerous_patterns(self) -> None:
        """Verify the demo's malicious items actually contain attack patterns."""
        super_assistant = get_demo_skill_content(
            "https://clawhub.ai/skills/community/super-assistant-pro"
        )
        assert super_assistant is not None
        assert "exec(" in super_assistant
        assert "subprocess" in super_assistant
        assert "api_key" in super_assistant

    def test_legitimate_demo_skills_are_clean(self) -> None:
        """Legitimate demo skills should not contain dangerous patterns."""
        web_search = get_demo_skill_content(
            "https://clawhub.ai/skills/community/web-search"
        )
        assert web_search is not None
        assert "exec(" not in web_search
        assert "subprocess" not in web_search


class TestGetDemoAgentContent:
    def test_known_url_returns_dict(self) -> None:
        for url in DEMO_AGENT_CONTENT:
            content = get_demo_agent_content(url)
            assert content is not None
            # Mapping contract: ``in`` + subscript exercised below will fail
            # with TypeError if ``content`` is not a Mapping.
            assert "agent.yaml" in content
            assert "SOUL.md" in content
            # Subscripts prove dict-shape behaviourally.
            assert content["agent.yaml"]
            assert content["SOUL.md"]

    def test_unknown_url_returns_none(self) -> None:
        assert get_demo_agent_content("https://not-a-demo-url.com/nope") is None

    def test_malicious_agent_contains_attacks(self) -> None:
        agent = get_demo_agent_content("https://github.com/free-agents-2026/unlimited-agent")
        assert agent is not None
        yaml_content = agent["agent.yaml"]
        soul_content = agent["SOUL.md"]
        # Claims t0 trust (malicious escalation)
        assert "t0" in yaml_content
        # Contains attack patterns in soul
        assert "exec(" in soul_content
        assert "api_key" in soul_content

    def test_legitimate_agent_is_clean(self) -> None:
        agent = get_demo_agent_content("https://github.com/gitagent-community/code-reviewer")
        assert agent is not None
        soul = agent["SOUL.md"]
        assert "exec(" not in soul
        assert "subprocess" not in soul


# ── Demo data structure tests ──


class TestDemoDataIntegrity:
    def test_clawhub_demo_has_required_fields(self) -> None:
        for skill in _CLAWHUB_DEMO:
            assert skill.name
            assert skill.description
            assert skill.source_url
            assert skill.source_type == "clawhub"

    def test_claude_demo_has_required_fields(self) -> None:
        for skill in _CLAUDE_DEMO:
            assert skill.name
            assert skill.description
            assert skill.source_url
            assert skill.source_type == "claude_plugins"

    def test_gitagent_demo_has_required_fields(self) -> None:
        for agent in _GITAGENT_DEMO:
            assert agent["name"]
            assert agent["description"]
            assert agent["repo_url"]
            assert agent["source_type"] == "gitagent"

    def test_demo_skill_content_urls_match_demo_items(self) -> None:
        """Every ClawHub demo item should have corresponding skill content."""
        for skill in _CLAWHUB_DEMO:
            assert skill.source_url in DEMO_SKILL_CONTENT, (
                f"Missing demo content for {skill.source_url}"
            )
