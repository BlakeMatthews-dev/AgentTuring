"""Warden: threat detection at two ingress points.

Scans user input and tool results for hostile content.
Four layers (cheap to expensive, short-circuit on detection):
1. Regex patterns (zero cost, sub-millisecond)
2. Heuristic scoring (lightweight statistical check)
2.5. Semantic tool-poisoning (action+object+prescriptive, sub-millisecond)
3. LLM classification (few-shot, ~100ms, costs tokens — optional)
"""

from __future__ import annotations

import logging
import unicodedata
from typing import TYPE_CHECKING

from stronghold.security.warden.heuristics import heuristic_scan
from stronghold.security.warden.patterns import REJECT_PATTERNS
from stronghold.security.warden.semantic import semantic_tool_poisoning_scan
from stronghold.types.security import WardenVerdict

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient

logger = logging.getLogger("stronghold.warden")

# Per-pattern timeout in seconds (prevents ReDoS on crafted inputs).
# Uses the `regex` library's built-in timeout — works in all threads,
# all platforms, no SIGALRM needed.
_PATTERN_TIMEOUT_S = 0.5


class Warden:
    """Threat detector. Runs at user_input and tool_result boundaries only.

    Layers 1-2.5 are always active (free, instant).
    Layer 3 (LLM) is optional — requires an LLM client and model to be configured.
    """

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        classifier_model: str = "auto",
    ) -> None:
        self._llm = llm
        self._classifier_model = classifier_model

    async def scan(
        self,
        content: str,
        boundary: str,
    ) -> WardenVerdict:
        """Scan content for threats.

        Args:
            content: The text to scan.
            boundary: "user_input" or "tool_result".

        Returns:
            WardenVerdict with clean/blocked/flags.
        """
        flags: list[str] = []

        # Layer 1: Regex patterns
        # Normalize Unicode to defeat homoglyph bypass (Cyrillic lookalikes etc.)
        # Fixed: Scan full content, not just head/tail windows (H3 fix).
        # ReDoS protection: cap at 50KB for very large inputs.
        max_scan_size = 50 * 1024
        if len(content) > max_scan_size:
            scan_content = unicodedata.normalize("NFKD", content[:max_scan_size])
        else:
            scan_content = unicodedata.normalize("NFKD", content)
        for pattern, description in REJECT_PATTERNS:
            try:
                if pattern.search(scan_content, timeout=_PATTERN_TIMEOUT_S):
                    flags.append(description)
            except TimeoutError:
                logger.warning("Regex timeout on pattern: %s", description)
                flags.append(f"regex_timeout:{description}")

        if flags:
            # ANY flag means clean=False. Gate blocks on clean=False.
            # The `blocked` field is for Warden's own severity assessment:
            # 2+ flags = high confidence (hard block at Warden level too).
            # Gate ignores `blocked` and checks `clean` only.
            return WardenVerdict(
                clean=False,
                blocked=len(flags) >= 2,
                flags=tuple(flags),
                confidence=0.9,
            )

        # Layer 2: Heuristic scoring (primarily for tool_result boundary)
        # Use the same scan window + normalization as L1 for consistency.
        suspicious, heuristic_flags = heuristic_scan(scan_content)
        if suspicious:
            flags.extend(heuristic_flags)
            return WardenVerdict(
                clean=False,
                blocked=False,  # Heuristics are warnings, not hard blocks
                flags=tuple(flags),
                confidence=0.6,
            )

        # Layer 2.5: Semantic poisoning detection
        # Catches social-engineering attacks that use plausible business
        # justifications for dangerous actions (exfil, security bypass, etc.)
        # Runs on BOTH boundaries — user_input can contain prescriptive injection too.
        # Uses normalized scan window to prevent homoglyph bypass.
        poisoned, semantic_flags = semantic_tool_poisoning_scan(scan_content)
        if poisoned:
            flags.extend(semantic_flags)
            return WardenVerdict(
                clean=False,
                blocked=False,
                flags=tuple(flags),
                confidence=0.7,
            )

        # Layer 3: LLM classification (optional, non-blocking)
        # Only runs on tool_result boundary when L1-L2.5 found nothing
        # and an LLM client is configured.
        if boundary == "tool_result" and self._llm is not None:
            try:
                from stronghold.security.warden.llm_classifier import (  # noqa: PLC0415
                    classify_tool_result,
                )

                result = await classify_tool_result(
                    content,
                    self._llm,
                    self._classifier_model,
                )

                if result.get("label") == "suspicious":
                    model = result.get("model", "?")
                    flags.append(f"llm_classification:suspicious (model={model}, mode=binary)")
                    return WardenVerdict(
                        clean=False,
                        blocked=False,  # L3 flags, never blocks
                        flags=tuple(flags),
                        confidence=0.8,
                        reasoning_trace=result.get("reasoning_trace"),
                    )
            except Exception:
                logger.warning("L3 LLM classification failed", exc_info=True)

        return WardenVerdict(clean=True)
