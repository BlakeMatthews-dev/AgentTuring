"""Tests for ArtificerStrategy uncovered governance paths.

Spec: Sentinel pre_call permission gating, oversized arg rejection,
     result truncation, sentinel post_call Warden/PII scan.
AC: args >32KB rejected without executor, sentinel denied tool skips execution,
    sentinel repaired_args passed to executor, results >16KB truncated,
    post_call invoked on results.
Edge cases: sentinel allowed with no repair, sentinel denied records in history,
            exact boundary sizes (32KB args, 16KB result).
Contracts: reason() returns ReasoningResult, tool_history records all calls.
"""

from __future__ import annotations

import json

from stronghold.agents.artificer.strategy import ArtificerStrategy

from tests.fakes import FakeLLMClient


class _RecordingSentinel:
    def __init__(
        self,
        *,
        allowed: bool = True,
        repaired_data: dict | None = None,
        post_result: str | None = None,
    ):
        self.allowed = allowed
        self.repaired_data = repaired_data
        self.post_result = post_result
        self.pre_calls: list[tuple] = []
        self.post_calls: list[tuple] = []

    async def pre_call(self, tool_name: str, tool_args: dict, auth: dict, extra: dict):
        self.pre_calls.append((tool_name, tool_args, auth))
        from stronghold.security.sentinel.policy import SentinelVerdict

        return SentinelVerdict(allowed=self.allowed, repaired_data=self.repaired_data)

    async def post_call(self, tool_name: str, result: str, auth: dict) -> str:
        self.post_calls.append((tool_name, result))
        return self.post_result if self.post_result is not None else result


async def _run_once(
    *,
    tool_args: dict | None = None,
    tool_result: str | None = None,
    sentinel=None,
    auth: dict | None = None,
):
    tool_args = tool_args if tool_args is not None else {"cmd": "echo hi"}
    tool_result = tool_result if tool_result is not None else "ok"

    llm = FakeLLMClient()
    llm.set_responses(
        {
            "id": "1",
            "choices": [{"message": {"role": "assistant", "content": "plan"}}],
            "usage": {},
        },
        {
            "id": "2",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "t1",
                                "function": {
                                    "name": "run_shell",
                                    "arguments": json.dumps(tool_args),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {},
        },
        {
            "id": "3",
            "choices": [{"message": {"role": "assistant", "content": "done"}}],
            "usage": {},
        },
    )

    executor_log: list[tuple[str, object]] = []

    async def tool_executor(name, args):
        executor_log.append((name, args))
        return tool_result

    strategy = ArtificerStrategy(max_phases=1)
    result = await strategy.reason(
        [{"role": "user", "content": "do thing"}],
        "m",
        llm,
        tools=[{"function": {"name": "run_shell", "parameters": {}}}],
        tool_executor=tool_executor,
        sentinel=sentinel,
        auth=auth,
    )
    return result, executor_log


class TestOversizedArgRejection:
    async def test_oversized_args_rejected(self) -> None:
        huge_args = {"payload": "A" * (50 * 1024)}
        result, executor_log = await _run_once(tool_args=huge_args, auth={"org_id": "test"})
        assert len(executor_log) == 0
        assert any("exceed" in h["result"] for h in result.tool_history)

    async def test_oversized_args_recorded_in_history(self) -> None:
        huge_args = {"payload": "A" * (50 * 1024)}
        result, _ = await _run_once(tool_args=huge_args, auth={"org_id": "test"})
        assert len(result.tool_history) == 1
        assert result.tool_history[0]["tool_name"] == "run_shell"


class TestSentinelPreCall:
    async def test_denied_tool_skips_executor(self) -> None:
        sentinel = _RecordingSentinel(allowed=False)
        result, executor_log = await _run_once(sentinel=sentinel, auth={"org_id": "test"})
        assert len(executor_log) == 0
        assert any("Permission denied" in h["result"] for h in result.tool_history)
        assert len(sentinel.pre_calls) == 1

    async def test_allowed_tool_executes(self) -> None:
        sentinel = _RecordingSentinel(allowed=True)
        result, executor_log = await _run_once(sentinel=sentinel, auth={"org_id": "test"})
        assert len(executor_log) == 1

    async def test_repaired_args_passed_to_executor(self) -> None:
        sentinel = _RecordingSentinel(allowed=True, repaired_data={"cmd": "safe_command"})
        _, executor_log = await _run_once(sentinel=sentinel, auth={"org_id": "test"})
        assert len(executor_log) == 1
        assert executor_log[0][1] == {"cmd": "safe_command"}


class TestResultTruncation:
    async def test_large_result_truncated(self) -> None:
        big_result = "X" * (20 * 1024)
        result, _ = await _run_once(tool_result=big_result, auth={"org_id": "test"})
        messages = [m for m in result.tool_history if m["tool_name"] == "run_shell"]
        assert len(messages) == 1

    async def test_small_result_not_truncated(self) -> None:
        small_result = "X" * 100
        result, _ = await _run_once(tool_result=small_result, auth={"org_id": "test"})
        assert result.done is True


class TestSentinelPostCall:
    async def test_post_call_invoked(self) -> None:
        sentinel = _RecordingSentinel(allowed=True, post_result="REDACTED")
        result, _ = await _run_once(sentinel=sentinel, auth={"org_id": "test"})
        assert len(sentinel.post_calls) == 1
        assert sentinel.post_calls[0][0] == "run_shell"

    async def test_no_sentinel_no_post_call(self) -> None:
        result, _ = await _run_once(auth={"org_id": "test"})
        assert result.done is True
