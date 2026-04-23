# SEC-H5: Close DNS-rebinding gap in `/agents/import-url`

## User Story

As a **security auditor**, I want URL-import fetches to reject internal
IPs at connect time (not just at pre-check), so that DNS rebinding cannot
redirect fetches to cloud-metadata endpoints or internal services.

## Background

`src/stronghold/api/routes/agents.py:370–461` calls
`ip.is_private | is_loopback | is_link_local | is_reserved` at URL-parse
time. The subsequent `httpx` request re-resolves DNS. An attacker
controlling DNS for their domain can return a public IP during the check
and a private IP (e.g., `169.254.169.254`) during the actual connect.

## Acceptance Criteria

- AC1: Given a hostname that resolves to a public IP at check time, When the HTTP connect happens, Then the resolved IP is re-checked and rejected if private/loopback/link-local/reserved.
- AC2: Given an HTTP redirect response, When received, Then it is not followed (current behavior preserved with `follow_redirects=False`).
- AC3: Given the response body exceeds `IMPORT_URL_MAX_BYTES` (default 1 MiB), When streaming, Then the fetch aborts with 413-equivalent error.
- AC4: Given the fetch exceeds `IMPORT_URL_TIMEOUT_S` (default 10s), When running, Then it aborts with timeout error.
- AC5: Given any step rejects the URL, When the handler returns, Then the response body does not echo the resolved IP (avoid leaking internal topology).

## Test Mapping

| AC  | Test path                              | Test function                              | Tier     |
|-----|----------------------------------------|--------------------------------------------|----------|
| AC1 | tests/api/test_agents_import_url.py    | test_dns_rebinding_rejected_at_connect     | critical |
| AC2 | tests/api/test_agents_import_url.py    | test_redirect_not_followed                 | critical |
| AC3 | tests/api/test_agents_import_url.py    | test_body_over_max_bytes_aborted           | critical |
| AC4 | tests/api/test_agents_import_url.py    | test_fetch_timeout_enforced                | happy    |
| AC5 | tests/api/test_agents_import_url.py    | test_error_body_does_not_leak_ip           | happy    |

## Files to Touch

- Modify: `src/stronghold/api/routes/agents.py` — after `httpx` resolves, inspect the underlying socket (`transport.get_extra_info("peername")`) or use an HTTP client that accepts a pre-resolved `(ip, port)` tuple and re-check.
- Alternative: resolve DNS manually, pick a single public IP, pass `Host:` header + connect to IP (SNI needs `server_hostname`).
- New: `tests/api/test_agents_import_url.py` — use `httpx.MockTransport` + an ephemeral DNS fake.

## Rollback

Single-file revert. Consider feature-flagging `STRONGHOLD_IMPORT_URL_STRICT_SSRF=1` for a canary window.
