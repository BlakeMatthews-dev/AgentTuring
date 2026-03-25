"""Request sufficiency analyzer: determines if a request has enough detail.

Checks for task-type-specific signals:
- WHAT: what needs to be done (action, feature, fix, device, query)
- WHERE: which target (file, device, service, topic)
- HOW: expected behavior, constraints, format
- CONTEXT: framework, language, domain context

Conversation-aware: prior messages in the session can supply missing context,
so a follow-up like "yes do it" is sufficient if the prior turn was detailed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MissingDetail:
    """A piece of information the request is missing."""

    category: str  # what, where, how, context
    question: str  # the follow-up question to ask


@dataclass
class SufficiencyResult:
    """Result of analyzing whether a request is detailed enough."""

    sufficient: bool
    confidence: float  # 0-1
    missing: list[MissingDetail] = field(default_factory=list)
    summary: str = ""


# ── Per-task-type signal definitions ──────────────────────────────

_TASK_PROFILES: dict[str, dict[str, Any]] = {
    "code": {
        "what": [
            re.compile(r"\b(function|class|method|endpoint|api|route)\b", re.I),
            re.compile(r"\b(fix|add|create|implement|write|build|update|remove|delete)\b", re.I),
            re.compile(r"\b(bug|error|issue|problem|broken|crash|fail)\b", re.I),
        ],
        "where": [
            re.compile(r"\b\w+\.(py|js|ts|go|rs|java|yaml|json|md)\b", re.I),
            re.compile(r"\b(file|module|package|directory|folder|repo)\b", re.I),
            re.compile(r"\b(auth|router|database|middleware|handler|controller)\b", re.I),
        ],
        "how": [
            re.compile(r"\b(return|output|result|should|expect|response)\b", re.I),
            re.compile(r"\b(tests?|verify|check|assert|validate)\b", re.I),
            re.compile(r"\b(type hints?|typed|mypy|strict)\b", re.I),
            re.compile(r"\b(401|403|404|500|true|false|none|null)\b", re.I),
        ],
        "context": [
            re.compile(r"\b(python|javascript|typescript|fastapi|django|react)\b", re.I),
            re.compile(r"\b(jwt|oauth|session|cookie|token)\b", re.I),
            re.compile(r"\b(postgres|redis|sqlite|mongodb)\b", re.I),
            re.compile(r"\b(docker|kubernetes|k8s|helm)\b", re.I),
        ],
        "min_words": 6,
        "what_question": "What specifically needs to be done? (e.g., write a function, fix a bug)",
        "where_question": "Which file, module, or system? (e.g., auth.py, the login endpoint)",
        "how_question": "What should the expected behavior be? (e.g., return 200)",
    },
    "automation": {
        "what": [
            re.compile(r"\b(turn|set|switch|toggle|dim|lock|unlock|open|close)\b", re.I),
            re.compile(r"\b(on|off|start|stop|enable|disable)\b", re.I),
            re.compile(r"\b(run|execute|trigger|schedule|remind)\b", re.I),
        ],
        "where": [
            re.compile(r"\b(light|fan|switch|lock|thermostat|cover|valve|sensor)\b", re.I),
            re.compile(r"\b(bedroom|kitchen|living|office|garage|bathroom|hallway)\b", re.I),
            re.compile(r"\b(device|entity|service|automation)\b", re.I),
        ],
        "how": [],  # Automation rarely needs HOW — action + device is enough
        "context": [],
        "min_words": 3,
        "what_question": "What action? (e.g., turn on, set brightness, lock)",
        "where_question": "Which device or room? (e.g., bedroom light, front door)",
    },
    "search": {
        "what": [
            re.compile(r"\b(search|find|look|query|what|how|why|when|where|who)\b", re.I),
        ],
        "where": [],  # Search doesn't need WHERE
        "how": [],
        "context": [],
        "min_words": 2,
        "what_question": "What are you looking for?",
    },
    "creative": {
        "what": [
            re.compile(r"\b(write|compose|draft|generate|create|brainstorm)\b", re.I),
            re.compile(r"\b(poem|story|essay|email|letter|message|post|blog|article|copy)\b", re.I),
        ],
        "where": [
            re.compile(r"\b(audience|reader|recipient|client|team|boss|friend|child)\b", re.I),
        ],
        "how": [
            re.compile(
                r"\b(tone|style|formal|casual|funny|serious|short|long|persuasive|heartfelt)\b",
                re.I,
            ),
            re.compile(r"\b(for|about|regarding|on the topic)\b", re.I),
        ],
        "context": [
            re.compile(r"\b(theme|topic|subject|genre|mood|include|mention|reference)\b", re.I),
        ],
        "min_words": 8,
        "max_missing": 0,
        "what_question": "What kind of content? (e.g., email, story, blog post, poem)",
        "where_question": "Who is the audience? (e.g., a client, your team, social media)",
        "how_question": "What tone or style? (e.g., formal, casual, persuasive, heartfelt)",
        "context_question": "What topic or theme? Any specific points to include?",
    },
    "chat": {
        # Chat is almost always sufficient — it's conversational
        "what": [],
        "where": [],
        "how": [],
        "context": [],
        "min_words": 1,
        "always_sufficient": True,
    },
    "reasoning": {
        "what": [
            re.compile(r"\b(analyze|explain|compare|evaluate|reason|think|solve)\b", re.I),
            re.compile(r"\b(why|how|what if|prove|derive|calculate)\b", re.I),
        ],
        "where": [],
        "how": [
            re.compile(r"\b(step by step|detail|thorough|brief|concise)\b", re.I),
        ],
        "context": [],
        "min_words": 5,
        "what_question": "What should be analyzed or explained?",
    },
}

# Confirmation patterns that indicate a follow-up to a prior detailed message
_CONFIRMATION_PATTERNS = re.compile(
    r"^(yes|yeah|yep|ok|okay|sure|do it|go ahead|proceed|confirm|approved|lgtm|"
    r"that works|sounds good|exactly|correct|right|please|go)\b",
    re.I,
)


def analyze_request_sufficiency(
    text: str,
    task_type: str = "code",
    *,
    conversation_context: list[dict[str, str]] | None = None,
) -> SufficiencyResult:
    """Analyze if a request has enough detail for a specialist agent.

    Args:
        text: The user's current message.
        task_type: The classified task type (code, automation, search, etc.)
        conversation_context: Prior messages in the session. If the prior turn
            already established context, a short confirmation is sufficient.
    """
    profile = _TASK_PROFILES.get(task_type, _TASK_PROFILES["code"])

    # Chat is always sufficient
    if profile.get("always_sufficient"):
        return SufficiencyResult(sufficient=True, confidence=1.0)

    # Check if this is a confirmation of a prior detailed message
    if conversation_context and _is_confirmation(text, conversation_context):
        return SufficiencyResult(
            sufficient=True,
            confidence=0.85,
            summary="Follow-up confirmation of prior detailed request",
        )

    # Check signals
    missing: list[MissingDetail] = []
    signal_flags: dict[str, bool] = {}

    for category in ("what", "where", "how", "context"):
        patterns = profile.get(category, [])
        if not patterns:
            signal_flags[category] = True  # No patterns = not required for this task type
            continue
        signal_flags[category] = any(p.search(text) for p in patterns)
        if not signal_flags[category]:
            question = profile.get(
                f"{category}_question", f"Please provide more {category} detail."
            )
            missing.append(MissingDetail(category, question))

    word_count = len(text.split())
    min_words = profile.get("min_words", 6)
    signal_count = sum(signal_flags.values())
    total_signals = len(signal_flags)

    # Hard floor: under min_words is never sufficient
    if word_count < min_words:
        return SufficiencyResult(
            sufficient=False,
            confidence=0.1,
            missing=missing or [MissingDetail("detail", "Please provide more detail.")],
        )

    # Confidence based on signal coverage + length
    signal_ratio = signal_count / max(total_signals, 1)
    if signal_ratio >= 0.75:  # noqa: PLR2004
        confidence = 0.9 if word_count >= 10 else 0.7  # noqa: PLR2004
    elif signal_ratio >= 0.5:  # noqa: PLR2004
        confidence = 0.7 if word_count >= 8 else 0.5  # noqa: PLR2004
    elif signal_ratio >= 0.25:  # noqa: PLR2004
        confidence = 0.4
    else:
        confidence = 0.1

    max_missing = profile.get("max_missing", 1)
    sufficient = confidence >= 0.7 and len(missing) <= max_missing

    return SufficiencyResult(
        sufficient=sufficient,
        confidence=confidence,
        missing=missing,
    )


# Patterns indicating the assistant made a proposal the user can confirm
_PROPOSAL_PATTERNS = re.compile(
    r"(shall I|should I|want me to|I'll|I will|I can|let me|"
    r"here's my plan|my approach|I propose|I recommend|"
    r"would you like me to|do you want me to|ready to proceed|"
    r"proceed\?|go ahead\?|sound good\?)",
    re.I,
)


def _is_confirmation(
    text: str,
    conversation_context: list[dict[str, str]],
) -> bool:
    """Check if the current message is a confirmation of a prior proposal.

    A short affirmative like "yes do it" is sufficient ONLY if the previous
    assistant message was explicitly a proposal (contains proposal language),
    not just any long response. This prevents confirmation hijacking where
    an attacker gets a long response on topic A then says "yes" to trigger
    topic B.
    """
    # Must be short (confirmation messages are brief)
    if len(text.split()) > 10:  # noqa: PLR2004
        return False

    # Must match a confirmation pattern
    if not _CONFIRMATION_PATTERNS.search(text.strip()):
        return False

    # Must have a prior assistant message that was a PROPOSAL (not just long)
    for msg in reversed(conversation_context):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            # Prior message must be substantial AND contain proposal language
            if len(content.split()) >= 15 and _PROPOSAL_PATTERNS.search(content):  # noqa: PLR2004
                return True
            break

    return False
