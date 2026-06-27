---
date: 2026-06-26
topic: orchestrator-plan-policy-adoption
prd: docs/prds/024-orchestrator-plan-policy-adoption/024-prd-orchestrator-plan-policy-adoption.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 024 Orchestrator plan-policy adoption (fan-out)

Generated from the frozen PRD spec union **R18–R23 (parent) + R35–R37 (amendment A1)**. Fan-out is sequenced in
009-audit order (`/sw-debug` → `/sw-doc` → `/sw-feedback`), each landing its full row set before the next, behind
shared scaffolding (program gate, orchestrator-step-plan schema, guideline packs, `signal_context`, state
isolation). Everything is **wire-only** over the frozen 021/022/023 machinery — no kernel/gate/driver/loop
re-authoring. Default stays `canonical`; the whole fan-out is dormant until the 023 R31 decision rule returns
positive (TR0/R35).

## Tasks

### 1. Program dependency gate + R31-inconclusive fail-closed — S

- [ ] 1.1 Mechanical program gate (TR0)
  - **File:** `scripts/test/run-fanout-fixtures.sh`, `scripts/fanout_gate.py`
  - **Expected:** `fanout-024-blocked-without-023-r31` — debug/doc/feedback `proposed` adoption **and** 024 task generation are refused until the named 023 pilot fixtures are green **and** the R31 decision rule returns **positive**; mirrors 023 TR0.
  - **R-IDs:** TR0, SC7
- [ ] 1.2 Inconclusive-N treated as non-positive (R35)
  - **File:** `scripts/fanout_gate.py`, `scripts/test/run-fanout-fixtures.sh`
  - **Expected:** `fanout-024-insufficient-n-not-adopted` — an **inconclusive** R31 outcome (insufficient N) refuses fan-out **identically to a negative** outcome (program exit, fail-closed); no intermediate deferred/blocked-then-maybe state keyed on N (extends `fanout-024-blocked-without-023-r31`).
  - **R-IDs:** R35

### 2. Orchestrator-step-plan schema (single-tier) + gate orchestrator tier — M

- [ ] 2.1 `orchestrator-step-plan.schema.json` closed-world vocabulary (TR1)
  - **File:** `core/sw-reference/schemas/orchestrator-step-plan.schema.json`
  - **Expected:** single-tier, closed-world step vocabulary per orchestrator mapped from existing procedures (debug: triage → normalize → enrich → RCA → route; doc: tier-gated atomic chain; feedback: normalize → redact → route → handoff). Distinct from deliver wave/phase tiers.
  - **R-IDs:** TR1, R20
- [ ] 2.2 Extend `wave.sh plan validate` with orchestrator tier (TR1, R20)
  - **File:** `scripts/wave.sh`, `scripts/wave_plan_validate.py`
  - **Expected:** validate single-tier orchestrator plans under an **orchestrator tier** using the *same* fail-closed gate as deliver (no weaker path); unknown step IDs rejected closed-world; `orchestrator-plan-rejects-unknown-step`.
  - **R-IDs:** R20
- [ ] 2.3 Adoption call-site map skeleton + kernel-completeness lint (TR8)
  - **File:** `core/sw-reference/adoption-call-site-map.md`, `scripts/kernel-completeness-lint.sh`
  - **Expected:** 022 TR9 adoption-side map (proposal site, canonical chain source, guideline-pack id, durable owner path, `signal_context` snapshot point, parity fixture set per orchestrator); completeness lint covers the new orchestrator step IDs.
  - **R-IDs:** TR8, R18

### 3. Guideline packs + deny-lists + variance probe / consistency-only mode — M

- [ ] 3.1 Author debug/doc/feedback guideline packs (TR2, R18)
  - **File:** `core/sw-reference/guidelines/{debug,doc,feedback}.pack.json`
  - **Expected:** canonical fallback chains + signal-conditional **floors** (R33) pinning mandatory steps + **forbidden deliver-only steps** (merge enqueue/run-next, terminal-ship, git-push, main-merge, inline `/sw-execute`, lock-acquire where N/A); schema-validated via the extended 021 harness with a completeness lint; `orchestrator-proposed-plan-rejects-deliver-only-steps` (per orchestrator, SC4).
  - **R-IDs:** R18
- [ ] 3.2 Variance probe + consistency-only adoption mode (R36, R36a–c)
  - **File:** `scripts/variance_probe.py`, `scripts/test/run-fanout-fixtures.sh`
  - **Expected:** a **once-at-authoring** variance probe runs the orchestrator's canonical-parity row + at most one plan-shape-latitude check from its TR1 vocabulary → boolean `canonical ≡ proposed`. If equal → **consistency-only** (manifest + selector + canonical wiring land; proposed pack/surface **deferred, not built**); else full adoption (TR1–TR7). `/sw-doc` **defaults consistency-only** pending its probe. `orchestrator-consistency-only-defers-proposed-pack`.
  - **R-IDs:** R36
- [ ] 3.3 Consistency-only proposed-fixture exemption (R36d)
  - **File:** `scripts/test/run-fanout-fixtures.sh`
  - **Expected:** `consistency-only-exempts-proposed-fixtures` — a consistency-only orchestrator passes canonical-parity + selector (SC1/SC2) and treats **all** its `proposed`-path rows as N/A (`*-proposed-*`, `*-022-parity-under-proposed`, and SC3 halt rows lacking a `proposed` substring); halt preservation (R19) proven on the **canonical** path; the orchestrator's "full row set" for Rollout gating is the reduced set.
  - **R-IDs:** R36

### 4. signal_context capture + state isolation + episodic model — M

- [ ] 4.1 Entry-time `signal_context` snapshot per orchestrator (TR3)
  - **File:** orchestrator entry hooks, `core/sw-reference/adoption-call-site-map.md`
  - **Expected:** snapshot + owner captured **before** `plan validate` (debug: signal type + relatedFiles + Sentry ref; feedback: sourceClass + invocation + route; doc: tier + doc_path) so the gate's anti-spoof/divergence check (022 R6) applies; owner is **session/ephemeral** for debug/feedback (R37b).
  - **R-IDs:** TR3, R37
- [ ] 4.2 Cross-orchestrator state isolation (TR6, R37e)
  - **File:** run-dir namespacing (`sw-debug-runs/`, `sw-feedback-runs/`), `.sw/layout.md`, `core/sw-reference/layout.md`
  - **Expected:** durable/scratch artifacts namespaced by orchestrator + runId; debug/feedback isolation is **ephemeral per-invocation** scratch (abandoned on terminal halt, no crash-resume checkpoint, no shared-state writes); `cross-orchestrator-state-isolation` — a debug/feedback run cannot mutate a deliver run's state or selector output.
  - **R-IDs:** R37
- [ ] 4.3 Episodic non-deliver run model + no durable resume (R37, R37a–d)
  - **File:** `scripts/test/run-fanout-fixtures.sh`
  - **Expected:** `non-deliver-episodic-no-durable-resume` — `/sw-debug`/`/sw-feedback` validate the plan at entry, surface R21 into the **existing episodic run/handoff summary**, expose **no** durable run-record/crash-resume; parent `resume-revalidates-planpolicy-mode` is **N/A** for them (deliver/doc-handoff-scoped); session-scoped budget counters still driver-enforced within the run (R37c).
  - **R-IDs:** R37

### 5. `/sw-debug` adoption (wire-only, episodic) — M

- [ ] 5.1 Debug proposal-site wiring + canonical parity (TR4a, R18, R20)
  - **File:** `core/commands/sw-debug.md`, `core/skills/debug/SKILL.md`
  - **Expected:** read `orchestration.planPolicy`; when `proposed`, propose single-tier plan → `wave.sh plan validate` → selector → persist → drive from stored plan (kernel re-check each `advance`); `canonical` byte-identical. `debug-canonical-parity`, `debug-proposed-routes-gate-selector`.
  - **R-IDs:** R18, R20
- [ ] 5.2 Preserve debug legitimate halts (R19)
  - **File:** `core/commands/sw-debug.md`, debug guideline floor
  - **Expected:** after **one** human route confirmation continue in-turn (DBG-A1) but the route-confirm and RCA human-decision halts are **driver-asserted** (a plan omitting/reordering them is rejected fail-closed); `debug-route-confirm-halt-required`, `debug-rca-human-decision-halt-required`.
  - **R-IDs:** R19
- [ ] 5.3 Sentry ingestion redaction + budgets + surfacing + parity (R21, R22, R23)
  - **File:** `core/skills/debug/SKILL.md`, ingestion path, `scripts/test/run-fanout-fixtures.sh`
  - **Expected:** Sentry bodies redacted before any persist/handoff incl. DBG-A2 concurrency; `debug-proposed-sentry-enrich-redact-before-preflight`; driver-enforced budget/no-progress `debug-budget-trip` (R22); chosen plan + capability set + rejections in episodic summary `debug-r21-surfacing` (R21); orchestrator-applicable 022 TR7 subset green `debug-022-parity-under-proposed` (R23).
  - **R-IDs:** R21, R22, R23

### 6. `/sw-doc` adoption (consistency-only default) — M

- [ ] 6.1 Doc proposal-site wiring + canonical parity + probe outcome (TR4b, R18, R20, R36c)
  - **File:** `core/commands/sw-doc.md`
  - **Expected:** `/sw-doc` defaults **consistency-only** (009 audit: no routine yields) — manifest + selector + canonical wiring land; a probe showing latitude flips to full adoption (recorded in task notes). `doc-canonical-parity`; `doc-proposed-routes-gate-selector` only if probe shows latitude (else N/A per R36d).
  - **R-IDs:** R18, R20
- [ ] 6.2 Preserve doc-review + afterTasks halts (R19)
  - **File:** `core/commands/sw-doc.md`, doc guideline floor
  - **Expected:** doc-review `manual`/`gated_auto` trade-off halts fire before any freeze step; `doc.afterTasks` (`stop`/`confirm`/`auto`) boundary preserved; halts proven on the canonical path for consistency-only. `doc-review-halt-{manual,gated-auto}-required`, `doc-afterTasks-checkpoint-required`. Deliver handoff reuses 023 wiring unchanged.
  - **R-IDs:** R19

### 7. `/sw-feedback` adoption (untrusted-signal chokepoint, episodic) — M

- [ ] 7.1 Feedback proposal-site wiring + canonical parity (TR4c, R18, R20)
  - **File:** `core/commands/sw-feedback.md`, `core/skills/feedback/SKILL.md`
  - **Expected:** read `planPolicy`; propose single-tier plan → gate → selector → persist → drive (episodic, R37); `canonical` byte-identical. `feedback-canonical-parity`, `feedback-proposed-routes-gate-selector`.
  - **R-IDs:** R18, R20
- [ ] 7.2 Untrusted-signal hard halt + redact-before-record + human-confirm (R19, R23)
  - **File:** `core/commands/sw-feedback.md`, ingestion path
  - **Expected:** `invocation ∈ {hook, monitor}` (`≠ human`) → **hard halt**, never auto-dispatch; full signal JSON redacted (`memory-redact.sh`) and wrapped `untrusted_payload` before any route record/memory write; routed dispatch requires persisted human-ack keyed by signalId. `feedback-hook-trigger-no-autodispatch-under-proposed`, `feedback-proposed-human-confirm-before-dispatch`, `feedback-proposed-inbound-redact-fail-closed`.
  - **R-IDs:** R19, R23
- [ ] 7.3 Feedback budgets + surfacing + parity (R21, R22, R23)
  - **File:** `core/skills/feedback/SKILL.md`, `scripts/test/run-fanout-fixtures.sh`
  - **Expected:** driver-enforced budget/no-progress `feedback-budget-trip` (R22); chosen plan + capability set + rejections in episodic summary `feedback-r21-surfacing` (R21); orchestrator-applicable 022 TR7 subset green `feedback-022-parity-under-proposed` (R23).
  - **R-IDs:** R21, R22, R23

### 8. Docs + emitter propagation + freshness — M

- [ ] 8.1 Per-orchestrator command/skill/rule prose (R18, R19, R37)
  - **File:** `core/commands/sw-debug.md`, `core/commands/sw-doc.md`, `core/commands/sw-feedback.md`, `core/skills/conductor/SKILL.md`, `core/skills/debug/SKILL.md`, `core/skills/feedback/SKILL.md`, `core/rules/sw-naming.mdc`, `core/rules/sw-conductor.mdc`
  - **Expected:** Plan-policy adoption subsection per command (read `planPolicy`; route single-tier plan via gate + selector by reference; preserved halts; R21 surfacing; default `canonical`); conductor adoption-table extension distinguishing **run durability** (`durable` deliver/doc→deliver vs `episodic` debug/feedback) and **adoption mode** (`full` vs `consistency-only`); one-line naming/conductor notes (episodic adoption; `/sw-doc` defaults consistency-only). No gate/selector duplication.
  - **R-IDs:** R18, R19, R37
- [ ] 8.2 Guides + CONTRIBUTING + layout (R35, R36)
  - **File:** `docs/guides/configuration.md`, `docs/guides/workflows.md`, `docs/guides/commands.md`, `README.md`, `docs/guides/getting-started.md`, `CONTRIBUTING.md`, `.sw/layout.md`, `core/sw-reference/layout.md`
  - **Expected:** list all four orchestrators as flag consumers (default `canonical`; flip remains 023-metric-gated); state R35 (inconclusive N = non-positive → program exit) and R36 (consistency-only via variance probe; `/sw-doc` default; pack deferred when `canonical ≡ proposed`); named per-orchestrator + amendment fixture suites with R-ID mapping; episodic ephemeral scratch documented separately from deliver durable run-state. **Do not** touch `INDEX.md`/`COMPLETION-LOG.md`/`GAP-BACKLOG.md`.
  - **R-IDs:** R35, R36
- [ ] 8.3 Regenerate both dist trees; freshness gate green (TR9)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** command/skill/rule/schema/layout deltas propagated; `emitter-freshness-stale-fails` green; `dist/` parity with `core/`.
  - **R-IDs:** TR9, SC1

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 2 |
| 5 | 3, 4 |
| 6 | 5 |
| 7 | 6 |
| 8 | 5, 6, 7 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R18 | 3.1, 5.1, 6.1, 7.1 | `orchestrator-proposed-plan-rejects-deliver-only-steps`; `{debug,doc,feedback}-proposed-routes-gate-selector` |
| R19 | 5.2, 6.2, 7.2 | `debug-route-confirm-halt-required`; `debug-rca-human-decision-halt-required`; `doc-review-halt-{manual,gated-auto}-required`; `doc-afterTasks-checkpoint-required`; `feedback-hook-trigger-no-autodispatch-under-proposed` |
| R20 | 2.1, 2.2, 5.1 | `orchestrator-plan-rejects-unknown-step`; `{debug,doc,feedback}-canonical-parity` |
| R21 | 5.3, 7.3 | `{debug,doc,feedback}-r21-surfacing` |
| R22 | 5.3, 7.3 | `{debug,doc,feedback}-budget-trip` |
| R23 | 5.3, 7.2, 7.3 | `{debug,doc,feedback}-022-parity-under-proposed`; `feedback-proposed-inbound-redact-fail-closed`; `debug-proposed-sentry-enrich-redact-before-preflight` |
| R35 | 1.2 | `fanout-024-insufficient-n-not-adopted` |
| R36 | 3.2, 3.3 | `orchestrator-consistency-only-defers-proposed-pack`; `consistency-only-exempts-proposed-fixtures` |
| R37 | 4.1, 4.2, 4.3 | `non-deliver-episodic-no-durable-resume`; `cross-orchestrator-state-isolation` |

## Relevant Files

- `core/commands/sw-debug.md`, `core/commands/sw-doc.md`, `core/commands/sw-feedback.md` — per-orchestrator Plan-policy adoption subsections
- `core/skills/debug/SKILL.md`, `core/skills/feedback/SKILL.md`, `core/skills/conductor/SKILL.md` — cross-refs + adoption table (durability + adoption-mode columns)
- `core/sw-reference/schemas/orchestrator-step-plan.schema.json` — single-tier closed-world step vocabulary
- `scripts/wave.sh` / `scripts/wave_plan_validate.py` — orchestrator-tier gate extension (same fail-closed gate)
- `core/sw-reference/guidelines/{debug,doc,feedback}.pack.json` — canonical chains + floors + forbidden deliver-only steps
- `scripts/variance_probe.py` — once-at-authoring consistency-only probe
- `scripts/fanout_gate.py` — TR0/R35 program gate (positive R31 + sufficient N)
- run-dir namespacing (`sw-debug-runs/`, `sw-feedback-runs/`) + ephemeral episodic scratch — `.sw/layout.md`, `core/sw-reference/layout.md`
- `core/sw-reference/adoption-call-site-map.md` — TR8 adoption-side call-site map
- `scripts/test/run-fanout-fixtures.sh` — all 024 + amendment fixtures
- `core/rules/sw-naming.mdc`, `core/rules/sw-conductor.mdc` — one-line boundary notes

## Notes

- **Program gate is mechanical and blocks task execution (TR0/R35).** Phase 1 must be green — 023 pilot fixtures
  green **and** R31 positive — before any adoption wiring runs; an inconclusive (insufficient-N) R31 is treated
  exactly like a negative outcome (program exit). If non-positive, 024 is **not adopted**: `proposed` wiring is
  retired/iterated, default stays `canonical`, and 021/022 standalone value is retained.
- **Sequential per-orchestrator rollout.** Phases 5 → 6 → 7 are a hard chain (009-audit order); each orchestrator
  lands its full row set green before the next begins (Rollout step 2). Shared scaffolding (2/3/4) fans out from
  the gate so the chain isn't blocked on each other's adoption.
- **Consistency-only is a scope reduction *within* the gated fan-out (R36).** The variance probe decides per
  orchestrator; `/sw-doc` defaults consistency-only, so its proposed pack/surface and all `proposed`-path
  fixtures (incl. SC3 halt rows) are N/A and halt preservation is proven on canonical — the reduced row set is
  authoritative for its Rollout gating.
- **Episodic non-deliver runs (R37).** `/sw-debug` + `/sw-feedback` validate at entry and surface R21 into their
  existing episodic summaries with ephemeral per-invocation scratch; no durable run-record/crash-resume (stays
  PRD-007/013 scoped); `resume-revalidates-planpolicy-mode` is N/A for them. The `/sw-doc → /sw-deliver` handoff
  inherits deliver durability unchanged.
- **Wire-only.** No change to the kernel classification, the gate, the deterministic step driver, the guideline
  schema, or the conductor loop — all consumed from frozen 021/022/023.
- Amendment doc/dist deltas fold into phase 8 (parent TR9) — no separate doc phase per A1.
