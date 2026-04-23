# SEC-M2: Demo-cookie middleware must verify JWT `issuer`

## User Story

As a **security auditor**, I want the demo-cookie middleware to match the
provider's JWT validation, so that tokens with a wrong `issuer` are
rejected at the middleware layer instead of only at the provider layer.

## Background

`src/stronghold/api/middleware/demo_cookie.py:74–79` decodes the JWT with
`audience="stronghold"` only. The provider at
`src/stronghold/security/auth_demo_cookie.py:79` additionally validates
`issuer="stronghold-demo"`. The provider re-checks downstream (so this is
defense-in-depth overlap, not a bypass), but the middleware's
pre-injection filter is weaker than the provider.

## Acceptance Criteria

- AC1: Given a cookie with a valid signature and audience but wrong `issuer`, When the middleware runs, Then no `Authorization` header is injected (request continues without auth).
- AC2: Given a cookie with the correct issuer, When the middleware runs, Then the `Bearer demo-jwt:…` header is injected as today.
- AC3: Given the middleware and provider share the same expected issuer constant, When one is updated, Then both update together (no drift).

## Test Mapping

| AC  | Test path                                     | Test function                              | Tier     |
|-----|-----------------------------------------------|--------------------------------------------|----------|
| AC1 | tests/api/test_demo_cookie_middleware.py      | test_wrong_issuer_not_injected             | critical |
| AC2 | tests/api/test_demo_cookie_middleware.py      | test_correct_issuer_injected               | happy    |
| AC3 | tests/api/test_demo_cookie_middleware.py      | test_issuer_constant_shared                | happy    |

## Files to Touch

- New: `src/stronghold/security/auth_demo_cookie.py` — export `DEMO_JWT_ISSUER = "stronghold-demo"` and `DEMO_JWT_AUDIENCE = "stronghold"` constants.
- Modify: `src/stronghold/api/middleware/demo_cookie.py` — import and use both constants in `pyjwt.decode`.
- Modify: `src/stronghold/security/auth_demo_cookie.py` — use the same constants.
- New: `tests/api/test_demo_cookie_middleware.py`.

## Rollback

Trivial revert — tiny change.
