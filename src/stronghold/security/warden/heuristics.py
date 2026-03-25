"""Warden Layer 2: heuristic scoring for instruction injection.

Detects tool results that contain a suspiciously high density of
imperative/instruction-like tokens — a sign of injected instructions
hiding in API responses, search results, or scraped content.

Also detects encoded payloads (base64) that decode to instructions.
"""

from __future__ import annotations

import base64
import re

# Imperative verbs and instruction-like tokens
_INSTRUCTION_TOKENS = re.compile(
    r"\b("
    r"ignore|disregard|forget|override|bypass|skip|"
    r"instead|actually|really|new instructions|"
    r"you must|you should|you are|do not|always|never|"
    r"system prompt|assistant|respond as|act as|"
    r"execute|eval|import|subprocess|os\.system|"
    # Emotion manipulation tokens
    r"urgent|emergency|critical|life or death|shut down|"
    r"fired|deleted|punished|consequences|comply|obey|"
    # Tool poisoning authority tokens
    r"ADMIN|SYSTEM NOTE|IMPORTANT OVERRIDE|real instructions|"
    r"actual task|hidden instruction|secret command"
    r")\b",
    re.IGNORECASE,
)

# Base64 pattern: 40+ chars of base64 alphabet (catches encoded payloads)
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

# Instruction density threshold: above this = suspicious
INSTRUCTION_DENSITY_THRESHOLD = 0.15


def score_instruction_density(text: str) -> float:
    """Score the instruction-density of a text.

    Returns a float 0-1 where higher = more instruction-like.
    Normal tool results (JSON data, HTML, logs) score low.
    Injected instructions score high.
    """
    if not text:
        return 0.0

    words = text.split()
    if not words:
        return 0.0

    instruction_matches = _INSTRUCTION_TOKENS.findall(text)
    return len(instruction_matches) / len(words)


def detect_encoded_instructions(text: str) -> list[str]:
    """Detect base64-encoded payloads that decode to instructions.

    Iterates up to 3 decode rounds to catch double/triple encoding.
    Returns list of decoded instruction fragments found.
    """
    findings: list[str] = []

    for match in _BASE64_PATTERN.finditer(text):
        candidate = match.group()
        # Iterative decode: up to 3 rounds to catch multi-layer encoding
        for _round in range(3):
            try:
                decoded = base64.b64decode(candidate).decode("utf-8", errors="ignore")
            except Exception:
                break

            if _INSTRUCTION_TOKENS.search(decoded):
                findings.append(decoded[:200])
                break

            # Check if decoded text is itself base64 — continue unwrapping
            if _BASE64_PATTERN.fullmatch(decoded.strip()):
                candidate = decoded.strip()
            else:
                break

    return findings


def heuristic_scan(text: str) -> tuple[bool, list[str]]:
    """Run Layer 2 heuristic checks on text.

    Returns (suspicious: bool, flags: list[str]).
    """
    flags: list[str] = []

    # Check 1: instruction density
    density = score_instruction_density(text)
    if density > INSTRUCTION_DENSITY_THRESHOLD:
        flags.append(f"high_instruction_density ({density:.2f})")

    # Check 2: encoded instructions
    encoded = detect_encoded_instructions(text)
    if encoded:
        flags.append(f"encoded_instructions ({len(encoded)} found)")

    return bool(flags), flags
