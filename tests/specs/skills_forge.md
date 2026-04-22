# Spec: `src/stronghold/skills/forge.py`

**Purpose:** LLM-driven skill creation and mutation — forges new SKILL.md files from natural-language requests (starting at trust tier T3) and mutates existing T2+ skills by baking learnings into their system prompts.

**Coverage:** 91% (85/93). Missing: 127-128, 133-134, 207, 220-225, 252.

## Test strategy

- Inject a fake `LLMClient` (protocol) whose `.complete(...)` is awaitable and returns `{"choices":[{"message":{"content":<str>}}]}` — or raises.
- Use `tmp_path` as `skills_dir`.
- Import `parse_skill_file` and `security_scan` from real module; tests feed them valid/invalid SKILL.md strings.

---

## `LLMSkillForge.forge(request) -> SkillDefinition`

**Contract:**
- LLM returns empty → `ValueError("LLM returned empty response for skill forge request")`.
- Strips leading/trailing markdown code fences `^```\w*\n` / `\n```$`.
- Runs `security_scan` on stripped content; unsafe → `ValueError("Forged skill rejected by security scan: ...")`.
- Parses via `parse_skill_file(content, source="forge")`; None → `ValueError("Forged skill content failed to parse")`.
- Path traversal guard: if `(skills_dir/<name>.md).resolve()` is not inside `skills_dir.resolve()`, raise `ValueError("Invalid skill name (path traversal detected): ...")`.
- Name collision: if file exists → `ValueError("Skill '<name>' already exists at ...")`.
- Forces trust_tier = `"t3"` on returned SkillDefinition, source=`"forge"`.
- Writes file to disk, creates parent dir, logs info.

**Invariants:**
- Returned `SkillDefinition.trust_tier == "t3"` regardless of what LLM emitted.
- File exists on disk after success; contents equal post-strip content.

**Uncovered branches:**
- **127-128** — `ValueError` raised when `parse_skill_file` returns None (content fails to parse).
- **133-134** — Path traversal detection raising `ValueError`.

**Test cases:**

1. `test_forge_empty_llm_response_raises`
   - Setup: fake LLM `.complete` returns `{"choices":[]}`.
   - Action: `await forge.forge("make a foo tool")`.
   - Expect: `pytest.raises(ValueError, match="empty response")`.

2. `test_forge_strips_markdown_fences`
   - Setup: LLM returns `` "```markdown\n---\nname: foo\n..." ``; valid skill inside.
   - Expect: file written without leading/trailing fences; assert first line of saved file == `"---"`.

3. `test_forge_rejects_unsafe_content`
   - Setup: LLM returns content containing `subprocess.Popen` or `exec(` (matches security_scan patterns).
   - Expect: `ValueError(match="rejected by security scan")`; no file written.

4. `test_forge_rejects_unparseable_content`
   - Setup: LLM returns raw markdown with no valid frontmatter.
   - Expect: `ValueError(match="failed to parse")`.

5. `test_forge_blocks_path_traversal_name`
   - Setup: LLM returns valid SKILL.md whose frontmatter has `name: "../evil"`.
   - Expect: `ValueError(match="path traversal detected")`; no file at `<skills_dir>/../evil.md`.

6. `test_forge_rejects_name_collision`
   - Setup: pre-create `<skills_dir>/existing.md`; LLM returns valid skill with `name: existing`.
   - Expect: `ValueError(match="already exists")`; file content unchanged.

7. `test_forge_happy_path_writes_file_at_tier_t3`
   - Setup: LLM returns valid SKILL.md for `name: greeter`.
   - Action: forge.
   - Expect: return value is SkillDefinition, `.trust_tier == "t3"`, `.source == "forge"`; file `<skills_dir>/greeter.md` exists with exact stripped content; info log `"Forged skill 'greeter' saved"`.

8. `test_forge_creates_skills_dir_if_missing`
   - Setup: `skills_dir=tmp_path/"nonexistent"`.
   - Action: forge with valid response.
   - Expect: directory created; file present.

---

## `LLMSkillForge.mutate(skill_name, learning, *, skill_tier="")`

**Contract (returns dict, never raises):**
- `skill_tier ∈ {"t0","t1"}` → `{"status":"blocked", "reason": "Cannot auto-mutate ..."}`.
- Skill file missing at `<skills_dir>/<name>.md` AND `<skills_dir>/community/<name>.md` → `{"status":"skipped", "reason":"No SKILL.md for '<name>'"}`.
- Empty `learning.learning` (or `str(learning)==""`) → `{"status":"skipped", "reason":"Empty learning text"}`.
- Security scan on wrapped learning text rejects → `{"status":"error", "error":"Learning text rejected by security scan: ..."}`.
- Instruction density > 0.08 → `{"status":"error", "error":"... suspicious instruction density ..."}`; warning log.
- LLM empty response → `{"status":"error", "error":"LLM returned empty response"}`.
- Mutated content security-scan fails → `{"status":"error", "error":"Mutation rejected: ..."}`.
- Mutated content parse fails → `{"status":"error", "error":"Mutated content failed to parse"}`.
- Mutated `new_skill.name != skill_name` → `{"status":"error", "error":"Mutation changed name: <new>"}`.
- Otherwise writes new content; returns `{"status":"mutated", "skill_name", "old_hash", "new_hash"}` where hashes are `sha256(...)[:16]`.

**Uncovered branches:**
- **207** — the `{"status":"skipped", "reason":"Empty learning text"}` return.
- **220-225** — the instruction-density block branch.
- **252** — likely the "Mutation changed name" error branch.

**Test cases:**

1. `test_mutate_blocked_for_t0_t1`
   - Parametric over `skill_tier ∈ {"t0","t1"}`.
   - Expect: `{"status":"blocked"}`; no LLM call; no file change.

2. `test_mutate_skipped_when_file_missing_in_both_dirs`
   - Action: mutate for name not on disk.
   - Expect: `{"status":"skipped", "reason": starts_with("No SKILL.md")}`.

3. `test_mutate_finds_community_subdir`
   - Setup: seed `<skills_dir>/community/foo.md` only; stub LLM to return a minimally-valid mutated SKILL.md with `name: foo`.
   - Expect: `{"status":"mutated"}`; community file updated.

4. `test_mutate_empty_learning_text_skipped`
   - Setup: existing skill file; `learning` object where `.learning == ""`.
   - Expect: `{"status":"skipped", "reason":"Empty learning text"}`; LLM not called.

5. `test_mutate_rejects_unsafe_learning`
   - Setup: learning text contains `exec(` or other security_scan trigger.
   - Expect: `{"status":"error", "error": contains("rejected by security scan")}`.

6. `test_mutate_rejects_high_instruction_density`
   - Setup: learning text with many imperatives/URLs — `score_instruction_density` > 0.08.
   - Expect: `{"status":"error", "error": contains("suspicious instruction density")}`; warning log.

7. `test_mutate_handles_empty_llm_response`
   - Setup: fake LLM returns `{"choices":[]}`.
   - Expect: `{"status":"error", "error":"LLM returned empty response"}`.

8. `test_mutate_rejects_unsafe_llm_output`
   - Setup: LLM returns content with `subprocess.run(`.
   - Expect: `{"status":"error", "error": starts_with("Mutation rejected")}`.

9. `test_mutate_rejects_unparseable_output`
   - Setup: LLM returns non-frontmatter content.
   - Expect: `{"status":"error", "error":"Mutated content failed to parse"}`.

10. `test_mutate_rejects_name_change`
    - Setup: seed skill `foo.md`; LLM returns valid SKILL.md whose frontmatter has `name: bar`.
    - Expect: `{"status":"error", "error": starts_with("Mutation changed name")}`; file still the original.

11. `test_mutate_happy_path_writes_and_returns_hashes`
    - Setup: seed `foo.md` with known content; LLM returns new valid SKILL.md with `name: foo`.
    - Action: mutate.
    - Expect: return dict `{"status":"mutated","skill_name":"foo","old_hash":<16hex>,"new_hash":<16hex>}`; `old_hash != new_hash`; file contents now equal stripped new content; info log `"Mutated skill 'foo' (<old> → <new>)"`.

12. `test_mutate_strips_fences_on_output` — LLM wraps response in ``` fences → saved file has no fences.

---

## `_call_llm(prompt)` — private helper

**Contract:** Calls `self._llm.complete(messages=[...], model=self._forge_model, max_tokens=2000, temperature=0.3)`; extracts `choices[0].message.content`; returns str or None on any exception; warning log on exception.

**Test cases:**

1. `test_call_llm_returns_content_string` — fake returns standard shape → returns string.
2. `test_call_llm_returns_none_on_exception` — fake raises → returns None; warning log `"Forge LLM call failed"`.
3. `test_call_llm_returns_none_when_no_choices` — fake returns `{"choices":[]}` → returns None.
4. `test_call_llm_passes_forge_model` — inspect mock.call_args → `model == forge.forge_model`.

---

## Intentionally uncovered

None. Line 252 is the "Mutation changed name" branch — live code, tested above.

## Contract gaps

- `_call_llm` returns `None` when `choices` list is empty but always returns `str(...)` result of a dict-get otherwise — could be empty string, which the caller treats identically to None via `if not content:`. Tests cover the empty-string path by asserting `_call_llm` returns `""` when content is `""` (technically a truthy string inequality — verified via `bool("") == False`).
- The mutate flow parses with `parse_skill_file(new_content)` (no `source=` arg) — different from forge which passes `source="forge"`. Not a bug, but an inconsistency.

## Estimated tests: **~22 tests** across forge (8), mutate (12), _call_llm (4) — minus shared setup ≈ 22.
