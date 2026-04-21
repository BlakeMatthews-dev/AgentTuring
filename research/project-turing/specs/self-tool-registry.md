# Spec 31 — Self-tool registry

*The runtime surface that turns the self-tool Python functions into OpenAI function-call schemas the perception LLM can invoke, gated by trust tier. Closes F35.*

**Depends on:** [self-surface.md](./self-surface.md), [tool-layer.md](./tool-layer.md).
**Depended on by:** [memory-mirroring.md](./memory-mirroring.md), [warden-on-self-writes.md](./warden-on-self-writes.md), [conduit-runtime.md](./conduit-runtime.md), and every later self-facing spec.

---

## Current state

- `self_surface.py` defines helper functions (`recall_self`, `render_minimal_block`) but no registry.
- `self_nodes.py`, `self_todos.py` etc. expose `note_passion`, `write_self_todo`, etc. as plain callables.
- `SelfTool` dataclass and `SELF_TOOL_REGISTRY` are described in spec 28 §28.2 but not in code.
- The perception LLM call (spec 30 §30.2) has no tool set to bind.

## Target

A single registry keyed by tool name, carrying the OpenAI function-call schema, the handler, and the trust tier. `register_self_tool()` at module import; `SelfRuntime.tool_schemas()` at perception time. Three tools specced elsewhere but not yet coded — `write_contributor`, `record_personality_claim`, `retract_contributor_by_counter` — land in this spec's implementation.

## Acceptance criteria

### Registry shape

- **AC-31.1.** `SelfTool` is a frozen dataclass with fields `name: str`, `description: str`, `schema: dict`, `handler: Callable`, `trust_tier: str = "t0"`. Construction validates `len(description) ≤ TOOL_DESCRIPTION_MAX = 400` and `trust_tier == "t0"`; violation raises `ToolRegistrationError`. Test.
- **AC-31.2.** `SELF_TOOL_REGISTRY: dict[str, SelfTool]` is module-global in `self_surface.py`. `register_self_tool(tool)` inserts; a second register of the same `name` raises. Test.
- **AC-31.3.** Every tool name in spec 28 AC-28.1 is present in the registry after module import. Test iterates the expected-name set and asserts each resolves to a `SelfTool`.
- **AC-31.4.** `tool.description` opens with a first-person clause matching regex `^I \w+`. Violation at registration raises `ToolRegistrationError`. Test with `"The self notices..."` negative case.

### Schema export

- **AC-31.5.** `SelfRuntime.tool_schemas()` returns a list of OpenAI function-call schema dicts shaped `{"type": "function", "function": {"name", "description", "parameters"}}`. Parameters follow JSON Schema draft-07. Test.
- **AC-31.6.** On first call, `tool_schemas()` also writes them to `research/project-turing/config/self_tools.json` (spec 28 AC-28.2) as a deterministic JSON dump. Repeat calls read the cached file if fresh. Test.

### Invocation

- **AC-31.7.** `SelfRuntime.invoke(tool_name, self_id, args)` dispatches to `handler(self_id=self_id, **args)`. Unknown name raises `UnknownSelfTool`. Test.
- **AC-31.8.** Invocation wraps the handler call in a single transaction on `SelfRepo.conn`. Any exception rolls back; a companion OBSERVATION "I attempted {tool}; the write failed: {err}" is written via `memory-mirroring` (spec 32). Test with a failing fake handler.
- **AC-31.9.** `invoke` enforces `trust_tier == "t0"` by checking the caller context; a caller stamped `t1` or lower raises `TrustTierViolation`. Test.

### `write_contributor` tool

- **AC-31.10.** `write_contributor(self_id, target_node_id, target_kind, source_id, source_kind, weight, rationale, *, origin=ContributorOrigin.SELF)` validates `origin != RETRIEVAL` (spec 25 AC-25.13); validates range and no-self-loop per the `ActivationContributor` ctor; inserts the row; invalidates the target's cache (spec 35); mirrors an OBSERVATION. Test.

### `record_personality_claim` tool

- **AC-31.11.** `record_personality_claim(self_id, facet_id, claim_text, evidence)` validates `facet_id in FACET_TO_TRAIT` (spec 23 AC-23.22); mints an OPINION memory with `content = f"I notice: {claim_text}"`, `intent_at_time = "narrative personality revision"`, `context = {facet_id, evidence}`; inserts a contributor from that memory to the facet with `weight = narrative_weight(evidence, claim_text)` (spec 23 §23.5), `origin = SELF`. Test.

### `retract_contributor_by_counter` tool

- **AC-31.12.** `retract_contributor_by_counter(self_id, target_node_id, source_id, weight, rationale)` writes a **new** contributor row with `weight = -weight` and `rationale` prepended by `"counter:"`. The original row is not mutated. Test: after retraction, `active_now` on the target returns the sum including both rows (which net to zero or opposite sign).
- **AC-31.13.** `retract_contributor_by_counter` with parameters that do not match any existing contributor raises `NoMatchingContributor`. Test.

### Edge cases

- **AC-31.14.** Importing `self_surface` twice does not duplicate registrations (module-level import is idempotent). Test.
- **AC-31.15.** A tool whose handler raises `SelfNotReady` does not leak a partial memory mirror. Test with a handler that raises after writing nothing.

## Implementation

```python
# self_surface.py additions

TOOL_DESCRIPTION_MAX: int = 400

@dataclass(frozen=True)
class SelfTool:
    name: str
    description: str
    schema: dict
    handler: Callable[..., object]
    trust_tier: str = "t0"

    def __post_init__(self) -> None:
        if len(self.description) > TOOL_DESCRIPTION_MAX:
            raise ToolRegistrationError(f"description too long: {self.name}")
        if not self.description.lstrip().startswith("I "):
            raise ToolRegistrationError(
                f"tool {self.name} description must start with 'I '"
            )
        if self.trust_tier != "t0":
            raise ToolRegistrationError(f"self-tools are t0; got {self.trust_tier}")


SELF_TOOL_REGISTRY: dict[str, SelfTool] = {}


def register_self_tool(tool: SelfTool) -> None:
    if tool.name in SELF_TOOL_REGISTRY:
        raise ToolRegistrationError(f"duplicate tool: {tool.name}")
    SELF_TOOL_REGISTRY[tool.name] = tool


# At module-import time, register every tool (recall_self, write_self_todo,
# note_passion, note_hobby, note_interest, note_preference, note_skill,
# revise_self_todo, complete_self_todo, archive_self_todo, practice_skill,
# downgrade_skill, rerank_passions, write_contributor,
# record_personality_claim, retract_contributor_by_counter, note_engagement,
# note_interest_trigger).
```

`write_contributor`, `record_personality_claim`, `retract_contributor_by_counter` live in `self_contributors.py` (new file) so their implementations don't bloat `self_surface.py`.

## Open questions

- **Q31.1.** `tool_schemas()` caches to a JSON file on disk. In-memory cache is cheaper; file cache matches spec 28 AC-28.2 wording. Keep the file write or drop to in-memory only?
- **Q31.2.** Trust-tier enforcement in `invoke` assumes a caller-context object; the spec 30 pipeline is expected to stamp it. If a test or script calls `invoke` directly, the default is `t0` — which bypasses the check. A stricter default (`t3`, overridable only by `SelfRuntime.__init__`) is more secure but adds friction.
