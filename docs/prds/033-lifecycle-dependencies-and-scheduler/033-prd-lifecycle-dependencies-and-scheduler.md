---
date: 2026-06-27
topic: planning-feedback-lifecycle
brainstorm: docs/brainstorms/2026-06-27-planning-feedback-lifecycle-requirements.md
depends: [031, 032]
frozen: true
frozen_at: 2026-06-27
---

# PRD 033 — Lifecycle State Machine, Dependency Graph & Scheduler

## Overview

Build the behavioral layer on top of the PRD 031 model and PRD 032 in-flight signal: a full unit
**lifecycle state machine**, a **dependency DAG** with cycle detection, a **priority-ranked scheduler**
that fails closed on unmet prerequisites, mechanical **supersession/absorption** edge effects, and a
deterministic **maintenance reconciler** that regenerates the INDEX (with active/archived views) and
reconciles derived status with no prompts. This is what makes the graph reflect true status and lets
`/sw-deliver` pick and order work correctly.

`depends:` on PRD 031 (unit schema, path helper, INDEX generator seam, type-conditioned status) and PRD
032 (the committed `inFlight` INDEX region the reconciler reads to derive `in-progress`). Derived from
frozen brainstorm requirements R2, R17–R26, R39, R44–R45, and R48 (scheduler portion); resolves brainstorm
OQ7 (archive view format). Lifecycle automation here is the answer to the user's prerequisite-ordering,
supersession-tracking, priority-enforcement, and index-maintenance concerns.

**Atomic cutover + substrate-first (PRD 031 D11/R27, refined by doc-review).** The 031 substrate (schema,
path helper, INDEX generator + dual-region seam, lifecycle stub enum, tokenizer Phase A) lands and passes
fixtures **as prerequisites first**; 033 then ships in the **one-commit cutover with 031 (Phase B) and
032**. 033 owns the cutover compatibility surface: it **generates the legacy `docs/prds/GAP-BACKLOG.md` +
`INDEX.md` projections** from the planning/gap units so `wave_living_docs`, `reconcile-status`, and
`feedback-backlog` keep working until those consumers are migrated, and it provides the **relief acceptance
check** (post-reconcile `derived` status matches deliver state) and the **reconciler-accuracy floor** that
PRD 031's kill-criteria (031 R28) gate the cutover on. See R14/R20/R20a.

## Goals

- Define the complete unit lifecycle (working plus branch/terminal states) and which transitions are
  mechanical vs human-gated, single-sourcing the lifecycle enum that PRD 031 R4 references.
- Make `depends:`/`blocks:` a validated DAG, compute `blocked` from unmet edges, and resolve
  depends-on-terminal-unit safely.
- Give `/sw-deliver` a hard dependency gate, a graph-driven `next` selector, and soft priority enforcement
  on explicit task-list starts.
- Make `supersedes:`/`absorbs:` edges drive lifecycle flips mechanically (subsuming the cancelled-028 gap
  `planned`-prefix flip), including the `partially resolved` transition.
- Ship a deterministic maintenance reconciler that regenerates the INDEX with separate active and archived
  views and is the sole writer of the `derived` INDEX region — never reading or writing the deliver-owned
  `inFlight` region except as a read-only input.

## Non-Goals

- The unit schema, migration, tokenizer, INDEX generator seam, and type-conditioned status enum definition
  (PRD 031).
- The in-flight signal *writer* and the mutation-safety guards (PRD 032). The reconciler only **reads**
  `inFlight`; **stale-marker repair and clearing are PRD 032's deliver writer** — the reconciler never
  writes `inFlight` and never invents `in-progress` without deliver evidence.
- Visibility/privacy, the `planning.store`, and private-unit materialization (PRD 034).
- Backlog pull-in proposals, autonomy posture, full-conductor, and two-track edits (PRD 035). The
  `planning.autonomy` config key is **owned by PRD 035**; 033 only reads it (R8) and treats an absent key as
  `maintenance-only`.
- Any change to the wave/conductor execution engine or the human merge-to-`main` gate.

## Requirements

- **R1** The lifecycle enum is single-sourced here and referenced by PRD 031 R4's type-conditioned
  validation: non-gap units use `proposed → planned(frozen) → in-progress → complete` plus branch/terminal
  `superseded`, `cancelled`, `deferred`, `blocked`; gap units use the gap enum (`open`, `planned`,
  `partially resolved`, `resolved`). The shared enum module rejects unknown tokens and documents the
  per-type meaning of the `planned` homonym. (031 ships a values-only stub of this module; 033 replaces it
  with transitions — same module, no drift.)
- **R2** `in-progress` and `complete` are derived mechanically: `in-progress` is derived from the PRD 032
  committed `inFlight` region plus git, and `complete` from deliver/merge state; `proposed → planned` is the
  freeze gate; `superseded`/`cancelled`/`deferred` are human-gated authoring transitions recorded as edges.
- **R3** `blocked` is computed from unmet `depends:` edges and is never hand-set; a unit with all
  dependencies satisfied is automatically eligible.
- **R4** `depends:`/`blocks:` edges form a DAG over units; validation performs cycle detection and fails
  closed with the offending cycle path. A **pre-commit whole-graph cycle check** runs over all staged unit
  frontmatter so a cycle introduced across two files in one commit cannot land (closes the adversarial
  split-commit cycle scenario).
- **R5** A `depends:` edge whose target is `superseded`/`cancelled` is flagged `dependency-dead` by the
  reconciler (with a doctor warning suggesting edge retraction or repoint) rather than leaving the dependent
  unit permanently `blocked` with no path forward; the PRD 035 pull-in scanner may auto-*propose* the edge
  retraction (human-confirmed).
- **R6** Each unit carries a `priority:` ranking; the INDEX and scheduler order eligible units by priority
  then dependency topological order, deterministically (stable tie-break on unit id).
- **R7** `/sw-deliver` hard-gates on unmet `depends:` prerequisites — it fails closed with the blocking unit
  ids and a `--override` escape hatch (which requires `--override-reason` and is logged; repeated overrides
  surface in `/sw-status` as drift), mirroring the existing `--from` prerequisite halt lifted to unit level.
- **R8** A `/sw-deliver next` selects the next eligible highest-priority unit from the graph. When an
  explicit `--task-list` is supplied and a higher-priority eligible unit exists, delivery emits a **confirm
  prompt** (soft-enforcement) before proceeding — not a silent warning; the dependency gate (R7) still
  hard-applies. The confirm behavior is gated on the `planning.autonomy` config key **owned by PRD 035 R17**;
  **033 stubs the key in the config schema with default `maintenance-only` and treats an absent key as
  `maintenance-only`**, so the behavior is fully defined at the atomic cutover even though 035 ships later.
- **R9** Both `/sw-deliver next` auto-pick and an explicit `--task-list` start **re-validate eligibility and
  the dependency gate against current derived status at run-start** (not only at selection time), refusing if
  the unit became `superseded`/`cancelled` since selection (closes the adversarial select-then-supersede
  race).
- **R10** `supersedes: [id]` flips the superseded unit's status to `superseded` and records the relation in a
  generated SUPERSEDED manifest; `extends: [id]` records additive lineage without superseding.
- **R11** `absorbs: [id]` edges drive the absorbed gap unit's lifecycle mechanically: `open → planned` when
  the absorbing unit freezes, `→ partially resolved` when the absorbing unit is `in-progress` with the gap
  not yet fully addressed, and `→ resolved` when it completes (subsuming the cancelled-028 mechanics
  including the `planned`-prefix flip); this gives `partially resolved` (brainstorm R26) an explicit
  transition rule.
- **R12** The scheduler and INDEX exclude `superseded`/`cancelled`/`deferred` units from eligible work while
  still rendering them in the archived view.
- **R13** A deterministic maintenance reconciler regenerates the INDEX and reconciles lifecycle flips,
  supersession/absorption edges, gap status, dependency-graph integrity, and counts with no prompts; it is
  idempotent, fails closed, and is serialized through the living-doc single-writer lock. It is the **sole
  writer of the `derived` INDEX region** and reads (never writes) the deliver-owned `inFlight` region. It
  uses read-merge-write (PRD 031 R9/R24) and **re-reads the `inFlight` region immediately before serializing**
  so a concurrent run-start write is never clobbered (closes the adversarial read-merge-write TOCTOU); it
  never clears a live in-flight tuple (clearing is 032's writer).
- **R14** The INDEX is generated with distinct active and archived views; `complete`/`superseded`/`cancelled`
  units collapse into a **separate generated archive file**, with the **terminal-state set** as the collapse
  threshold (`deferred`/`blocked` stay in the active view because still actionable) — resolving brainstorm
  OQ7.
- **R15** The GAP-BACKLOG table is fully replaced by gap rows in the generated unified INDEX (folder-per-item
  from PRD 031), eliminating the hand-maintained table; gap status flips are driven by absorption edges
  (R11), not manual edits. **Cutover compatibility:** during the atomic-train window the reconciler also
  **generates read-only legacy `docs/prds/GAP-BACKLOG.md` + `INDEX.md` projections** from the planning/gap
  units (frontmatter-only — a fixture proves no body bytes appear in projections), regenerated each
  reconcile. To avoid dual-truth (adversarial), `/sw-feedback` gap-capture writes **canonical gap units**
  during the window (the legacy file is a read-only echo; a doctor warning fires on any manual legacy-path
  edit). The projections are removed once `wave_living_docs`/`reconcile-status`/`feedback-backlog` resolve via
  `planningDir`.
- **R16** The reconciler is the sole writer of derived INDEX status; the `gap-resolve`/living-status drift
  class (stale `planned`/`open` rows, GAP-043/044/046) is structurally eliminated because no derived status
  is hand-maintained.
- **R17** Interim behavior until PRD 035 two-track edits land: the reconciler serializes through the
  living-doc lock and commits locally / via the existing docs path, but does **not** auto-open PRs; this
  avoids reintroducing per-change docs-on-a-branch friction mid-program before the two-track driver exists.
- **R18** No regression to the documentation that feeds the delivery loop: frozen immutability,
  traceability, and spec-rigor gates are preserved; the human merge-to-`main` gate is unchanged;
  foundational frozen workflow invariants are retained.

## Technical Requirements

- **R19** A graph module computes the DAG, cycle detection (including the pre-commit whole-graph check),
  `blocked` derivation, dependency-dead detection, and the priority + topological ordering; it is
  pure/deterministic and unit-tested with fixtures.
- **R20** `wave_deliver`/`/sw-deliver` gain a dependency-gate preflight (fail closed + `--override`
  `--override-reason`), a `next` subcommand, the run-start eligibility re-validation (R9), and the
  soft-enforce confirm path reading the stubbed `planning.autonomy` key; all resolve paths via the PRD 031
  path helper.
- **R21** The maintenance reconciler is a script (`scripts/planning-graph.sh reconcile` or equivalent) wired
  into the living-doc single-writer lock; it regenerates INDEX active/archived views and the SUPERSEDED
  manifest from frontmatter + deliver/git state + the `inFlight` region (read-only, re-read before
  serialize), emits the frontmatter-only legacy GAP-BACKLOG/INDEX projections (R15), and uses the INDEX
  read-merge-write contract (PRD 031 R9/R24) so it never clobbers the `inFlight` region.
- **R22** The reconciler exposes a **relief acceptance check** (post-reconcile `derived` status matches
  deliver/git state across the corpus) and a **reconciler-accuracy metric** on the fixture corpus; both are
  emitted as machine-readable verdicts that PRD 031's cutover gate (031 R28) consumes — the cutover proceeds
  only when the relief check passes, and the accuracy metric falling below the documented floor trips the
  031 kill-criteria fallback to shim + legacy layout. The fixture corpus **must include** inFlight/derived
  conflict cases, the legacy-projection consumers, and cross-worktree in-flight tuples (adversarial relief
  false-negative), so a reconciler that passes the gate but mis-derives in production is caught.
- **R23** The single-sourced lifecycle/state enum module (R1) is the same module PRD 031's validator imports
  for type-conditioned status, so schema and behavior cannot drift.
- **R24** Reconciler and scheduler artifacts land in `core/` and propagate to both dist trees;
  `copy-to-core` parity and emitter-freshness fixtures cover the new scripts and the stubbed
  `planning.autonomy` schema key.
- **R25** This PRD updates the operator-facing docs it changes, as **acceptance criteria**:
  `core/skills/living-status/SKILL.md` (replace GAP-BACKLOG/gap-resolve/3-state INDEX with unit lifecycle,
  reconciler, active/archive INDEX, in-flight column), `core/commands/sw-deliver.md` (`next`, dependency
  gate, run-start re-validation, soft-enforce), `core/commands/sw-status.md` (gap-unit index echo, override
  drift), `docs/guides/workflows.md` (**033-owned sections only**: lifecycle state machine, dependency gate,
  `/sw-deliver next`, reconciler-driven INDEX active/archive, GAP-BACKLOG retirement + legacy-projection
  window — the two-track edit sections remain PRD 035-owned), and `docs/guides/getting-started.md` (living-doc
  currency bullet from hand-maintained GAP-BACKLOG to generated gap index + reconciler).

## Security & Compliance

- **R26** The reconciler and scheduler operate on tracked documentation/state only; they never read private
  bodies (visibility is PRD 034) and the legacy projections are **frontmatter-only** (R15 fixture) so no
  private body content can reach a tracked legacy artifact during the cutover window; they never move code,
  secrets, or config.
- **R27** All graph/reconciler logic is deterministic and offline (no network; same input yields same
  output) so CI gates remain reproducible.
- **R28** `--override` of the dependency gate is explicit, requires a reason, is logged to durable state
  (who/when/which edges/why), is rate-surfaced in `/sw-status`, and is never the default.

## Testing Strategy

- Enum/lifecycle fixtures (R1–R2): type-conditioned tokens validate; `in-progress` derives from the 032
  `inFlight` region + git; reconciler never invents `in-progress` without deliver evidence.
- DAG fixtures (R3–R5, R19): valid DAG accepted; cycle rejected with the cycle path; a split-commit cycle is
  rejected at pre-commit; `blocked` matches unmet edges; a depends-on-terminal target is flagged
  `dependency-dead`, not permanently blocked.
- Scheduler fixtures (R6–R9): `next` selects by priority then topo order with stable tie-break; the
  dependency gate fails closed and `--override`/`--override-reason` bypasses + logs; explicit `--task-list`
  with a higher-priority eligible unit triggers a confirm prompt under the stubbed default; a unit that
  became superseded between selection and run-start is refused.
- Supersession/absorption fixtures (R10–R11): `supersedes` flips status + manifest; `absorbs` drives
  `open → planned → partially resolved → resolved` across freeze/in-progress/complete.
- Reconciler/dual-writer fixtures (R13–R17, R21): idempotent regeneration; active/archived split; gap-index
  generation; **three-party concurrency** (reconcile + run-start + run-complete) preserves `inFlight` bytes
  with a re-read-before-serialize assertion; projections are frontmatter-only; `/sw-feedback` writes canonical
  gap units in the window; reconciler does not auto-open PRs; stale-`planned` drift reconciles automatically.
- Relief/kill-criteria fixtures (R22): the relief corpus includes inFlight/derived conflict, legacy-append,
  and cross-worktree tuples; the cutover gate fails if any consumer diverges.
- Doc-currency fixtures (R25) and emitter/parity fixtures (R24).
- No-regression run (R18).

## Rollout Plan

1. **Graph + enum substrate (prerequisite phase):** land the shared lifecycle/state enum module (consumed by
   031's validator), the graph module, cycle + dependency-dead detection + pre-commit whole-graph check,
   behind fixtures.
2. **Reconciler:** land the maintenance reconciler (INDEX active/archived + SUPERSEDED manifest + gap index +
   frontmatter-only legacy projections, reading the 032 `inFlight` region with re-read-before-serialize)
   wired to the single-writer lock, replacing hand-maintained derived status; no auto-PR (R17).
3. **Scheduler + gate:** add the `/sw-deliver` dependency gate, `/sw-deliver next`, run-start re-validation,
   and the soft-enforce confirm path reading the stubbed `planning.autonomy` key.
4. **Cutover (one commit with 031 Phase B + 032):** flip living-status/INDEX maintenance to the reconciler,
   retire the GAP-BACKLOG table for the generated gap index (legacy projections active during the window),
   run the relief acceptance check; update `living-status`/`sw-deliver`/`sw-status`/workflows/getting-started
   docs.

## Decision Log

- **D1** The lifecycle enum is single-sourced here and imported by 031's validator (resolves the coherence
  panel's status-enum collision) — schema and behavior share one module, type-conditioned by unit type; 031
  carries a values-only stub until this PRD lands in the same train.
- **D2** Lifecycle splits mechanical derivation (`in-progress`/`complete`/`blocked`) from human-gated
  authoring transitions (`superseded`/`cancelled`/`deferred`) — autonomy without surrendering spec-quality
  judgement (brainstorm K5).
- **D3** Dependency is a hard gate; priority is enforced when delivery auto-picks (`next`) and
  **soft-enforced (confirm prompt)** on explicit `--task-list` (doc-review priority decision) — prevents
  silent priority inversion while preserving deliberate override.
- **D4** Supersession/absorption are edge-driven status effects, not manual flips, with an explicit
  `partially resolved` transition — eliminates the stale-row drift class (GAP-043/044/046) at the mechanism
  level and gives brainstorm R26's fourth state a rule.
- **D5** The reconciler is the single writer of the `derived` INDEX region and **read-only** on the
  deliver-owned `inFlight` region; stale-marker repair/clearing is PRD 032's deliver writer, not the
  reconciler (resolves the coherence/scope/adversarial dual-ownership finding); reconcile re-reads inFlight
  before serialize.
- **D6** Resolves brainstorm OQ7 (archive view format): archived units render in a **separate generated
  archive file**, threshold = terminal states (`complete`/`superseded`/`cancelled`); `deferred`/`blocked`
  stay active because actionable.
- **D7** `/sw-deliver next` is the graph-driven scheduler entry; the reconciler is `scripts/planning-graph.sh`
  (command-surface naming finalized in PRD 035, which owns brainstorm OQ1).
- **D8** The reconciler does not auto-open PRs until PRD 035's two-track driver lands (R17) — avoids
  reintroducing per-change doc friction in the mid-program window.
- **D9** Depends-on-terminal targets are flagged `dependency-dead` (R5) rather than leaving a permanent
  `blocked` dead-end — closes the adversarial panel's never-unblocks scenario.
- **D10** 033 ships in the **one-commit cutover with 031 (Phase B) + 032** after the 031 substrate/Phase-A
  prerequisites validate (doc-review substrate-first decision) and owns the cutover compatibility surface —
  the frontmatter-only legacy projections (R15/R21), the relief acceptance check, and the reconciler-accuracy
  floor (R22) that PRD 031's kill-criteria (031 R28) gate on.
- **D11** `planning.autonomy` is **owned by PRD 035 R17** but **stubbed in the config schema (default
  `maintenance-only`)** by this train so R8's soft-enforce behavior is fully defined at cutover even though
  035 ships later (resolves the coherence/scope/feasibility forward-reference finding).
- **D12** `next`/explicit-start **re-validate eligibility at run-start** (R9), not only at selection — closes
  the adversarial select-then-supersede race; the relief corpus (R22) is expanded to adversarial cases so the
  031 kill-criteria cannot pass on an under-specified corpus.
