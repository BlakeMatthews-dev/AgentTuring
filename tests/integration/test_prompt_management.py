"""Tests for prompt management API."""

import pytest
from fastapi.testclient import TestClient

from stronghold.api.app import create_app


class TestPromptAPI:
    def test_list_prompts(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/prompts",
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "prompts" in data
            # Should have at least the seeded agent souls
            assert len(data["prompts"]) >= 2

    def test_get_prompt_by_name(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/prompts/agent.arbiter.soul",
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "agent.arbiter.soul"
            assert len(data["content"]) > 0

    def test_get_prompt_not_found(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/prompts/nonexistent",
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 404

    def test_create_new_prompt(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/prompts/test.prompt",
                json={"content": "Hello world prompt", "label": "staging"},
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "test.prompt"
            assert data["version"] >= 1

    def test_version_history(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            # Create two versions
            client.put(
                "/v1/stronghold/prompts/versioned.test",
                json={"content": "Version 1", "label": "production"},
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            client.put(
                "/v1/stronghold/prompts/versioned.test",
                json={"content": "Version 2", "label": "staging"},
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            resp = client.get(
                "/v1/stronghold/prompts/versioned.test/versions",
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["versions"]) >= 2

    def test_promote_label(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            # Create v1 as production
            client.put(
                "/v1/stronghold/prompts/promo.test",
                json={"content": "V1", "label": "production"},
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            # Create v2 as staging
            client.put(
                "/v1/stronghold/prompts/promo.test",
                json={"content": "V2", "label": "staging"},
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            # Promote v2 to production
            resp = client.post(
                "/v1/stronghold/prompts/promo.test/promote",
                json={"from_label": "staging", "to_label": "production"},
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 200

            # Verify production now returns V2
            resp = client.get(
                "/v1/stronghold/prompts/promo.test",
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.json()["content"] == "V2"
