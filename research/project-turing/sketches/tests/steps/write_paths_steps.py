"""Step definitions for write_paths.feature."""

# type: ignore[attr-defined]

from pytest_bdd import when, then


@when("handle_accomplishment_candidate is called with empty intent")
def handle_accomplishment_empty_intent():
    from turing.write_paths import handle_accomplishment_candidate, Outcome

    ctx.result = handle_accomplishment_candidate(
        ctx.repo,
        Outcome(affect=0.6, surprise_delta=0.4),
    )


@then("an ACCOMPLISHMENT memory is created")
def accomplisment_created():
    from turing.types import MemoryTier

    memory = ctx.repo.get(ctx.result)
    assert memory is not None
    assert memory.tier == MemoryTier.ACCOMPLISHMENT
