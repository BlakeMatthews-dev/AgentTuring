"""Tests for token optimization on tool results."""

from stronghold.security.sentinel.token_optimizer import optimize_result


class TestTokenOptimization:
    def test_short_result_passthrough(self) -> None:
        result = optimize_result("OK")
        assert result == "OK"

    def test_long_result_truncated(self) -> None:
        long_result = "x" * 10000
        result = optimize_result(long_result)
        assert len(result) <= 4000
        assert "truncated" in result

    def test_json_compacted(self) -> None:
        import json

        data = {"key": "value", "nested": {"a": 1, "b": 2}}
        long_json = json.dumps(data, indent=4) * 200
        result = optimize_result(long_json)
        assert len(result) <= 4000
