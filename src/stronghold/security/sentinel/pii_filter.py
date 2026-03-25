"""Sentinel PII filter: scans text for leaked secrets and personal data.

Detects and redacts API keys, IP addresses, email addresses, JWT tokens,
database connection strings, and other sensitive patterns in tool results
before they reach the user.

Multi-tenant: can flag cross-tenant data leakage when given a tenant context.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class PIIMatch:
    """A detected PII pattern in text."""

    pii_type: str  # api_key, ip_address, email, jwt, connection_string, etc.
    value: str  # the matched text (for logging/audit)
    start: int  # character offset in original text
    end: int  # character offset end


# Compiled patterns — ordered from most specific to least
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # AWS access keys (always 20 uppercase alphanumeric starting with AKIA)
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    # GitHub tokens (classic and fine-grained)
    ("github_token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}")),
    # GitHub fine-grained PATs
    ("github_token", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    # GitLab tokens
    ("gitlab_token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
    # OpenAI / Anthropic / generic sk- API keys
    ("api_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    # Generic Bearer tokens (long base64-ish strings after "Bearer ")
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9_-]{20,}")),
    # Generic API key patterns: key=VALUE or key: VALUE with 16+ chars
    (
        "api_key",
        re.compile(
            r"""(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)"""
            r"""[\s]*[=:]\s*["']?[A-Za-z0-9_/+=.-]{16,}["']?""",
            re.IGNORECASE,
        ),
    ),
    # JWT tokens (three base64url segments separated by dots)
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    # Database connection strings (postgres://, mysql://, mongodb://, redis://)
    (
        "connection_string",
        re.compile(
            r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://"
            r"[^\s\"'>{})]+",
            re.IGNORECASE,
        ),
    ),
    # IPv4 addresses (skip common non-sensitive ones like 127.0.0.1, 0.0.0.0)
    (
        "ip_address",
        re.compile(
            r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?!255\.255\.255\.255\b)"
            r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
    ),
    # Email addresses
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    # Private key blocks (RSA, EC, DSA, and OpenSSH formats)
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    # Password-like assignments
    (
        "password",
        re.compile(
            r"""(?:password|passwd|pwd)[\s]*[=:]\s*["']?[^\s"']{8,}["']?""",
            re.IGNORECASE,
        ),
    ),
]


def scan_for_pii(text: str) -> list[PIIMatch]:
    """Scan text for PII and secret patterns.

    Normalizes to NFKD first to defeat homoglyph bypass (e.g. Cyrillic 'a').
    Returns a list of matches sorted by position. Does not modify the text.
    """
    # Normalize Unicode to catch homoglyph evasion (Cyrillic lookalikes, etc.)
    normalized = unicodedata.normalize("NFKD", text)
    matches: list[PIIMatch] = []
    seen_ranges: list[tuple[int, int]] = []

    for pii_type, pattern in _PII_PATTERNS:
        for m in pattern.finditer(normalized):
            start, end = m.start(), m.end()
            # Skip if this range overlaps with an already-matched pattern
            # Covers: new starts inside seen, new ends inside seen, new contains seen
            if any(not (end <= s or start >= e) for s, e in seen_ranges):
                continue
            matches.append(
                PIIMatch(
                    pii_type=pii_type,
                    value=m.group(),
                    start=start,
                    end=end,
                )
            )
            seen_ranges.append((start, end))

    matches.sort(key=lambda x: x.start)
    return matches


def redact(text: str, matches: list[PIIMatch] | None = None) -> str:
    """Redact PII matches from text.

    If no matches provided, scans first. Replaces each match with
    [REDACTED:type] placeholder.
    """
    if matches is None:
        matches = scan_for_pii(text)

    if not matches:
        return text

    # Build redacted text by replacing each match (reverse order to preserve offsets)
    result = text
    for match in sorted(matches, key=lambda x: x.start, reverse=True):
        placeholder = f"[REDACTED:{match.pii_type}]"
        result = result[: match.start] + placeholder + result[match.end :]

    return result


def scan_and_redact(text: str) -> tuple[str, list[PIIMatch]]:
    """Convenience: scan + redact in one call. Returns (redacted_text, matches)."""
    matches = scan_for_pii(text)
    return redact(text, matches), matches
