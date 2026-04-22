"""Integration tests against REAL LiteLLM (requires port-forward to localhost:4000).

Run with: pytest tests/integration/test_real_llm.py -v
Skip if LiteLLM not available: pytest -m "not real_llm"
"""

import pytest
import httpx


# Check if LiteLLM is reachable
def _litellm_available() -> bool:
    try:
        resp = httpx.get(
            "http://127.0.0.1:4000/health",
            timeout=3.0,
            headers={"Authorization": "Bearer sk-conductor-litellm-2026"},
        )
        # Service is up if we get either 200 (authorized) or 401 (unauthorized
        # but responding). Check each explicitly rather than with ``in (…)``
        # so the intent is obvious in a failure mode.
        code = resp.status_code
        return code == 200 or code == 401
    except Exception:
        return False


skip_no_litellm = pytest.mark.skipif(
    not _litellm_available(),
    reason="LiteLLM not available at localhost:4000",
)


@skip_no_litellm
class TestRealLLM:
    @pytest.mark.asyncio
    async def test_complete_returns_response(self) -> None:
        from stronghold.api.litellm_client import LiteLLMClient

        llm = LiteLLMClient(
            base_url="http://localhost:4000",
            api_key="sk-conductor-litellm-2026",
        )
        result = await llm.complete(
            [{"role": "user", "content": "Say exactly: STRONGHOLD_TEST_OK"}],
            "mistral/mistral-small-latest",
            max_tokens=20,
            temperature=0.0,
        )
        content = result["choices"][0]["message"]["content"]
        assert "STRONGHOLD_TEST_OK" in content

    @pytest.mark.asyncio
    async def test_full_pipeline_with_real_llm(self) -> None:
        """Test the full Stronghold pipeline against real LiteLLM."""
        from stronghold.api.litellm_client import LiteLLMClient
        from stronghold.agents.base import Agent
        from stronghold.agents.context_builder import ContextBuilder
        from stronghold.agents.strategies.direct import DirectStrategy
        from stronghold.prompts.store import InMemoryPromptManager
        from stronghold.security.warden.detector import Warden
        from stronghold.types.agent import AgentIdentity
        from tests.factories import build_auth_context

        llm = LiteLLMClient(
            base_url="http://localhost:4000",
            api_key="sk-conductor-litellm-2026",
        )
        prompts = InMemoryPromptManager()
        await prompts.upsert(
            "agent.test.soul",
            "You are a test agent. Always respond with exactly: PIPELINE_OK",
            label="production",
        )

        agent = Agent(
            identity=AgentIdentity(
                name="test",
                soul_prompt_name="agent.test.soul",
                model="mistral/mistral-small-latest",
                memory_config={},
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )

        result = await agent.handle(
            [{"role": "user", "content": "test"}],
            build_auth_context(),
        )
        assert result.content  # got a response
        assert not result.blocked
        assert result.agent_name == "test"
