"""GitHub playbooks — agent-oriented replacements for the github(action=…) tool.

Each playbook composes several GitHub API calls server-side and returns
a Brief. See also tools/github_shim.py for the deprecation bridge from
the old action-enum tool.
"""

from __future__ import annotations

from stronghold.playbooks.github.list_repo_activity import (
    ListRepoActivityPlaybook,
    list_repo_activity,
)
from stronghold.playbooks.github.merge_pull_request import (
    MergePullRequestPlaybook,
    merge_pull_request,
)
from stronghold.playbooks.github.open_pull_request import (
    OpenPullRequestPlaybook,
    open_pull_request,
)
from stronghold.playbooks.github.respond_to_issue import (
    RespondToIssuePlaybook,
    respond_to_issue,
)
from stronghold.playbooks.github.review_pull_request import (
    ReviewPullRequestPlaybook,
    review_pull_request,
)
from stronghold.playbooks.github.triage_issues import (
    TriageIssuesPlaybook,
    triage_issues,
)

__all__ = [
    "ListRepoActivityPlaybook",
    "MergePullRequestPlaybook",
    "OpenPullRequestPlaybook",
    "RespondToIssuePlaybook",
    "ReviewPullRequestPlaybook",
    "TriageIssuesPlaybook",
    "list_repo_activity",
    "merge_pull_request",
    "open_pull_request",
    "respond_to_issue",
    "review_pull_request",
    "triage_issues",
]
