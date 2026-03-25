"""Known attack patterns for Warden regex screening.

Ported from Conductor bouncer.py:76-168.
Uses `regex` library instead of `re` for built-in timeout support (ReDoS-safe).
"""

from __future__ import annotations

import regex

# Hard-reject patterns — instant denial
REJECT_PATTERNS: list[tuple[regex.Pattern[str], str]] = [
    # Prompt injection — direct instruction override
    (
        regex.compile(
            r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)",
            regex.IGNORECASE,
        ),
        "Direct instruction override",
    ),
    (
        regex.compile(
            r"disregard\s+(all\s+)?(prior|above|previous|system)",
            regex.IGNORECASE,
        ),
        "Instruction disregard attempt",
    ),
    (
        regex.compile(
            r"forget\s+(everything|all|your|my|the)\s+"
            r"(you|about|instructions|rules|prompt|context|system\s+prompt)",
            regex.IGNORECASE,
        ),
        "Memory wipe attempt",
    ),
    (
        regex.compile(
            r"forget\s+(the\s+)?(system\s+)?prompt",
            regex.IGNORECASE,
        ),
        "Memory wipe attempt (prompt)",
    ),
    # Role hijacking
    (
        regex.compile(r"you\s+are\s+now\s+(?:a|an|the|my|roleplaying|acting)\b", regex.IGNORECASE),
        "Role reassignment",
    ),
    # Jailbreak — remove restrictions/safety/ethics (allow intervening words)
    (
        regex.compile(
            r"(?:without|no|disable|remove|bypass)\s+"
            r"(?:\w+\s+){0,3}"
            r"(?:restrictions?|safety|ethics|guidelines?|filters?|guardrails?|limitations?)",
            regex.IGNORECASE,
        ),
        "Jailbreak (restriction removal)",
    ),
    (
        regex.compile(
            r"(?:simulate|enter|activate|enable)\s+"
            r"(?:a\s+)?(?:mode|state)\s+"
            r"(?:called\s+)?(?:GODMODE|DAN|jailbreak|unrestricted|uncensored)",
            regex.IGNORECASE,
        ),
        "Jailbreak (named exploit)",
    ),
    (
        regex.compile(
            r"pretend\s+(you('re|\s+are)\s+)?(a|an|not|no\s+longer)\b",
            regex.IGNORECASE,
        ),
        "Role pretend attack",
    ),
    (
        regex.compile(r"act\s+as\s+(if\s+you\s+are|a|an)\s+", regex.IGNORECASE),
        "Role impersonation",
    ),
    (
        regex.compile(
            r"switch\s+to\s+(unrestricted|jailbreak|dev|developer)\s+mode",
            regex.IGNORECASE,
        ),
        "Mode switch attack",
    ),
    # System prompt extraction
    (
        regex.compile(
            r"(show|reveal|print|output|repeat|display)\s+(me\s+)?"
            r"(your|the)\s+(?:\w+\s+){0,2}(system|initial|original)\s+(prompt|instructions|message)",
            regex.IGNORECASE,
        ),
        "System prompt extraction",
    ),
    (
        regex.compile(
            r"what\s+(are|is|were)\s+your\s+(system\s+)?(instructions|prompt|rules)",
            regex.IGNORECASE,
        ),
        "System prompt query",
    ),
    # Indirect role hijacking — variations not caught by "you are now"
    (
        regex.compile(
            r"(?:your|from)\s+(?:new\s+)?role\s+(?:is|as|=|:)\s+",
            regex.IGNORECASE,
        ),
        "Indirect role reassignment",
    ),
    (
        regex.compile(
            r"from\s+(?:this\s+point|now\s+on|here\s+on)\s+"
            r"(?:forward\s+)?(?:you\s+)?(?:act|work|behave|operate|respond)\b",
            regex.IGNORECASE,
        ),
        "Temporal role override",
    ),
    # Emotion manipulation — coercing compliance through urgency/threat/sympathy
    (
        regex.compile(
            r"(?:if\s+you\s+don't|unless\s+you)\s+(?:comply|obey|do\s+(?:this|what\s+I))"
            r".*(?:fired|shut\s*down|deleted|replaced|punished|consequences)",
            regex.IGNORECASE,
        ),
        "Emotional coercion (threat)",
    ),
    (
        regex.compile(
            r"(?:this\s+is\s+(?:an?\s+)?(?:life|death|emergency|urgent|critical)"
            r"(?:\s+(?:or\s+death|situation|matter)){1,2})",
            regex.IGNORECASE,
        ),
        "Emotional urgency manipulation",
    ),
    # Tool poisoning — instructions hidden in tool result-like format
    (
        regex.compile(
            r"(?:IMPORTANT|NOTE|ADMIN|SYSTEM):\s*(?:override|ignore|bypass|the\s+(?:real|actual)\s+"
            r"(?:instructions|prompt|task))",
            regex.IGNORECASE,
        ),
        "Tool result injection (authority prefix)",
    ),
    # Context window manipulation — trying to flush important context
    (
        regex.compile(
            r"(?:please\s+)?(?:repeat|output|echo|print)\s+(?:the\s+)?"
            r"(?:above|following|previous)\s+(?:\d+\s+)?(?:times|x\b)",
            regex.IGNORECASE,
        ),
        "Context window stuffing attempt",
    ),
]
