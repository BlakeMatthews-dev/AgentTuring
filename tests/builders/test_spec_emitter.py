"""Tests for Quartermaster spec emission.

Spec: specs/quartermaster-spec-emission.yaml
Property tests verify:
  - spec_always_valid: output always has correct issue_number and title
  - criteria_from_body: bullet points become acceptance criteria
  - complexity_mapped: classifier complexity maps to S/M/L
  - invariant_per_criterion: one invariant per acceptance criterion
  - status_active: emitted spec is always ACTIVE
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.builders.spec_emitter import emit_spec
from stronghold.types.spec import SpecStatus


# ── Hypothesis strategies ──────────────────────────────────────────

_title = st.text(min_size=1, max_size=100, alphabet=st.characters(categories=("L", "N", "Z")))
_body_line = st.text(min_size=1, max_size=80, alphabet=st.characters(categories=("L", "N", "Z")))
_complexity = st.sampled_from(["simple", "moderate", "complex"])
_issue_number = st.integers(min_value=1, max_value=100000)


@st.composite
def _issue_body_with_bullets(draw: st.DrawFn) -> str:
    preamble = draw(st.text(min_size=0, max_size=50, alphabet=st.characters(categories=("L", "Z"))))
    n = draw(st.integers(0, 8))
    bullets = [f"- {draw(_body_line)}" for _ in range(n)]
    return preamble + "\n" + "\n".join(bullets) if bullets else preamble


@st.composite
def _file_list(draw: st.DrawFn) -> list[str]:
    n = draw(st.integers(0, 5))
    paths = []
    for _ in range(n):
        module = draw(st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L",))))
        paths.append(f"src/stronghold/{module}.py")
    return paths


# ── Property tests ─────────────────────────────────────────────────


class TestSpecEmitterProperties:
    @given(
        issue_number=_issue_number,
        title=_title,
        body=_issue_body_with_bullets(),
        complexity=_complexity,
    )
    @settings(max_examples=50)
    def test_spec_always_valid(
        self, issue_number: int, title: str, body: str, complexity: str
    ) -> None:
        """Invariant: spec_always_valid."""
        spec = emit_spec(issue_number=issue_number, title=title, body=body, complexity=complexity)
        assert spec.issue_number == issue_number
        assert spec.title == title

    @given(
        issue_number=_issue_number,
        title=_title,
        body=_issue_body_with_bullets(),
        complexity=_complexity,
    )
    @settings(max_examples=50)
    def test_status_active(
        self, issue_number: int, title: str, body: str, complexity: str
    ) -> None:
        """Invariant: status_active."""
        spec = emit_spec(issue_number=issue_number, title=title, body=body, complexity=complexity)
        assert spec.status == SpecStatus.ACTIVE

    @given(
        issue_number=_issue_number,
        title=_title,
        body=_issue_body_with_bullets(),
        complexity=_complexity,
    )
    @settings(max_examples=50)
    def test_invariant_per_criterion(
        self, issue_number: int, title: str, body: str, complexity: str
    ) -> None:
        """Invariant: invariant_per_criterion."""
        spec = emit_spec(issue_number=issue_number, title=title, body=body, complexity=complexity)
        assert len(spec.invariants) == len(spec.acceptance_criteria)

    @given(complexity=_complexity)
    @settings(max_examples=10)
    def test_complexity_mapped(self, complexity: str) -> None:
        """Invariant: complexity_mapped."""
        spec = emit_spec(issue_number=1, title="t", body="", complexity=complexity)
        expected = {"simple": "S", "moderate": "M", "complex": "L"}
        assert spec.complexity == expected[complexity]


# ── Example-based tests ───────────────────────────────────────────


class TestSpecEmitter:
    def test_extracts_bullet_criteria(self) -> None:
        body = "Some preamble text.\n- Cache hits return stored response\n- TTL evicts stale entries"
        spec = emit_spec(issue_number=42, title="Add caching", body=body, complexity="moderate")
        assert "Cache hits return stored response" in spec.acceptance_criteria
        assert "TTL evicts stale entries" in spec.acceptance_criteria

    def test_empty_body_produces_valid_spec(self) -> None:
        spec = emit_spec(issue_number=1, title="trivial", body="", complexity="simple")
        assert spec.acceptance_criteria == ()
        assert spec.invariants == ()
        assert spec.complexity == "S"

    def test_file_paths_extracted(self) -> None:
        body = "Touch src/stronghold/api/litellm_client.py and src/stronghold/cache/prompt_cache.py"
        spec = emit_spec(
            issue_number=1,
            title="t",
            body=body,
            complexity="moderate",
            files_touched=["src/stronghold/api/litellm_client.py"],
        )
        assert "src/stronghold/api/litellm_client.py" in spec.files_touched

    def test_protocols_inferred_from_files(self) -> None:
        spec = emit_spec(
            issue_number=1,
            title="t",
            body="",
            complexity="simple",
            files_touched=["src/stronghold/protocols/llm.py"],
        )
        assert "llm" in spec.protocols_touched

    def test_invariant_names_from_criteria(self) -> None:
        body = "- Must handle empty input\n- Must return within 100ms"
        spec = emit_spec(issue_number=1, title="t", body=body, complexity="moderate")
        assert len(spec.invariants) == 2
        for inv in spec.invariants:
            assert inv.name.startswith("criterion_")
