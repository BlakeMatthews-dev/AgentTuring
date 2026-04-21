# Tranche 7 — Plan

*Closing the Tranche 6 implementation gaps and landing the Tranche 6 audit's guardrails in dependency order. Five tranches, sequenced so each depends only on earlier ones. All land on `research/project-turing` via PRs targeting `project_Turing`.*

**Prerequisite doc:** [`AUDIT-self-model-guardrails.md`](./AUDIT-self-model-guardrails.md) — findings and guardrail numbering referenced here.

---

## Why this order

Guardrails assume the tools they gate exist. Today's sketch is a library — schema, math, tests — with three load-bearing runtime pieces absent: the self-tool registry (F35), memory mirroring (F38), and scheduled jobs (F37), plus the entire self-as-Conduit pipeline (F39). A guardrail like G1 ("Warden on self-writes") gates tools that have no runtime surface; a guardrail like G6 ("rolling-sum mood cap") assumes mood is decaying on a schedule.

So Tranche 7 starts with foundation closure. Guardrails follow. The Conduit rewrite and operator-oversight design are later tranches because they are the largest surface-area changes and need the earlier work to land first.

| # | Theme | Blocks | Depends on |
|---|---|---|---|
| 7.0 | Foundation closure (critical impl gaps) | F35, F36, F37, F38, F39 (partial), F30, F29, F33 | — |
| 7.1 | Boundary hardening | G1, G2, G5, G17 | 7.0.1, 7.0.2 |
| 7.2 | Drift bounds | G3, G4, G6, G10 | 7.0.1, 7.0.3 |
| 7.3 | Self-as-Conduit runtime | F39 (full), F40 | 7.0 complete |
| 7.4 | Operator oversight | G12, G13, G14, G15, G16, G18 | 7.1, 7.3 |
| 7.5 | Growth and operational | G7, G8, G9, G11 | 7.0.2 |
