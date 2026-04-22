"""Tests for tool dispatcher: routing, timeout, HTTP fallback."""

import pytest

from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.types.tool import ToolDefinition, ToolResult


class TestBasicDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_to_registered_executor(self) -> None:
        reg = InMemoryToolRegistry()

        async def echo(args: dict) -> ToolResult:  # type: ignore[type-arg]
            return ToolResult(content=f"echo: {args.get('msg', '')}")

        reg.register(ToolDefinition(name="echo", description="echo"), executor=echo)
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("echo", {"msg": "hello"})
        assert result == "echo: hello"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        reg = InMemoryToolRegistry()
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("nonexistent", {})
        assert "not registered" in result

    @pytest.mark.asyncio
    async def test_executor_error_returns_error_string(self) -> None:
        reg = InMemoryToolRegistry()

        async def failing(args: dict) -> ToolResult:  # type: ignore[type-arg]
            msg = "boom"
            raise RuntimeError(msg)

        reg.register(ToolDefinition(name="fail", description="fail"), executor=failing)
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("fail", {})
        assert "Error" in result
        assert "boom" in result

    @pytest.mark.asyncio
    async def test_executor_returning_error_result(self) -> None:
        reg = InMemoryToolRegistry()

        async def err(args: dict) -> ToolResult:  # type: ignore[type-arg]
            return ToolResult(content="", success=False, error="bad input")

        reg.register(ToolDefinition(name="err", description="err"), executor=err)
        dispatcher = ToolDispatcher(reg)
        result = await dispatcher.execute("err", {})
        assert "bad input" in result


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error(self) -> None:
        import asyncio

        reg = InMemoryToolRegistry()

        async def slow(args: dict) -> ToolResult:  # type: ignore[type-arg]
            await asyncio.sleep(10)
            return ToolResult(content="done")

        reg.register(ToolDefinition(name="slow", description="slow"), executor=slow)
        dispatcher = ToolDispatcher(reg, default_timeout=0.1)
        result = await dispatcher.execute("slow", {})
        assert "timed out" in result


class TestHTTPFallback:
    @pytest.mark.asyncio
    async def test_tool_with_endpoint_uses_http(self) -> None:
        """Tool with endpoint but no executor should try HTTP (will fail in test)."""
        reg = InMemoryToolRegistry()
        reg.register(
            ToolDefinition(
                name="remote",
                description="remote tool",
                endpoint="http://localhost:99999/nonexistent",
            )
        )
        dispatcher = ToolDispatcher(reg, default_timeout=2.0)
        result = await dispatcher.execute("remote", {"q": "test"})
        assert "Error" in result  # HTTP will fail (no server)


# ─────────────────────────────────────────────────────────────────────
# Execute dispatcher — additional coverage (TimeoutError, exception path,
# and the string-return contract for successful results).
# ─────────────────────────────────────────────────────────────────────

import asyncio  # noqa: E402
import logging  # noqa: E402
import socket  # noqa: E402

import httpx  # noqa: E402
from pytest import LogCaptureFixture, MonkeyPatch  # noqa: E402

from stronghold.tools.executor import ToolDispatcher as _Dispatcher  # noqa: E402


class TestExecuteEdgeCases:
    """Covers lines 151-152 (TimeoutError branch), 158-159 (exception branch)."""

    async def test_execute_unregistered_tool_no_endpoint_returns_error_string(self) -> None:
        reg = InMemoryToolRegistry()
        d = ToolDispatcher(reg)
        result = await d.execute("ghost", {})
        assert result == "Error: Tool 'ghost' not registered"

    async def test_execute_registered_success_returns_content(self) -> None:
        reg = InMemoryToolRegistry()

        async def fake(args: dict) -> ToolResult:  # type: ignore[type-arg]
            return ToolResult(content="hello", success=True)

        reg.register(ToolDefinition(name="fake", description=""), executor=fake)
        d = ToolDispatcher(reg)
        result = await d.execute("fake", {"x": 1})
        assert result == "hello"

    async def test_execute_registered_unsuccessful_returns_error_prefixed(self) -> None:
        reg = InMemoryToolRegistry()

        async def fake(args: dict) -> ToolResult:  # type: ignore[type-arg]
            return ToolResult(content="", success=False, error="bad args")

        reg.register(ToolDefinition(name="fake", description=""), executor=fake)
        d = ToolDispatcher(reg)
        result = await d.execute("fake", {})
        assert result == "Error: bad args"

    async def test_execute_timeout_returns_error_and_logs_warning(
        self, caplog: LogCaptureFixture,
    ) -> None:
        reg = InMemoryToolRegistry()

        async def slow(args: dict) -> ToolResult:  # type: ignore[type-arg]
            await asyncio.sleep(5)
            return ToolResult(content="nope")

        reg.register(ToolDefinition(name="slow", description=""), executor=slow)
        d = ToolDispatcher(reg, default_timeout=0.05)
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.executor"):
            result = await d.execute("slow", {})
        assert result == "Error: Tool 'slow' timed out after 0.05s"
        assert any("timed out" in rec.message for rec in caplog.records)

    async def test_execute_executor_exception_returns_error_and_logs(
        self, caplog: LogCaptureFixture,
    ) -> None:
        reg = InMemoryToolRegistry()

        async def crashy(args: dict) -> ToolResult:  # type: ignore[type-arg]
            raise RuntimeError("boom")

        reg.register(ToolDefinition(name="crashy", description=""), executor=crashy)
        d = ToolDispatcher(reg)
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.executor"):
            result = await d.execute("crashy", {})
        assert result == "Error: Tool 'crashy' failed: boom"
        assert any("failed" in rec.message for rec in caplog.records)


# ─────────────────────────────────────────────────────────────────────
# _execute_http — SSRF prefix blocklist
# ─────────────────────────────────────────────────────────────────────


class TestHTTPFallbackSSRFPrefix:
    async def _dispatch_with(self, endpoint: str) -> str:
        reg = InMemoryToolRegistry()
        reg.register(
            ToolDefinition(name="remote", description="", endpoint=endpoint),
        )
        d = ToolDispatcher(reg, default_timeout=1.0)
        return await d.execute("remote", {})

    async def test_http_fallback_blocks_loopback(
        self, caplog: LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.executor"):
            result = await self._dispatch_with("http://127.0.0.1:8080/x")
        assert result == "Error: Tool endpoint blocked by security policy"
        assert any("SSRF blocked" in rec.message for rec in caplog.records)

    async def test_http_fallback_blocks_metadata_ip(self) -> None:
        result = await self._dispatch_with("http://169.254.169.254/latest/meta-data/")
        assert result == "Error: Tool endpoint blocked by security policy"

    async def test_http_fallback_blocks_rfc1918_10_x(self) -> None:
        result = await self._dispatch_with("http://10.1.2.3/x")
        assert result == "Error: Tool endpoint blocked by security policy"

    async def test_http_fallback_blocks_file_scheme(self) -> None:
        result = await self._dispatch_with("file:///etc/passwd")
        assert result == "Error: Tool endpoint blocked by security policy"

    async def test_http_fallback_requires_https(
        self, caplog: LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.executor"):
            result = await self._dispatch_with("http://public.example.com/x")
        assert result == "Error: Tool endpoints must use HTTPS"
        assert any("Non-HTTPS endpoint" in rec.message for rec in caplog.records)


# ─────────────────────────────────────────────────────────────────────
# _execute_http — DNS rebinding + malformed URL + 2xx/non-2xx/exception
# ─────────────────────────────────────────────────────────────────────


def _addrinfo_entry(ip: str):
    """Construct a getaddrinfo-style tuple for a given IP."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    # (family, type, proto, canonname, sockaddr)
    if ":" in ip:
        return (family, socket.SOCK_STREAM, 0, "", (ip, 0, 0, 0))
    return (family, socket.SOCK_STREAM, 0, "", (ip, 0))


class TestHTTPFallbackDNS:
    async def _dispatch_with(
        self,
        endpoint: str,
        monkeypatch: MonkeyPatch,
        *,
        getaddrinfo=None,
        http_handler=None,
    ) -> str:
        if getaddrinfo is not None:
            # Patch the socket module used internally in _resolve_blocks_private
            monkeypatch.setattr("socket.getaddrinfo", getaddrinfo)

        if http_handler is not None:
            transport = httpx.MockTransport(http_handler)
            orig_init = httpx.AsyncClient.__init__

            def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                kwargs["transport"] = transport
                orig_init(self, *args, **kwargs)

            monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)

        reg = InMemoryToolRegistry()
        reg.register(
            ToolDefinition(name="x", description="", endpoint=endpoint),
        )
        d = ToolDispatcher(reg, default_timeout=1.0)
        return await d.execute("x", {"q": 1})

    async def test_http_fallback_malformed_url_returns_malformed_error(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        # Force urlparse to raise inside _execute_http.
        from stronghold.tools import executor as mod

        def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise ValueError("bad url")

        # urlparse is imported inline in _execute_http via `from urllib.parse
        # import urlparse` each call — patch at the source module.
        import urllib.parse as up
        monkeypatch.setattr(up, "urlparse", boom)

        reg = InMemoryToolRegistry()
        reg.register(
            ToolDefinition(name="y", description="", endpoint="https://ok.example.com/x"),
        )
        d = mod.ToolDispatcher(reg, default_timeout=1.0)
        result = await d.execute("y", {})
        assert result == "Error: Malformed tool endpoint URL"

    async def test_http_fallback_dns_rebinding_blocks_private_resolution(
        self, monkeypatch: MonkeyPatch, caplog: LogCaptureFixture,
    ) -> None:
        def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("10.0.0.5")]

        with caplog.at_level(logging.WARNING, logger="stronghold.tools.executor"):
            result = await self._dispatch_with(
                "https://evil.example.com/x",
                monkeypatch,
                getaddrinfo=fake_getaddrinfo,
            )
        assert result == "Error: Tool endpoint blocked by security policy"
        assert any(
            "SSRF DNS rebinding" in rec.message and "10.0.0.5" in rec.message
            for rec in caplog.records
        )

    async def test_http_fallback_public_dns_proceeds(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/x"
            return httpx.Response(200, json={"result": "ok"})

        result = await self._dispatch_with(
            "https://public.example.com/x",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler,
        )
        assert result == "ok"

    async def test_http_fallback_unresolvable_hostname_proceeds_to_connect_fail(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_getaddrinfo(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise socket.gaierror("no such host")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("cannot connect")

        result = await self._dispatch_with(
            "https://missing.example.com/x",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler,
        )
        assert result.startswith("Error: HTTP tool 'x' failed: ")

    async def test_http_fallback_200_extracts_result_field(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_getaddrinfo(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": "hi"})

        result = await self._dispatch_with(
            "https://public.example.com/y",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler,
        )
        assert result == "hi"

    async def test_http_fallback_200_falls_back_to_content_then_str(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_getaddrinfo(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        def handler1(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"content": "hello"})

        result = await self._dispatch_with(
            "https://public.example.com/a",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler1,
        )
        assert result == "hello"

    async def test_http_fallback_200_unknown_shape_is_stringified(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_getaddrinfo(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"foo": 1})

        result = await self._dispatch_with(
            "https://public.example.com/b",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler,
        )
        assert result == str({"foo": 1})

    async def test_http_fallback_non_200_returns_status_error(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_getaddrinfo(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="oops")

        result = await self._dispatch_with(
            "https://public.example.com/c",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler,
        )
        assert result == "Error: HTTP tool returned 500"

    async def test_http_fallback_no_redirects(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        """follow_redirects=False: a 302 is returned as non-200, never followed."""
        def fake_getaddrinfo(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "http://10.0.0.1/evil"})

        result = await self._dispatch_with(
            "https://public.example.com/d",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler,
        )
        assert result == "Error: HTTP tool returned 302"

    async def test_http_fallback_exception_wraps(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_getaddrinfo(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        result = await self._dispatch_with(
            "https://public.example.com/e",
            monkeypatch,
            getaddrinfo=fake_getaddrinfo,
            http_handler=handler,
        )
        assert result.startswith("Error: HTTP tool 'x' failed: ")


# ─────────────────────────────────────────────────────────────────────
# _resolve_blocks_private — static helper
# ─────────────────────────────────────────────────────────────────────


class TestResolveBlocksPrivate:
    def test_resolve_blocks_private_returns_none_for_public(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_gai(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("93.184.216.34")]

        monkeypatch.setattr("socket.getaddrinfo", fake_gai)
        assert _Dispatcher._resolve_blocks_private("example.com") is None

    def test_resolve_blocks_private_returns_ip_for_private(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_gai(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("10.0.0.1")]

        monkeypatch.setattr("socket.getaddrinfo", fake_gai)
        assert _Dispatcher._resolve_blocks_private("intranet") == "10.0.0.1"

    def test_resolve_blocks_private_returns_none_on_gaierror(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_gai(*a, **k):  # type: ignore[no-untyped-def]
            raise socket.gaierror("no host")

        monkeypatch.setattr("socket.getaddrinfo", fake_gai)
        assert _Dispatcher._resolve_blocks_private("nope") is None

    def test_resolve_blocks_private_skips_malformed_sockaddr(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_gai(*a, **k):  # type: ignore[no-untyped-def]
            # sockaddr[0] is not a valid IP string → continue
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("not-an-ip", 0))]

        monkeypatch.setattr("socket.getaddrinfo", fake_gai)
        assert _Dispatcher._resolve_blocks_private("host") is None

    def test_resolve_blocks_private_catches_ipv6_link_local(
        self, monkeypatch: MonkeyPatch,
    ) -> None:
        def fake_gai(*a, **k):  # type: ignore[no-untyped-def]
            return [_addrinfo_entry("fe80::1")]

        monkeypatch.setattr("socket.getaddrinfo", fake_gai)
        assert _Dispatcher._resolve_blocks_private("ll") == "fe80::1"
