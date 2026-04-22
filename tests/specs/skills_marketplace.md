# Spec: `src/stronghold/skills/marketplace.py`

**Purpose:** Community-skill marketplace that fetches SKILL.md from URLs (with SSRF + DNS-rebinding defense), security-scans them, saves to the community directory, and registers them with a configurable trust tier (T2 by default).

**Coverage:** 92% (90/98). Missing: 36, 65-67, 93-94, 100-101.

## Test strategy

- Inject a fake `HTTPClient` that implements the `.get(url) -> HTTPResponse` protocol.
- Use `tmp_path` for `skills_dir`; use an in-memory SkillRegistry fake.
- For SSRF tests: feed URLs directly; don't mock `socket.getaddrinfo` unless testing the DNS branch.
- For DNS rebinding: monkeypatch `socket.getaddrinfo` to return private IP.

---

## `_is_blocked_ip(addr)` module function (line 36 uncovered)

**Contract:** Returns False for non-IP objects; True if `is_private|is_loopback|is_link_local|is_reserved|is_multicast`; False for public addresses.

**Uncovered:**
- **36** — the `if not isinstance(addr, (IPv4Address, IPv6Address)): return False` early-return branch.

**Test cases:**

1. `test_is_blocked_ip_returns_false_for_non_ip_object`
   - Action: `_is_blocked_ip("not an ip")` and `_is_blocked_ip(None)`.
   - Expect: False.

2. `test_is_blocked_ip_blocks_private_ipv4`
   - `_is_blocked_ip(IPv4Address("10.0.0.1"))` → True.
   - `_is_blocked_ip(IPv4Address("192.168.1.1"))` → True.

3. `test_is_blocked_ip_blocks_loopback_ipv6`
   - `_is_blocked_ip(IPv6Address("::1"))` → True.

4. `test_is_blocked_ip_permits_public`
   - `_is_blocked_ip(IPv4Address("8.8.8.8"))` → False.

---

## `_block_ssrf(url)` module function

**Contract:** Raises `ValueError("Blocked: ...")` on any violation. Steps:
1. urlparse — malformed → `ValueError("Blocked: malformed URL")`.
2. Hostname prefix match `metadata.` or `localhost` → blocked.
3. If hostname parses as IP literal:
   - Private/meta → blocked;
   - Public IP → return (skip DNS check).
4. Else DNS-resolve hostname; any returned IP private → blocked ("resolves to private/internal").
5. Unresolvable hostname → silently returns (will fail at fetch time).

**Uncovered branches:**
- **65-67** — urlparse exception path raising "malformed URL".
- **93-94** — literal-IP public path that returns without DNS check.
- **100-101** — DNS gaierror silent return path.

**Test cases:**

1. `test_block_ssrf_rejects_metadata_hostname`
   - Action: `_block_ssrf("https://metadata.google.internal/computeMetadata/v1/token")`.
   - Expect: `ValueError(match="private/metadata network")`.

2. `test_block_ssrf_rejects_localhost`
   - `_block_ssrf("http://localhost/x")` → raises.

3. `test_block_ssrf_rejects_private_ip_literal`
   - `_block_ssrf("http://10.0.0.5/x")` → raises with `private/metadata network (10.0.0.5)`.

4. `test_block_ssrf_rejects_ipv6_loopback`
   - `_block_ssrf("http://[::1]/x")` → raises.

5. `test_block_ssrf_rejects_integer_encoded_private_ip`
   - `_block_ssrf("http://2130706433/")` (integer form of 127.0.0.1) → raises (ipaddress.ip_address parses the integer).

6. `test_block_ssrf_allows_public_ip_literal_without_dns`
   - Setup: spy on `socket.getaddrinfo`.
   - Action: `_block_ssrf("https://8.8.8.8/x")`.
   - Expect: does NOT raise; getaddrinfo **not** called (literal-IP fast-path).

7. `test_block_ssrf_rejects_dns_rebinding_to_private`
   - Setup: monkeypatch `socket.getaddrinfo` → `[(_, _, _, "", ("10.1.2.3", 0))]`.
   - Action: `_block_ssrf("https://attacker.example.com/x")`.
   - Expect: raises, message includes `"resolves to private/internal"` and `"10.1.2.3"`.

8. `test_block_ssrf_allows_public_dns_resolution`
   - Setup: `getaddrinfo → [(_, _, _, "", ("8.8.8.8", 0))]`.
   - Action: returns None (no raise).

9. `test_block_ssrf_unresolvable_hostname_silently_passes`
   - Setup: `getaddrinfo` raises `socket.gaierror`.
   - Action: `_block_ssrf("https://nope.invalid/x")`.
   - Expect: returns None; no raise.

10. `test_block_ssrf_malformed_url`
    - Setup: monkeypatch `urlparse` to raise.
    - Action: `_block_ssrf("https://x")`.
    - Expect: `ValueError(match="malformed URL")`.

---

## `SkillMarketplaceImpl.search(query, max_results=10)`

**Contract:** Placeholder — always returns `[]`.

**Test cases:**

1. `test_search_returns_empty_list` — `await market.search("anything")` → `[]`.

---

## `SkillMarketplaceImpl.install(url, trust_tier="t2")`

**Contract:**
- Calls `_block_ssrf(url)` — raises on violation.
- Calls `self._http.get(url)`. Network exception → `ValueError("Failed to fetch skill from <url>: <e>")` with `__cause__`.
- Non-200 status → `ValueError("Skill fetch returned <status> from <url>")`.
- Security scan on content; reject → `ValueError("Skill rejected by security scan: ...")`.
- Parse; None → `ValueError("Failed to parse skill from <url>")`.
- Returns SkillDefinition with `.trust_tier == trust_tier` and `.source == url` (regardless of what was parsed).
- Writes to `<skills_dir>/community/<name>.md`, creates dir.
- Registers via `self._registry.register(skill)`.
- Logs info with name, url, tier, and count of findings starting with `"WARNING:"`.

**Invariants:**
- Registry `.register()` always called once on success; never on failure.
- File always written before register.

**Test cases:**

1. `test_install_ssrf_blocked_url_raises_before_http`
   - Setup: spy on fake http.get.
   - Action: `install("http://localhost/x")`.
   - Expect: `ValueError(match="private/metadata network")`; http.get not called.

2. `test_install_http_exception_wraps`
   - Setup: `http.get` raises `RuntimeError("net down")`.
   - Action: `install("https://example.com/s.md")`.
   - Expect: `ValueError(match="Failed to fetch skill from")` with the inner exception chained via `raise ... from e`.

3. `test_install_non_200_raises`
   - Setup: `http.get` returns `HTTPResponse(status_code=404, text="")`.
   - Expect: `ValueError(match="Skill fetch returned 404")`.

4. `test_install_security_scan_rejection`
   - Setup: 200 response with content containing `subprocess.Popen(`.
   - Expect: `ValueError(match="rejected by security scan")`; file NOT created; registry not called.

5. `test_install_parse_failure_raises`
   - Setup: 200 response with garbage content.
   - Expect: `ValueError(match="Failed to parse skill from")`.

6. `test_install_happy_path_saves_and_registers_at_default_tier`
   - Setup: 200 response with valid SKILL.md for `name: greeter`; fake registry.
   - Action: `install("https://example.com/greeter.md")`.
   - Expect: returned SkillDefinition with `.name=="greeter"`, `.trust_tier=="t2"`, `.source=="https://example.com/greeter.md"`; file exists at `<skills_dir>/community/greeter.md`; registry.register called once with this skill.

7. `test_install_honors_custom_trust_tier`
   - Action: `install(url, trust_tier="t3")`.
   - Expect: returned SkillDefinition `.trust_tier=="t3"`.

8. `test_install_creates_community_dir_if_missing`
   - Setup: `skills_dir=tmp_path/"new"` (doesn't exist).
   - Action: install.
   - Expect: `<skills_dir>/community/` created; file present.

9. `test_install_info_log_includes_warning_count`
   - Setup: content triggers security_scan to return `safe=True, findings=["WARNING: some warning"]`.
   - Action: install.
   - Expect: caplog INFO `"Installed skill 'greeter' from ... (tier=t2, warnings=1)"`.

---

## `SkillMarketplaceImpl.uninstall(name)`

**Contract:**
- File missing at `<skills_dir>/community/<name>.md` → `ValueError("Community skill '<name>' not found")`.
- Else unlink file, call `self._registry.delete(name)`, log info.

**Test cases:**

1. `test_uninstall_missing_raises`
   - Action: `market.uninstall("ghost")`.
   - Expect: `ValueError(match="Community skill 'ghost' not found")`; registry.delete not called.

2. `test_uninstall_removes_file_and_registry_entry`
   - Setup: pre-create `<skills_dir>/community/foo.md`; registry has `foo` registered.
   - Action: `uninstall("foo")`.
   - Expect: file gone; registry.delete called with `"foo"`; caplog INFO `"Uninstalled skill: foo"`.

---

## `HTTPResponse` / `HTTPClient` Protocol

Boilerplate. No tests beyond the implicit use in install tests.

---

## Intentionally uncovered

None.

## Contract gaps

- `_block_ssrf` treats `metadata.` as a hostname prefix. This catches `metadata.google.internal` and `metadata.example.com`. The latter is likely a false positive. Flag for future: use exact hostnames or stricter patterns.
- The DNS check runs `socket.getaddrinfo` synchronously inside an async function, blocking the event loop. Not a correctness bug, but a latency concern — out of scope for unit tests.

## Estimated tests: **~23 tests** across `_is_blocked_ip` (4), `_block_ssrf` (10), search (1), install (9), uninstall (2) — minus trivial sharing ≈ 23.
