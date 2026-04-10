#!/usr/bin/env python3
"""LLM-based code smell analysis for PR diffs.

Runs in CI against every PR. Sends the diff to a capable model via the
Stronghold conductor-router (or LiteLLM directly) and asks for a rigorous
code review. Blocks the PR on any findings the model flags as P0 (critical)
or P1 (high).

Usage:
    scripts/ci/llm-code-review.py <base_ref>

Exit codes:
    0 — no blocking findings
    1 — P0/P1 findings present; PR should block
    2 — LLM or network error (retryable)

Environment:
    LITELLM_URL          LiteLLM proxy URL (default: http://localhost:4000)
    LITELLM_MASTER_KEY   LiteLLM master key
    REVIEW_MODEL         Model to use (default: gemini-2.5-pro)
    GITHUB_TOKEN         For posting PR comments (optional)
    PR_NUMBER            PR number (optional; posts comment if set)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-ci-test-key-minimum-32-characters")
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "gemini-2.5-pro")
MAX_DIFF_BYTES = 80_000  # ~20k tokens; above this we summarize per file

REVIEW_SYSTEM_PROMPT = """\
You are a senior Python/infrastructure code reviewer for Stronghold, an
enterprise multi-tenant agent governance platform. You review PR diffs
for code smells, bugs, security issues, and maintainability problems.

For each issue you find, classify severity:
- **P0 (BLOCKER)**: security vulnerability, data corruption, crash, broken auth/policy
- **P1 (HIGH)**: bug likely to cause incidents, leaks, races, missing validation
- **P2 (MEDIUM)**: code smell, maintainability, missing tests, weak error handling
- **P3 (LOW)**: style, naming, minor refactoring suggestions

BLOCK the PR if you find ANY P0 or P1 issues.

Focus areas (in priority order):
1. **Cross-tenant isolation**: every DB query in persistence/ must scope by org_id
2. **Security**: auth bypass, JWT forgery, injection, SSRF, missing input validation
3. **Warden/Sentinel gaps**: LLM calls without scans, tool dispatch without policy check
4. **Correctness**: race conditions, error paths, resource leaks, missing await
5. **Tests**: new code without tests, assertions that don't actually verify behavior
6. **Code smells**: duplication, overly complex functions, dead code, unclear naming

Output MUST be valid JSON with this exact schema:
{
  "summary": "1-2 sentence overall assessment",
  "verdict": "APPROVE" | "BLOCK",
  "findings": [
    {
      "severity": "P0" | "P1" | "P2" | "P3",
      "file": "path/to/file.py",
      "line": 42,
      "category": "security | correctness | tests | smell | style",
      "title": "Short description",
      "detail": "Explanation of what's wrong and how to fix it"
    }
  ]
}

If there are no issues, return {"summary": "LGTM", "verdict": "APPROVE", "findings": []}.
Only BLOCK if there is at least one P0 or P1 finding.
Do not wrap the JSON in markdown code fences.
"""


def get_diff(base_ref: str) -> str:
    """Get the diff against the base branch, limited to Python + YAML files."""
    result = subprocess.run(
        [
            "git", "diff",
            f"{base_ref}...HEAD",
            "--",
            "*.py", "*.yml", "*.yaml", "Dockerfile*",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"git diff failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)
    return result.stdout


def truncate_diff(diff: str, max_bytes: int) -> str:
    """Truncate diff to fit in the model's context."""
    if len(diff) <= max_bytes:
        return diff
    # Keep the top of each file header + the first N bytes of each hunk
    print(f"Diff is {len(diff)} bytes, truncating to {max_bytes}", file=sys.stderr)
    return diff[:max_bytes] + "\n\n[... truncated ...]"


def call_llm(diff: str) -> dict[str, Any]:
    """Call LiteLLM with the diff and return the parsed JSON review."""
    import urllib.error
    import urllib.request

    body = {
        "model": REVIEW_MODEL,
        "messages": [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Review this PR diff. Return ONLY valid JSON per the "
                    "schema in the system prompt.\n\n"
                    f"```diff\n{diff}\n```"
                ),
            },
        ],
        "temperature": 0.0,
        "max_tokens": 4000,
    }
    req = urllib.request.Request(
        f"{LITELLM_URL}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LITELLM_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"LLM HTTP error: {e.code} {e.read().decode()[:500]}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"LLM call failed: {e}", file=sys.stderr)
        sys.exit(2)

    content = data["choices"][0]["message"]["content"].strip()
    # Strip markdown fences if the model added them despite instructions
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"LLM returned invalid JSON: {e}", file=sys.stderr)
        print(f"Raw content: {content[:1000]}", file=sys.stderr)
        sys.exit(2)


def format_pr_comment(review: dict[str, Any]) -> str:
    """Format the review as a GitHub PR comment."""
    summary = review.get("summary", "No summary")
    verdict = review.get("verdict", "UNKNOWN")
    findings = review.get("findings", [])

    icon = ":white_check_mark:" if verdict == "APPROVE" else ":x:"

    lines = [
        f"## {icon} LLM Code Review — {verdict}",
        "",
        f"**Model:** `{REVIEW_MODEL}`",
        f"**Summary:** {summary}",
        "",
    ]

    if not findings:
        lines.append("No findings. :sparkles:")
        return "\n".join(lines)

    # Group by severity
    by_severity: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_severity.setdefault(f.get("severity", "P3"), []).append(f)

    for sev in ["P0", "P1", "P2", "P3"]:
        if sev not in by_severity:
            continue
        icon_map = {"P0": ":rotating_light:", "P1": ":warning:", "P2": ":bulb:", "P3": ":speech_balloon:"}
        lines.append(f"### {icon_map[sev]} {sev} ({len(by_severity[sev])})")
        lines.append("")
        for f in by_severity[sev]:
            file_path = f.get("file", "?")
            line_num = f.get("line", "?")
            category = f.get("category", "?")
            title = f.get("title", "No title")
            detail = f.get("detail", "")
            lines.append(f"- **`{file_path}:{line_num}`** ({category}) — {title}")
            if detail:
                lines.append(f"  - {detail}")
        lines.append("")

    return "\n".join(lines)


def post_pr_comment(pr_number: str, body: str) -> None:
    """Post a comment on the PR via gh CLI."""
    result = subprocess.run(
        ["gh", "pr", "comment", pr_number, "--body", body],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Failed to post PR comment: {result.stderr}", file=sys.stderr)
    else:
        print(f"Posted PR comment to #{pr_number}", file=sys.stderr)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: llm-code-review.py <base_ref>", file=sys.stderr)
        return 2

    base_ref = sys.argv[1]
    diff = get_diff(base_ref)

    if not diff.strip():
        print("No relevant changes in diff — skipping LLM review.", file=sys.stderr)
        return 0

    diff = truncate_diff(diff, MAX_DIFF_BYTES)
    print(f"Sending {len(diff)} bytes of diff to {REVIEW_MODEL}...", file=sys.stderr)

    review = call_llm(diff)
    comment = format_pr_comment(review)
    print(comment)

    pr_number = os.environ.get("PR_NUMBER")
    if pr_number:
        post_pr_comment(pr_number, comment)

    verdict = review.get("verdict", "UNKNOWN")
    findings = review.get("findings", [])
    blocking = [f for f in findings if f.get("severity") in ("P0", "P1")]

    if verdict == "BLOCK" or blocking:
        print(
            f"\n::error::LLM review blocked: {len(blocking)} P0/P1 findings",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
