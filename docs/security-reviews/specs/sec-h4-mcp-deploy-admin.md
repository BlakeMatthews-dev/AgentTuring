# SEC-H4: MCP server deploy requires `admin` role

## User Story

As a **platform operator**, I want MCP server deployment gated by the
`admin` role, so that any authenticated user cannot ship an arbitrary
Docker image into the shared K8s cluster.

## Background

`src/stronghold/api/routes/mcp.py` (deploy endpoint, ~line 152 onward)
authenticates the caller but does not verify role. `image` is taken from
the request body, meaning any authenticated user can deploy an
attacker-supplied container.

## Acceptance Criteria

- AC1: Given a caller without `admin` role, When they POST to the deploy endpoint, Then it returns 403.
- AC2: Given a caller with `admin` role, When they POST with a valid body, Then the deployment proceeds as today.
- AC3: Given `image` is provided, When validated, Then it must match `^[a-z0-9.\-/]+:[a-zA-Z0-9._\-]+$` AND the registry prefix must be in `MCP_IMAGE_REGISTRY_ALLOWLIST` (e.g., `ghcr.io/<org>/`, `<acr>.azurecr.io/`); otherwise 400.
- AC4: Given a successful deploy, When the audit log is written, Then it includes `actor`, `image`, `namespace`, and `scope`.

## Test Mapping

| AC  | Test path                              | Test function                              | Tier     |
|-----|----------------------------------------|--------------------------------------------|----------|
| AC1 | tests/api/test_mcp_deploy.py           | test_non_admin_cannot_deploy               | critical |
| AC2 | tests/api/test_mcp_deploy.py           | test_admin_can_deploy                      | happy    |
| AC3 | tests/api/test_mcp_deploy.py           | test_image_outside_allowlist_rejected      | critical |
| AC4 | tests/api/test_mcp_deploy.py           | test_deploy_is_audit_logged                | happy    |

## Files to Touch

- Modify: `src/stronghold/api/routes/mcp.py` — add `if "admin" not in auth.roles: raise HTTPException(403)`; add image-registry allowlist check; call audit log.
- Modify: `src/stronghold/types/config.py` — add `mcp.image_registry_allowlist: list[str]`.
- New: `tests/api/test_mcp_deploy.py`.

## Rollback

Single-commit revert. No data migration.
