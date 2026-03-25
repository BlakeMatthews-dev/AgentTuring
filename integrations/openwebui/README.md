# OpenWebUI Integration

Connect OpenWebUI to Stronghold via the Pipelines container.

## Setup

1. Deploy the Pipelines container alongside OpenWebUI:

```yaml
# docker-compose.yml (add to your existing OpenWebUI stack)
services:
  pipelines:
    image: ghcr.io/open-webui/pipelines:main
    ports:
      - "9099:9099"
    volumes:
      - ./pipelines:/app/pipelines
    environment:
      - PIPELINES_DIR=/app/pipelines
```

2. Copy the pipeline function:

```bash
cp stronghold_pipeline.py ./pipelines/
```

3. Configure OpenWebUI to use Pipelines:
   - Set `OPENAI_API_BASE_URLS` to include `http://pipelines:9099`
   - Or add via Admin > Settings > Connections

4. Configure the pipeline in Pipelines UI:
   - Set `STRONGHOLD_URL` to your Stronghold instance (e.g., `http://stronghold:8100`)
   - Set `STRONGHOLD_API_KEY` to your Stronghold API key

## What Happens

- Stronghold agents appear as model choices in OpenWebUI's model picker
- "Stronghold (Auto-Route)" lets the classifier pick the best agent
- Specific agents (Artificer, Ranger, etc.) route directly
- OpenWebUI user identity is forwarded via X-OpenWebUI-User-* headers
- All requests go through Stronghold's security stack (Gate, Warden, Sentinel)
