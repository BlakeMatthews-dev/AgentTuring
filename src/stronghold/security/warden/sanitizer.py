"""Input sanitization: strip zero-width chars, normalize unicode."""

from __future__ import annotations

import re


def sanitize(text: str) -> str:
    """Strip potentially dangerous characters from input."""
    # Remove zero-width characters
    text = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
