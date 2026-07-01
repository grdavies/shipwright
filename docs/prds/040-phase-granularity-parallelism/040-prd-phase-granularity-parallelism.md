---
brainstorm: docs/brainstorms/2026-06-30-loop-hardening-requirements.md
date: 2026-06-30
topic: phase-granularity-parallelism
visibility: public
frozen: true
frozen_at: 2026-06-30
---
# PRD 040 — Phase Granularity & Parallelism

## Overview

PRD B of the **loop-hardening** program. Today `/sw-tasks` sizes phases informally (author-labeled S/M/L)
and `/sw-deliver` plans waves from the `## Phase Dependencies` table plus contention edges that
`wave_deliver.py` injects from `**File:**`-path overlap **and** named serializing families (shared
migrations, `INDEX`, `CHANGELOG`, doc-numbering, generator-output / golden-manifest globs). The 2026
research treats **small, well-bounded units** as a *design constraint* for reviewability and throughput
(Osmani; Faros reports agent PRs ~51% larger). This PRD adds a **deterministic sizing heuristic** to
`/sw-tasks`, an **advisory split-suggestion** that decomposes an oversized/separable phase into smaller
units with explicit dependency edges (never auto-rewriting a frozen task list, never dropping a contention
edge), and authoring guidance biasing toward many small parallelizable phases — all by improving the
*input graph* the existing `wave_deliver` planner consumes, not by adding a new scheduler.

Scope traces to brainstorm requirements **R15–R19** (plus cross-cutting **R30–R31**). It depends on no PRD A
code primitive and MAY be delivered in parallel with PRD A Phases 1–2.

## Goals

- Replace author-vibe S/M/L sizing with a **deterministic sizing heuristic** over observable structural
  signals (files touched, traceability scenarios, dependency fan-out, sub-task count, distinct-directory
  fan-out) with documented thresholds and min/max bounds.
- Surface an **advisory split suggestion** for oversized/separable phases proposing smaller units + explicit
  dependency edges — **suggestion only**; frozen task lists are never auto-rewritten and the advisory block
  never persists into a frozen artifact.
- **Maximize achievable wave parallelism** within `worktree.parallelCeiling` by reusing the *same*
  contention primitives `wave_deliver` uses, validated by a dry-run wave preflight — never proposing a split
  that drops a serializing edge or collapses to width-1.
- Make "**small phases**" an explicit, research-referenced design constraint in task authoring guidance,
  bounded by a minimum-viable-phase floor so granularity does not explode merge-gate load.
- Prove the change with **outcome metrics** (phase PR diff size, realized wave width), not only fixture
  determinism.

## Non-Goals

- **No auto-rewrite of frozen task lists** and **no auto-write of `## Phase Dependencies` or `### N.`
  headings** — splitting is advisory, pre-freeze, human-adopted only.
- **No reimplementation of wave planning, scheduling, or `/sw-deliver next` next-action selection** (PRD
  004/033/035); B *imports* contention/wave helpers for simulation and tunes the input graph only.
- **No retrospective inefficiency / parallelizability / timing scanning** (deliver-state, CI timing, test
  duration) — that is **PRD C (R25–R26)**. B operates at `/sw-tasks` authoring time on structural signals.
- **No wall-clock or cost estimation** — sizing uses structural signals, not predicted durations.
- **No triage/blast-radius tier input to the scorer in v1** — tier-aware split weighting is out of scope
  (resolved OQ); high blast-radius work must never be auto-biased toward *more* splits.
- **Explicitly deferred to PRD A (R1–R14):** quality/refactor/TDD gates. **Deferred to PRD C (R20–R29):**
  inefficiency scanning, recurring-failure RCA, meta channel.
- No re-implementation of shipped predecessor items (PRD 004 wave orchestrator, 013 file-set fallback,
  033/035 scheduler).

## Requirements

Carried forward from the brainstorm (stable R-IDs).

- **R15** `/sw-tasks` SHALL apply a **formal sizing heuristic** for phases using deterministic signals
  (files touched, **traceability scenarios** counted from the `## Traceability` rows, dependency fan-out,
  sub-task count, distinct-directory fan-out) with **documented thresholds and min/max bounds**. Scenario
  counting maps a task ref to its integer phase prefix; when `## Traceability` is absent (mid-draft) the
  scorer emits `null` with a notice rather than a false-low score.
- **R16** When a phase exceeds sizing thresholds or contains separable file-sets, the loop SHALL emit a
  **split suggestion** decomposing it into smaller units with explicit dependency edges — **as a suggestion
  only**, never auto-rewriting frozen task lists (parity with `tasks-suggest` *frozen behavior*).
  Separability SHALL be computed as connected components of an **intra-phase contention graph** built with
  the same `wave_deliver` contention primitives (see Technical Requirements), not naive file-set disjointness.
- **R17** Sizing/splitting SHALL aim to **maximize wave parallelism** within `worktree.parallelCeiling`
  while honoring **all** existing contention families (`**File:**`-path overlap, shared migrations, `INDEX`,
  `CHANGELOG`, doc-numbering, generator-output / golden-manifest globs). Every proposed decomposition SHALL
  be validated by a `wave_deliver` **dry-run preflight** and rejected (fail-closed with a notice) if it
  introduces a dependency/contention cycle or collapses to wave width 1.
- **R18** Task authoring guidance SHALL state **small phases as a design constraint** for reviewability and
  parallelism, with rationale referenced from the research, **bounded by a minimum-viable-phase floor**
  (splitting below the floor is not rewarded).
- **R19** The model SHALL **prefer many small phases with declared dependency edges** over few large
  sequential phases. `/sw-tasks` SHALL require an explicit `## Phase Dependencies` table at freeze
  (unchanged spec-rigor behavior); at deliver time the **existing PRD 013 ladder** applies for legacy lists
  that omit it (declared edges → `**File:**`-overlap file-set inference → strict sequential + notice). This
  PRD does not regress that ladder.
- **R30** All new gates/signals SHALL preserve human-owns-merge, human-gated promotion, and no nested
  orchestrator dispatch; automation may propose but never merge or promote. Sizing/split output is advisory,
  never mutates a frozen artifact, and the advisory block is excluded from the frozen artifact at `/sw-freeze`.
- **R31** All new commands/skills SHALL obey `sw-` naming, orchestrator/atomic boundaries, and the
  model-tier floor, and route external/provider context through the redaction chokepoint.

## Technical Requirements

- **Sizing heuristic (`scripts/phase-sizing.sh`).** Deterministic scorer consumed by `/sw-tasks`, parsing
  the draft task list via the shared `doc_format.py` tokenizer. Per phase it emits JSON validated against
  `core/sw-reference/phase-sizing.schema.json`:
  `{ phase, filesTouched, distinctDirs, subTaskCount, traceabilityScenarios|null, depFanOut,
  size: small|medium|large, overThreshold: bool, belowFloor: bool, separableSets: [...] }`. All signals are
  derived structurally (no model judgment). Thresholds + bounds live in config
  (`tasks.sizing.{thresholds,minPhaseFiles,minPhaseScenarios,maxPhaseCount}`) with documented defaults.
- **Declared-scope cross-check (anti-gaming).** Before scoring, the scorer reconciles `**File:**` lines
  against `## Relevant Files` and sub-task prose; when prose implies undeclared paths it emits a
  `scopeUnderDeclared` advisory. Deliver-time reconciliation of declared vs post-phase diff reuses the
  existing `contentionFeedback` channel (parity with `tasks-suggest`), surfaced on the next `/sw-tasks` run.
- **Separability + contention integrity.** `separableSets` are connected components under an intra-phase
  contention graph constructed by importing `wave_deliver.py` helpers
  (`inject_contention_edges` / `paths_contend` + `expand_generator_contention_paths` +
  `contention_serialized_defaults`). A proposed split runs **full pairwise contention simulation** on the
  expanded sub-unit file-sets; any pair that still contends gets a **mandatory serializing edge**, and a
  split whose expanded contention closure differs from the parent phase's is rejected.
- **Parallelism objective (advisory heuristic, not a scheduler).** Phase 3 is a **greedy split scorer**:
  propose hypothetical sub-phases, simulate `deps_to_edges → apply_contention → assign_waves` via the
  imported helpers (and a `wave_deliver` dry-run preflight), score projected wave count/width, and keep the
  decomposition only if it raises independent-phase count without violating contention or
  `worktree.parallelCeiling`. It performs **no** graph-optimality search and does **not** touch the deliver
  mechanism, merge gate, or next-action selection.
- **Advisory block + freeze hygiene.** Suggestions render into a `## Sizing & Split Suggestions` block in
  the **draft** task list (or operator stdout), including a structural cost estimate
  (projected waves × merge gates). `scripts/phase-sizing.sh --check-frozen` is **print-only / fail-closed**
  on `frozen: true`. `/sw-freeze` (and `check-frozen.py` / spec-rigor) SHALL strip or reject a
  `## Sizing & Split Suggestions` block from a frozen artifact; adopting a split requires an unfrozen re-run
  + re-freeze, never an in-place frozen edit.
- **Authoring guidance (R18/R19).** `core/skills/tasks/SKILL.md` + `core/commands/sw-tasks.md` replace
  informal S/M/L with the heuristic `small|medium|large` + a research-referenced small-phase design
  constraint + a minimum-viable-phase floor + prefer-many-small directive. The deliver-time fallback ladder
  is documented authoritatively in `core/skills/deliver/SKILL.md` / `core/commands/sw-deliver.md` (PRD 013
  parity), and split suggestions cite the contention families documented in `core/skills/parallelism/SKILL.md`.
- **Deliver visibility (read-only).** An optional `--sizing-report` on `/sw-deliver next` surfaces the
  sizing JSON for operator visibility only; it SHALL NOT feed scheduling or next-action selection.

### Documentation deliverables

- **Config/schema:** `core/sw-reference/config.schema.json` (+`tasks.sizing.*`), `workflow.config.example.json`,
  `docs/guides/configuration.md`, `core/sw-reference/phase-sizing.schema.json`.
- **Layout:** `core/sw-reference/layout.md` **and** `.sw/layout.md` (advisory block shape + draft-only /
  frozen print-only policy + sizing-JSON registry row).
- **Skills/commands:** `core/skills/tasks/SKILL.md`, `core/commands/sw-tasks.md` (sizing + split + floor +
  small-phase constraint); `core/skills/deliver/SKILL.md`, `core/commands/sw-deliver.md` (`--sizing-report`,
  reconcile the PRD 013 fallback-ladder docs, reframe the contention-feedback deferral to exclude advisory
  print-only sizing); `core/skills/parallelism/SKILL.md` (shared contention-family cross-reference).
- **Freeze hygiene:** `scripts/check-frozen.py` / `core/skills/spec-rigor/SKILL.md` advisory-block strip/flag.

## Security & Compliance

- Sizing/split output is advisory metadata derived from the task list; persisted summaries route through
  `scripts/memory-redact.py` (R31) before write.
- No new network egress; the scorer is a local deterministic script.
- The scorer SHALL NOT mutate frozen artifacts (R30); `--check-frozen` is print-only/fail-closed, and the
  freeze path strips/flags any advisory block so it cannot pollute a frozen artifact's content hash.

## Success Criteria

Determinism + correctness:

- **SC1** On a fixture oversized phase, `scripts/phase-sizing.sh` reports `size: large` / `overThreshold:
  true` deterministically (identical input → byte-identical output).
- **SC2** On a fixture phase with separable sets, the split proposes ≥2 smaller units with edges that
  preserve external dependencies and raise the count of independently schedulable phases — verified by the
  `wave_deliver` dry-run preflight, not assertion alone.
- **SC3** A frozen task list is never modified; `--check-frozen` is print-only; `/sw-freeze` strips/flags a
  stray advisory block.
- **SC4** A legacy list missing `## Phase Dependencies` resolves via the PRD 013 ladder (file-set inference
  → sequential + notice) with no regression to `wave_deliver` behavior.
- **SC5** No suggested split crosses a serializing family (`**File:**` overlap, migrations, INDEX, CHANGELOG,
  doc-numbering, **generator-output/golden-manifest**); fixtures include generator-output separation cases.

Outcome (wired to `benefitMetric` / deliver run-state, measured on a dogfood pilot):

- **SC6** Phase-0 corpus calibration establishes a baseline distribution of phase file-count / scenarios /
  realized wave width across existing frozen task lists; thresholds are set from that baseline.
- **SC7** Post-rollout, median phase PR diff size does not increase and mean realized wave width (vs
  `parallelCeiling`) does not decrease on the pilot — i.e. more granularity does not regress throughput or
  inflate merge-gate cycles.

## Testing Strategy

Fixture-driven. New suite `run-phase-sizing-fixtures.sh`:

- sizing determinism + threshold/floor classification incl. sub-task & distinct-dir signals (R15);
- declared-scope cross-check emits `scopeUnderDeclared` on under-declared `**File:**` (R15 anti-gaming);
- split proposes smaller units with edge preservation; transitive fan-in/fan-out semantics (R16);
- contention integrity — split never drops a serializing family incl. generator-output; mandatory edges
  injected; dry-run preflight rejects cycle / width-1 collapse (R16, R17, SC5);
- parallelism objective raises independent-phase count within ceiling without contention violation (R17);
- over-split DoS bound — `maxPhaseCount` / min-floor enforced; cost estimate emitted (R18);
- frozen print-only + freeze strips advisory block (R16, R30);
- missing `## Phase Dependencies` → PRD 013 ladder (no regression) (R19, SC4);
- authoring-guidance conformance snapshot for the small-phase design-constraint docs (R18).

Each requirement **R15–R19** maps to a named fixture scenario; **R30** (no frozen mutation / advisory strip)
and **R31** (redaction of persisted summaries) carry explicit invariant fixtures.

## Rollout Plan

0. **Phase 0 — Corpus calibration (read-only).** Audit existing frozen task lists for phase
   file-count/scenario/wave-width distributions; set `tasks.sizing.*` defaults from the baseline (SC6).
   Gates Phase 1 (no thresholds shipped without calibration).
1. **Phase 1 — Sizing scorer + schema.** `scripts/phase-sizing.sh` + `phase-sizing.schema.json` + config +
   declared-scope cross-check (R15). Read-only; emits report, no task-list change.
2. **Phase 2 — Split suggestion (advisory) + contention integrity.** Decomposition emitter using imported
   `wave_deliver` contention primitives + full pairwise simulation; `## Sizing & Split Suggestions` draft
   block; frozen print-only + freeze strip (R16, R30).
3. **Phase 3 — Parallelism objective + preflight validation.** Greedy split scorer with `wave_deliver`
   dry-run preflight; cycle/width-1 fail-closed; `maxPhaseCount`/floor; `--sizing-report` deliver visibility
   (R17, R18).
4. **Phase 4 — Authoring guidance + fallback-ladder reconciliation.** Small-phase design-constraint docs,
   prefer-many-small directive, PRD 013 ladder doc alignment across tasks/deliver/parallelism skills (R18, R19).

Backward compatible: with sizing unconfigured the scorer reports defaults and changes no task-list content;
`/sw-deliver` wave behavior and the PRD 013 fallback ladder are unchanged.

## Decision Log

- **2026-06-30** Sizing is **deterministic over structural signals** (files, traceability scenarios, dep
  fan-out, sub-task count, distinct-dir fan-out), not model judgment or predicted duration.
- **2026-06-30** Splitting is **advisory, pre-freeze only**, and the advisory block is **excluded from the
  frozen artifact** (stripped/flagged at `/sw-freeze`) — preserving freeze immutability (R30).
- **2026-06-30 (doc-review synthesis)** Separability + split validation **reuse `wave_deliver` contention
  primitives** (incl. generator-output/golden-manifest expansion) and a dry-run preflight — closes the P0
  risk of splits dropping serializing edges and causing parallel-wave corruption.
- **2026-06-30 (doc-review synthesis)** The parallelism objective is a **greedy advisory split scorer that
  simulates** via imported helpers, **not** a new scheduler or graph-optimizer — avoids duplicating PRD
  004/033/035 scope; deliver mechanism untouched.
- **2026-06-30 (doc-review synthesis)** R19/SC4 **aligned to the shipped PRD 013 fallback ladder**
  (declared → file-set inference → sequential+notice); `/sw-tasks` still requires the table at freeze.
- **2026-06-30 (doc-review synthesis)** Added a **minimum-viable-phase floor + `maxPhaseCount`** and a cost
  estimate to prevent a granularity DoS (many tiny phases inflating merge-gate load).
- **2026-06-30 (doc-review synthesis)** Added **outcome SCs (SC6/SC7)** + a Phase-0 corpus calibration gate
  so B proves it shrank PRs / preserved wave width, not just fixture determinism (product P0).
- **2026-06-30 (resolved OQ)** Triage/blast-radius tier is **out of scope for the v1 scorer**; high
  blast-radius work must never be auto-biased toward more splits.

## Open Questions

1. **Sizing thresholds (R15):** exact file-count / scenario / fan-out / sub-task cut-points and the
   minimum-viable-phase floor — set from the Phase-0 corpus calibration (SC6) before Phase 1 freeze.
