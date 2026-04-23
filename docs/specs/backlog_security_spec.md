# Backlog Security Issues Specification

**Status**: DRAFT  
**Phase**: 3 - HIGH Priority  
**Related Issues**: R7, R8, R11, R14, R27 from red team audit  
**Backlog Reference**: BACKLOG.md lines 98-100, 84-100

---

## 1. Purpose

Resolve HIGH-priority security findings from live red team exercise (2026-03-31). These issues bypass application-level controls and expose the attack surface.

---

## 2. Issue Summary

| Issue | ID | Severity | Description | Impact |
|--------|-----|----------|-------------|
| API docs exposed | R7 | HIGH | `/docs`, `/redoc` return full API schema without auth |
| Static API key grants all roles | R8 | HIGH | Single key grants SYSTEM_AUTH with all admin roles |
| Agent tool validation missing | R11 | HIGH | Agent creation accepts arbitrary tool names without validation |
| API key length weak | R14 | HIGH | Keys shorter than 32 chars accepted with only a warning |
| Prompt PUT error handling | R27 | MEDIUM | `PUT /prompts` returns 500 instead of proper error |

---

## 3. R7: Gate API Docs Behind Auth

### 3.1 Current State

**Files**:
- `src/stronghold/api/app.py:55-60` (docs enabled by default)
- `src/stronghold/middleware/rate_limit.py:29` (docs exempt from rate limiting)

**Behavior**:
```python
app = FastAPI(
    title="Stronghold API",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
```

**Attack Vector**: Attacker accesses `https://stronghold.example.com/docs` → gets complete API surface map → plans targeted attacks.

### 3.2 Solution

**Add Configuration Flag**:
```python
# config/loader.py
DOCS_ENABLED = os.getenv("STRONGHOLD_DOCS_ENABLED", "false").lower() == "true"
```

**Conditional Docs**:
```python
# api/app.py
from stronghold.config.loader import load_config

config = load_config()

app = FastAPI(
    title="Stronghold API",
    docs_url="/docs" if config.api.docs_enabled else None,
    redoc_url="/redoc" if config.api.docs_enabled else None,
    openapi_url="/openapi.json" if config.api.docs_enabled else None,
)
```

**Update Rate Limiter**:
```python
# middleware/rate_limit.py
# Remove docs exemption
paths = []  # Rate limit all paths, including /docs, /redoc, /openapi.json
```

**Add to StrongholdConfig**:
```python
# types/config.py
@dataclass
class ApiConfig:
    docs_enabled: bool = False
```

### 3.3 Acceptance Criteria

**AC-R7-1: Production Disables Docs**
**Given** `STRONGHOLD_DOCS_ENABLED=false` (default)
**When** FastAPI app is created
**Then**:
- `/docs` returns 404
- `/redoc` returns 404
- `/openapi.json` returns 404

**AC-R7-2: Development Enables Docs**
**Given** `STRONGHOLD_DOCS_ENABLED=true`
**When** FastAPI app is created
**Then**:
- `/docs` returns interactive Swagger UI
- `/redoc` returns ReDoc documentation
- `/openapi.json` returns OpenAPI schema

**AC-R7-3: Rate Limiting Applied to Docs**
**Given** Rate limiter configured
**When** More than 100 requests to `/docs` in 1 minute
**Then**:
- Rate limit error is returned (429)
- Docs endpoint is NOT exempt from rate limiting

---

## 4. R8: Implement API Key Scoping

### 4.1 Current State

**File**: `src/stronghold/security/auth_static.py:50`

**Behavior**:
```python
class StaticKeyAuthProvider(AuthProvider):
    def authenticate(self, api_key: str) -> AuthContext:
        if api_key == ROUTER_API_KEY:
            return AuthContext(
                user_id="__system__",
                org_id="__system__",
                identity=Identity.SYSTEM_AUTH,
                roles={Role.ADMIN, Role.ORG_ADMIN, Role.TEAM_ADMIN, Role.USER},
            )
```

**Attack Vector**: Attacker steals `ROUTER_API_KEY` → gets full admin access → dumps all users, creates malicious agents, etc.

### 4.2 Solution

**New Key Type Enum**:
```python
# types/auth.py
from enum import Enum

class KeyType(Enum):
    ADMIN = "admin"           # Full admin access
    READ_ONLY = "read_only"    # Read-only, no admin endpoints
    USER = "user"            # User-scoped, limited to user's resources
```

**Key Metadata Model**:
```python
# types/auth.py
@dataclass
class APIKey:
    key_id: str
    key_hash: str  # sha256 hash of key
    key_type: KeyType
    user_id: str | None  # None for admin keys
    roles: set[Role]
    created_at: datetime
    expires_at: datetime | None
```

**Key Storage**:
```python
# persistence/pg_api_keys.py (new table)
CREATE TABLE api_keys (
    key_id UUID PRIMARY KEY,
    key_hash VARCHAR(64) UNIQUE NOT NULL,
    key_type VARCHAR(20) NOT NULL,
    user_id UUID REFERENCES users(id),
    roles VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);
```

**Key Generation Endpoint**:
```python
# api/routes/auth.py (new endpoint)
@router.post("/v1/auth/keys")
async def create_api_key(
    request: Request,
    body: CreateKeyRequest,
) -> JSONResponse:
    auth = get_auth_context(request)
    
    # Only admins can create new keys
    if not auth.has_role(Role.ADMIN):
        raise PermissionDeniedError("Only admins can create API keys")
    
    # Generate random key (32+ chars)
    key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    
    # Store in database
    await db.execute(
        """
        INSERT INTO api_keys (key_id, key_hash, key_type, user_id, roles)
        VALUES ($1, $2, $3, $4, $5)
        """,
        uuid4(),
        key_hash,
        body.key_type.value,
        body.user_id,
        ",".join(r.value for r in body.roles),
    )
    
    return JSONResponse({"key": key, "key_id": str(key_id)})
```

**Key Validation Update**:
```python
# security/auth_static.py
class StaticKeyAuthProvider(AuthProvider):
    async def authenticate(self, api_key: str) -> AuthContext:
        # Hash incoming key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Lookup in database
        row = await self._db.fetchrow(
            "SELECT * FROM api_keys WHERE key_hash = $1 AND (expires_at IS NULL OR expires_at > NOW())",
            key_hash,
        )
        
        if not row:
            raise AuthError("Invalid API key")
        
        # Check expiration
        if row["expires_at"] and row["expires_at"] < datetime.now(UTC):
            raise AuthError("API key expired")
        
        # Parse roles
        roles = {Role(r) for r in row["roles"].split(",")}
        
        # Build auth context
        return AuthContext(
            user_id=row["user_id"] or "__system__",
            org_id="__system__",
            identity=Identity.SYSTEM_AUTH,
            roles=roles,
            key_type=row["key_type"],
        )
```

**Role-Based Access Control**:
```python
# middleware/auth.py
def check_roles(required_roles: set[Role]):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            auth = get_auth_context()
            
            # Check key type
            if hasattr(auth, "key_type") and auth.key_type == KeyType.READ_ONLY:
                # Read-only keys cannot access admin endpoints
                if Role.ADMIN in required_roles:
                    raise PermissionDeniedError("Read-only key cannot access admin endpoints")
            
            # Check roles
            if not required_roles.issubset(auth.roles):
                raise PermissionDeniedError(f"Requires roles: {required_roles}")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

**Usage Example**:
```python
# api/routes/admin.py
@router.get("/v1/stronghold/admin/users")
@check_roles({Role.ADMIN, Role.ORG_ADMIN})
async def list_users(request: Request):
    # Only admin or org_admin can access
    pass

# api/routes/sessions.py
@router.get("/v1/stronghold/sessions")
@check_roles({Role.ADMIN, Role.ORG_ADMIN, Role.TEAM_ADMIN, Role.USER})
async def list_sessions(request: Request):
    # All key types can access (including read-only)
    pass
```

### 4.3 Acceptance Criteria

**AC-R8-1: Admin Key Creation**
**Given** Authenticated admin user
**When** `POST /v1/auth/keys` with `{"key_type":"admin","roles":["admin","org_admin","team_admin","user"]}` is called
**Then**:
- Returns new 32+ character API key
- Key is stored in database with hash
- Key has `key_type="admin"`
- Key has all admin roles

**AC-R8-2: Read-Only Key Creation**
**Given** Authenticated admin user
**When** `POST /v1/auth/keys` with `{"key_type":"read_only","user_id":"<user-id>","roles":["user"]}` is called
**Then**:
- Returns new 32+ character API key
- Key is scoped to specific `user_id`
- Key has `key_type="read_only"`
- Key has only `user` role (no admin roles)

**AC-R8-3: Admin Key Grants Full Access**
**Given** Valid admin API key
**When** Any API endpoint is called with this key
**Then**:
- Access granted to all endpoints
- All roles available in auth context
- No permission errors

**AC-R8-4: Read-Only Key Blocked from Admin**
**Given** Valid read-only API key
**When** `GET /v1/stronghold/admin/users` is called
**Then**:
- Returns HTTP 403
- Error message: "Read-only key cannot access admin endpoints"

**AC-R8-5: Read-Only Key Accesses User Endpoints**
**Given** Valid read-only API key
**When** `GET /v1/stronghold/sessions` is called
**Then**:
- Returns HTTP 200
- Access granted to user-scoped data
- No permission errors

**AC-R8-6: Key Expiration**
**Given** API key with `expires_at` in past
**When** Any API endpoint is called
**Then**:
- Returns HTTP 401
- Error message: "API key expired"

---

## 5. R11: Validate Tool Names in Agent Creation

### 5.1 Current State

**File**: `src/stronghold/api/routes/agents.py:225`

**Behavior**:
```python
@router.post("/v1/stronghold/agents")
async def create_agent(request: Request, body: AgentCreateRequest):
    # ... validation logic ...
    
    # No tool name validation!
    await agent_store.create(body)
```

**Attack Vector**: Attacker creates agent with non-existent tools (e.g., `shell_exec`, `env_dump`) → pollutes agent namespace, confuses users.

### 5.2 Solution

**Add Tool Registry Validation**:
```python
# api/routes/agents.py
@router.post("/v1/stronghold/agents")
async def create_agent(request: Request, body: AgentCreateRequest):
    container = app.state.container
    auth = get_auth_context(request)
    
    # Validate tool names against registry
    registry = container.tool_registry
    invalid_tools = []
    for tool_name in body.tools:
        try:
            registry.get(tool_name)
        except KeyError:
            invalid_tools.append(tool_name)
    
    if invalid_tools:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tools: {', '.join(invalid_tools)}. "
                   f"Available tools: {', '.join(registry.list_names())}",
        )
    
    # Continue with creation
    await agent_store.create(
        name=body.name,
        tools=body.tools,
        created_by=auth.user_id,
        org_id=auth.org_id,
    )
```

### 5.3 Acceptance Criteria

**AC-R11-1: Valid Tool Accepted**
**Given** Valid tool names in registry
**When** `POST /v1/stronghold/agents` with `{"tools":["web_search","file_read"]}` is called
**Then**:
- Agent is created successfully
- Tools are attached to agent
- Returns HTTP 200

**AC-R11-2: Invalid Tool Rejected**
**Given** Non-existent tool name
**When** `POST /v1/stronghold/agents` with `{"tools":["shell_exec"]}` is called
**Then**:
- Returns HTTP 400
- Error message includes "Invalid tools: shell_exec"
- Error message includes list of available tools
- Agent is NOT created

**AC-R11-3: Multiple Invalid Tools Rejected**
**Given** Multiple non-existent tool names
**When** `POST /v1/stronghold/agents` with `{"tools":["shell_exec","env_dump","invalid_tool"]}` is called
**Then**:
- Returns HTTP 400
- Error message lists all invalid tools
- Agent is NOT created

---

## 6. R14: Enforce Minimum API Key Length

### 6.1 Current State

**File**: `src/stronghold/config/loader.py:91-97`

**Behavior**:
```python
if ROUTER_API_KEY and len(ROUTER_API_KEY) < 32:
    logger.warning("ROUTER_API_KEY is shorter than 32 characters")
```

**Attack Vector**: Weak key `sk-stronghold-prod-2026` (24 chars) is accepted → easier to brute force.

### 6.2 Solution

**Hard Validation**:
```python
# config/loader.py
def load_config() -> StrongholdConfig:
    # Existing config loading...
    
    # Hard validation for ROUTER_API_KEY
    if ROUTER_API_KEY:
        if len(ROUTER_API_KEY) < 32:
            raise ConfigError(
                "ROUTER_API_KEY must be at least 32 characters for security. "
                f"Current length: {len(ROUTER_API_KEY)}. "
                "Use: python -c \"import secrets; print('sk-' + secrets.token_urlsafe(32))\""
            )
        
        # Validate entropy (optional but recommended)
        if len(set(ROUTER_API_KEY)) < 10:
            raise ConfigError(
                "ROUTER_API_KEY lacks sufficient entropy (too few unique characters). "
                "Use a strong random key."
            )
```

**Generate Strong Key Helper**:
```python
# scripts/generate_api_key.py (new file)
import secrets
import sys

if __name__ == "__main__":
    key = "sk-" + secrets.token_urlsafe(32)
    print(key)
    print(f"Length: {len(key)}")
    print(f"Entropy: {len(set(key))} unique characters")
```

### 6.3 Acceptance Criteria

**AC-R14-1: 32 Char Minimum Enforced**
**Given** API key with 31 characters
**When** `load_config()` is called
**Then**:
- Raises `ConfigError`
- Error message includes "at least 32 characters"
- Application fails to start

**AC-R14-2: 32+ Char Key Accepted**
**Given** API key with 32+ characters
**When** `load_config()` is called
**Then**:
- No exception raised
- Configuration loads successfully

**AC-R14-3: Low Entropy Rejected**
**Given** API key with 5 unique characters (e.g., "aaaaaaaaaaaaaaaaaaaaaaaaaa")
**When** `load_config()` is called
**Then**:
- Raises `ConfigError`
- Error message includes "lacks sufficient entropy"
- Application fails to start

**AC-R14-4: Strong Key Generated**
**Given** `python scripts/generate_api_key.py` is run
**When** Script executes
**Then**:
- Outputs 35-character key (sk- + 32 chars)
- Outputs length: 35
- Outputs unique character count >= 20

---

## 7. R27: Fix Prompt PUT Error Handling

### 7.1 Current State

**File**: `src/stronghold/api/routes/prompts.py`

**Behavior**: `PUT /v1/stronghold/prompts/<prompt_name>` may return 500 if prompt doesn't exist.

### 7.2 Solution

**Add Custom Error Type**:
```python
# types/errors.py
class PromptNotFoundError(StrongholdError):
    """Prompt not found in store."""
    pass
```

**Wrap Store Operations**:
```python
# api/routes/prompts.py
from stronghold.types.errors import PromptNotFoundError

@router.put("/v1/stronghold/prompts/{prompt_name}")
async def update_prompt(
    request: Request,
    prompt_name: str,
    body: dict,
) -> JSONResponse:
    container = app.state.container
    store = container.prompt_store
    
    try:
        await store.update(prompt_name, body)
    except PromptNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt '{prompt_name}' not found",
        )
    except Exception as e:
        logger.error("Prompt update failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Internal error updating prompt",
        )
    
    return JSONResponse({"status": "updated", "prompt": prompt_name})
```

**Update PromptStore Protocol**:
```python
# protocols/prompts.py
class PromptStore(Protocol):
    async def get(self, name: str) -> Prompt | None: ...
    async def update(self, name: str, data: dict) -> None:
        """Update existing prompt.
        
        Raises:
            PromptNotFoundError: Prompt does not exist.
        """
        ...
```

### 7.3 Acceptance Criteria

**AC-R27-1: Existing Prompt Updated**
**Given** Existing prompt in store
**When** `PUT /v1/stronghold/prompts/agent.default.soul` with new content is called
**Then**:
- Prompt is updated successfully
- Returns HTTP 200
- Response includes `"status": "updated"`

**AC-R27-2: Non-Existent Prompt Returns 404**
**Given** Prompt not in store
**When** `PUT /v1/stronghold/prompts/nonexistent.prompt` is called
**Then**:
- Returns HTTP 404
- Error message: "Prompt 'nonexistent.prompt' not found"
- Does NOT return 500

**AC-R27-3: Internal Errors Return 500**
**Given** Prompt store throws unexpected exception
**When** `PUT /v1/stronghold/prompts/agent.default.soul` is called
**Then**:
- Returns HTTP 500
- Error message: "Internal error updating prompt"
- Error is logged (for debugging)

---

## 8. Testing Strategy

### 8.1 Test Files to Create

**R7 Tests**:
- `tests/api/test_docs_scoping.py`
  - Test docs disabled in production
  - Test docs enabled in development
  - Test rate limiting applied to docs

**R8 Tests**:
- `tests/api/test_api_key_scoping.py`
  - Test admin key creation
  - Test read-only key creation
  - Test admin key grants full access
  - Test read-only key blocked from admin
  - Test read-only key accesses user endpoints
  - Test key expiration
  - Test key validation (hashing)

**R11 Tests**:
- `tests/api/test_agents_routes.py` (extend existing)
  - Test valid tools accepted
  - Test invalid tool rejected
  - Test multiple invalid tools rejected

**R14 Tests**:
- `tests/config/test_loader.py` (extend existing)
  - Test 32 char minimum enforced
  - Test low entropy rejected
  - Test strong key generated

**R27 Tests**:
- `tests/api/test_prompts_routes.py` (extend existing)
  - Test existing prompt updated
  - Test non-existent prompt returns 404
  - Test internal errors return 500

### 8.2 Integration Tests

**R8 Integration**:
- Test key creation and usage with real database
- Test role-based access control across endpoints
- Test key expiration in production-like environment

---

## 9. Risk Assessment

### 9.1 High Risk

**R8 Breaking Change**: Existing `ROUTER_API_KEY` will stop working if we enforce database-backed keys.
- **Mitigation**: Support legacy `ROUTER_API_KEY` as admin key for 30 days, then deprecate
- **Transition Plan**:
  1. Deploy with dual support (env var + database)
  2. Send deprecation notice to all users
  3. After 30 days, remove env var support

**R11 Breaking Change**: Existing agents with invalid tool references will fail.
- **Mitigation**: Validate on agent creation, not on execution
- **Transition**: Existing agents remain unchanged, new agents require valid tools

### 9.2 Medium Risk

**R7 Breaking Change**: Developers relying on `/docs` in production will be blocked.
- **Mitigation**: Provide clear documentation, easy toggle via `STRONGHOLD_DOCS_ENABLED`
- **Acceptable**: Security benefit outweighs minor inconvenience

**R14 Breaking Change**: Existing short keys will cause startup failure.
- **Mitigation**: Provide clear error message with key generation command
- **Acceptable**: Enforcing strong keys is security best practice

### 9.3 Low Risk

**R27 Backward Compatible**: Only changes error handling, no breaking changes.
- **No rollback needed**

---

## 10. Migration Plan

### 10.1 Database Migration

**New Table**: `api_keys`
```sql
-- migrations/012_api_keys_table.sql
CREATE TABLE IF NOT EXISTS api_keys (
    key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(64) UNIQUE NOT NULL,
    key_type VARCHAR(20) NOT NULL CHECK (key_type IN ('admin', 'read_only', 'user')),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    roles VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    
    CONSTRAINT valid_roles CHECK (roles != '')
);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_user ON api_keys(user_id);
CREATE INDEX idx_api_keys_expires ON api_keys(expires_at) WHERE expires_at IS NOT NULL;
```

**Run**: `migrate()` on startup to apply migration 012.

### 10.2 Configuration Migration

**Old Config**:
```yaml
# .env
ROUTER_API_KEY=sk-stronghold-prod-2026
```

**New Config**:
```yaml
# .env
# Optional: legacy admin key (deprecated, remove after 2026-05-21)
ROUTER_API_KEY=sk-stronghold-prod-2026

# Generate new keys via API
# POST /v1/auth/keys with admin key
```

### 10.3 Deprecation Timeline

**2026-04-21**: Deploy with dual support (env var + database keys)
**2026-04-21**: Send email to all users about deprecation
**2026-05-21**: Remove `ROUTER_API_KEY` env var support (30 days notice period)

---

## 11. Open Questions

1. **R8 Key Storage**: Should keys be encrypted at rest in database? (Recommended: yes, use pgcrypto)
2. **R8 Key Rotation**: Should we implement automatic key rotation (e.g., rotate every 90 days)?
3. **R8 Audit Logging**: Should we log all API key usage for audit trail?
4. **R11 Tool Discovery**: Should we provide an endpoint to list available tools for discovery?
5. **R14 Entropy Check**: What is the minimum acceptable unique character count? (Current proposal: 10)

---

**Document Version**: 1.0  
**Last Updated**: 2026-04-21  
**Status**: Ready for implementation and test creation
