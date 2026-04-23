# SEC-H2: Require `webhook_org_id` when webhooks are mounted

## User Story

As a **tenant admin**, I want webhook endpoints rejected at startup if no
`webhook_org_id` is configured, so that a shared webhook secret cannot be
used to impersonate any org via the `X-Webhook-Org` header.

## Background

`src/stronghold/api/routes/webhooks.py:108–129` logs a warning and then
accepts whatever `X-Webhook-Org` the caller sends when
`config.webhook_org_id` is empty. Any holder of the bearer secret can
therefore act as any org. The bearer + timestamp + nonce checks
themselves are correct.

## Acceptance Criteria

- AC1: Given `STRONGHOLD_WEBHOOK_SECRET` is set and `webhook_org_id` is empty, When the app starts, Then startup fails with `ConfigError("webhook_org_id required when webhook endpoints enabled")`.
- AC2: Given both are set, When a webhook request arrives with a matching `X-Webhook-Org`, Then it is accepted as today.
- AC3: Given both are set, When a webhook request arrives with a mismatched `X-Webhook-Org`, Then it is rejected with 403.
- AC4: Given `STRONGHOLD_WEBHOOK_SECRET` is unset, When the app starts, Then webhook routes are not mounted at all (current behavior, preserved).

## Test Mapping

| AC  | Test path                                     | Test function                                  | Tier     |
|-----|-----------------------------------------------|------------------------------------------------|----------|
| AC1 | tests/api/test_webhooks.py                    | test_startup_fails_without_webhook_org_id      | critical |
| AC2 | tests/api/test_webhooks.py                    | test_matching_org_accepted                     | happy    |
| AC3 | tests/api/test_webhooks.py                    | test_mismatched_org_rejected_403               | critical |
| AC4 | tests/api/test_webhooks.py                    | test_webhook_routes_not_mounted_without_secret | happy    |

## Files to Touch

- Modify: `src/stronghold/api/routes/webhooks.py` — remove the "no expected org" fallback; require `webhook_org_id` unconditionally.
- Modify: `src/stronghold/api/app.py` (or the router-registration site) — assert `config.webhook_org_id` when registering webhook router.
- Modify: `src/stronghold/config/loader.py` — validate the pair `(webhook_secret, webhook_org_id)` must both be set or both empty.

## Rollback

Single-commit revert. Existing deployments that already set both values are unaffected.
