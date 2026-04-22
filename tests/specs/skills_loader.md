# Spec: `src/stronghold/skills/loader.py`

**Purpose:** Loads SKILL.md files from a directory (plus `community/` subdir) into SkillDefinition objects, and merges skills into an existing tool list — skipping any name that already exists.

**Coverage:** 91% (48/53). Missing: 43-45, 61-62.

## Test strategy

- Create temp dir with seeded `*.md` files (valid and invalid).
- Use real `parse_skill_file` from `stronghold.skills.parser`.
- Inject known-bad OSError by creating a file with no read permission, or monkeypatch `Path.read_text` to raise.

---

## `FilesystemSkillLoader.load_all() -> list[SkillDefinition]`

**Contract:**
- Nonexistent dir → returns `[]`; debug log.
- Iterates `*.md` in **sorted** order at top level.
- Skips symlinks with warning log "Skipping symlink in skills dir".
- OSError on read → warning log "Cannot read skill file"; skipped.
- Parse failure (None) → warning log "Invalid skill file (parse failed)"; skipped.
- After top level, iterates `community/*.md` with same read behavior — parse failures silently skipped (no log).
- Logs `"Loaded N skills from <dir>"` at INFO.

**Invariants:**
- Order: top-level skills sorted alphabetically, then community skills sorted alphabetically.
- Symlinks ALWAYS skipped (security invariant — prevents path traversal).

**Uncovered branches:**
- **43-45** — OSError on read for top-level skill file; warning emitted.
- **61-62** — OSError on read for a community skill file; silently skipped (no warning log — this is the diff vs top level).

**Test cases:**

1. `test_load_all_returns_empty_when_dir_missing`
   - Setup: `loader = FilesystemSkillLoader(tmp_path/"nope")`.
   - Action: `loader.load_all()`.
   - Expect: `== []`; debug log contains "does not exist".

2. `test_load_all_loads_two_valid_skills_sorted`
   - Setup: write `zeta.md` and `alpha.md` both valid.
   - Action: load.
   - Expect: list length 2; `skills[0].name == "alpha"` and `skills[1].name == "zeta"` (alphabetical).

3. `test_load_all_skips_symlinks_with_warning`
   - Setup: write `real.md`, then `os.symlink(real, tmp_path/"link.md")`.
   - Action: load.
   - Expect: exactly 1 skill returned (the real one, counted once since symlink is skipped); warning log `"Skipping symlink in skills dir"`.

4. `test_load_all_logs_and_skips_unreadable_file`
   - Setup: write `bad.md`; `os.chmod(bad, 0o000)` (or monkeypatch `Path.read_text` to raise OSError for bad.md only).
   - Action: load.
   - Expect: skill list doesn't include `bad`; caplog WARNING contains `"Cannot read skill file"`.

5. `test_load_all_skips_invalid_skill_with_warning`
   - Setup: write `broken.md` containing raw text (no frontmatter).
   - Action: load.
   - Expect: not in result; caplog WARNING contains `"Invalid skill file (parse failed)"`.

6. `test_load_all_includes_community_skills`
   - Setup: `alpha.md` at top level; `community/beta.md`.
   - Action: load.
   - Expect: list contains both; top-level first, then community — order `[alpha, beta]`.

7. `test_load_all_community_unreadable_silently_skipped`
   - Setup: `community/bad.md` with read error (monkeypatch `Path.read_text` to raise OSError only for this file).
   - Action: load.
   - Expect: skill not in result; NO warning log about the community file (differs from top-level behavior).

8. `test_load_all_community_parse_failure_silently_skipped`
   - Setup: `community/bad.md` with invalid content.
   - Expect: skipped, no log.

9. `test_load_all_info_log_has_correct_count`
   - Setup: 3 valid skills total (2 top + 1 community).
   - Expect: caplog INFO message `"Loaded 3 skills from <dir>"`.

---

## `FilesystemSkillLoader.merge_into_tools(skills, existing_tools) -> list[ToolDefinition]`

**Contract:**
- Returns list. Never mutates inputs.
- If a skill name is in `existing_tools` → skill is skipped; debug log.
- Else, skill becomes a new `ToolDefinition` preserving `name, description, parameters, groups, endpoint, auth_key_env`.
- Later skills with names already merged are also skipped (cascading dedup).

**Invariants:**
- Resulting list length == len(existing_tools) + (number of skills with unique names).
- Original `existing_tools` list identity not reused (returns a copy).

**Test cases:**

1. `test_merge_adds_new_skill_as_tool`
   - Action: merge 1 skill `foo` into empty existing list.
   - Expect: returned list has 1 ToolDefinition with `.name == "foo"`; original skills/existing lists unchanged.

2. `test_merge_skips_skill_when_tool_exists`
   - Setup: existing has `ToolDefinition(name="foo", ...)`; skills = `[SkillDef(name="foo", ...)]`.
   - Action: merge.
   - Expect: returned list length 1 (unchanged); debug log `"Skill 'foo' skipped (tool already exists)"`.

3. `test_merge_dedupes_within_skills_list`
   - Setup: skills = `[SkillDef(name="foo"), SkillDef(name="foo")]`.
   - Action: merge into empty existing.
   - Expect: returned list has 1 ToolDefinition named `foo`; debug log on second one.

4. `test_merge_preserves_skill_fields`
   - Setup: skill with `description="d", groups=("general",), parameters={"type":"object"}, endpoint="", auth_key_env="FOO_TOKEN"`.
   - Action: merge.
   - Expect: produced ToolDefinition has matching fields (exact equality).

5. `test_merge_does_not_mutate_inputs`
   - Action: merge.
   - Expect: `len(existing_tools)` unchanged after call; `skills` list unchanged.

---

## Intentionally uncovered

None — both OSError branches (top and community) are tested.

## Contract gaps

- The top-level loop logs `warning` on unreadable/invalid skill files, but the community loop silently swallows identical errors. This asymmetry is now codified in the spec; consider homogenizing.
- `parse_skill_file(content, source=str(path))` — `source` is path, but for community the same is passed. No observable difference for callers.

## Estimated tests: **~14 tests** across load_all (9), merge_into_tools (5).
