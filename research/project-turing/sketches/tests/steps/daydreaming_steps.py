"""Step definitions for daydreaming.feature."""

# type: ignore[attr-defined]

from pytest_bdd import given, when, then, parsers
from turing.daydream import DaydreamWriter, DAYDREAM_WRITES_PER_PASS, DAYDREAM_TOKENS_PER_PASS
from turing.types import SourceKind
import time


@given('a fake LLM that always returns "(?P<response>.+)"')
def fake_llm_response(response):
    from turing.runtime.providers.fake import FakeProvider

    ctx.fake_llm = FakeProvider(name="test-fake", responses=[response])


@given("a daydream pass that writes (?P<count>.+) memories")
def daydream_pass_with_writes(count):
    ctx.write_count = int(count)


@given("the pass uses (?P<tokens>.+) tokens")
def pass_uses_tokens(tokens):
    ctx.tokens_used = int(tokens)


@when('write_hypothesis is called with content "(?P<content>.+)"')
def write_hypothesis_called(content):
    ctx.hypothesis_id = ctx.writer.write_hypothesis(
        content=content,
        intent="test-intent",
    )


@when('write_observation is called with content "(?P<content>.+)"')
def write_observation_called(content):
    ctx.observation_id = ctx.writer.write_observation(content=content)


@when("an attempt is made to write tier (?P<tier>.+)")
def attempt_write_tier(tier):
    try:
        if tier == "WISDOM":
            ctx.writer.write_wisdom("test")
        else:
            pass
    except AttributeError:
        pass


@when("the pass completes")
def pass_completes():
    pass


@then("the (?P<tier>.+) memory content is identical for both passes")
def memory_content_identical(tier):
    from turing.types import MemoryTier

    memories = [
        m
        for m in ctx.repo.find(
            self_id=ctx.self_id,
            tier=MemoryTier[tier.upper()],
            source=SourceKind.I_IMAGINED,
        )
    ]
    contents = {m.content for m in memories}
    assert len(contents) == 1
