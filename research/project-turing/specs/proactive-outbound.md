# Spec 55 — Proactive Outbound Messaging

*The agent can initiate conversations and send messages to users.*

**Depends on:** 54 (conversation threads), 17 (chat-surface), 9 (motivation)
**Depended on by:** 56

---

## Current state

- Turing only responds to inbound HTTP requests. `ChatBridge` resolves pending requests but cannot initiate.
- The motivation system has no concept of "talk to a user" as a dispatchable action.
- OpenWebUI has a REST API (`POST /api/v1/chats/new`) that accepts `ChatForm {chat: dict, folder_id: str}` to create conversations.

## Target

Enable Turing to proactively create conversations and send messages to users via OpenWebUI's API. Outbound messages enter the motivation backlog at P20-P30 priority (same tier as daydreaming, blog posts). User replies arrive at P1.

## Acceptance criteria

### Outbound dispatch

- **AC-55.1.** New dispatch kind `"outbound_message"` registered in `main.py`. Handler receives a `BacklogItem` with payload:
  ```
  {
    "target_user_id": str,
    "content": str,
    "conversation_id": str | None,   -- if set, append to existing; if None, create new
    "title": str                      -- title for new conversations
  }
  ```
  Test: insert outbound item into motivation backlog, verify dispatch handler fires.

- **AC-55.2.** Outbound items are inserted at priority class 20-30 (configurable). Default: P25. This is below user replies (P1) but above routine maintenance (P40+). Test that a P1 chat_message always dispatches before a P25 outbound_message.

- **AC-55.3.** When `conversation_id` is None, the handler:
  1. Checks `conversation_quotas` for `target_user_id` today (US Central).
  2. If `threads_created >= 1`, logs OBSERVATION memory and aborts.
  3. Calls OpenWebUI `POST /api/v1/chats/new` with a `ChatForm` containing the message.
  4. Stores the returned chat ID as `ow_chat_id` in the `conversations` table.
  5. Increments the quota.
  6. Writes the assistant message to `conversation_messages`.
  Test end-to-end with a fake OpenWebUI API.

- **AC-55.4.** When `conversation_id` is set, the handler:
  1. Verifies the conversation exists and is `active`.
  2. Appends the message to the existing conversation via OpenWebUI's update API.
  3. Writes to `conversation_messages`.
  Test.

### OpenWebUI API client

- **AC-55.5.** New module `runtime/openwebui_client.py` with class `OpenWebUIClient`:
  - `__init__(base_url: str, api_key: str)`
  - `create_chat(user_id: str, title: str, messages: list[dict]) -> str` (returns chat ID)
  - `append_message(chat_id: str, messages: list[dict]) -> None`
  - `list_chats(user_id: str) -> list[dict]`
  Uses `urllib.request` (stdlib, no new dependency). Test with a fake HTTP server.

- **AC-55.6.** OpenWebUI API key is stored in `RuntimeConfig` as `openwebui_api_key`. Loaded from environment variable `OPENWEBUI_API_KEY`. If absent, outbound messaging is disabled (logged as warning, items discarded). Test.

### Outbound triggers

- **AC-55.7.** The agent can create outbound items from any dispatch handler (daydream, RSS reflection, working memory maintenance) by calling `motivation.insert(BacklogItem(..., kind="outbound_message", class_=25))`. Test that RSS reflection can trigger an outbound message.

- **AC-55.8.** When the agent writes a WISDOM memory (dreaming consolidation), it MAY create an outbound message to share notable self-insight with the user. This is a P30 item — lowest priority outbound. Test.

- **AC-55.9.** When a newsletter item scores interest >= 0.9, the agent MAY create a P25 outbound to share it with the user. Test.

### Quota enforcement

- **AC-55.10.** The daily quota (Spec 54 AC-54.9) applies to agent-initiated conversations. The agent can send unlimited messages to *existing* active conversations. Test: agent creates 1 conversation (allowed), tries to create a second (rejected), sends 5 messages to the first conversation (all allowed).

- **AC-55.11.** Quota rejection does not prevent the agent from replying to user messages. Inbound replies are always P1 and go through the existing `chat_message` dispatch. Test.

### Edge cases

- **AC-55.12.** OpenWebUI API returns 401/403: agent logs a REGRET memory ("I tried to reach out to the user but was denied access") and discards the item. Test.

- **AC-55.13.** Target user has no active conversations and agent quota is exhausted: agent writes OBSERVATION "I have thoughts I want to share but I'll wait until tomorrow" and the backlog item is evicted. Test.

- **AC-55.14.** OpenWebUI is unreachable: handler retries once after 5 seconds. On second failure, REGRET + discard. Test.

## Implementation

### 55.1 OpenWebUIClient

```python
class OpenWebUIClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key

    def create_chat(self, *, title: str, messages: list[dict]) -> str:
        payload = json.dumps({
            "chat": {"title": title, "messages": messages},
        }).encode()
        req = urllib.request.Request(
            f"{self._base}/api/v1/chats/new",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return body["id"]

    def append_message(self, chat_id: str, messages: list[dict]) -> None:
        ...
```

### 55.2 Dispatch handler registration

In `main.py`, after chat server setup:

```python
if cfg.openwebui_api_key:
    owui = OpenWebUIClient(
        base_url=cfg.openwebui_base_url,
        api_key=cfg.openwebui_api_key,
    )
    conv_repo = ConversationRepo(raw_repo.conn)

    def _on_outbound(item: BacklogItem, chosen_pool: str) -> None:
        payload = item.payload or {}
        target = payload.get("target_user_id", "")
        content = payload.get("content", "")
        conv_id = payload.get("conversation_id")
        title = payload.get("title", "Message from Turing")
        ...

    motivation.register_dispatch("outbound_message", _on_outbound)
```

### 55.3 Config additions

`RuntimeConfig` gets:
- `openwebui_base_url: str` (default: `"http://localhost:30080"`)
- `openwebui_api_key: str | None`

CLI args: `--openwebui-url`, `--openwebui-api-key`

## Resolved questions

- **Q55.1.** Outbound messages are written to `conversation_messages` and surface via retrieval. Agent remembers what it said. ✓
- **Q55.2.** No broadcast in v1. One user per outbound. ✓
