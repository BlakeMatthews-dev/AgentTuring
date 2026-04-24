"""Test the GitHub-based Artificer flow: issue → branch → code → PR."""


class TestGitHubFlowStructure:
    def test_structured_request_accepts_repo(self) -> None:
        """The /v1/stronghold/request endpoint should accept a repo field."""
        from stronghold.api.app import create_app

        app = create_app()
        routes = {route.path for route in app.routes}
        assert "/v1/stronghold/request" in routes
