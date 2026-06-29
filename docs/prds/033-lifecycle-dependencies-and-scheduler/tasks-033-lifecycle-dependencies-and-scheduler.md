---
date: 2026-06-27
topic: planning-feedback-lifecycle
prd: docs/prds/033-lifecycle-dependencies-and-scheduler/033-prd-lifecycle-dependencies-and-scheduler.md
amendments:
  - docs/prds/033-lifecycle-dependencies-and-scheduler/amendments/A1-post-merge-index-reconcile-safety.md
  - docs/prds/033-lifecycle-dependencies-and-scheduler/amendments/A2-decision-id-union-exclusion.md
frozen: true
frozen_at: 2026-06-29
---

# Tasks — PRD 033 Lifecycle state machine, dependency graph & scheduler

Generated from the frozen PRD spec union **R1–R36** (parent R1–R28 + amendment A1 R29–R36; A1 is purely
additive — no parent requirement superseded or retracted). Eight dependency-ordered phases mirror
the PRD rollout: a single-sourced lifecycle/state enum + pure graph module land first as the substrate
(Phase 1); the deterministic maintenance reconciler — sole writer of the `derived` INDEX region, read-only on
the PRD 032 `inFlight` region with re-read-before-serialize — builds on it (Phase 2); the `/sw-deliver`
scheduler, hard dependency gate, `next`, run-start re-validation, and soft-enforce confirm follow (Phase 3);
supersession/absorption edge effects mechanize the lifecycle flips (Phase 4); the one-commit cutover (with
PRD 031 Phase B + PRD 032) retires the hand-maintained GAP-BACKLOG and runs the relief acceptance check
(Phase 5); emitter/dist parity covers the new scripts and the stubbed `planning.autonomy` schema key
(Phase 6); the 033-owned operator docs are updated as acceptance criteria (Phase 7); and amendment A1 hardens
the reconciler and deliver-writer contracts for post-merge safety — git-ancestry-primary and monotonic
terminal derived status, default-branch reconcile refusal, and a finalize-only `merged-complete` completion
chokepoint (Phase 8). Phase Dependencies
are intra-PRD only; the cross-PRD atomic-train ordering (031 substrate first, then 031 Phase B + 032 + 033 in
one commit) is owned by the program rollout, not these edges. Every phase ships behind passing fixtures
registered in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.

> Refreshed 2026-06-29 to apply amendment A1 (R29–R36, post-merge INDEX reconcile safety + completion-finalize
> chokepoint; absorbs GAP-053 and GAP-055). Phase 8 and the R29–R36 traceability rows are the only additions;
> parent phases 1–7 (R1–R28) are unchanged.

## Tasks

### 1. Lifecycle enum + pure graph module (substrate) — L

- [ ] 1.1 Single-sourced lifecycle/state enum module (R1)
  - **File:** `core/scripts/planning_lifecycle.py`
  - **Expected:** replaces PRD 031's values-only stub (same module path, no drift) with the full
    type-conditioned enum — non-gap `proposed -> planned(frozen) -> in-progress -> complete` plus terminal/branch
    `superseded`/`cancelled`/`deferred`/`blocked`, and gap `open`/`planned`/`partially resolved`/`resolved`;
    rejects unknown tokens closed-world and documents the per-type meaning of the `planned` homonym. Fixture:
    `enum-type-conditioned-tokens`.
  - **R-IDs:** R1
- [ ] 1.2 Mechanical-vs-human-gated transition classification (R2)
  - **File:** `core/scripts/planning_lifecycle.py`
  - **Expected:** classifies transitions — `in-progress`/`complete`/`blocked` mechanical (derived from the
    PRD 032 `inFlight` region + git + deliver/merge state), `proposed -> planned` as the freeze gate, and
    `superseded`/`cancelled`/`deferred` as human-gated authoring edges; the table is data, not behavior, so the
    reconciler never invents `in-progress` without deliver evidence. Fixture: `derived-status-from-inflight`.
  - **R-IDs:** R2
- [ ] 1.3 DAG build + cycle detection + pre-commit whole-graph check (R4)
  - **File:** `core/scripts/planning_graph.py`, `core/hooks/pre-commit`, `core/scripts/install-hooks.sh`
  - **Expected:** `depends:`/`blocks:` frontmatter forms a DAG; validation fails closed with the offending
    cycle path; a pre-commit `planning-graph cycle-check --staged` runs the whole staged-frontmatter graph so a
    cycle split across two files in one commit cannot land. Fixture: `whole-graph-cycle-precommit-reject`.
  - **R-IDs:** R4
- [ ] 1.4 `blocked` derivation + eligibility (R3)
  - **File:** `core/scripts/planning_graph.py`
  - **Expected:** `blocked` is computed solely from unmet `depends:` edges (never hand-set); a unit with all
    dependencies satisfied is automatically eligible. Fixture: `blocked-matches-unmet-edges`.
  - **R-IDs:** R3
- [ ] 1.5 Priority + topological ordering (R6)
  - **File:** `core/scripts/planning_graph.py`
  - **Expected:** orders eligible units by `priority:` then dependency topological order, deterministically,
    with a stable tie-break on unit id; the same ordering feeds the INDEX and the scheduler. Fixture:
    `priority-topo-stable-tiebreak`.
  - **R-IDs:** R6
- [ ] 1.6 Graph module determinism + offline reproducibility + fixtures (R19, R27)
  - **File:** `core/scripts/planning_graph.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** the graph module (DAG, cycle detection, `blocked` derivation, dependency-dead detection,
    priority+topo ordering) is pure/deterministic, offline (no network), and unit-tested with fixtures — same
    input yields the same output so CI gates stay reproducible. Fixtures: `graph-module-deterministic`,
    `graph-offline-reproducible`.
  - **R-IDs:** R19, R27
- [ ] 1.7 Shared-module import contract with PRD 031 validator (R23)
  - **File:** `core/scripts/planning_lifecycle.py`
  - **Expected:** the same enum module is the one PRD 031's type-conditioned-status validator imports, so
    schema and behavior cannot drift; a fixture asserts the validator and the reconciler resolve identical
    token sets from one source. Fixture: `enum-shared-module-no-drift`.
  - **R-IDs:** R23

### 2. Deterministic maintenance reconciler — L

- [ ] 2.1 Reconciler core: sole derived-region writer, read-only `inFlight`, re-read before serialize (R13)
  - **File:** `core/scripts/planning-graph.sh`, `core/scripts/planning_graph.py`, `core/scripts/wave_living_doc_lock.py`
  - **Expected:** `planning-graph.sh reconcile` regenerates INDEX + reconciles flips idempotently with no
    prompts, fails closed, serializes through the living-doc single-writer lock, is the sole writer of the
    `derived` INDEX region, reads (never writes) the deliver-owned `inFlight` region, uses read-merge-write
    (PRD 031 R9/R24), and **re-reads `inFlight` immediately before serializing** so a concurrent run-start
    write is never clobbered and a live in-flight tuple is never cleared. Fixture:
    `reconcile-reread-before-serialize` (three-party reconcile + run-start + run-complete concurrency).
  - **R-IDs:** R13
- [ ] 2.2 INDEX active/archive views + separate archive file (R14)
  - **File:** `core/scripts/planning_graph.py`, `docs/prds/INDEX.md`, `docs/prds/INDEX-archive.md`
  - **Expected:** the INDEX is generated with distinct active and archived views; terminal-state units
    (`complete`/`superseded`/`cancelled`) collapse into a separate generated archive file while
    `deferred`/`blocked` stay in the active view because still actionable (resolves brainstorm OQ7). Fixture:
    `index-active-archive-split`.
  - **R-IDs:** R14
- [ ] 2.3 Reconciler script regeneration contract + SUPERSEDED manifest + legacy projections wiring (R21)
  - **File:** `core/scripts/planning-graph.sh`, `core/scripts/planning_graph.py`
  - **Expected:** the reconciler script regenerates the INDEX active/archived views and the SUPERSEDED
    manifest from frontmatter + deliver/git state + the `inFlight` region (read-only, re-read before
    serialize), emits the frontmatter-only legacy GAP-BACKLOG/INDEX projections, and uses the INDEX
    read-merge-write contract so it never clobbers the `inFlight` region. Fixture: `reconcile-idempotent-regen`.
  - **R-IDs:** R21
- [ ] 2.4 Dependency-dead flagging + doctor warning (R5)
  - **File:** `core/scripts/planning_graph.py`, `core/scripts/host-doctor.sh`
  - **Expected:** a `depends:` edge whose target is `superseded`/`cancelled` is flagged `dependency-dead` (with
    a doctor warning suggesting edge retraction or repoint) instead of leaving the dependent permanently
    `blocked`; the warning notes PRD 035's pull-in scanner may auto-*propose* the retraction (human-confirmed).
    Fixture: `dependency-dead-flagged-not-blocked`.
  - **R-IDs:** R5
- [ ] 2.5 Sole-writer derived status drift elimination (R16)
  - **File:** `core/scripts/planning_graph.py`, `core/scripts/reconcile-status.sh`
  - **Expected:** because the reconciler is the sole writer of derived INDEX status and no derived status is
    hand-maintained, the `gap-resolve`/living-status drift class (stale `planned`/`open` rows, GAP-043/044/046)
    is structurally eliminated and reconciles automatically. Fixture: `stale-planned-drift-reconciled`.
  - **R-IDs:** R16
- [ ] 2.6 Interim no-auto-PR commit posture (R17)
  - **File:** `core/scripts/planning-graph.sh`, `core/scripts/docs_pr.sh`
  - **Expected:** until PRD 035's two-track driver lands, the reconciler serializes through the living-doc lock
    and commits locally / via the existing docs path but does **not** auto-open PRs, avoiding per-change
    docs-on-a-branch friction mid-program. Fixture: `reconciler-no-auto-pr`.
  - **R-IDs:** R17
- [ ] 2.7 Relief acceptance check + reconciler-accuracy metric (R22)
  - **File:** `core/scripts/planning-graph.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** the reconciler emits a machine-readable **relief acceptance check** (post-reconcile `derived`
    status matches deliver/git state across the corpus) and a **reconciler-accuracy metric** that PRD 031's
    cutover gate (031 R28) consumes — cutover proceeds only when relief passes; accuracy below the documented
    floor trips the 031 kill-criteria fallback. The fixture corpus includes inFlight/derived conflict cases,
    legacy-projection consumers, and cross-worktree in-flight tuples. Fixture: `relief-corpus-adversarial`.
  - **R-IDs:** R22
- [ ] 2.8 Reconciler/scheduler tracked-only, frontmatter-only safety (R26)
  - **File:** `core/scripts/planning_graph.py`, `core/scripts/planning-graph.sh`
  - **Expected:** the reconciler and scheduler operate on tracked documentation/state only, never read private
    bodies (visibility is PRD 034), emit frontmatter-only legacy projections so no private body content reaches
    a tracked legacy artifact during the cutover window, and never move code, secrets, or config. Fixture:
    `reconciler-no-private-bodies`.
  - **R-IDs:** R26

### 3. Scheduler + `/sw-deliver` dependency gate — M

- [ ] 3.1 Dependency hard-gate preflight + `--override` (R7)
  - **File:** `core/scripts/wave_deliver.py`, `core/scripts/pilot_dependency_gate.py`
  - **Expected:** `/sw-deliver` hard-gates on unmet `depends:` prerequisites, failing closed with the blocking
    unit ids and a `--override` escape hatch (requires `--override-reason`), lifting the existing `--from`
    prerequisite halt to unit level. Fixture: `dependency-gate-fail-closed`.
  - **R-IDs:** R7
- [ ] 3.2 `/sw-deliver next` + soft-enforce confirm reading stubbed `planning.autonomy` (R8)
  - **File:** `core/scripts/wave_deliver.py`, `core/sw-reference/config.schema.json`, `.sw/config.schema.json`
  - **Expected:** `/sw-deliver next` selects the next eligible highest-priority unit; an explicit `--task-list`
    with a higher-priority eligible unit emits a **confirm prompt** (not a silent warning) gated on the
    `planning.autonomy` key, which this PRD **stubs in the config schema with default `maintenance-only`** and
    treats an absent key as `maintenance-only`; the R7 gate still hard-applies. Fixture:
    `soft-enforce-confirm-stubbed-default`.
  - **R-IDs:** R8
- [ ] 3.3 Run-start eligibility re-validation (R9)
  - **File:** `core/scripts/wave_deliver.py`
  - **Expected:** both `next` auto-pick and an explicit `--task-list` start re-validate eligibility and the
    dependency gate against current derived status **at run-start** (not only at selection), refusing if the
    unit became `superseded`/`cancelled` since selection (closes the select-then-supersede race). Fixture:
    `run-start-revalidate-supersede-refuse`.
  - **R-IDs:** R9
- [ ] 3.4 Deliver integration umbrella + path-helper resolution (R20)
  - **File:** `core/scripts/wave_deliver.py`, `core/scripts/planning_paths.py`
  - **Expected:** `wave_deliver`/`/sw-deliver` gain the dependency-gate preflight, the `next` subcommand, the
    run-start re-validation, and the soft-enforce confirm path reading the stubbed `planning.autonomy` key, with
    all unit/INDEX paths resolved through the PRD 031 path helper. Fixture: `deliver-dependency-preflight`.
  - **R-IDs:** R20
- [ ] 3.5 Override durable logging + drift surfacing (R28)
  - **File:** `core/scripts/wave_deliver.py`, `core/scripts/shipwright-state.sh`, `core/commands/sw-status.md`
  - **Expected:** a dependency-gate `--override` is explicit, requires a reason, is logged to durable state
    (who/when/which edges/why), is rate-surfaced in `/sw-status` as drift, and is never the default. Fixture:
    `override-logged-rate-surfaced`.
  - **R-IDs:** R28

### 4. Supersession / absorption edge effects — M

- [ ] 4.1 `supersedes`/`extends` edge effects + SUPERSEDED manifest (R10)
  - **File:** `core/scripts/planning_graph.py`, `docs/prds/SUPERSEDED.md`
  - **Expected:** `supersedes: [id]` flips the target's status to `superseded` and records the relation in the
    generated SUPERSEDED manifest; `extends: [id]` records additive lineage without superseding. Fixture:
    `supersedes-flip-manifest`.
  - **R-IDs:** R10
- [ ] 4.2 `absorbs` gap-lifecycle progression (R11)
  - **File:** `core/scripts/planning_graph.py`, `core/scripts/planning_lifecycle.py`
  - **Expected:** `absorbs: [id]` drives the absorbed gap unit mechanically — `open -> planned` when the
    absorbing unit freezes, `-> partially resolved` when it is `in-progress` with the gap not yet fully
    addressed, and `-> resolved` when it completes (subsuming the cancelled-028 `planned`-prefix flip), giving
    brainstorm R26's `partially resolved` an explicit rule. Fixture: `absorbs-lifecycle-progression`.
  - **R-IDs:** R11
- [ ] 4.3 Terminal-state exclusion from eligible work (R12)
  - **File:** `core/scripts/planning_graph.py`, `core/scripts/wave_deliver.py`
  - **Expected:** the scheduler and INDEX exclude `superseded`/`cancelled`/`deferred` units from eligible work
    while still rendering them in the archived view. Fixture: `terminal-excluded-from-eligible`.
  - **R-IDs:** R12

### 5. Atomic cutover (one commit with 031 Phase B + 032) — M

- [ ] 5.1 GAP-BACKLOG retirement + legacy projections + canonical gap capture (R15)
  - **File:** `core/scripts/planning_graph.py`, `core/scripts/feedback-backlog.sh`, `docs/prds/GAP-BACKLOG.md`, `docs/prds/INDEX.md`
  - **Expected:** the hand-maintained GAP-BACKLOG table is fully replaced by gap rows in the generated unified
    INDEX (folder-per-item), with gap status driven by absorption edges (R11) not manual edits; during the
    window the reconciler also generates **read-only frontmatter-only** legacy `GAP-BACKLOG.md` + `INDEX.md`
    projections, `/sw-feedback` gap-capture writes canonical gap units (legacy file is a read-only echo, doctor
    warning on manual legacy edits), and projections are removed once
    `wave_living_docs`/`reconcile-status`/`feedback-backlog` resolve via `planningDir`. Fixture:
    `legacy-projection-frontmatter-only`.
  - **R-IDs:** R15
- [ ] 5.2 Cutover no-regression run (R18)
  - **File:** `core/scripts/spec-rigor-check.sh`, `core/scripts/traceability-check.sh`, `core/scripts/wave_living_docs.py`
  - **Expected:** the cutover flips living-status/INDEX maintenance to the reconciler with no regression —
    frozen immutability, traceability, and spec-rigor gates preserved, the human merge-to-`main` gate
    unchanged, and foundational frozen workflow invariants retained. Fixture:
    `frozen-traceability-no-regression`.
  - **R-IDs:** R18

### 6. Emitter / dist parity — S

- [ ] 6.1 `copy-to-core` parity + emitter-freshness for new scripts and `planning.autonomy` key (R24)
  - **File:** `core/scripts/copy-to-core.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** the reconciler/scheduler artifacts land in `core/` and propagate to both dist trees
    (`dist/cursor`, `dist/claude-code`); `copy-to-core` parity and emitter-freshness fixtures cover the new
    scripts and the stubbed `planning.autonomy` schema key. Fixture: `emitter-parity-planning-autonomy`.
  - **R-IDs:** R24

### 7. Operator-doc acceptance criteria (033-owned) — M

- [ ] 7.1 Living-status SKILL + deliver/status command docs (R25)
  - **File:** `core/skills/living-status/SKILL.md`, `core/commands/sw-deliver.md`, `core/commands/sw-status.md`
  - **Expected:** `living-status/SKILL.md` replaces GAP-BACKLOG/gap-resolve/3-state INDEX with the unit
    lifecycle, reconciler, active/archive INDEX, and in-flight column; `sw-deliver.md` documents `next`, the
    dependency gate, run-start re-validation, and soft-enforce; `sw-status.md` documents the gap-unit index echo
    and override drift. Fixture: `doc-currency-033-sections` (living-status + commands).
  - **R-IDs:** R25
- [ ] 7.2 Workflows + getting-started guide sections (R25)
  - **File:** `docs/guides/workflows.md`, `docs/guides/getting-started.md`
  - **Expected:** `workflows.md` 033-owned sections (lifecycle state machine, dependency gate, `/sw-deliver
    next`, reconciler-driven active/archive INDEX, GAP-BACKLOG retirement + legacy-projection window) are added
    without touching the PRD 035-owned two-track sections; `getting-started.md`'s living-doc-currency bullet
    moves from the hand-maintained GAP-BACKLOG to the generated gap index + reconciler. Fixture:
    `doc-currency-033-sections` (guides).
  - **R-IDs:** R25

### 8. Post-merge INDEX reconcile safety + completion-finalize chokepoint — amendment A1 — M

- [ ] 8.1 Git-ancestry-primary `complete` predicate + monotonic terminal derived status (R29, R30)
  - **File:** `core/scripts/planning_graph.py`, `core/scripts/planning-graph.sh`
  - **Expected:** derived `complete` for non-gap units is determined from **git facts first** — the unit's
    terminal integration/feature branch is an ancestor of `defaultBaseBranch` (or a squash-merge of it),
    corroborated by host PR merge metadata when available; slug-scoped deliver state is secondary and the
    append-only COMPLETION-LOG is audit-only (never the sole predicate, extends GAP-053). Terminal states
    (`complete`, `superseded`) are **monotonic**: the reconciler MUST NOT downgrade a row unless an explicit
    `--override-status` names the unit id, prior status, new status, and reason; default reconcile is a no-op for
    terminal rows when git/deliver evidence still supports the terminal state. Fixtures:
    `reconcile-complete-from-git-ancestry`, `reconcile-terminal-monotonic`.
  - **R-IDs:** R29, R30
- [ ] 8.2 Default-branch reconcile refusal + stale-branch precedence (R31, R32)
  - **File:** `core/scripts/planning-graph.sh`, `core/scripts/reconcile-status.sh`, `core/skills/living-status/SKILL.md`
  - **Expected:** the maintenance reconciler and the legacy `reconcile-status.sh reconcile` shim it replaces
    **refuse to commit** when the current git branch is `defaultBaseBranch` — exit non-zero with an actionable
    message naming the allowed post-merge path (`set-index-status` + `append-log-idempotent` on a docs branch
    for single units; full-corpus reconcile only via the reconciler entrypoint on a non-default branch or the
    deliver completion finalizer); a `--allow-default-branch` escape hatch exists for fixtures/CI only and logs
    actor + reason. Reconcile inputs degrade safely when local branch inventory is stale: a local feature branch
    MUST NOT imply `in-progress` when git ancestry / host merge metadata show the unit terminal; the precedence
    order is documented in `living-status/SKILL.md`. Fixtures: `reconcile-refuse-default-branch`,
    `reconcile-stale-local-branches`.
  - **R-IDs:** R31, R32
- [ ] 8.3 Finalize-only `merged-complete` completion save guard (R33)
  - **File:** `core/scripts/wave_state.py`, `core/scripts/wave_compound.py`
  - **Expected:** only `wave_compound.py:cmd_completion_finalize_if_merged` (via
    `bash scripts/wave.sh completion finalize-if-merged`) may transition `completion.status` from
    `completed-pending-merge` to `merged-complete` and set `mergedAt`; direct hand-edits or ad-hoc `wave_state`
    saves that set `merged-complete` without passing the finalizer are rejected at the save guard (exit
    non-zero, no partial write). Fixture: `completion-finalize-chokepoint`.
  - **R-IDs:** R33
- [ ] 8.4 Deliver post-merge path: finalize-only, no bare reconcile suggestion (R34)
  - **File:** `core/scripts/wave_deliver_loop.py`, `core/commands/sw-retrospective.md`, `core/commands/sw-status.md`
  - **Expected:** the deliver-loop post-merge path invokes `finalize-if-merged` only; on guard failure it emits
    a consolidated halt with `resumeCommand` and MUST NOT suggest bare `reconcile-status.sh reconcile`; operator
    docs (`sw-retrospective.md`, `sw-status.md`) state the post-merge playbook — single-unit bookkeeping on a
    **docs branch**, never full-corpus `reconcile` on `main`. Fixture: `deliver-postmerge-finalize-no-reconcile`.
  - **R-IDs:** R34
- [ ] 8.5 Relief acceptance corpus extension + manifest registration (R35)
  - **File:** `core/scripts/planning-graph.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** the relief acceptance corpus (extends parent R22) includes, at minimum: (1) forward drift
    (GAP-053) — unit merged to `main` but INDEX `not-started` → reconciled `complete`; (2) backward regression
    (PRD 036) — INDEX `complete` with terminal branch ancestor of `main` but stale local branches + missing
    slug-scoped deliver state → derived status stays `complete`; (3) monotonic guard — downgrade without
    override refuses / no-op; (4) branch guard — `reconcile` on `main` exits non-zero, no commit; (5) finalize
    chokepoint — premature `merged-complete` rejected, valid `finalize-if-merged` succeeds. All five register in
    `pr-test-plan.manifest.json` and run in `verify.test`. Fixture: `relief-corpus-postmerge-safety`.
  - **R-IDs:** R35
- [ ] 8.6 Operator-doc acceptance — living-status SKILL + sw-status (A1 playbook) (R36)
  - **File:** `core/skills/living-status/SKILL.md`, `core/commands/sw-status.md`
  - **Expected:** `living-status/SKILL.md` and `sw-status.md` document the post-merge playbook, monotonic
    terminal status, default-branch reconcile refusal, and the finalize-only completion transition as
    acceptance criteria. Fixture: `doc-currency-033-a1-sections`.
  - **R-IDs:** R36

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 1, 2 |
| 5 | 2, 3, 4 |
| 6 | 2, 3, 4 |
| 7 | 5 |
| 8 | 2, 3 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | enum-type-conditioned-tokens |
| R2 | 1.2 | derived-status-from-inflight |
| R3 | 1.4 | blocked-matches-unmet-edges |
| R4 | 1.3 | whole-graph-cycle-precommit-reject |
| R5 | 2.4 | dependency-dead-flagged-not-blocked |
| R6 | 1.5 | priority-topo-stable-tiebreak |
| R7 | 3.1 | dependency-gate-fail-closed |
| R8 | 3.2 | soft-enforce-confirm-stubbed-default |
| R9 | 3.3 | run-start-revalidate-supersede-refuse |
| R10 | 4.1 | supersedes-flip-manifest |
| R11 | 4.2 | absorbs-lifecycle-progression |
| R12 | 4.3 | terminal-excluded-from-eligible |
| R13 | 2.1 | reconcile-reread-before-serialize |
| R14 | 2.2 | index-active-archive-split |
| R15 | 5.1 | legacy-projection-frontmatter-only |
| R16 | 2.5 | stale-planned-drift-reconciled |
| R17 | 2.6 | reconciler-no-auto-pr |
| R18 | 5.2 | frozen-traceability-no-regression |
| R19 | 1.6 | graph-module-deterministic |
| R20 | 3.4 | deliver-dependency-preflight |
| R21 | 2.3 | reconcile-idempotent-regen |
| R22 | 2.7 | relief-corpus-adversarial |
| R23 | 1.7 | enum-shared-module-no-drift |
| R24 | 6.1 | emitter-parity-planning-autonomy |
| R25 | 7.1, 7.2 | doc-currency-033-sections |
| R26 | 2.8 | reconciler-no-private-bodies |
| R27 | 1.6 | graph-offline-reproducible |
| R28 | 3.5 | override-logged-rate-surfaced |
| R29 | 8.1 | reconcile-complete-from-git-ancestry |
| R30 | 8.1 | reconcile-terminal-monotonic |
| R31 | 8.2 | reconcile-refuse-default-branch |
| R32 | 8.2 | reconcile-stale-local-branches |
| R33 | 8.3 | completion-finalize-chokepoint |
| R34 | 8.4 | deliver-postmerge-finalize-no-reconcile |
| R35 | 8.5 | relief-corpus-postmerge-safety |
| R36 | 8.6 | doc-currency-033-a1-sections |

## Notes

- New surfaces: `core/scripts/planning_lifecycle.py` (single-sourced enum; replaces PRD 031's values-only
  stub), `core/scripts/planning_graph.py` (pure graph module), `core/scripts/planning-graph.sh` (reconciler +
  `cycle-check` entry per PRD D7), and the `core/hooks/pre-commit` whole-graph cycle check.
- Existing surfaces touched: `core/scripts/wave_deliver.py`, `core/scripts/pilot_dependency_gate.py`,
  `core/scripts/wave_living_doc_lock.py`, `core/scripts/wave_living_docs.py`, `core/scripts/feedback-backlog.sh`,
  `core/scripts/reconcile-status.sh`, `core/sw-reference/config.schema.json`, `.sw/config.schema.json`,
  `core/scripts/copy-to-core.sh`.
- Cross-PRD: the reconciler reads (never writes) PRD 032's `inFlight` region; the relief check + accuracy floor
  (2.7) feed PRD 031's cutover kill-criteria (031 R28); `planning.autonomy` is owned by PRD 035 and only
  stubbed here. These cross-PRD relationships are not Phase Dependencies edges (intra-PRD only).
- Amendment A1 (Phase 8) surfaces: `core/scripts/wave_state.py` + `core/scripts/wave_compound.py`
  (finalize-only `merged-complete` save guard, R33), `core/scripts/wave_deliver_loop.py` (post-merge
  finalize-only path, R34), `core/commands/sw-retrospective.md` + `core/commands/sw-status.md` (post-merge
  playbook, R34/R36); A1 extends the Phase 2 reconciler (`planning-graph.sh`, `planning_graph.py`) and the
  legacy `reconcile-status.sh` shim for git-ancestry-primary, monotonic terminal status, and default-branch
  reconcile refusal (R29–R32). A1 absorbs GAP-053 and GAP-055.
- All new fixtures register in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.
