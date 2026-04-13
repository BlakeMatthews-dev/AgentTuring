"""Retrospective learning manager -- daily analysis of pipeline history.

Performs 5 analysis passes over pipeline run history:
1. First-pass success: runs that succeeded on first attempt
2. Rework feedback: runs that required rework (rework_count > 0)
3. Persistent failures: runs that failed at any stage
4. Model performance: aggregate success/failure by model
5. Tool effectiveness: aggregate success/failure by tool used

Results are deduplicated by trigger_keys to prevent repeated insights.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class RetrospectiveLearningManager:
    """Analyze pipeline run history and produce actionable insights."""

    def __init__(self) -> None:
        self._seen_keys: set[str] = set()

    def _dedup_key(self, pass_name: str, identifier: object) -> str:
        return f"{pass_name}:{identifier}"

    def _add_if_new(
        self,
        insights: list[dict[str, Any]],
        pass_name: str,
        identifier: object,
        data: dict[str, Any],
    ) -> None:
        key = self._dedup_key(pass_name, identifier)
        if key not in self._seen_keys:
            self._seen_keys.add(key)
            data["pass"] = pass_name
            insights.append(data)

    async def analyze_runs(self, pipeline_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run all 5 passes over pipeline history. Returns a list of insight dicts."""
        insights: list[dict[str, Any]] = []

        # Pass 1: First-pass success
        self._pass_first_success(pipeline_history, insights)

        # Pass 2: Rework feedback
        self._pass_rework_feedback(pipeline_history, insights)

        # Pass 3: Persistent failures
        self._pass_persistent_failures(pipeline_history, insights)

        # Pass 4: Model performance
        self._pass_model_performance(pipeline_history, insights)

        # Pass 5: Tool effectiveness
        self._pass_tool_effectiveness(pipeline_history, insights)

        return insights

    def _pass_first_success(
        self,
        runs: list[dict[str, Any]],
        insights: list[dict[str, Any]],
    ) -> None:
        """Pass 1: Identify runs that completed on the first attempt."""
        for run in runs:
            status = run.get("status", "")
            rework = run.get("rework_count", 0)
            issue = run.get("issue_number", 0)
            if status == "completed" and rework == 0:
                self._add_if_new(
                    insights,
                    "first_pass_success",
                    issue,
                    {"issue_number": issue, "summary": "succeeded on first attempt"},
                )

    def _pass_rework_feedback(
        self,
        runs: list[dict[str, Any]],
        insights: list[dict[str, Any]],
    ) -> None:
        """Pass 2: Identify runs that required rework."""
        for run in runs:
            rework = run.get("rework_count", 0)
            issue = run.get("issue_number", 0)
            if rework > 0:
                self._add_if_new(
                    insights,
                    "rework_feedback",
                    issue,
                    {
                        "issue_number": issue,
                        "rework_count": rework,
                        "summary": f"required {rework} rework cycles",
                    },
                )

    def _pass_persistent_failures(
        self,
        runs: list[dict[str, Any]],
        insights: list[dict[str, Any]],
    ) -> None:
        """Pass 3: Identify runs with stage failures."""
        for run in runs:
            status = run.get("status", "")
            issue = run.get("issue_number", 0)
            if "failed" in status:
                failed_stages = [
                    s["name"] for s in run.get("stages", []) if s.get("status") == "failed"
                ]
                self._add_if_new(
                    insights,
                    "persistent_failure",
                    issue,
                    {
                        "issue_number": issue,
                        "failed_stages": failed_stages,
                        "run_status": status,
                        "summary": f"failed at: {', '.join(failed_stages) or status}",
                    },
                )

    def _pass_model_performance(
        self,
        runs: list[dict[str, Any]],
        insights: list[dict[str, Any]],
    ) -> None:
        """Pass 4: Aggregate success/failure counts per model."""
        model_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"completed": 0, "failed": 0, "total": 0}
        )
        for run in runs:
            model = run.get("model", "unknown")
            status = run.get("status", "")
            model_stats[model]["total"] += 1
            if status == "completed":
                model_stats[model]["completed"] += 1
            elif "failed" in status:
                model_stats[model]["failed"] += 1

        for model, stats in model_stats.items():
            success_rate = stats["completed"] / stats["total"] if stats["total"] > 0 else 0.0
            self._add_if_new(
                insights,
                "model_performance",
                model,
                {
                    "model": model,
                    "total_runs": stats["total"],
                    "completed": stats["completed"],
                    "failed": stats["failed"],
                    "success_rate": round(success_rate, 2),
                    "summary": (
                        f"{model}: {stats['completed']}/{stats['total']} "
                        f"({success_rate:.0%} success)"
                    ),
                },
            )

    def _pass_tool_effectiveness(
        self,
        runs: list[dict[str, Any]],
        insights: list[dict[str, Any]],
    ) -> None:
        """Pass 5: Aggregate success/failure by tool used."""
        tool_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0, "total": 0}
        )
        for run in runs:
            tools = run.get("tools_used", [])
            status = run.get("status", "")
            succeeded = status == "completed"
            for tool in tools:
                tool_stats[tool]["total"] += 1
                if succeeded:
                    tool_stats[tool]["success"] += 1
                else:
                    tool_stats[tool]["failure"] += 1

        for tool, stats in tool_stats.items():
            success_rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0.0
            self._add_if_new(
                insights,
                "tool_effectiveness",
                tool,
                {
                    "tool": tool,
                    "total_uses": stats["total"],
                    "successes": stats["success"],
                    "failures": stats["failure"],
                    "success_rate": round(success_rate, 2),
                    "summary": (
                        f"{tool}: {stats['success']}/{stats['total']} ({success_rate:.0%} success)"
                    ),
                },
            )
