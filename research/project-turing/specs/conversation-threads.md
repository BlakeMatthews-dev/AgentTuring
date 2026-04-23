# Spec 54 — Conversation Threads

*Stateful conversations on top of Turing's stateless chat endpoint.*

**Depends on:** 17 (chat-surface), 9 (motivation)
**Depended on by:** 55, 56

---

## Current state

- `chat.py` treats each `/v1/chat/completions` call as independent. No conversation continuity.
- No per-user identity — OpenWebUI sends a `user` field in the request but Turing ignores it.
- No concept of threads, quotas, or outbound messaging.
- OpenWebUI manages its own conversation history and sends the full message array each time.

## Target

Add conversation tracking, per-user identity, and daily thread quotas to Turing's chat server. Conversations are persisted in Turing's SQLite DB so the agent can reference past conversations in its memory and prompt construction.

## Acceptance criteria

### Conversation model

- **AC-54.1.** New `conversations` table (see Implementation). Test: insert and retrieve a conversation row.

- **AC-54.2.** New `conversation_messages` table (see Implementation). Test: insert messages, query by conversation_id.

- **AC-54.3.** New `conversation_quotas` table (see Implementation). Test: upsert and query quota.

### User identity

- **AC-54.4.** `POST /v1/chat/completions` extracts `user` field from the OpenAI-compatible request payload. If absent, uses `"anonymous"`. The `owner_user_id` is this value. Test.

### Conversation lifecycle

- **AC-54.5.** When a request arrives with no `conversation_id` in the payload metadata, a new conversation is created with `created_by = 'user'` and `status = 'active'`. Test.

- **AC-54.6.** When a request arrives with `conversation_id` in metadata, messages are appended to that conversation. If the conversation status is `'archived'`, it is rejected with HTTP 410. Test.

- **AC-54.7.** Every user message and every assistant reply is written to `conversation_messages`. Test that a round-trip produces two rows.

- **AC-54.8.** The `_build_chat_prompt` function in `main.py` receives conversation history from the DB (not just the `messages` array from the HTTP request). If a `conversation_id` is present, the DB history supplements the request messages. Test.

### Quota enforcement

- **AC-54.9.** Agent-initiated conversation creation (`created_by = 'agent'`) checks the quota: if `threads_created >= 1` for this user on this date (US Central), the creation is rejected. Test with quota at 0 (allowed) and 1 (rejected).

- **AC-54.10.** User-initiated conversation creation has no quota limit. Test that creating 5 user conversations succeeds.

- **AC-54.11.** Quota date is computed as midnight US Central (`America/Chicago`). The date rolls at midnight local, not UTC. Test with a fake clock crossing midnight Central.

- **AC-54.12.** On quota rejection, the agent logs an OBSERVATION memory: "I wanted to start a new conversation with {user_id} but reached my daily thread limit." Test.

### API endpoints

- **AC-54.13.** `GET /v1/conversations` — returns list of active conversations for the requesting user (from `user` query param or header). Response: `[{id, title, status, created_at, updated_at}]`. Test.

- **AC-54.14.** `POST /v1/conversations/{id}/archive` — sets status to `'archived'`. Only the owning user or the agent can archive. Archived conversations are read-only. Test.

- **AC-54.15.** `GET /v1/conversations/{id}` — returns conversation metadata + last 50 messages. Test.

### Edge cases

- **AC-54.16.** Two requests with the same `conversation_id` from different users: the second is rejected with HTTP 403. Conversations are 1:1. Test.

- **AC-54.17.** A conversation with no messages after 7 days is auto-archived on next access. Test with a fake clock.

- **AC-54.18.** The `ow_chat_id` field is set when the agent creates a conversation via OpenWebUI API (Spec 55). For user-initiated conversations, it is null. Test.

## Implementation

### 54.1 Schema additions

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,
    owner_user_id   TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived')),
    ow_chat_id      TEXT,
    created_by      TEXT NOT NULL CHECK (created_by IN ('user', 'agent')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_owner
    ON conversations (owner_user_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id                TEXT PRIMARY KEY,
    conversation_id   TEXT NOT NULL REFERENCES conversations(id),
    role              TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content           TEXT NOT NULL,
    turing_memory_id  TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON conversation_messages (conversation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS conversation_quotas (
    user_id           TEXT NOT NULL,
    quota_date        TEXT NOT NULL,
    threads_created   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, quota_date)
);
```

### 54.2 ConversationRepo

New class `ConversationRepo` wrapping the three tables. Methods:

- `create(user_id, created_by, title, ow_chat_id) -> Conversation`
- `get(conv_id) -> Conversation | None`
- `list_active(user_id) -> list[Conversation]`
- `archive(conv_id)`
- `append_message(conv_id, role, content, memory_id=None)`
- `get_messages(conv_id, limit=50) -> list[Message]`
- `check_quota(user_id, quota_date) -> int` (returns threads_created)
- `increment_quota(user_id, quota_date)`

### 54.3 Chat endpoint changes

In `chat.py`:

- `_handle_openai_chat_completions` extracts `user` from payload
- Checks for `conversation_id` in `metadata` sub-object of the request
- If no conversation_id → create new (user quota not checked; agent quota checked in Spec 55)
- After dispatch, write user message + assistant reply to `conversation_messages`
- Pass conversation history to `_build_chat_prompt`

### 54.4 Central timezone helper

```python
from datetime import datetime
from dateutil.tz import gettz

CENTRAL = gettz("America/Chicago")

def quota_date_now() -> str:
    return datetime.now(CENTRAL).strftime("%Y-%m-%d")
```

## Resolved questions

- **Q54.1.** Use the `messages` array for the current turn. DB history only for retrieval when agent resumes a conversation (Spec 55). ✓
- **Q54.2.** Conversations are OBSERVATION-tier equivalents. No auto-pruning; agent promotes notable exchanges via normal write paths. ✓
