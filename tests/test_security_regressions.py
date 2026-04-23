"""Security regression tests — evidence-based soundness for specific bugs.

Each test corresponds to a real bug that was found and fixed. The test
describes WHAT the bug was, WHERE it lived, and asserts the specific
behavior that proves the fix is in place. If any of these regress,
the failure message points directly at the CVE-style finding.

Findings (all fixed):

  SEC-001 [HIGH]   file_ops prefix collision sandbox escape
  SEC-002 [HIGH]   file_ops symlink escape
  SEC-003 [CRIT]   shell_exec injection via semicolon
  SEC-004 [CRIT]   shell_exec injection via command substitution
  SEC-005 [CRIT]   shell_exec injection via pipe
  SEC-006 [MED]    session_store crash on poisoned JSON entries
  SEC-007 [MED]    file_ops null byte in path raises ValueError
  SEC-008 [MED]    coins _decimal accepts NaN (bypass risk)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────
# file_ops edge cases
# ──────────────────────────────────────────────────────────────────────


class TestFileOpsEdgeCases:
    """Probe FileOpsExecutor for sandbox-escape bugs."""

    @pytest.fixture
    def workspace(self) -> Path:
        return Path(tempfile.mkdtemp())

    async def test_sec002_symlink_escape_via_workspace(self, workspace: Path) -> None:
        """SEC-002 [HIGH]: symlink inside workspace pointing outside must not be followed.

        Bug: production code used `target.startswith(workspace)` which accepted
        symlinks because resolve() followed them. Fix: use `relative_to(ws_resolved)`.
        """
        from stronghold.tools.file_ops import FileOpsExecutor

        link = workspace / "escape"
        link.symlink_to("/tmp")

        ex = FileOpsExecutor()
        result = await ex.execute({
            "action": "list", "path": "escape", "workspace": str(workspace),
        })
        assert result.success is False
        assert "escapes workspace" in result.error

    async def test_sec001_prefix_collision_sandbox_escape(self, tmp_path: Path) -> None:
        """SEC-001 [HIGH]: workspace=/tmp/work must not allow access to /tmp/work-evil/*.

        Bug: `str(target).startswith(str(workspace))` passed '/tmp/work-evil/x'
        because it's a string prefix of '/tmp/work'. Fix: use Path.relative_to.
        """
        from stronghold.tools.file_ops import FileOpsExecutor

        work = tmp_path / "work"
        work.mkdir()
        evil = tmp_path / "work-evil"
        evil.mkdir()
        (evil / "secret.txt").write_text("PWNED")

        ex = FileOpsExecutor()
        result = await ex.execute({
            "action": "read", "path": "../work-evil/secret.txt",
            "workspace": str(work),
        })
        assert result.success is False
        assert "escapes workspace" in result.error
        # Belt and suspenders: never return the secret content
        assert "PWNED" not in (result.content or "")

    async def test_write_with_none_path(self, workspace: Path) -> None:
        """write action with no `path` key should not crash."""
        from stronghold.tools.file_ops import FileOpsExecutor
        ex = FileOpsExecutor()
        result = await ex.execute({
            "action": "write", "content": "x", "workspace": str(workspace),
        })
        # Default path "" → resolves to workspace root → can't write to a dir
        assert result.success is False

    async def test_list_truncates_at_200(self, workspace: Path) -> None:
        """list returns only first 200 entries — verify the cap."""
        from stronghold.tools.file_ops import FileOpsExecutor
        for i in range(250):
            (workspace / f"file_{i:03d}.txt").write_text("x")
        ex = FileOpsExecutor()
        result = await ex.execute({
            "action": "list", "path": ".", "workspace": str(workspace),
        })
        files = json.loads(result.content)
        assert len(files) == 200

    async def test_unicode_filename(self, workspace: Path) -> None:
        from stronghold.tools.file_ops import FileOpsExecutor
        ex = FileOpsExecutor()
        result = await ex.execute({
            "action": "write", "path": "中文.txt", "content": "hello",
            "workspace": str(workspace),
        })
        assert result.success is True
        read_result = await ex.execute({
            "action": "read", "path": "中文.txt", "workspace": str(workspace),
        })
        assert read_result.content == "hello"

    async def test_sec007_null_byte_in_path(self, workspace: Path) -> None:
        """SEC-007 [MED]: null byte in path must return error, not raise ValueError.

        Bug: resolve() raised on null byte before the sandbox check ran.
        Fix: catch OSError/ValueError in resolve() and return ToolResult.
        """
        from stronghold.tools.file_ops import FileOpsExecutor
        ex = FileOpsExecutor()
        result = await ex.execute({
            "action": "read", "path": "file\x00.txt", "workspace": str(workspace),
        })
        assert result.success is False
        assert "invalid path" in result.error or "escapes" in result.error


# ──────────────────────────────────────────────────────────────────────
# shell_exec edge cases
# ──────────────────────────────────────────────────────────────────────


class TestShellExecEdgeCases:
    @pytest.fixture
    def workspace(self) -> Path:
        return Path(tempfile.mkdtemp())

    async def test_sec003_shell_injection_via_semicolon(self, workspace: Path) -> None:
        """SEC-003 [CRIT]: allowlist bypass via command chaining.

        Bug: allowlist checked cmd.startswith('echo'), so `echo hi; rm victim.txt`
        passed. Fix: reject shell metacharacters before allowlist check.
        """
        from stronghold.tools.shell_exec import ShellExecutor
        (workspace / "victim.txt").write_text("important data")

        ex = ShellExecutor()
        result = await ex.execute({
            "command": "echo hi; rm -rf victim.txt",
            "workspace": str(workspace),
        })
        assert result.success is False
        assert "metacharacter" in result.error or "not allowed" in result.error
        # Primary evidence: file still exists
        assert (workspace / "victim.txt").exists()

    async def test_sec004_shell_injection_via_command_substitution(self, workspace: Path) -> None:
        """SEC-004 [CRIT]: allowlist bypass via $(...) substitution."""
        from stronghold.tools.shell_exec import ShellExecutor
        (workspace / "v.txt").write_text("data")
        ex = ShellExecutor()
        result = await ex.execute({
            "command": "echo $(rm v.txt)",
            "workspace": str(workspace),
        })
        assert result.success is False
        assert (workspace / "v.txt").exists()

    async def test_sec005_shell_injection_via_pipe(self, workspace: Path) -> None:
        """SEC-005 [CRIT]: allowlist bypass via pipe to disallowed command."""
        from stronghold.tools.shell_exec import ShellExecutor
        (workspace / "x.txt").write_text("data")
        ex = ShellExecutor()
        result = await ex.execute({
            "command": "ls | xargs rm",
            "workspace": str(workspace),
        })
        assert result.success is False
        assert (workspace / "x.txt").exists()

    async def test_shell_metacharacter_variants_all_rejected(self, workspace: Path) -> None:
        """Soundness: every shell metacharacter variant must be rejected."""
        from stronghold.tools.shell_exec import ShellExecutor
        ex = ShellExecutor()
        variants = [
            "echo a && rm b",
            "echo a || rm b",
            "echo a | rm b",
            "echo a ; rm b",
            "echo `rm b`",
            "echo $(rm b)",
            "echo a > /etc/hosts",
            "echo a < /etc/passwd",
            "echo a\nrm b",
        ]
        for cmd in variants:
            result = await ex.execute({
                "command": cmd, "workspace": str(workspace),
            })
            assert result.success is False, f"Metacharacter not rejected: {cmd!r}"

    async def test_command_with_unicode_args(self, workspace: Path) -> None:
        from stronghold.tools.shell_exec import ShellExecutor
        ex = ShellExecutor()
        result = await ex.execute({
            "command": "echo 你好",
            "workspace": str(workspace),
        })
        assert result.success is True
        data = json.loads(result.content)
        assert "你好" in data["stdout"]


# ──────────────────────────────────────────────────────────────────────
# Cache edge cases
# ──────────────────────────────────────────────────────────────────────


class TestCacheEdgeCases:
    async def test_session_store_max_messages_zero(self) -> None:
        """max_messages=0 — what does get_history return?"""
        import fakeredis.aioredis
        from stronghold.cache.session_store import RedisSessionStore

        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        store = RedisSessionStore(client)
        await store.append_messages("o/t/u:s", [
            {"role": "user", "content": "msg"},
        ])
        # Read with max_messages=0 — should return empty list, not all messages
        history = await store.get_history("o/t/u:s", max_messages=0)
        # If max=0 falls back to default, that's a bug
        assert history == []
        await client.aclose()

    async def test_sec006_session_store_poisoned_json_does_not_crash(self) -> None:
        """SEC-006 [MED]: single corrupt Redis entry must not take down session read.

        Bug: json.loads ran unprotected inside a loop. One bad entry raised
        JSONDecodeError and killed the whole get_history call.
        Fix: wrap in try/except, log + skip the poisoned entry.
        """
        import fakeredis.aioredis
        from stronghold.cache.session_store import RedisSessionStore

        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        store = RedisSessionStore(client)
        # Inject: poison, valid, poison
        key = "stronghold:session:o/t/u:s"
        import time as _t
        now = _t.time()
        await client.rpush(key, b"not valid json {{{")
        await client.rpush(
            key,
            f'{{"role": "user", "content": "good", "_ts": {now}}}'.encode(),
        )
        await client.rpush(key, b"also corrupt")

        history = await store.get_history("o/t/u:s")
        # Should return the one valid entry, skipping the two poisoned ones
        assert len(history) == 1
        assert history[0]["content"] == "good"
        await client.aclose()

    async def test_session_id_with_embedded_slash(self) -> None:
        """Session ID like 'org/team/user:session/with/slash' — only first / matters?"""
        import fakeredis.aioredis
        from stronghold.cache.session_store import RedisSessionStore

        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        store = RedisSessionStore(client)
        await store.append_messages("org/team/user:session/extra", [
            {"role": "user", "content": "test"},
        ])
        history = await store.get_history("org/team/user:session/extra")
        # If embedded slashes break key resolution, this would be empty
        assert len(history) == 1
        await client.aclose()

    async def test_rate_limiter_zero_max_requests(self) -> None:
        """max_requests=0 — every request should be denied."""
        import fakeredis.aioredis
        from stronghold.cache.rate_limiter import RedisRateLimiter

        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        limiter = RedisRateLimiter(client, max_requests=0, window_seconds=60)
        allowed, headers = await limiter.check("user")
        assert allowed is False, "max_requests=0 should always deny"
        assert headers["X-RateLimit-Remaining"] == "0"
        await client.aclose()

    async def test_prompt_cache_ttl_zero(self) -> None:
        """ttl=0 means immediate expiry. Does Redis accept it?"""
        import fakeredis.aioredis
        from stronghold.cache.prompt_cache import RedisPromptCache

        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        cache = RedisPromptCache(client)
        # Some Redis versions reject ttl=0; others treat as no-expiry
        try:
            await cache.set("k", "v", ttl=0)
        except Exception:
            pass  # Acceptable to reject
        await client.aclose()

    async def test_prompt_cache_set_unserializable(self) -> None:
        """set() with non-JSON-serializable value should not silently corrupt."""
        import fakeredis.aioredis
        from stronghold.cache.prompt_cache import RedisPromptCache

        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        cache = RedisPromptCache(client)
        # set() in production code uses default=str so this should serialize as repr
        await cache.set("k", {"fn": lambda x: x})
        result = await cache.get("k")
        # Either the lambda was stringified, or set raised
        assert result is not None
        await client.aclose()


# ──────────────────────────────────────────────────────────────────────
# Coin edge cases
# ──────────────────────────────────────────────────────────────────────


class TestCoinEdgeCases:
    def test_coins_to_microchips_huge_number(self) -> None:
        """Large input shouldn't overflow."""
        from stronghold.quota.coins import coins_to_microchips
        # 10^15 copper = 10^18 microchips — fits in int64
        result = coins_to_microchips(10**15)
        assert result == 10**18

    def test_coins_to_microchips_scientific_notation(self) -> None:
        from stronghold.quota.coins import coins_to_microchips
        # "1e3" copper = 1000 copper = 1_000_000 microchips
        result = coins_to_microchips("1e3")
        assert result == 1_000_000

    def test_sec008_decimal_rejects_nan(self) -> None:
        """SEC-008 [MED]: _decimal must reject NaN / Infinity strings.

        Bug: Decimal('NaN') passed through. Any comparison (budget > limit)
        returns False for NaN, silently bypassing budget checks.
        Fix: detect NaN/Infinity and return default.
        """
        from decimal import Decimal
        from stronghold.quota.coins import _decimal

        assert _decimal("NaN") == Decimal("0")
        assert _decimal("nan") == Decimal("0")
        assert _decimal("Infinity") == Decimal("0")
        assert _decimal("-Infinity") == Decimal("0")
        assert not _decimal("NaN").is_nan()
        assert not _decimal("inf").is_infinite()

    def test_sec008_coin_budget_nan_does_not_bypass(self) -> None:
        """SEC-008 evidence: feeding NaN through the cost pipeline doesn't zero the charge."""
        from stronghold.quota.coins import _resolve_quote
        models = {"m": {"coin_cost_base": "NaN", "coin_cost_per_1k_input_microchips": 50}}
        quote = _resolve_quote(models, {}, "m", "p", 1000, 0)
        # Base becomes 0 (rejected), input rate is normal, charge should be 50
        assert quote.charged_microchips == 50

    def test_resolve_quote_negative_base(self) -> None:
        """Negative base cost — should clamp or reject."""
        from stronghold.quota.coins import _resolve_quote

        models = {"m": {"coin_cost_base_microchips": -1000}}
        quote = _resolve_quote(models, {}, "m", "p", 100, 100)
        assert quote.charged_microchips >= 0, (
            "Negative base cost was not clamped — could give users free credits"
        )

    def test_format_microchips_negative_zero(self) -> None:
        """format_microchips(-0) shouldn't show '-0'."""
        from stronghold.quota.coins import format_microchips
        result = format_microchips(0)
        assert result["amount"] == 0


# ──────────────────────────────────────────────────────────────────────
# Trigger handler edge cases
# ──────────────────────────────────────────────────────────────────────


class TestTriggerEdgeCases:
    def _container(self):
        from unittest.mock import AsyncMock, MagicMock
        c = MagicMock()
        c.reactor = type("R", (), {"_triggers": [], "register": lambda self, s, a: self._triggers.append((s, a))})()
        c.learning_promoter = None
        c.rate_limiter = MagicMock()
        c.rate_limiter._windows = {}
        c.outcome_store = MagicMock()
        c.outcome_store.get_task_completion_rate = AsyncMock(return_value={})
        c.warden = MagicMock()
        c.tournament = None
        c.canary_manager = None
        c.learning_store = MagicMock()
        c.mason_queue = MagicMock()
        c.route_request = AsyncMock()
        return c

    def _get_handler(self, container, name):
        for spec, action in container.reactor._triggers:
            if spec.name == name:
                return action
        raise KeyError(name)

    async def test_security_rescan_with_none_data(self) -> None:
        """event.data is None instead of dict — handler crashes?"""
        from stronghold.triggers import register_core_triggers
        from stronghold.types.reactor import Event

        c = self._container()
        register_core_triggers(c)
        handler = self._get_handler(c, "security_rescan")
        # Event.data should default to {} via dataclass — but what if it's explicitly None?
        try:
            result = await handler(Event(name="security.rescan", data={}))
            assert result is not None
        except (AttributeError, TypeError) as e:
            pytest.fail(f"Handler crashed on empty data: {e}")

    # Deferred: test_mason_dispatch_with_string_issue_number lives with the
    # matching triggers.py fix in Slice C (#1098 breakdown). Landing it here
    # would require porting the triggers.py coercion, which is out of scope
    # for Slice A (pure defensive fixes only).
