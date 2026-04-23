# SEC-H3: Org-scoped admin mutations + role allowlist

## User Story

As a **tenant admin**, I want admin mutations on users to be org-scoped
by default and the role field to be validated against a known enum, so
that a non-system admin cannot escalate users in another tenant and no
admin can assign arbitrary role strings.

## Background

`src/stronghold/api/routes/admin.py:261–322, 399–424` implements
`/admin/users/{user_id}/approve`, `/reject`, and `PUT
/admin/users/{user_id}/roles`. Non-system admins rely on an `org_id`
filter that is not applied uniformly; `roles` is only validated as a
`list[str]`, with no allowlist against the project's role enum.

## Acceptance Criteria

- AC1: Given a non-system admin calls approve/reject/update-roles with a `user_id` that belongs to a different org, When the handler runs, Then it returns 404 (not 403 — no existence disclosure).
- AC2: Given `roles` contains any value not in `ALLOWED_ROLES = {"user", "team_admin", "org_admin", "admin"}`, When the handler runs, Then it returns 400 with `detail="invalid role"`.
- AC3: Given a system admin calls a cross-org mutation, When the handler runs, Then the request body MUST include `org_id` and an audit log entry is written with `actor`, `target_user`, `target_org`, `roles_before`, `roles_after`.
- AC4: Given an approve/reject/update-roles handler, When the database UPDATE runs, Then the WHERE clause includes `org_id = $N` for every path except the explicit system-admin cross-org path.

## Test Mapping

| AC  | Test path                                    | Test function                                | Tier     |
|-----|----------------------------------------------|----------------------------------------------|----------|
| AC1 | tests/api/test_admin_authz.py                | test_cross_org_mutation_returns_404          | critical |
| AC2 | tests/api/test_admin_authz.py                | test_unknown_role_rejected_400               | critical |
| AC3 | tests/api/test_admin_authz.py                | test_system_admin_cross_org_audited          | critical |
| AC4 | tests/api/test_admin_authz.py                | test_org_scoped_update_query_filter          | happy    |

## Files to Touch

- Modify: `src/stronghold/api/routes/admin.py` — add `_ALLOWED_ROLES` constant; add `org_id` WHERE clause to every user-mutation query; require `org_id` body field on system-admin cross-org path; add audit-log call.
- New: `tests/api/test_admin_authz.py`.
- Use: existing `PgAudit` helper.

## Rollback

Per-endpoint commits so each handler can be reverted independently. The
role allowlist is additive; existing callers passing valid roles are unaffected.
