"""Worker entry point: runs as a separate pod/process.

Claims tasks from the queue, runs agent pipelines, reports results.
"""

from __future__ import annotations

import asyncio
import logging

from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.agents.worker import AgentWorker
from stronghold.api.litellm_client import LiteLLMClient
from stronghold.config.loader import load_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stronghold.worker")


async def main() -> None:
    """Start the worker loop."""
    config = load_config()

    llm = LiteLLMClient(
        base_url=config.litellm_url,
        api_key=config.litellm_key,
    )

    # For demo: in-process queue (shared with API via import)
    # For production: PostgreSQL-backed queue
    queue = InMemoryTaskQueue()

    worker = AgentWorker(queue=queue, llm=llm)

    logger.info("Worker started. Polling for tasks...")
    await worker.run_loop(max_idle_seconds=3600)


if __name__ == "__main__":
    asyncio.run(main())
