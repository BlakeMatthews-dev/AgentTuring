"""Deep edge-case probes — second-pass review.

Hunts for subtler bugs: concurrency, unicode collisions, numeric
overflow, state-machine violations, protocol edge cases, time-based
assumptions. Each failing test is a real finding.
"""

from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ──────────────────────────────────────────────────────────────────────
# Rate limiter deeper probes
# ──────────────────────────────────────────────────────────────────────


class TestRateLimiterDeep:
    async def _client(self):
        import fakeredis.aioredis

        return fakeredis.aioredis.FakeRedis(decode_responses=False)

    async def test_negative_max_requests(self) -> None:
        """max_requests=-1: must deny, not allow (would be soundness failure)."""
        from stronghold.cache.rate_limiter import RedisRateLimiter

        client = await self._client()
        limiter = RedisRateLimiter(client, max_requests=-1, window_seconds=60)
        allowed, _ = await limiter.check("u")
        assert allowed is False
        await client.aclose()

    async def test_check_does_not_record(self) -> None:
        """check() must be idempotent — multiple calls don't consume budget."""
        from stronghold.cache.rate_limiter import RedisRateLimiter

        client = await self._client()
        limiter = RedisRateLimiter(client, max_requests=5, window_seconds=60)
        _, h1 = await limiter.check("u")
        _, h2 = await limiter.check("u")
        assert h1["X-RateLimit-Remaining"] == h2["X-RateLimit-Remaining"] == "5"
        await client.aclose()

    async def test_record_then_check_consistent(self) -> None:
        from stronghold.cache.rate_limiter import RedisRateLimiter

        client = await self._client()
        limiter = RedisRateLimiter(client, max_requests=3, window_seconds=60)
        await limiter.record("u")
        _, h1 = await limiter.check("u")
        await limiter.record("u")
        _, h2 = await limiter.check("u")
        assert int(h1["X-RateLimit-Remaining"]) == 2
        assert int(h2["X-RateLimit-Remaining"]) == 1
        await client.aclose()


# ──────────────────────────────────────────────────────────────────────
# Session store deeper probes
# ──────────────────────────────────────────────────────────────────────


class TestSessionStoreDeep:
    async def _client(self):
        import fakeredis.aioredis

        return fakeredis.aioredis.FakeRedis(decode_responses=False)

    async def test_negative_max_messages_safe(self) -> None:
        """Negative max_messages must not crash or return garbage."""
        from stronghold.cache.session_store import RedisSessionStore

        client = await self._client()
        store = RedisSessionStore(client)
        await store.append_messages(
            "o/t/u:s", [{"role": "user", "content": f"m{i}"} for i in range(5)]
        )
        history = await store.get_history("o/t/u:s", max_messages=-3)
        assert isinstance(history, list)
        await client.aclose()

    async def test_sec009_non_dict_message_skipped(self) -> None:
        """SEC-009: append_messages must skip non-dict entries, not crash."""
        from stronghold.cache.session_store import RedisSessionStore

        client = await self._client()
        store = RedisSessionStore(client)
        await store.append_messages(
            "o/t/u:s",
            [
                "not a dict",  # type: ignore[list-item]
                {"role": "user", "content": "valid"},
                42,  # type: ignore[list-item]
                None,  # type: ignore[list-item]
                {"role": "assistant", "content": "also valid"},
            ],
        )
        history = await store.get_history("o/t/u:s")
        contents = {m["content"] for m in history}
        assert "valid" in contents
        assert "also valid" in contents
        await client.aclose()

    async def test_large_message_10mb(self) -> None:
        """10MB single message must round-trip intact."""
        from stronghold.cache.session_store import RedisSessionStore

        client = await self._client()
        store = RedisSessionStore(client)
        huge = "x" * (10 * 1024 * 1024)
        await store.append_messages("o/t/u:s", [{"role": "user", "content": huge}])
        history = await store.get_history("o/t/u:s")
        assert len(history) == 1
        assert len(history[0]["content"]) == len(huge)
        await client.aclose()

    async def test_unicode_content_roundtrip(self) -> None:
        """Emoji + RTL + combining chars survive round trip."""
        from stronghold.cache.session_store import RedisSessionStore

        client = await self._client()
        store = RedisSessionStore(client)
        text = "Hello 🌍 مرحبا e\u0301"
        await store.append_messages("o/t/u:s", [{"role": "user", "content": text}])
        history = await store.get_history("o/t/u:s")
        assert history[0]["content"] == text
        await client.aclose()

    async def test_session_id_with_control_chars_isolated(self) -> None:
        """Forged session_id containing control chars must not escape into another session."""
        from stronghold.cache.session_store import RedisSessionStore

        client = await self._client()
        store = RedisSessionStore(client)
        await store.append_messages(
            "acme/t/alice:s1",
            [
                {"role": "user", "content": "alice secret"},
            ],
        )
        forged = "evil/t/bob:s\r\nstronghold:session:acme/t/alice:s1"
        history = await store.get_history(forged)
        assert not any("secret" in m.get("content", "") for m in history)
        await client.aclose()


# ──────────────────────────────────────────────────────────────────────
# Prompt cache deeper probes
# ──────────────────────────────────────────────────────────────────────


class TestPromptCacheDeep:
    async def _client(self):
        import fakeredis.aioredis

        return fakeredis.aioredis.FakeRedis(decode_responses=False)

    async def test_null_ambiguity_documented(self) -> None:
        """Setting None is indistinguishable from 'missing' — known limitation."""
        from stronghold.cache.prompt_cache import RedisPromptCache

        client = await self._client()
        cache = RedisPromptCache(client)
        await cache.set("k", None)
        assert await cache.get("k") is None
        assert await cache.get("nonexistent") is None
        await client.aclose()

    async def test_invalidate_pattern_does_not_leak_across_prefixes(self) -> None:
        """Critical: invalidate_pattern('*') under prefix 'a:' must not delete 'b:'."""
        from stronghold.cache.prompt_cache import RedisPromptCache

        client = await self._client()
        a = RedisPromptCache(client, key_prefix="a:")
        b = RedisPromptCache(client, key_prefix="b:")
        await a.set("x", "a-val")
        await b.set("x", "b-val")
        await a.invalidate_pattern("*")
        assert await a.get("x") is None
        assert await b.get("x") == "b-val"
        await client.aclose()

    async def test_1mb_value_roundtrip(self) -> None:
        from stronghold.cache.prompt_cache import RedisPromptCache

        client = await self._client()
        cache = RedisPromptCache(client)
        big = {"text": "x" * (1024 * 1024)}
        await cache.set("k", big)
        result = await cache.get("k")
        assert result["text"] == big["text"]
        await client.aclose()


# ──────────────────────────────────────────────────────────────────────
# File ops deeper probes
# ──────────────────────────────────────────────────────────────────────


class TestFileOpsDeep:
    @pytest.fixture
    def workspace(self) -> Path:
        return Path(tempfile.mkdtemp())

    async def test_workspace_is_itself_symlink(self, tmp_path: Path) -> None:
        """Workspace path is a symlink to a real dir — should still work."""
        from stronghold.tools.file_ops import FileOpsExecutor

        real = tmp_path / "real"
        real.mkdir()
        (real / "file.txt").write_text("hello")
        link = tmp_path / "link"
        link.symlink_to(real)

        ex = FileOpsExecutor()
        result = await ex.execute(
            {
                "action": "read",
                "path": "file.txt",
                "workspace": str(link),
            }
        )
        assert result.success is True
        assert result.content == "hello"

    async def test_list_subdirectory_relative_paths(self, workspace: Path) -> None:
        """list on subdir should return paths relative to workspace."""
        from stronghold.tools.file_ops import FileOpsExecutor

        sub = workspace / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("a")
        (sub / "b.txt").write_text("b")

        ex = FileOpsExecutor()
        result = await ex.execute(
            {
                "action": "list",
                "path": "sub",
                "workspace": str(workspace),
            }
        )
        assert result.success is True
        files = json.loads(result.content)
        assert "sub/a.txt" in files
        assert "sub/b.txt" in files

    async def test_mkdir_collision_with_existing_file(self, workspace: Path) -> None:
        """mkdir on a path that already exists as a file must error."""
        from stronghold.tools.file_ops import FileOpsExecutor

        (workspace / "thing").write_text("i am a file")
        ex = FileOpsExecutor()
        result = await ex.execute(
            {
                "action": "mkdir",
                "path": "thing",
                "workspace": str(workspace),
            }
        )
        assert result.success is False

    async def test_write_empty_content_creates_empty_file(self, workspace: Path) -> None:
        from stronghold.tools.file_ops import FileOpsExecutor

        ex = FileOpsExecutor()
        result = await ex.execute(
            {
                "action": "write",
                "path": "empty.txt",
                "content": "",
                "workspace": str(workspace),
            }
        )
        assert result.success is True
        assert (workspace / "empty.txt").read_text() == ""


# ──────────────────────────────────────────────────────────────────────
# Shell exec deeper probes
# ──────────────────────────────────────────────────────────────────────


class TestShellExecDeep:
    @pytest.fixture
    def workspace(self) -> Path:
        return Path(tempfile.mkdtemp())

    async def test_empty_command_after_strip(self, workspace: Path) -> None:
        """Whitespace-only command rejected."""
        from stronghold.tools.shell_exec import ShellExecutor

        ex = ShellExecutor()
        result = await ex.execute(
            {
                "command": "   \t  ",
                "workspace": str(workspace),
            }
        )
        assert result.success is False
        assert "empty" in result.error.lower()

    async def test_all_metacharacter_variants_rejected(self, workspace: Path) -> None:
        """Soundness: every shell metacharacter variant rejected."""
        from stronghold.tools.shell_exec import ShellExecutor

        ex = ShellExecutor()
        variants = [
            "echo a ; rm b",
            "echo a | rm b",
            "echo a & rm b",
            "echo `rm b`",
            "echo $(rm b)",
            "echo > /tmp/x",
            "echo < /etc/passwd",
            "echo a\nrm b",
        ]
        for cmd in variants:
            result = await ex.execute(
                {
                    "command": cmd,
                    "workspace": str(workspace),
                }
            )
            assert result.success is False, f"Metacharacter not rejected: {cmd!r}"

    async def test_command_quoted_metachar_still_rejected(self, workspace: Path) -> None:
        """Even inside quotes, semicolon should be rejected (conservative).

        `echo "hi; fine"` has a literal semicolon that shell doesn't interpret,
        but our check is conservative and rejects it anyway. This is documented.
        """
        from stronghold.tools.shell_exec import ShellExecutor

        ex = ShellExecutor()
        result = await ex.execute(
            {
                "command": 'echo "hi; done"',
                "workspace": str(workspace),
            }
        )
        # Current behavior: reject. Intentional false positive, safer.
        assert result.success is False


# ──────────────────────────────────────────────────────────────────────
# Coins deeper probes
# ──────────────────────────────────────────────────────────────────────


class TestCoinsDeep:
    def test_negative_rate_value_clamped(self) -> None:
        """Negative per-1k rate must not give users credits (charged >= 0)."""
        from stronghold.quota.coins import _resolve_quote

        models = {"m": {"coin_cost_per_1k_input_microchips": -100}}
        quote = _resolve_quote(models, {}, "m", "p", 1000, 0)
        assert quote.charged_microchips >= 0

    def test_format_microchips_10_to_18(self) -> None:
        """Very large microchip count must produce sensible output."""
        from stronghold.quota.coins import format_microchips

        result = format_microchips(10**18)
        assert result["denomination"] == "diamond"
        assert result["microchips"] == 10**18
        assert result["amount"] > 0

    def test_coins_to_microchips_accepts_decimal(self) -> None:
        """Decimal input works (not just str)."""
        from stronghold.quota.coins import coins_to_microchips

        assert coins_to_microchips(Decimal("1.5")) == 1500

    def test_find_model_case_sensitive(self) -> None:
        """Lookup is case-sensitive — documented behavior."""
        from stronghold.quota.coins import _find_model

        models = {"gpt-4": {"provider": "openai"}}
        _, key = _find_model(models, "GPT-4")
        assert key == "GPT-4"  # not found, key echoed back

    def test_resolve_denomination_empty_explicit(self) -> None:
        from stronghold.quota.coins import _resolve_denomination

        assert _resolve_denomination({"coin_denomination": ""}, 0, 0, 0) == "copper"


# ──────────────────────────────────────────────────────────────────────
# Scanner deeper probes
# ──────────────────────────────────────────────────────────────────────


class TestScannerDeep:
    @pytest.fixture
    def project(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "src" / "stronghold" / "protocols").mkdir(parents=True)
        (root / "tests").mkdir()
        return root

    def test_sec010_binary_file_does_not_crash(self, project: Path) -> None:
        """SEC-010: detect_todo_fixme must not crash on non-UTF-8 bytes."""
        from stronghold.tools.scanner import detect_todo_fixme

        binary = project / "src" / "stronghold" / "binary.py"
        binary.write_bytes(b"\x80\x81\x82\x83")
        result = detect_todo_fixme(project / "src")
        assert isinstance(result, list)

    def test_todo_in_string_vs_comment(self, project: Path) -> None:
        """Only comments match, string literals do not."""
        from stronghold.tools.scanner import detect_todo_fixme

        (project / "src" / "stronghold" / "s.py").write_text(
            'msg = "TODO: this is a string, not a comment"\n'
            "# TODO: this one is a real comment with long enough desc\n"
        )
        result = detect_todo_fixme(project / "src")
        assert len(result) == 1
        assert "real comment" in result[0].description


# ──────────────────────────────────────────────────────────────────────
# Mason HMAC signature verification
# ──────────────────────────────────────────────────────────────────────


class TestMasonHmacDeep:
    def test_signature_off_by_one(self) -> None:
        """Differing by a single character must fail."""
        import hashlib
        import hmac

        from stronghold.api.routes.mason import _verify_signature

        body = b'{"test": 1}'
        secret = "s"
        correct = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        almost = correct[:-1] + ("0" if correct[-1] != "0" else "1")
        assert _verify_signature(body, secret, correct) is True
        assert _verify_signature(body, secret, almost) is False

    def test_signature_empty_body(self) -> None:
        import hashlib
        import hmac

        from stronghold.api.routes.mason import _verify_signature

        body = b""
        secret = "x"
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert _verify_signature(body, secret, sig) is True

    def test_signature_missing_prefix(self) -> None:
        from stronghold.api.routes.mason import _verify_signature

        assert _verify_signature(b"x", "s", "abc123") is False


# ──────────────────────────────────────────────────────────────────────
# Trigger handler exception propagation
# ──────────────────────────────────────────────────────────────────────


class TestTriggersDeep:
    def _container(self):
        c = MagicMock()
        c.reactor = type(
            "R",
            (),
            {
                "_triggers": [],
                "register": lambda self, s, a: self._triggers.append((s, a)),
            },
        )()
        c.learning_promoter = None
        c.rate_limiter = MagicMock()
        c.rate_limiter._windows = {}
        c.outcome_store = MagicMock()
        c.outcome_store.get_task_completion_rate = AsyncMock(return_value={})
        c.warden = MagicMock()
        c.warden.scan = AsyncMock(return_value=MagicMock(clean=True, flags=[]))
        c.tournament = None
        c.canary_manager = None
        c.learning_store = MagicMock()
        c.mason_queue = MagicMock()
        c.route_request = AsyncMock()
        return c

    def _handler(self, c, name):
        for spec, action in c.reactor._triggers:
            if spec.name == name:
                return action
        raise KeyError(name)

    async def test_canary_check_propagates_exception(self) -> None:
        """Document: canary_manager errors bubble up (no swallow)."""
        from stronghold.triggers import register_core_triggers
        from stronghold.types.reactor import Event

        c = self._container()
        c.canary_manager = MagicMock()
        c.canary_manager.list_active = MagicMock(
            return_value=[{"skill_name": "x", "stage": "10%"}],
        )
        c.canary_manager.check_promotion_or_rollback = MagicMock(
            side_effect=RuntimeError("boom"),
        )
        register_core_triggers(c)
        handler = self._handler(c, "canary_deployment_check")
        with pytest.raises(RuntimeError):
            await handler(Event(name="timer"))

    async def test_security_rescan_default_boundary(self) -> None:
        """boundary defaults to 'tool_result' when absent."""
        from stronghold.triggers import register_core_triggers
        from stronghold.types.reactor import Event

        c = self._container()
        register_core_triggers(c)
        handler = self._handler(c, "security_rescan")
        await handler(Event(name="security.rescan", data={"content": "test"}))
        c.warden.scan.assert_called_once_with("test", "tool_result")


# ──────────────────────────────────────────────────────────────────────
# NoOpCoinLedger state invariants
# ──────────────────────────────────────────────────────────────────────


class TestNoOpCoinLedgerStateMachine:
    def test_denominations_stable(self) -> None:
        from stronghold.quota.coins import NoOpCoinLedger

        ledger = NoOpCoinLedger()
        assert ledger.denominations() == ledger.denominations()

    def test_quote_deterministic(self) -> None:
        """Same inputs → same quote (required for caching)."""
        from stronghold.quota.coins import NoOpCoinLedger

        ledger = NoOpCoinLedger()
        q1 = ledger.quote("m", "p", 100, 200)
        q2 = ledger.quote("m", "p", 100, 200)
        assert q1 == q2
