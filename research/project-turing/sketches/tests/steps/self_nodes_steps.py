"""Step definitions for self_nodes.feature (only additions not in common_steps.py)."""

# type: ignore[attr-defined]

from pytest_bdd import given, when, then
from turing.self_nodes import SkillKind


@given('a (?P<node_type>.+) named "(?P<name>.+)" already exists')
def node_already_exists(node_type, name):
    if node_type == "Hobby":
        from turing.self_nodes import note_hobby

        note_hobby(ctx.repo, ctx.self_id, name, "initial entry")
        ctx.node_exists = True


@when(
    'note_skill is called with name "(?P<name>.+)" and level "(?P<level>.+)" and kind "(?P<kind>.+)"'
)
def note_skill_with_kind_called(name, level, kind):
    from turing.self_nodes import note_skill, SkillKind

    ctx.kind = kind
    try:
        ctx.skill_id = note_skill(ctx.repo, ctx.self_id, name, level, SkillKind[kind])
    except Exception as e:
        ctx.error = e


@then('ValueError is raised with message "(?P<msg>.+)"')
def value_error_raised_with_msg(msg):
    assert isinstance(ctx.error, ValueError)
    assert msg in str(ctx.error)
