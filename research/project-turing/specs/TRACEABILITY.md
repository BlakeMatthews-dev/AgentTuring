# Project Turing — Spec / AC / Test Traceability Matrix

Every row binds three things: the spec, the acceptance criterion, and the test function. The triangle must close: spec ↔ AC ↔ test. If any leg is missing, it's a gap.

**Contract rule:** No spec is "done" until:
1. Every AC has a passing test (this matrix shows no PENDING rows for that spec)
2. Mutmut kill rate meets the gate for that tranche
3. Any surviving mutants are documented in `MUTMUT_EXCEPTIONS.md`

---

## Tranche 1: Memory Layer

### Spec 1: schema.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-1.1 | EpisodicMemory auto-generates UUID memory_id | test_ac_1_1_memory_id_auto_generated | DONE |
| AC-1.2 | SourceKind contains exactly I_DID, I_WAS_TOLD, I_IMAGINED | test_ac_1_2_source_kind_enum | DONE |
| AC-1.3 | Durable tier with I_IMAGINED source raises ProvenanceViolation | test_ac_1_3_durable_requires_i_did | DONE |
| AC-1.4 | Self-superseding memory raises ProvenanceViolation | test_ac_1_4_no_self_supersede | DONE |
| AC-1.5 | Frozen-after-construction: setting content raises ImmutableViolation | test_ac_1_5_frozen_fields | DONE |
| AC-1.6 | affect out of [-1,1] raises ValueError | test_ac_1_6_affect_range | DONE |
| AC-1.7 | ACCOMPLISHMENT requires non-empty intent_at_time | test_ac_1_7_accomplishment_intent | DONE |

### Spec 2: tiers.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-2.1 | MemoryTier has exactly 8 members | test_ac_2_1_eight_tiers | DONE |
| AC-2.2 | ACCOMPLISHMENT weight bounds are [0.6, 1.0] | test_ac_2_2_accomplishment_bounds | DONE |
| AC-2.3 | clamp_weight clips above max | test_ac_2_3_clamp_above | DONE |
| AC-2.4 | clamp_weight clips below min | test_ac_2_4_clamp_below | DONE |
| AC-2.5 | WISDOM has highest inheritance priority | test_ac_2_5_wisdom_priority | DONE |
| AC-2.6 | INHERITANCE_PRIORITY is monotonically non-decreasing for durable tiers | test_ac_2_6_priority_ordering | DONE |

### Spec 3: durability-invariants.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-3.1 | Durable memory cannot be soft-deleted | test_ac_3_1_no_soft_delete_durable | DONE |
| AC-3.2 | Durable memory requires I_DID source | test_ac_3_2_durable_i_did_source | DONE |
| AC-3.3 | WISDOM without origin_episode_id raises WisdomInvariantViolation | test_ac_3_3_wisdom_needs_origin | DONE |
| AC-3.4 | Existing WISDOM cannot be superseded by new WISDOM | test_ac_3_4_no_supersede_wisdom | DONE |
| AC-3.5 | Weight insert below tier floor raises | test_ac_3_5_weight_floor | DONE |
| AC-3.6 | Weight insert above tier ceiling raises | test_ac_3_6_weight_ceiling | DONE |
| AC-3.7 | superseded_by can only be set once | test_ac_3_7_superseded_by_once | DONE |
| AC-3.8 | Durable tier rows go to durable_memory table | test_ac_3_8_dual_table_routing | DONE |

### Spec 4: write-paths.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-4.1 | High-surprise contradiction mints REGRET | test_ac_4_1_regret_minted | DONE |
| AC-4.2 | Low-surprise outcome mints no REGRET | test_ac_4_2_no_regret_low_surprise | DONE |
| AC-4.3 | REGRET supersedes predecessor; predecessor.superseded_by set | test_ac_4_3_supersede_chain | DONE |
| AC-4.4 | Predecessor contradiction_count incremented | test_ac_4_4_contradiction_count | DONE |
| AC-4.5 | Non-stance predecessor rejected | test_ac_4_5_non_stance_rejected | DONE |
| AC-4.6 | ACCOMPLISHMENT with high surprise and affect mints | test_ac_4_6_accomplishment_minted | DONE |
| AC-4.7 | ACCOMPLISHMENT with empty intent mints nothing | test_ac_4_7_accomplishment_no_intent | DONE |
| AC-4.8 | AFFIRMATION is revocable (immutable=False) | test_ac_4_8_affirmation_revocable | DONE |

### Spec 5: wisdom-write-path.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-5.1 | Dream session with 3+ patterns produces WISDOM candidate | test_ac_5_1_dream_produces_wisdom | DONE |
| AC-5.2 | WISDOM without dream session origin raises | test_ac_5_2_wisdom_needs_dream | DONE |
| AC-5.3 | Lineage memory_ids validated on WISDOM insert | test_ac_5_3_lineage_validated | DONE |
| AC-5.4 | Phase 4 LESSON consolidation extracts REGRET→success patterns | test_ac_5_4_lesson_consolidation | DONE |
| AC-5.5 | Non-durable pruning soft-deletes low-weight old memories | test_ac_5_5_prune_non_durable | DONE |
| AC-5.6 | Dream skips if < min_new_durable since last session | test_ac_5_6_skip_few_durable | DONE |
| AC-5.7 | Session markers written at start and end | test_ac_5_7_session_markers | DONE |

### Spec 6: retrieval.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-6.1 | Durable memories fill first in token budget | test_ac_6_1_durable_first | DONE |
| AC-6.2 | Unused durable quota cascades to non-durable | test_ac_6_2_cascade | DONE |
| AC-6.3 | Total returned content does not exceed budget | test_ac_6_3_budget_respected | DONE |
| AC-6.4 | Default source filter is I_DID only | test_ac_6_4_default_i_did | DONE |
| AC-6.5 | retrieve_history walks supersede chain chronologically | test_ac_6_5_lineage_walk | DONE |
| AC-6.6 | retrieve_head walks forward to current | test_ac_6_6_head_walk | DONE |
| AC-6.7 | semantic_retrieve scores by similarity × weight | test_ac_6_7_semantic_scoring | DONE |
| AC-6.8 | top-K limits semantic_retrieve results | test_ac_6_8_top_k_limit | DONE |

### Spec 7: persistence.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-7.1 | Durable-tier insert goes to durable_memory table | test_ac_7_1_durable_table | DONE |
| AC-7.2 | Non-durable insert goes to episodic_memory table | test_ac_7_2_episodic_table | DONE |
| AC-7.3 | DELETE on durable_memory blocked by trigger | test_ac_7_3_delete_blocked | DONE |
| AC-7.4 | get() retrieves from correct table | test_ac_7_4_get_cross_table | DONE |
| AC-7.5 | find() queries across both tables | test_ac_7_5_find_cross_table | DONE |
| AC-7.6 | decay_weight clamps to tier floor | test_ac_7_6_decay_clamp | DONE |
| AC-7.7 | self_id minted if none exists | test_ac_7_7_self_id_mint | DONE |
| AC-7.8 | archive_and_mint_new creates new active self_id | test_ac_7_8_archive_mint | DONE |
| AC-7.9 | FK enforcement on self_id | test_ac_7_9_fk_enforcement | DONE |
| AC-7.10 | Schema version migration applies upgrades | test_ac_7_10_schema_migration | PENDING |

---

## Tranche 2: Motivation and Dispatch

### Spec 8: motivation.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-8.1 | P0 item dispatches before P20 item | test_ac_8_1_priority_order | DONE |
| AC-8.2 | Pressure escalates effective priority | test_ac_8_2_pressure_escalation | DONE |
| AC-8.3 | Concurrent dispatch limit enforced | test_ac_8_3_concurrent_limit | DONE |
| AC-8.4 | BacklogItem carries cost_estimate_tokens | test_ac_8_4_cost_estimate | DONE |
| AC-8.5 | score() returns base + max(pressure × fit) | test_ac_8_5_score_formula | DONE |
| AC-8.6 | insert() returns item_id | test_ac_8_6_insert_returns_id | DONE |
| AC-8.7 | evict() removes from backlog | test_ac_8_7_evict | DONE |
| AC-8.8 | on_tick runs action sweep every cadence ticks | test_ac_8_8_action_sweep | DONE |
| AC-8.9 | top_x selects top-N by score | test_ac_8_9_top_x | DONE |
| AC-8.10 | DispatchObservation recorded on dispatch | test_ac_8_10_dispatch_observation | DONE |
| AC-8.11 | Quiet zone suppresses dispatch | test_ac_8_11_quiet_zone | DONE |
| AC-8.12 | priority_base interpolation between anchors | test_ac_8_12_priority_interpolation | DONE |
| AC-8.13 | register_dispatch binds handler by kind | test_ac_8_13_register_dispatch | DONE |
| AC-8.14 | set_pressure clamps to PRESSURE_MAX | test_ac_8_14_pressure_clamp | DONE |
| AC-8.15 | Empty fit returns zero score | test_ac_8_15_empty_fit | DONE |
| AC-8.16 | Dropped items (readiness=False) skip dispatch | test_ac_8_16_readiness_gate | DONE |
| AC-8.17 | In-flight count tracked | test_ac_8_17_inflight | DONE |

### Spec 9: scheduler.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-9.1 | Item not dispatched before delivery_time | test_ac_9_1_hold_until_delivery | DONE |
| AC-9.2 | Early-executable window fires callback | test_ac_9_2_early_executable | DONE |
| AC-9.3 | Output buffered until delivery_time | test_ac_9_3_buffer_output | DONE |
| AC-9.4 | Quiet zones extend 5× around dream time | test_ac_9_4_quiet_zones | DONE |
| AC-9.5 | schedule() adds to pending | test_ac_9_5_schedule_adds | DONE |
| AC-9.6 | register_callback binds named handler | test_ac_9_6_register_callback | DONE |
| AC-9.7 | produce_output test hook stashes result | test_ac_9_7_produce_output | DONE |
| AC-9.8 | on_tick promotes ready items to motivation | test_ac_9_8_tick_promotes | DONE |

### Spec 10: daydreaming.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-10.1 | DaydreamWriter only writes I_IMAGINED source | test_ac_10_1_imagined_only | DONE |
| AC-10.2 | DaydreamWriter cannot reach durable tiers | test_ac_10_2_no_durable | DONE |
| AC-10.3 | Seed selection prefers unresolved REGRETs | test_ac_10_3_seed_prefers_regret | DONE |
| AC-10.4 | Daydream priority never below P20 | test_ac_10_4_floor_p20 | DONE |
| AC-10.5 | DaydreamProducer submits candidate on tick | test_ac_10_5_producer_tick | DONE |
| AC-10.6 | Zero pressure evicts candidate | test_ac_10_6_zero_pressure_evict | DONE |
| AC-10.7 | write_hypothesis produces HYPOTHESIS tier | test_ac_10_7_write_hypothesis | DONE |
| AC-10.8 | write_observation produces OBSERVATION tier | test_ac_10_8_write_observation | DONE |
| AC-10.9 | Session markers written per pass | test_ac_10_9_session_marker | DONE |
| AC-10.10 | DAYDREAM_TOKENS_PER_PASS limits retrieval | test_ac_10_10_token_limit | DONE |
| AC-10.11 | ACCOMPLISHMENT_BIAS counter-weights seeds | test_ac_10_11_accomplishment_bias | DONE |
| AC-10.12 | Quiet zone blocks readiness | test_ac_10_12_quiet_blocks | DONE |
| AC-10.13 | default_imagine returns one hypothesis variant | test_ac_10_13_default_imagine | DONE |

### Spec 11: tuning.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-11.1 | CoefficientTable.seed() returns defaults | test_ac_11_1_seed_defaults | DONE |
| AC-11.2 | CoefficientTable.from_repo() applies non-superseded AFFIRMATIONs | test_ac_11_2_from_repo | DONE |
| AC-11.3 | parse_coefficient_commitment round-trips | test_ac_11_3_parse_roundtrip | DONE |
| AC-11.4 | apply_update replaces single field | test_ac_11_4_apply_update | DONE |
| AC-11.5 | validate_table rejects out-of-range | test_ac_11_5_validate_range | DONE |
| AC-11.6 | CoefficientUpdate.to_content serializes | test_ac_11_6_to_content | DONE |
| AC-11.7 | Tuner submits tuning_candidate on cadence | test_ac_11_7_tuner_cadence | DONE |
| AC-11.8 | Pool utilization >80% proposes pressure adjustment | test_ac_11_8_pool_utilization | DONE |
| AC-11.9 | Daydream fire rate >50% raises fire_floor | test_ac_11_9_fire_rate_high | DONE |
| AC-11.10 | Daydream fire rate <1% lowers fire_floor | test_ac_11_10_fire_rate_low | DONE |
| AC-11.11 | Prior lookup prevents duplicate proposals | test_ac_11_11_no_duplicate | DONE |
| AC-11.12 | Invalid coefficient name in parse raises | test_ac_11_12_invalid_name | DONE |
| AC-11.13 | Unknown field in apply_update raises | test_ac_11_13_unknown_field | DONE |
| AC-11.14 | DOCUMENTED_RANGES covers all 18 coefficients | test_ac_11_14_ranges_complete | DONE |
| AC-11.15 | from_repo with no AFFIRMATIONs returns seed | test_ac_11_15_no_affirmations | DONE |

---

## Tranche 3: Detectors

### D: detectors/README.md (Detector protocol)

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-D.1 | Detector.observe(event) returns list[BacklogItem] | test_ac_d_1_observe | DONE |
| AC-D.2 | Detector has name and kind properties | test_ac_d_2_properties | DONE |

### D.1: detectors/contradiction.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-D.1.1 | Contradictory durable memories produce backlog candidate | test_ac_d1_1_contradiction_candidate | DONE |
| AC-D.1.2 | Candidate includes both memory IDs | test_ac_d1_2_memory_ids | DONE |
| AC-D.1.3 | Same-tier memories not flagged | test_ac_d1_3_same_tier_skip | DONE |

---

## Tranche 4: Dreaming

### Spec 12: dreaming.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-12.1 | Dream session runs all 7 phases | test_ac_12_1_seven_phases | DONE |
| AC-12.2 | Pattern extraction groups by intent | test_ac_12_2_pattern_grouping | DONE |
| AC-12.3 | WISDOM candidacy capped at max_candidates | test_ac_12_3_max_candidates | DONE |
| AC-12.4 | AFFIRMATION proposals for accomplishment polarity | test_ac_12_4_affirmation_proposal | DONE |
| AC-12.5 | Review gate rejects contradicting WISDOM | test_ac_12_5_review_reject | DONE |
| AC-12.6 | Review gate commits valid WISDOM with lineage | test_ac_12_6_review_commit | DONE |
| AC-12.7 | Session fires once daily when schedule time crosses | test_ac_12_7_daily_schedule | DONE |
| AC-12.8 | DreamSessionReport has correct field counts | test_ac_12_8_report_fields | DONE |
| AC-12.9 | Non-durable pruning respects weight and age thresholds | test_ac_12_9_prune_thresholds | DONE |

---

## Tranche 5: Runtime + Integration

### Spec 13: journal.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-13.1 | narrative.md written with identity and date | test_ac_13_1_narrative_written | DONE |
| AC-13.2 | identity.md rewritten on WISDOM change | test_ac_13_2_identity_rewrite | DONE |
| AC-13.3 | Yesterday rollup summarizes previous day | test_ac_13_3_yesterday_rollup | PENDING |
| AC-13.4 | Weekly rollup summarizes last 7 days | test_ac_13_4_weekly_rollup | PENDING |
| AC-13.5 | Monthly rollup summarizes last 30 days | test_ac_13_5_monthly_rollup | PENDING |
| AC-13.6 | Recent-history rollup summarizes last N sessions | test_ac_13_6_recent_history | PENDING |

### Spec 14: working-memory.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-14.1 | add() inserts entry to working_memory | test_ac_14_1_add_entry | DONE |
| AC-14.2 | remove() deletes entry | test_ac_14_2_remove_entry | DONE |
| AC-14.3 | Entries sorted by priority | test_ac_14_3_priority_order | DONE |
| AC-14.4 | Eviction at capacity bound | test_ac_14_4_eviction | DONE |
| AC-14.5 | render() produces text block | test_ac_14_5_render | DONE |
| AC-14.6 | Capacity bounds enforced | test_ac_14_6_capacity | DONE |
| AC-14.7 | WM maintenance loop dispatches P13 | test_ac_14_7_maintenance_p13 | DONE |
| AC-14.8 | LLM-driven JSON add/remove parsed | test_ac_14_8_llm_json | DONE |
| AC-14.9 | Invalid JSON from LLM skipped | test_ac_14_9_invalid_json | DONE |
| AC-14.10 | Operator base prompt loaded | test_ac_14_10_base_prompt | PENDING |
| AC-14.11 | Prompt composition in chat | test_ac_14_11_prompt_composition | PENDING |
| AC-14.12 | inspect CLI working-memory subcommand | test_ac_14_12_inspect_cli | PENDING |
| AC-14.13 | Cross-self_id isolation | test_ac_14_13_self_id_isolation | PENDING |
| AC-14.14 | Concurrent add/remove safe | test_ac_14_14_concurrent_safe | DONE |

### Spec 15: rss-thinking.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-15.1 | RSS 2.0 feed parsed correctly | test_ac_15_1_rss_parse | DONE |
| AC-15.2 | Atom feed parsed correctly | test_ac_15_2_atom_parse | DONE |
| AC-15.3 | Dedup skips seen items | test_ac_15_3_dedup | DONE |
| AC-15.4 | Polling on schedule | test_ac_15_4_polling | DONE |
| AC-15.5 | 4-level progressive thinking pipeline | test_ac_15_5_progressive_thinking | PENDING |
| AC-15.6 | OBSERVATION always written | test_ac_15_6_observation_always | PENDING |
| AC-15.7 | WM entry on notable item | test_ac_15_7_wm_on_notable | PENDING |
| AC-15.8 | OPINION on interesting item | test_ac_15_8_opinion_interesting | PENDING |
| AC-15.9 | AFFIRMATION on commit | test_ac_15_9_affirmation_commit | PENDING |
| AC-15.10 | RSSFetcher drops items into backlog at P7 | test_ac_15_10_fetcher_p7 | DONE |

### Spec 16: semantic-retrieval.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-16.1 | EmbeddingIndex add/remove/search | test_ac_16_1_index_ops | DONE |
| AC-16.2 | cosine × weight scoring | test_ac_16_2_scoring | DONE |
| AC-16.3 | Source/tier filtering post-search | test_ac_16_3_filtering | DONE |
| AC-16.4 | Top-K limits results | test_ac_16_4_top_k | DONE |
| AC-16.5 | Superseded memories excluded | test_ac_16_5_no_superseded | DONE |
| AC-16.6 | IndexingRepo mirrors I_DID inserts | test_ac_16_6_indexing_repo | DONE |
| AC-16.7 | Rebuild from repo | test_ac_16_7_rebuild | DONE |
| AC-16.8 | Thread-safe index operations | test_ac_16_8_thread_safe | DONE |
| AC-16.9 | Min similarity threshold | test_ac_16_9_min_similarity | DONE |
| AC-16.10 | Empty query returns empty | test_ac_16_10_empty_query | DONE |

### Spec 17: chat-surface.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-17.1 | POST /v1/chat/completions returns OpenAI shape | test_ac_17_1_chat_shape | DONE |
| AC-17.2 | GET /v1/models lists models | test_ac_17_2_models_list | DONE |
| AC-17.3 | Streaming for plain replies | test_ac_17_3_streaming | PENDING |
| AC-17.4 | Non-streaming when tools fire | test_ac_17_4_non_streaming_tools | PENDING |
| AC-17.5 | GET /thoughts returns recent | test_ac_17_5_thoughts | DONE |
| AC-17.6 | GET /identity returns self info | test_ac_17_6_identity | DONE |
| AC-17.7 | GET / returns HTML UI | test_ac_17_7_html_ui | DONE |
| AC-17.8 | Per-user session tagging via header | test_ac_17_8_session_tag | PENDING |
| AC-17.9 | POST /chat dispatches to motivation | test_ac_17_9_chat_dispatch | DONE |
| AC-17.10 | Error response has OpenAI error shape | test_ac_17_10_error_shape | DONE |
| AC-17.11 | Prompt composition with base+WM+WISDOM | test_ac_17_11_prompt_composition | PENDING |
| AC-17.12 | Tool schemas included in context | test_ac_17_12_tool_schemas | PENDING |
| AC-17.13 | Token budget for prompt assembly | test_ac_17_13_token_budget | PENDING |
| AC-17.14 | Tool use from chat fires handler | test_ac_17_14_tool_use | PENDING |
| AC-17.15 | Tool result fed back to LLM | test_ac_17_15_tool_feedback | PENDING |
| AC-17.16 | Multi-turn tool loop | test_ac_17_16_multi_turn | PENDING |

### Spec 18: tool-layer.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-18.1 | Tool Protocol has name, mode, invoke | test_ac_18_1_tool_protocol | DONE |
| AC-18.2 | ToolRegistry register/get/names | test_ac_18_2_registry_ops | DONE |
| AC-18.3 | ToolNotPermitted on unregistered tool | test_ac_18_3_not_permitted | DONE |
| AC-18.4 | RSSReader is READ mode | test_ac_18_4_rss_mode | DONE |
| AC-18.5 | ObsidianWriter is WRITE mode | test_ac_18_5_obsidian_mode | DONE |
| AC-18.6 | ToolMode enum completeness | test_ac_18_6_mode_enum | DONE |
| AC-18.7 | schema() returns JSON Schema dict | test_ac_18_7_schema | PENDING |
| AC-18.8 | Failure produces OPINION | test_ac_18_8_failure_opinion | PENDING |
| AC-18.9 | Scaffold tools registered | test_ac_18_9_scaffold_tools | PENDING |

### Spec 19: litellm-provider.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-19.1 | complete() returns text | test_ac_19_1_complete | DONE |
| AC-19.2 | embed() returns vector | test_ac_19_2_embed | DONE |
| AC-19.3 | 429 backoff with cap at 60s | test_ac_19_3_429_backoff | DONE |
| AC-19.4 | 5xx retry | test_ac_19_4_5xx_retry | DONE |
| AC-19.5 | Per-provider independence | test_ac_19_5_provider_independence | DONE |
| AC-19.6 | quota_window() returns usage | test_ac_19_6_quota_window | DONE |
| AC-19.7 | Token accounting accurate | test_ac_19_7_token_accounting | DONE |
| AC-19.8 | close() releases connections | test_ac_19_8_close | DONE |

### Spec 20: runtime-reactor.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-20.1 | RealReactor tick loop runs handlers | test_ac_20_1_tick_loop | DONE |
| AC-20.2 | ThreadPoolExecutor spawn | test_ac_20_2_thread_spawn | DONE |
| AC-20.3 | Drift tracking via circular buffer | test_ac_20_3_drift_tracking | DONE |
| AC-20.4 | ReactorStatus reports state | test_ac_20_4_status | DONE |
| AC-20.5 | run_forever/stop lifecycle | test_ac_20_5_lifecycle | DONE |
| AC-20.6 | Handler exception isolation | test_ac_20_6_exception_isolation | DONE |
| AC-20.7 | FakeReactor synchronous spawn | test_ac_20_7_fake_reactor | DONE |

### Spec 21: observability.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-21.1 | MetricsCollector update/set/inc | test_ac_21_1_metrics_ops | DONE |
| AC-21.2 | render() produces Prometheus text | test_ac_21_2_prometheus_render | DONE |
| AC-21.3 | HTTP /metrics endpoint | test_ac_21_3_http_metrics | DONE |
| AC-21.4 | Inspect CLI summarize subcommand | test_ac_21_4_summarize | DONE |
| AC-21.5 | Inspect CLI dispatch-log | test_ac_21_5_dispatch_log | DONE |
| AC-21.6 | Inspect CLI lineage | test_ac_21_6_lineage | DONE |
| AC-21.7 | Smoke mode checklist | test_ac_21_7_smoke | DONE |

---

## Tranche 6: Self-model

### Spec 22: self-schema.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-22.1 | All enums defined (Trait, NodeKind, etc.) | test_ac_22_1_enums | DONE |
| AC-22.2 | CANONICAL_FACETS has 24 entries | test_ac_22_2_24_facets | DONE |
| AC-22.3 | PersonalityFacet validation | test_ac_22_3_facet_validation | DONE |
| AC-22.4 | Skill with decay rate | test_ac_22_4_skill_decay | DONE |
| AC-22.5 | SelfTodo status enum | test_ac_22_5_todo_status | DONE |
| AC-22.6 | Mood range validation | test_ac_22_6_mood_range | DONE |
| AC-22.7 | ActivationContributor no self-loop | test_ac_22_7_no_self_loop | DONE |
| AC-22.8 | All dataclasses frozen where specified | test_ac_22_8_frozen | DONE |

### Spec 23: personality.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-23.1 | draw_bootstrap_profile produces 24 facets | test_ac_23_1_bootstrap_24 | DONE |
| AC-23.2 | Truncated normal distribution within bounds | test_ac_23_2_truncated_normal | DONE |
| AC-23.3 | sample_retest_items weighted + facet-diversity | test_ac_23_3_sample_retest | DONE |
| AC-23.4 | compute_facet_deltas reverse scoring | test_ac_23_4_reverse_scoring | DONE |
| AC-23.5 | apply_retest end-to-end | test_ac_23_5_apply_retest | DONE |
| AC-23.6 | narrative_weight evidence-length heuristic | test_ac_23_6_narrative_weight | DONE |

### Spec 24: self-nodes.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-24.1 | current_level with exponential decay | test_ac_24_1_decay | DONE |
| AC-24.2 | Default decay rates correct | test_ac_24_2_default_rates | DONE |
| AC-24.3 | Repo CRUD for all 5 node kinds | test_ac_24_3_crud | DONE |
| AC-24.4 | note_passion tool | test_ac_24_4_note_passion | PENDING |
| AC-24.5 | practice_skill tool | test_ac_24_5_practice_skill | PENDING |

### Spec 25: activation-graph.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-25.1 | active_now sigmoid computation | test_ac_25_1_sigmoid | PENDING |
| AC-25.2 | Self-loop contributor rejected | test_ac_25_2_no_self_loop | DONE |
| AC-25.3 | Expired contributor excluded | test_ac_25_3_expired_excluded | DONE |
| AC-25.4 | Contributor weight range enforced | test_ac_25_4_weight_range | DONE |
| AC-25.5 | insert_contributor persists | test_ac_25_5_insert | DONE |
| AC-25.6 | mark_contributor_retracted sets field | test_ac_25_6_retract | DONE |

### Spec 26: self-todos.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-26.1 | Todo insert/get/list | test_ac_26_1_crud | DONE |
| AC-26.2 | Revision append-only | test_ac_26_2_revision_append | DONE |
| AC-26.3 | max_revision_num correct | test_ac_26_3_max_revision | DONE |
| AC-26.4 | list_active_todos filters by status | test_ac_26_4_active_filter | DONE |
| AC-26.5 | complete_self_todo with AFFIRMATION | test_ac_26_5_complete | PENDING |

### Spec 27: mood.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-27.1 | Mood valence/arousal/focus range validation | test_ac_27_1_range_validation | DONE |
| AC-27.2 | Repo insert/update/get/has_mood | test_ac_27_2_crud | DONE |
| AC-27.3 | tick_mood_decay toward neutral | test_ac_27_3_decay | PENDING |
| AC-27.4 | nudge_mood with clamping | test_ac_27_4_nudge | PENDING |
| AC-27.5 | mood_descriptor qualitative label | test_ac_27_5_descriptor | PENDING |

### Spec 28: self-surface.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-28.1 | recall_self deep read | test_ac_28_1_recall_self | PENDING |
| AC-28.2 | render_minimal_block 4-line block | test_ac_28_2_minimal_block | PENDING |
| AC-28.3 | First-person framing | test_ac_28_3_first_person | PENDING |

### Spec 29: self-bootstrap.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-29.1 | run_bootstrap creates 24 facets | test_ac_29_1_24_facets | DONE |
| AC-29.2 | preflight_validate checks | test_ac_29_2_preflight | DONE |
| AC-29.3 | generate_likert_answers produces 200 | test_ac_29_3_200_answers | DONE |
| AC-29.4 | finalize inserts mood | test_ac_29_4_finalize_mood | DONE |
| AC-29.5 | Resume support | test_ac_29_5_resume | DONE |
| AC-29.6 | verify_final_state checks | test_ac_29_6_verify | DONE |

### Spec 30: self-as-conduit.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-30.1 | Pipeline processes request end-to-end | test_ac_30_1_pipeline | PENDING |
| AC-30.2 | reply_directly for straightforward requests | test_ac_30_2_reply_directly | PENDING |
| AC-30.3 | delegate for ambiguous requests | test_ac_30_3_delegate | PENDING |
| AC-30.4 | decline for dangerous requests | test_ac_30_4_decline | PENDING |
| AC-30.5 | ask_clarifying for ambiguous requests | test_ac_30_5_ask_clarifying | PENDING |

---

## Autonoetic Completion (Phase 2)

### Spec 31: source-monitoring.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-31.1 | validate_first_person accepts I-statements | test_ac_31_1_accepts_first_person | DONE |
| AC-31.2 | validate_first_person rejects third-person | test_ac_31_2_rejects_third_person | DONE |
| AC-31.3 | reconstruct_perspective rewrites to first person | test_ac_31_3_reconstruct | DONE |
| AC-31.4 | SourceMonitoringViolation raised on violation | test_ac_31_4_violation | DONE |
| AC-31.5 | CrossSelfStanceOwnership enforced | test_ac_31_5_cross_self | DONE |
| AC-31.6 | Empty content handled | test_ac_31_6_empty | DONE |
| AC-31.7 | Unicode content handled | test_ac_31_7_unicode | DONE |
| AC-31.8 | stance_owner_id on EpisodicMemory | test_ac_31_8_stance_owner | PENDING |
| AC-31.9 | Mixed-source content flagged | test_ac_31_9_mixed_source | DONE |
| AC-31.10 | validate_first_person case-insensitive | test_ac_31_10_case_insensitive | DONE |

### Spec 32: memory-source-state.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-32.1 | source_state reads real memory weight | test_ac_32_1_source_state | DONE |
| AC-32.2 | REGRET weight contributes higher | test_ac_32_4_regret_weight_contributes_higher | DONE |
| AC-32.3 | OBSERVATION weight contributes lower | test_ac_32_4_observation_weight_contributes_lower | DONE |
| AC-32.4 | Missing memory returns zero | test_ac_32_5_missing_returns_zero | DONE |
| AC-32.5 | REGRET outperforms OBSERVATION | test_ac_32_6_regret_outperforms | DONE |

### Spec 33: activation-cache.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-33.1 | Cache hit returns same value | test_ac_33_1_cache_hit | DONE |
| AC-33.2 | TTL expiry causes recomputation | test_ac_33_2_ttl_expiry | DONE |
| AC-33.3 | Contributor write invalidates cache | test_ac_33_3_write_invalidates | DONE |
| AC-33.4 | Cold start returns fresh computation | test_ac_33_4_cold_start | DONE |
| AC-33.5 | Thread-safety of concurrent reads | test_ac_33_5_thread_safety | PENDING |

### Spec 34: contradiction-regret.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-34.1 | Low surprise mints contradiction OPINION | test_ac_34_1_low_surprise_mints_contradiction_opinion | DONE |
| AC-34.2 | Contradiction OPINION content format | test_ac_34_2_contradiction_opinion_content_format | DONE |
| AC-34.3 | Contradiction OPINION has correct metadata | test_ac_34_3_contradiction_opinion_has_correct_metadata | DONE |
| AC-34.4 | High surprise mints OPINION and REGRET | test_ac_34_4_high_surprise_mints_opinion_and_regret | DONE |
| AC-34.5 | REGRET supersedes OPINION does not | test_ac_34_5_regret_supersedes_opinion_does_not | DONE |
| AC-34.6 | Zero surprise mints nothing | test_ac_34_6_zero_surprise_mints_nothing | DONE |
| AC-34.7 | Contradiction OPINION in episodic | test_ac_34_7_contradiction_opinion_in_episodic | DONE |

---

## Proactive Expansion (Phase 3)

### Spec 35: newsletter-reader.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-35.1 | Is READ tool | test_ac_35_1_is_read_tool | DONE |
| AC-35.2 | Requires vault_dir | test_ac_35_2_requires_vault_dir | DONE |
| AC-35.3 | Parses frontmatter | test_ac_35_3_parses_frontmatter | DONE |
| AC-35.4 | Incremental skips seen | test_ac_35_4_incremental_skips_seen | DONE |
| AC-35.5 | Full returns all | test_ac_35_5_full_returns_all | DONE |
| AC-35.6 | No frontmatter uses defaults | test_ac_35_6_no_frontmatter_defaults | DONE |
| AC-35.7 | Malformed skipped | test_ac_35_7_malformed_skipped | DONE |
| AC-35.8 | Non-md ignored | test_ac_35_8_non_md_ignored | DONE |
| AC-35.9 | Read-only | test_ac_35_9_readonly | DONE |
| AC-35.10 | Subdirectories scanned | test_ac_35_10_subdirectories | DONE |
| AC-35.11 | Empty dir returns empty | test_ac_35_11_empty_dir | DONE |

### Spec 37: stronghold-litellm.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-37.1 | Discovers models from proxy | test_ac_37_1_discovers_models | DONE |
| AC-37.2 | Merges with static pools | test_ac_37_2_merges_with_static | DONE |
| AC-37.3 | Unreachable returns empty | test_ac_37_3_unreachable_returns_empty | DONE |
| AC-37.4 | Embedding role detected | test_ac_37_4_embedding_role_detected | DONE |

---

## Guardrails (Tranche 9)

### Spec 39: guardrails.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-39.1 | Self-write validates first-person + injection scanner | test_ac_39_1_i_read_accepted | DONE |
| AC-39.2 | Injection scanner detects patterns | test_ac_39_2_detects_system_tag | DONE |
| AC-39.3 | Rejected writes produce OBSERVATION | test_ac_39_1_injection_blocked | DONE |
| AC-39.4 | Non-self origins bypass scanner | test_ac_39_4_nonscan_bypass | PENDING |
| AC-39.5 | Per-request budget: 3 nodes, 5 contributors, 2 todos, 3 claims | test_ac_39_6_node_budget_exceeded | DONE |
| AC-39.6 | Budget exceeded raises SelfWriteBudgetExceeded | test_ac_39_6_node_budget_exceeded | DONE |
| AC-39.7 | Budget resets per request_hash | test_ac_39_7_different_request_resets | DONE |
| AC-39.8 | Max 8 retrieval contributors per target | test_ac_39_10_retrieval_cap_limits_materialization | DONE |
| AC-39.9 | Sum retrieval weights ≤ 1.0 | test_ac_39_10_retrieval_cap_limits_materialization | DONE |
| AC-39.10 | 20 candidates → at most 8 materialized, sum ≤ 1.0 | test_ac_39_10_retrieval_cap_limits_materialization | DONE |
| AC-39.11 | request_hash + perception_tool_call_id on every write | test_ac_39_11_forensic_tag | PENDING |
| AC-39.12 | Direct repo insert without provenance raises | test_ac_39_12_provenance_missing | PENDING |
| AC-39.13 | Weekly drift cap 0.5 per facet | test_ac_39_13_drift_cap | PENDING |
| AC-39.14 | Retest past cap clips and mints OPINION | test_ac_39_14_drift_clip | PENDING |
| AC-39.15 | Drift tracking table | test_ac_39_15_drift_table | PENDING |
| AC-39.16 | ≤3 narrative claims per facet per week | test_ac_39_16_claim_rate | PENDING |
| AC-39.17 | Rolling 7-day mood nudge sum cap 2.0 | test_ac_39_17_mood_cap | PENDING |
| AC-39.18 | practice_skill requires supporting memory | test_ac_39_18_skill_honesty | PENDING |
| AC-39.19 | Contributor writes to facet/passion go pending | test_ac_39_19_pending | PENDING |
| AC-39.20 | Pending invisible to active_now() | test_ac_39_20_pending_invisible | PENDING |
| AC-39.21 | Weekly digest lists pending | test_ac_39_21_digest | PENDING |
| AC-39.22 | Operator ACK migrates to live | test_ac_39_22_ack_migrate | PENDING |
| AC-39.23 | Decline mints REGRET | test_ac_39_23_decline_regret | PENDING |
| AC-39.24 | acting_self_id mismatch raises CrossSelfAccess | test_ac_39_24_cross_self_access_detected | DONE |
| AC-39.25 | FK from every self-table to self_identity | test_ac_39_25_self_identity_must_exist_for_facet_insert | DONE |
| AC-39.26 | Bootstrap seed collision detection | test_ac_39_26_seed_collision | PENDING |
| AC-39.27 | --allow-seed-reuse mints LESSON | test_ac_39_27_seed_reuse | PENDING |
| AC-39.28 | Bootstrap finalize operator HMAC signature | test_ac_39_28_hmac | PENDING |
| AC-39.29 | SELF_TOOL_REGISTRY importable only via SelfRuntime | test_ac_39_29_import_firewall | PENDING |
| AC-39.30 | Scheduled GC sweep deletes expired retrieval | test_ac_39_30_gc_sweep | PENDING |
| AC-39.31 | Opportunistic GC on read | test_ac_39_31_gc_read | PENDING |
| AC-39.32 | Hard node caps per kind | test_ac_39_32_node_caps | PENDING |
| AC-39.33 | Eviction produces OBSERVATION | test_ac_39_33_evict_observation | PENDING |
| AC-39.34 | Near-duplicate cosine ≥ 0.88 flags review | test_ac_39_34_duplicate | PENDING |
| AC-39.35 | Pending-review muted 0.5× in active_now | test_ac_39_35_mute | PENDING |
| AC-39.36 | Weekly todo compaction | test_ac_39_36_todo_compact | PENDING |
| AC-39.37 | Personality answer compaction | test_ac_39_37_answer_compact | PENDING |

---

## Tranche 7.0–7.2: Foundation + Boundaries (Renumbered)

### Spec 68: self-tool-registry.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-68.1 | SelfTool frozen dataclass with validation | test_ac_68_1_selftool_validation | PENDING |
| AC-68.2 | SELF_TOOL_REGISTRY insert; duplicate raises | test_ac_68_2_registry_insert | PENDING |
| AC-68.3 | All spec 28 tools present after import | test_ac_68_3_all_tools_present | PENDING |
| AC-68.4 | Description opens with first-person clause | test_ac_68_4_first_person_desc | PENDING |
| AC-68.5 | tool_schemas() returns OpenAI function-call shape | test_ac_68_5_tool_schemas | PENDING |
| AC-68.6 | Schemas cached to config/self_tools.json | test_ac_68_6_schema_cache | PENDING |
| AC-68.7 | invoke dispatches to handler | test_ac_68_7_invoke_dispatch | PENDING |
| AC-68.8 | Transaction wrap on invoke failure | test_ac_68_8_transaction_wrap | PENDING |
| AC-68.9 | Trust tier enforcement | test_ac_68_9_trust_tier | PENDING |
| AC-68.10 | write_contributor validates and inserts | test_ac_68_10_write_contributor | PENDING |
| AC-68.11 | record_personality_claim mints OPINION | test_ac_68_11_personality_claim | PENDING |
| AC-68.12 | retract_contributor_by_counter net-zero | test_ac_68_12_retract_contributor | PENDING |
| AC-68.13 | Non-matching retraction raises | test_ac_68_13_no_match_retract | PENDING |
| AC-68.14 | Double import idempotent | test_ac_68_14_double_import | PENDING |
| AC-68.15 | SelfNotReady handler no memory leak | test_ac_68_15_no_leak | PENDING |

### Spec 69: memory-mirroring.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-69.1 | Bridge exposes 5 mirror helpers | test_ac_69_1_bridge_api | PENDING |
| AC-69.2 | Content length validation | test_ac_69_2_content_length | PENDING |
| AC-69.3 | Context includes self_id + request_hash | test_ac_69_3_context_fields | PENDING |
| AC-69.4 | Bootstrap answers mirror as OBSERVATION | test_ac_69_4_bootstrap_mirror | PENDING |
| AC-69.5 | Retest answers mirror | test_ac_69_5_retest_mirror | PENDING |
| AC-69.6 | Personality claim mirrors as OPINION | test_ac_69_6_claim_mirror | PENDING |
| AC-69.7 | note_engagement mirrors | test_ac_69_7_engagement_mirror | PENDING |
| AC-69.8 | practice_skill mirrors | test_ac_69_8_skill_mirror | PENDING |
| AC-69.9 | write_contributor mirrors | test_ac_69_9_contributor_mirror | PENDING |
| AC-69.10 | complete_self_todo mirrors AFFIRMATION | test_ac_69_10_todo_mirror | PENDING |
| AC-69.11 | nudge_mood mirrors | test_ac_69_11_mood_mirror | PENDING |
| AC-69.12 | Bootstrap finalize LESSON mirror | test_ac_69_12_finalize_mirror | PENDING |
| AC-69.13 | Warden block mirrors | test_ac_69_13_warden_block_mirror | PENDING |
| AC-69.14 | Mirror + write atomic | test_ac_69_14_atomic | PENDING |
| AC-69.15 | Bridge never mutates existing | test_ac_69_15_insert_only | PENDING |
| AC-69.16 | Mirrored memories tagged mirror=True | test_ac_69_16_mirror_tag | PENDING |
| AC-69.17 | Integration: mutation count matches mirror count | test_ac_69_17_integration_count | PENDING |

### Spec 70: self-schedules.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-70.1 | finalize registers mood-decay trigger | test_ac_70_1_mood_trigger | PENDING |
| AC-70.2 | finalize registers personality-retest trigger | test_ac_70_2_retest_trigger | PENDING |
| AC-70.3 | Re-registration idempotent | test_ac_70_3_idempotent | PENDING |
| AC-70.4 | run_personality_retest wrapper | test_ac_70_4_retest_wrapper | PENDING |
| AC-70.5 | Retest failure writes LESSON | test_ac_70_5_retest_failure | PENDING |
| AC-70.6 | Retest completion mirrors LESSON | test_ac_70_6_retest_complete | PENDING |
| AC-70.7 | 24 ticks produce 24 decay calls | test_ac_70_7_24_ticks | PENDING |
| AC-70.8 | Downtime catch-up: one call only | test_ac_70_8_downtime | PENDING |
| AC-70.9 | Archive unregisters triggers | test_ac_70_9_archive_unregister | PENDING |
| AC-70.10 | stronghold self triggers subcommand | test_ac_70_10_triggers_cli | PENDING |

### Spec 71: self-write-preconditions.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-71.1 | _bootstrap_complete checks facets + answers + mood | test_ac_71_1_bootstrap_check | PENDING |
| AC-71.2 | Every write-tool calls _bootstrap_complete | test_ac_71_2_all_tools_check | PENDING |
| AC-71.3 | recall_self already enforces | test_ac_71_3_recall_enforces | PENDING |
| AC-71.4 | Bootstrap direct writes bypass check | test_ac_71_4_bootstrap_bypass | PENDING |
| AC-71.5 | ActivationCache TTL 30s hit/miss | test_ac_71_5_cache_ttl | PENDING |
| AC-71.6 | Contributor write invalidates cache | test_ac_71_6_write_invalidates | PENDING |
| AC-71.7 | Source mutation invalidates cache | test_ac_71_7_source_invalidation | PENDING |
| AC-71.8 | Cache keyed on ctx.hash | test_ac_71_8_ctx_hash_key | PENDING |
| AC-71.9 | Cache LRU eviction at 1024 | test_ac_71_9_lru_eviction | PENDING |
| AC-71.10 | acting_self_id mismatch raises CrossSelfAccess | test_ac_71_10_cross_self | PENDING |
| AC-71.11 | insert_contributor checks acting_self_id | test_ac_71_11_contributor_self_id | PENDING |
| AC-71.12 | insert_todo_revision checks acting_self_id | test_ac_71_12_revision_self_id | PENDING |
| AC-71.13 | Bootstrap inserts pass acting_self_id | test_ac_71_13_bootstrap_passes | PENDING |
| AC-71.14 | Concurrent reads no double-fetch | test_ac_71_14_concurrent | PENDING |
| AC-71.15 | Cache not persistent across restart | test_ac_71_15_not_persistent | PENDING |
| AC-71.16 | _bootstrap_complete not cached | test_ac_71_16_not_cached | PENDING |

### Spec 72: warden-on-self-writes.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-72.1 | Gate invokes warden.scan | test_ac_72_1_gate_scans | PENDING |
| AC-72.2 | Every write-tool calls gate | test_ac_72_2_all_tools_gate | PENDING |
| AC-72.3 | Gate fires before any repo write | test_ac_72_3_before_write | PENDING |
| AC-72.4 | Block writes OBSERVATION memory | test_ac_72_4_block_memory | PENDING |
| AC-72.5 | Block-memory carries forensic tags | test_ac_72_5_forensic_tags | PENDING |
| AC-72.6 | Block-memory 80-char preview only | test_ac_72_6_preview_only | PENDING |
| AC-72.7 | Trust posture TOOL_RESULT | test_ac_72_7_trust_posture | PENDING |
| AC-72.8 | Bootstrap inserts not scanned | test_ac_72_8_bootstrap_exempt | PENDING |
| AC-72.9 | Mood nudges not scanned | test_ac_72_9_mood_exempt | PENDING |
| AC-72.10 | Prometheus counter on block | test_ac_72_10_metrics | PENDING |
| AC-72.11 | Warden failure treated as block | test_ac_72_11_warden_fail | PENDING |
| AC-72.12 | Large text truncated to 10k | test_ac_72_12_large_text | PENDING |
| AC-72.13 | No cached scan decisions | test_ac_72_13_no_cache | PENDING |

### Spec 73: self-write-budgets.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-73.1 | RequestWriteBudget defaults: 3/5/2/3 | test_ac_73_1_defaults | PENDING |
| AC-73.2 | RequestWriteBudget.new() fresh instance | test_ac_73_2_fresh | PENDING |
| AC-73.3 | ContextVar binding per request | test_ac_73_3_context_var | PENDING |
| AC-73.4 | use_budget context manager | test_ac_73_4_context_mgr | PENDING |
| AC-73.5 | Decrement before write; zero raises | test_ac_73_5_decrement_first | PENDING |
| AC-73.6 | Warden block refunds counter | test_ac_73_6_refund | PENDING |
| AC-73.7 | Tool-to-category map correct | test_ac_73_7_category_map | PENDING |
| AC-73.8 | Non-budgeted tools bypass | test_ac_73_8_unbudgeted | PENDING |
| AC-73.9 | Prometheus counter on exhaustion | test_ac_73_9_metrics | PENDING |
| AC-73.10 | OBSERVATION mirror on exhaustion | test_ac_73_10_exhaustion_mirror | PENDING |
| AC-73.11 | No cross-request budget leakage | test_ac_73_11_no_leakage | PENDING |
| AC-73.12 | Nested perception+observation share budget | test_ac_73_12_shared_budget | PENDING |
| AC-73.13 | Config-loaded defaults | test_ac_73_13_config_defaults | PENDING |

### Spec 74: retrieval-contributor-cap.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-74.1 | materialize inserts ≤ K per target | test_ac_74_1_k_limit | PENDING |
| AC-74.2 | Descending similarity order | test_ac_74_2_descending | PENDING |
| AC-74.3 | Sum cap stops insertion | test_ac_74_3_sum_cap | PENDING |
| AC-74.4 | At least one inserted even if exceeds cap | test_ac_74_4_at_least_one | PENDING |
| AC-74.5 | Weight = similarity × coefficient | test_ac_74_5_weight_formula | PENDING |
| AC-74.6 | expires_at = now + TTL | test_ac_74_6_expiry | PENDING |
| AC-74.7 | Per-request scope | test_ac_74_7_per_request | PENDING |
| AC-74.8 | Same repo path as write_contributor | test_ac_74_8_repo_path | PENDING |
| AC-74.9 | Post-materialization invariants hold | test_ac_74_9_invariants | PENDING |
| AC-74.10 | Both count and sum caps enforced | test_ac_74_10_both_caps | PENDING |
| AC-74.11 | Prometheus gauge active count | test_ac_74_11_gauge | PENDING |
| AC-74.12 | Prometheus counter dropped | test_ac_74_12_dropped | PENDING |
| AC-74.13 | Zero hits: no rows | test_ac_74_13_zero_hits | PENDING |
| AC-74.14 | Similarity > 1.0 clamped | test_ac_74_14_clamp | PENDING |
| AC-74.15 | Double call idempotent | test_ac_74_15_idempotent | PENDING |

### Spec 75: forensic-tagging.md

| AC-ID | Scenario | Test Function | Status |
|-------|----------|---------------|--------|
| AC-75.1 | ContextVars defined with default None | test_ac_75_1_vars_defined | PENDING |
| AC-75.2 | request_scope sets/unsets | test_ac_75_2_request_scope | PENDING |
| AC-75.3 | tool_call_scope nestable | test_ac_75_3_tool_call_scope | PENDING |
| AC-75.4 | Bridge stamps context from vars | test_ac_75_4_bridge_stamps | PENDING |
| AC-75.5 | Self-model rows carry forensic fields | test_ac_75_5_row_fields | PENDING |
| AC-75.6 | Out-of-band writes tagged | test_ac_75_6_out_of_band | PENDING |
| AC-75.7 | Direct insert without provenance raises | test_ac_75_7_no_provenance | PENDING |
| AC-75.8 | Index on request_hash | test_ac_75_8_index | PENDING |
| AC-75.9 | forensics CLI subcommand | test_ac_75_9_cli | PENDING |
| AC-75.10 | Pipeline computes and binds request_hash | test_ac_75_10_pipeline_hash | PENDING |
| AC-75.11 | Tool-call scope set per handler | test_ac_75_11_tool_call_bind | PENDING |
| AC-75.12 | Concurrent requests isolated | test_ac_75_12_concurrent | PENDING |
| AC-75.13 | Background task inherits parent vars | test_ac_75_13_inherit | PENDING |
| AC-75.14 | 64-bit hash documented | test_ac_75_14_hash_doc | PENDING |

---

## Tranche 7.2: Drift Bounds

### Spec 40: facet-drift-budget.md (14 ACs — all PENDING)
### Spec 41: narrative-claim-rate-limit.md (14 ACs — all PENDING)
### Spec 42: mood-rolling-sum-guard.md (13 ACs — all PENDING)
### Spec 43: skill-honesty-invariant.md (13 ACs — all PENDING)

---

## Tranche 7.3: Self-as-Conduit Runtime

### Spec 44: conduit-runtime.md (25 ACs — all PENDING)
### Spec 45: conduit-mode-shim.md (15 ACs — all PENDING)

---

## Tranche 7.4: Operator Oversight

### Spec 46: operator-review-gate.md (18 ACs — all PENDING)
### Spec 47: repo-self-id-enforcement.md (13 ACs — all PENDING)
### Spec 48: bootstrap-seed-registry.md (16 ACs — all PENDING)
### Spec 49: self-tool-import-firewall.md (16 ACs — all PENDING)

---

## Tranche 7.5: Growth and Operational

### Spec 50: retrieval-contributor-gc.md (13 ACs — all PENDING)
### Spec 51: per-kind-node-caps.md (16 ACs — all PENDING)
### Spec 52: near-duplicate-review.md (17 ACs — all PENDING)
### Spec 53: revision-compaction.md (15 ACs — all PENDING)

---

## Tranche 8: Reflection and Decision-Influence

### Spec 57: self-reflection-ritual.md (20 ACs — all PENDING)
### Spec 58: session-scoped-mood.md (28 ACs — all PENDING)
### Spec 59: mood-affects-decisions.md (20 ACs — all PENDING)
### Spec 60: prospective-simulation.md (23 ACs — all PENDING)
### Spec 61: self-naming-ritual.md (21 ACs — all PENDING)
### Spec 62: sentinel-self-interaction.md (19 ACs — all PENDING)

---

## Tranche 9: Detectors and Feedback Channels

### Spec 63: learning-extraction-detector.md (18 ACs — all PENDING)
### Spec 64: affirmation-candidacy-detector.md (17 ACs — all PENDING)
### Spec 65: prospection-accuracy-detector.md (15 ACs — all PENDING)
### Spec 66: operator-coaching-channel.md (22 ACs — all PENDING)
### Spec 67: cross-user-self-experience.md (23 ACs — all PENDING)

---

## Tranche 10: Conversations and Bootstrap

### Spec 54: conversation-threads.md (18 ACs — all PENDING)
### Spec 55: proactive-outbound.md (14 ACs — all PENDING)
### Spec 56: interactive-bootstrap.md (30 ACs — all PENDING)

---

## Summary

| Tranche | Specs | ACs | Done | Pending | Coverage |
|---------|-------|-----|------|---------|----------|
| 1: Memory | 1–7 | 68 | 67 | 1 | 99% |
| 2: Motivation | 8–11 | 53 | 53 | 0 | 100% |
| 3: Detectors | D, D.1 | 5 | 5 | 0 | 100% |
| 4: Dreaming | 12 | 9 | 9 | 0 | 100% |
| 5: Runtime | 13–21 | 119 | 86 | 33 | 72% |
| 6: Self-model | 22–30 | 58 | 31 | 27 | 53% |
| Autonoetic | 31–34 | 27 | 26 | 1 | 96% |
| Proactive | 35, 37 | 15 | 15 | 0 | 100% |
| Guardrails | 39 | 37 | 10 | 27 | 27% |
| 7.0–7.1 | 68–75 | 106 | 0 | 106 | 0% |
| 7.2 | 40–43 | 54 | 0 | 54 | 0% |
| 7.3 | 44–45 | 40 | 0 | 40 | 0% |
| 7.4 | 46–49 | 63 | 0 | 63 | 0% |
| 7.5 | 50–53 | 61 | 0 | 61 | 0% |
| 8: Reflection | 57–62 | 131 | 0 | 131 | 0% |
| 9: Detectors | 63–67 | 95 | 0 | 95 | 0% |
| 10: Conversations | 54–56 | 62 | 0 | 62 | 0% |
| **Total** | **67** | **~963** | **~302** | **~661** | **31%** |

---

## Mutation Testing Gates

| Tranche | Scope | Min Kill Rate |
|---------|-------|:---:|
| 1–3 | Core memory layer | 90% |
| 5 | Runtime integration | 85% |
| 6 | Self-model data layer | 80% |
| 7 | Guardrails | 95% |
| 8–9 | Detectors + decision-influence | 85% |
| 10 | Conversations + coaching | 85% |
