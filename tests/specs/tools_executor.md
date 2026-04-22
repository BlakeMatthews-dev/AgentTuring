# Spec: `src/stronghold/tools/executor.py`

**Purpose:** Tool dispatcher that routes tool calls to registered executors with timeout protection and falls back to HTTP endpoints (with SSRF + DNS-rebinding protection) when no local executor is registered.

**Coverage:** 81% (61/75). Missing: 151-152, 158-159, 167, 199-201, 206-212, 226-227, 229-230.

## Test strategy

- `InMemoryToolRegistry` fake already exists; use it to register real executors for the happy path.
- For HTTP-fallback tests: register a `ToolDefinition` with an `endpoint` URL but no executor, then monkeypatch `httpx.AsyncClient` to an injected MockTransport.
- For DNS-rebinding tests: monkeypatch `socket.getaddrinfo` to return a fake tuple list.

---

## `ToolDispatcher.execute(tool_name, arguments) -> str`

**Contract:**
- Returns a **string** (for LLM consumption) — not ToolResult.
- Unregistered tool with no endpoint → `"Error: Tool '<name>' not registered"`.
- Unregistered tool with HTTPS endpoint → delegate to `_execute_http`.
- Registered executor timeout (`asyncio.TimeoutError`) → `"Error: Tool '<name>' timed out after <Ns>"`; warning log.
- Registered executor exception → `"Error: Tool '<name>' failed: <msg>"`; warning log.
- Registered executor success → `result.content`.
- Registered executor unsuccessful ToolResult → `"Error: <error>"`.

**Invariants:** never raises; always returns a string; timeout is `self._default_timeout` (default 30.0).

**Uncovered branches:**
- **151-152** — TimeoutError path (executor exceeds timeout).
- **158-159** — generic Exception path.
- **167** — SSRF prefix match return (one specific prefix branch).

**Test cases:**

1. `test_execute_unregistered_tool_no_endpoint_returns_error_string`
   - Setup: empty registry.
   - Action: `await dispatcher.execute("ghost", {})`.
   - Expect: `== "Error: Tool 'ghost' not registered"`.

2. `test_execute_registered_success_returns_content`
   - Setup: register fake executor returning `ToolResult(content="hello", success=True)`.
   - Action: `await dispatcher.execute("fake", {"x": 1})`.
   - Expect: `== "hello"`.

3. `test_execute_registered_unsuccessful_returns_error_prefixed`
   - Setup: executor returns `ToolResult(success=False, error="bad args")`.
   - Expect: `== "Error: bad args"`.

4. `test_execute_timeout_returns_error_and_logs_warning`
   - Setup: executor sleeps `asyncio.sleep(5)`; `default_timeout=0.05`.
   - Action: execute.
   - Expect: returned string == `"Error: Tool 'slow' timed out after 0.05s"`; warning log `"timed out"`.

5. `test_execute_executor_exception_returns_error_and_logs`
   - Setup: executor raises `RuntimeError("boom")`.
   - Expect: returned string == `"Error: Tool 'crashy' failed: boom"`; warning log mentions failure.

---

## `_execute_http(endpoint, tool_name, arguments)` — HTTP fallback (lines 199-230)

**Contract:**
- Any endpoint whose lowercased prefix matches `_BLOCKED_URL_PREFIXES` → returns `"Error: Tool endpoint blocked by security policy"`; warning logged.
- Non-`https://` endpoint (not in blocklist, e.g. `http://public.example.com`) → returns `"Error: Tool endpoints must use HTTPS"`; warning logged.
- Malformed URL (urlparse raises) → `"Error: Malformed tool endpoint URL"`.
- DNS resolution returns a private/loopback/link-local/reserved/multicast IP → `"Error: Tool endpoint blocked by security policy"`; specific warning `"SSRF DNS rebinding blocked"`.
- Successful POST 200 → returns `str(data.get("result", data.get("content", str(data))))`.
- Non-200 → `"Error: HTTP tool returned <status>"`.
- Exception during POST → `"Error: HTTP tool '<name>' failed: <e>"`.

**Invariants:**
- `follow_redirects=False` on the httpx client (hard requirement for SSRF safety — redirects can bypass checks).
- Outbound JSON body is `{"tool_name": <name>, "arguments": <args>}`.

**Uncovered branches:**
- **199-201** — urlparse exception path (malformed URL).
- **206-212** — DNS rebinding detection branch.
- **226-227, 229-230** — POST response handling (non-200 status and exception wrap).

**Test cases:**

1. `test_http_fallback_blocks_loopback`
   - Setup: definition with `endpoint="http://127.0.0.1:8080/x"`, no executor.
   - Action: `await dispatcher.execute("remote", {})`.
   - Expect: `== "Error: Tool endpoint blocked by security policy"`; warning log contains `"SSRF blocked"`.

2. `test_http_fallback_blocks_metadata_ip`
   - Setup: `endpoint="http://169.254.169.254/latest/meta-data/"`.
   - Expect: blocked with same error string.

3. `test_http_fallback_blocks_rfc1918_10_x`
   - Setup: `endpoint="http://10.1.2.3/x"`.
   - Expect: blocked.

4. `test_http_fallback_blocks_file_scheme`
   - Setup: `endpoint="file:///etc/passwd"`.
   - Expect: blocked.

5. `test_http_fallback_requires_https`
   - Setup: `endpoint="http://public.example.com/x"` (public HTTP, not blocklisted).
   - Expect: `== "Error: Tool endpoints must use HTTPS"`; warning log "Non-HTTPS endpoint".

6. `test_http_fallback_malformed_url_returns_malformed_error`
   - Setup: `endpoint="https://"` then monkeypatch `urlparse` in module to raise.
   - Expect: `== "Error: Malformed tool endpoint URL"`.
   - Alt: use a URL with a hostname that the module's urlparse still handles; also verify empty hostname skips the DNS check.

7. `test_http_fallback_dns_rebinding_blocks_private_resolution`
   - Setup: `endpoint="https://evil.example.com/x"`; monkeypatch `socket.getaddrinfo` to return `[(AF_INET, SOCK_STREAM, 0, "", ("10.0.0.5", 0))]`.
   - Expect: `== "Error: Tool endpoint blocked by security policy"`; warning log mentions DNS rebinding and resolved IP `10.0.0.5`.

8. `test_http_fallback_public_dns_proceeds`
   - Setup: monkeypatch getaddrinfo → `[(_, _, _, "", ("93.184.216.34", 0))]` (example.com public IP).
   - Monkeypatch `httpx.AsyncClient` MockTransport → 200 `{"result":"ok"}`.
   - Expect: returned string `"ok"`.

9. `test_http_fallback_unresolvable_hostname_proceeds_to_connect_fail`
   - Setup: monkeypatch getaddrinfo to raise `socket.gaierror`.
   - Monkeypatch httpx to raise `httpx.ConnectError`.
   - Expect: `.startswith("Error: HTTP tool 'x' failed: ")`.

10. `test_http_fallback_200_extracts_result_field`
    - Setup: public DNS; mock transport returns 200 `{"result": "hi"}`.
    - Expect: `== "hi"`.

11. `test_http_fallback_200_falls_back_to_content_then_str`
    - Setup: mock returns 200 `{"content": "hello"}`.
    - Expect: `== "hello"`.
    - And with `{"foo": 1}` → `str({"foo": 1})`.

12. `test_http_fallback_non_200_returns_status_error`
    - Setup: mock returns 500.
    - Expect: `== "Error: HTTP tool returned 500"`.

13. `test_http_fallback_no_redirects`
    - Setup: mock returns 302 with Location → internal IP.
    - Expect: first response treated as non-200 (`Error: HTTP tool returned 302`); never follows.

14. `test_http_fallback_exception_wraps`
    - Setup: mock transport raises `httpx.ReadTimeout`.
    - Expect: string starts with `"Error: HTTP tool 'x' failed: "`.

---

## `_resolve_blocks_private(hostname)` — static helper

**Contract:** resolves hostname; returns offending IP string if any resolved address is private/loopback/link-local/reserved/multicast; `None` otherwise (including unresolvable).

**Test cases:**

1. `test_resolve_blocks_private_returns_none_for_public` — getaddrinfo → public IP → returns None.
2. `test_resolve_blocks_private_returns_ip_for_private` — getaddrinfo → `10.0.0.1` → returns `"10.0.0.1"`.
3. `test_resolve_blocks_private_returns_none_on_gaierror` — getaddrinfo raises → returns None.
4. `test_resolve_blocks_private_skips_malformed_sockaddr` — getaddrinfo returns an entry whose sockaddr[0] isn't a valid IP string → returns None (the `continue`).
5. `test_resolve_blocks_private_catches_ipv6_link_local` — getaddrinfo → `("fe80::1", 0, 0, 0)` → returns the IP string.

---

## Intentionally uncovered

None listed. All missing lines are reachable through public `execute()` with the right setup.

## Contract gaps

- The blocklist is a static prefix-match — a URL like `http://127.0.0.1.nip.io` (public hostname that *resolves* to 127.0.0.1) is handled by the DNS-resolution step. Spec tests cover both prefix and DNS paths.
- `str(data)` path (when neither `result` nor `content` present) is tested but the module's behavior for non-JSON 200 responses (e.g., HTML) is undefined — `resp.json()` would raise, caught by the outer try → wrapped as `"Error: HTTP tool '<n>' failed: ..."`. Spec asserts this generic-exception path.

## Estimated tests: **~20 tests** (5 for execute + 14 for _execute_http + 5 for _resolve_blocks_private).
