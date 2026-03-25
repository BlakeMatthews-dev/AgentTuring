# n8n Integration

Connect n8n workflows to Stronghold via webhook endpoints.

## Endpoints

### Chat Webhook
```
POST /v1/webhooks/chat
Body: {
  "message": "What's the weather?",
  "session_id": "n8n-workflow-123",  // optional
  "intent": "search",               // optional hint
  "webhook_secret": "your-secret"
}
Response: {
  "response": "The weather is...",
  "agent": "ranger",
  "intent": "search",
  "model": "mistral-small"
}
```

### Gate Security Scan
```
POST /v1/webhooks/gate
Body: {
  "content": "Text to check for safety",
  "webhook_secret": "your-secret"
}
Response: {
  "sanitized": "cleaned text",
  "blocked": false,
  "safe": true,
  "flags": []
}
```

## n8n Setup

1. Set `STRONGHOLD_WEBHOOK_SECRET` in Stronghold env
2. In n8n, use an **HTTP Request** node:
   - Method: POST
   - URL: `http://stronghold:8100/v1/webhooks/chat`
   - Body: JSON with `message` + `webhook_secret`
3. Parse the response JSON in downstream nodes

## Example Workflows

- **Approval flow**: User submits request → Stronghold processes → n8n routes for human approval
- **Scheduled digest**: n8n cron → POST /webhooks/chat with digest prompt → email result
- **Alert → action**: Monitoring alert → n8n → POST /webhooks/chat → HA automation
