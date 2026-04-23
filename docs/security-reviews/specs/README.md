# Security-Review Remediation Specs (2026-04-23)

One spec per finding from [`../2026-04-23-full-codebase-audit.md`]. Each
spec has a user story, acceptance criteria, test mapping, files to touch,
and a rollback note.

## Order of work

Ship in this sequence (each row is a single PR):

| # | Spec | Severity | Why this order |
|---|------|----------|----------------|
| 1 | [sec-c1-shell-injection](sec-c1-shell-injection.md)        | Critical | Highest blast radius; blocks #2. |
| 2 | [sec-c2-github-token-argv](sec-c2-github-token-argv.md)    | Critical | Needs #1's env-scrubbing machinery. |
| 3 | [sec-h1-tool-policy-fail-open](sec-h1-tool-policy-fail-open.md) | High | Misconfiguration becomes fatal; unblocks tighter policy work. |
| 4 | [sec-h2-webhook-org-spoof](sec-h2-webhook-org-spoof.md)    | High | One-file change; low risk. |
| 5 | [sec-h4-mcp-deploy-admin](sec-h4-mcp-deploy-admin.md)      | High | Independent; ship anytime. |
| 6 | [sec-h3-admin-authz](sec-h3-admin-authz.md)                | High | Touches many admin handlers; do after #3/#4/#5 to amortize review. |
| 7 | [sec-h5-ssrf-dns-rebinding](sec-h5-ssrf-dns-rebinding.md)  | High | Needs design decision on HTTP client; feature-flag. |
| 8 | [sec-h6-sentinel-fallback](sec-h6-sentinel-fallback.md)    | High | Refactor; do after Criticals land. |
| 9 | [sec-m2-demo-cookie-issuer](sec-m2-demo-cookie-issuer.md)  | Medium | Trivial; pair with #4. |
| 10 | [sec-m4-dockerfile-nonroot](sec-m4-dockerfile-nonroot.md) | Medium | Deploy-path; coordinate with Helm chart owner. |
| 11 | [sec-m5-compose-password](sec-m5-compose-password.md)     | Medium | Dev-ergonomics; docs update. |

## Convention

These follow [`../../specs/CONVENTIONS.md`](../../specs/CONVENTIONS.md)
with two relaxations:

- No `Evidence References` section (findings are first-party, not drawn from external research).
- No `Open Questions` section unless there is a genuine design question (see #7).

## Not specced here

Low-severity items L-1 through L-7 from the review are left as TODO
comments in a follow-up sweep. They are hardening, not remediation.
