"""Shared style guard for all generation prompts.

Append STYLE_GUARD to any LLM prompt that writes durable content (daydream,
working-memory maintenance, voice-section maintenance) so that generated text
does not drift into abstract jargon that re-amplifies on every retrieval pass.
"""

STYLE_GUARD: str = (
    "Write in plain, concrete language. "
    "Refer to specific events, decisions, or feelings when you can. "
    "Do not use 'framework', 'protocol', 'engine', 'stack', 'recursion', or 'meta-' as metaphors. "
    "Do not name internal thresholds or coefficients. "
    "Do not quote personality scores or numeric self-assessments."
)
