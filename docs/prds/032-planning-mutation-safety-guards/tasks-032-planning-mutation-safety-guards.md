---
date: 2026-06-27
topic: planning-feedback-lifecycle
prd: docs/prds/032-planning-mutation-safety-guards/032-prd-planning-mutation-safety-guards.md
frozen: true
frozen_at: 2026-06-27
---

# Tasks — PRD 032 Planning Mutation-Safety Guards (In-Flight Signal & Amendment-to-Completed)

Generated from the frozen PRD spec union **R1–R18** (no amendments). Seven dependency-ordered phases mirror the
PRD rollout, intra-PRD only (the program-level atomic cutover with 031 Phase B + 033, and the 031 substrate
prerequisites, are external sequencing): the committed **in-flight signal writer** (Phase 1) underpins the
**self-heal/staleness path** (Phase 2); the **shared authoring-guard preflight** (Phase 3) reads the signal and
runs inline reconcile; the **completed-unit immutability hook** (Phase 4) binds derived/structural status with a
reconcile-generation token; the **migration-bridge backfill** (Phase 5) promotes legacy markers within the
cutover; **emitter/dist parity** (Phase 6) and the **doc-impact acceptance criteria** (Phase 7) close the train.
New guard artifacts land in `core/` and propagate to both dist trees per R16; all fixtures register in
`core/sw-reference/pr-test-plan.manifest.json`.

## Tasks

### 1. Committed in-flight signal writer — L

- [ ] 1.1 In-flight tuple read/write in the committed INDEX `inFlight` region (R1)
  - **File:** `core/scripts/inflight_signal.py`, `core/scripts/inflight-signal.py`
  - **Expected:** writes/reads the tuple (**run id + implementing branch + lease epoch**) into the PRD-031
    `inFlight` INDEX region via read-merge-write; readable from any clone (committed git state, never gitignored
    local deliver state); the lifecycle `in-progress` status is **absent** from the tuple (derived by PRD 033).
    Fixture `inflight-write-read-clear`: run-start writes, a second clone reads, run completion clears, tuple
    carries no lifecycle status.
  - **R-IDs:** R1
- [ ] 1.2 Run-id lease + tuple compare-and-set + `--takeover` (R2)
  - **File:** `core/scripts/inflight_signal.py`, `.cursor/sw-deliver-runs/index.json`
  - **Expected:** run-start takes a durable **run-id lease** and writes the tuple with optimistic CAS on the
    prior tuple; a run-start finding a *different live* run-id fails closed unless `--takeover <reason>` is
    passed (logged); the durable lease — never git last-writer-wins — is authoritative. Fixture
    `cross-clone-cas-takeover-failclosed`: two staggered clones; second run-start fails closed without
    `--takeover`; lease wins over git merge.
  - **R-IDs:** R2
- [ ] 1.3 Wire the writer into deliver run-start under the single-writer lock (R11)
  - **File:** `core/scripts/wave_deliver_loop.py`, `core/skills/deliver/SKILL.md`
  - **Expected:** the signal is written at deliver run-start and cleared at run completion through the
    living-doc single-writer lock, inserted **after lock-acquire / before orchestrator-provision**, touching
    only the `inFlight` region and never the reconciler-owned `derived` region (PRD 033 R12/D5 dual-writer
    contract). Fixture `runstart-writer-inflight-region-only`: writer leaves `derived` byte-for-byte intact.
  - **R-IDs:** R11
- [ ] 1.4 Reserve the opaque-token (hashed-branch-suffix) schema form (R13)
  - **File:** `core/sw-reference/planning-unit.schema.json`, `core/sw-reference/layout.md`
  - **Expected:** the `inFlight` signal schema exposes run id + branch as committed metadata and **reserves an
    opaque-token form (hashed branch suffix)** so PRD 034 can redact private branch/codename metadata without a
    schema change; the `inFlight` region is documented as included in the PRD 034 emission-point registry/resolver
    handoff; the interim cleartext-for-non-private exposure window is documented. Fixture
    `inflight-opaque-token-slot-reserved`: schema validates both cleartext and opaque-token tuple forms.
  - **R-IDs:** R13
- [ ] 1.5 Fail-closed posture + durable override audit log (R17)
  - **File:** `core/scripts/inflight_signal.py`, `.cursor/sw-deliver-state.<slug>.json`
  - **Expected:** ambiguous in-flight/lifecycle-freshness state blocks the mutation (except the R12
    graceful-degraded mode); `--takeover`, `--handoff`, and any `--override` are explicit and append a durable
    audit entry (who/when/why) to deliver state. Fixture `override-logged-who-when-why`: each override path
    records an auditable entry and never proceeds silently.
  - **R-IDs:** R17
- [ ] 1.6 Tuple stores no body content and no secret (R18)
  - **File:** `core/scripts/inflight_signal.py`, `core/scripts/secret-scan.py`
  - **Expected:** the tuple persists only run-id + branch + lease epoch metadata — no body content and no
    secret; private-unit branch redaction defers to the PRD 034 handoff (R13). Fixture
    `inflight-tuple-no-secret`: a tuple write is rejected/scrubbed if it would carry body or secret material.
  - **R-IDs:** R18

### 2. Self-heal, staleness TTL & escape hatch — M

- [ ] 2.1 Reconcile/self-heal with terminal-run-state-only clearing (R3)
  - **File:** `core/scripts/inflight-reconcile.py`, `core/scripts/inflight_reconcile.py`
  - **Expected:** a missing branch or non-live run degrades to a warning and reconcile repairs stale/missing
    markers against actual runs; a tuple is classified **stale and clearable only when the durable run-state for
    its run-id is terminal/absent AND the branch is missing** — branch-absence alone (mid-rebase, slow CI) never
    clears a live tuple. Fixture `branch-absence-alone-no-clear`: a live run-state with a missing branch is not
    cleared; a terminal/absent run-id with missing branch reconciles to clearable.
  - **R-IDs:** R3
- [ ] 2.2 Bounded staleness TTL auto-clear + `clear-inflight` escape hatch (R4)
  - **File:** `core/scripts/clear-inflight.py`, `core/sw-reference/config.schema.json`, `core/sw-reference/workflow.config.example.json`
  - **Expected:** when a tuple's run-id is absent from the registry, its branch is missing, and no porcelain
    deliver state exists beyond the configured TTL, reconcile auto-clears it with an audit log; an operator may
    also run `clear-inflight <unit> --reason` (logged) to clear an ambiguous tuple. Fixtures
    `inflight-ttl-autoclear-audit` (past-TTL ambiguous tuple auto-clears with audit) and `clear-inflight-manual`
    (operator escape hatch logs and clears).
  - **R-IDs:** R4

### 3. Shared authoring-guard preflight & handoff route — M

- [ ] 3.1 Authoring-guard preflight: inline reconcile then fail-closed (R5)
  - **File:** `core/scripts/authoring_guard.py`, `core/scripts/authoring-guard.py`
  - **Expected:** the preflight **first runs inline stale-marker reconcile** (or reads the live run registry),
    then fails closed (reporting run id + branch) only when the target unit is *provably* in-flight after
    reconcile, so a crashed run with a deleted branch does not deadlock authoring while a live run still blocks.
    Fixture `authoring-guard-inline-reconcile-then-failclosed`: crashed-run+deleted-branch proceeds after inline
    reconcile; genuinely live run blocks with run id + branch.
  - **R-IDs:** R5
- [ ] 3.2 Share the preflight module across the unit-writing commands (R14)
  - **File:** `core/scripts/authoring_guard.py`, `core/commands/sw-amend.md`, `core/commands/sw-tasks.md`, `core/commands/sw-prd.md`, `core/scripts/planning_paths.py`
  - **Expected:** a single shared preflight module is invoked by `/sw-amend`, `/sw-tasks`, `/sw-prd`, and other
    unit-frontmatter/ancillary-file writers; it invokes the inline reconcile and reads the committed signal via
    the PRD-031 `planning_paths` helper. Fixture `authoring-guard-shared-across-commands`: each command routes
    through the same module and resolves the signal via the path helper.
  - **R-IDs:** R14
- [ ] 3.3 `--handoff` route records an artifact surfaced in `/sw-status` (R6)
  - **File:** `core/scripts/authoring_guard.py`, `core/commands/sw-status.md`, `core/scripts/reconcile-status.py`
  - **Expected:** when the operator chooses not to wait on a genuinely in-flight unit, `--handoff` records a
    handoff artifact instead of mutating; the artifact is **surfaced in `/sw-status` and to the PRD 035 pull-in
    scan** so it is reconciled into the graph rather than orphaned. Fixture `handoff-artifact-surfaced-in-status`:
    a `--handoff` invocation records the artifact and it appears in `/sw-status` output and the pull-in scan set.
  - **R-IDs:** R6

### 4. Completed-unit immutability — L

- [ ] 4.1 `/sw-amend` permitted only on `planned`/`in-progress`, refuses `complete` (R7)
  - **File:** `core/commands/sw-amend.md`, `core/scripts/authoring_guard.py`
  - **Expected:** `/sw-amend` is allowed on `planned` or `in-progress` units and refuses on `complete` units.
    Fixture `amend-refuses-complete-allows-planned`: amend succeeds on planned/in-progress, refuses on complete.
  - **R-IDs:** R7
- [ ] 4.2 Route a change request against a `complete` unit to a new unit/gap (R8)
  - **File:** `core/scripts/authoring_guard.py`, `core/commands/sw-amend.md`
  - **Expected:** a change request against a `complete` unit is mechanically routed to fork a new unit that
    `supersedes:`/`extends:` the completed one (or append a gap unit), so amendments to completed work are never
    silently lost. Fixture `complete-change-routes-to-new-unit`: a completed-unit request yields a superseding/
    extending unit or a gap, not an in-place edit.
  - **R-IDs:** R8
- [ ] 4.3 Whole-unit-folder immutability hook with reconcile-generation token (R9)
  - **File:** `core/hooks/pre-commit-completed-unit.sh`, `core/hooks/pre-commit`
  - **Expected:** a freeze/pre-commit hook rejects any mutation to a `status: complete` unit — its body **or any
    path under the unit folder, including the `amendments/` subtree** — regardless of invocation path (direct
    edit, agent write, command); the hook binds evaluation to a single **reconcile-generation token** (atomic
    re-read of derived status, or inline reconcile immediately before accept/reject) so a concurrent complete-flip
    cannot race the write. Fixtures `complete-unit-folder-mutation-rejected` (body, agent write, and new
    `amendments/` file all rejected) and `complete-flip-toctou-caught` (concurrent complete-flip racing an amend
    is caught by the generation token).
  - **R-IDs:** R9
- [ ] 4.4 Freeze/commit guard integration + graceful-degraded structural-status mode (R12)
  - **File:** `core/hooks/pre-commit-completed-unit.sh`, `core/hooks/pre-commit-frozen.sh`, `core/commands/sw-freeze.md`
  - **Expected:** the completed-unit hook chains from `core/hooks/pre-commit` into the existing
    `pre-commit-frozen` freeze/commit machinery (PRD 031 R17) and is mirrored in CI; **graceful-degraded mode:**
    when the 033 `derived` region is empty/unavailable (half-applied train), the hook evaluates against
    structural frontmatter `status` + the committed `inFlight` signal and **emits a warning** rather than
    fail-closing every guarded write. Fixture `completed-hook-graceful-degrade-warns`: with `derived` empty, the
    hook warns in structural-status mode instead of blocking every write.
  - **R-IDs:** R12

### 5. Migration-bridge backfill — S

- [ ] 5.1 Backfill the committed in-flight signal from legacy deliver state (R10)
  - **File:** `core/scripts/inflight-migration-bridge.py`, `core/scripts/inflight_migration_bridge.py`
  - **Expected:** a migration-bridge reconcile, run once **within the cutover**, promotes legacy in-progress
    markers from gitignored deliver state into the committed `inFlight` INDEX region **without desyncing any live
    run** (reads only gitignored deliver state, commits only tuple metadata), closing the 031 D7 deferral.
    Fixture `migration-bridge-backfill-no-desync`: legacy gitignored markers promote into the committed signal
    with no live-run desync.
  - **R-IDs:** R10

### 6. Emitter/dist parity — S

- [ ] 6.1 `copy-to-core` parity + emitter-freshness for new guards (R16)
  - **File:** `scripts/copy-to-core.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** guard artifacts land in `core/` and propagate to both dist trees; `copy-to-core` parity and
    emitter-freshness fixtures cover the new scripts and hooks (in-flight signal/reconcile/clear, authoring
    guard, completed-unit hook, migration bridge). Fixtures `inflight-guards-copy-to-core-parity` and
    `inflight-guards-emitter-freshness`.
  - **R-IDs:** R16

### 7. Doc-impact acceptance criteria — M

- [ ] 7.1 Update operator-facing docs the PRD changes (R15)
  - **File:** `core/commands/sw-amend.md`, `core/commands/sw-tasks.md`, `core/commands/sw-prd.md`, `core/commands/sw-freeze.md`, `core/skills/deliver/SKILL.md`
  - **Expected:** `sw-amend.md`/`sw-tasks.md`/`sw-prd.md` document the authoring-guard preflight, `--handoff`,
    and complete-unit refusal; `sw-freeze.md` documents the completed-unit body/ancillary mutation hook
    (R9/R12); `deliver/SKILL.md` documents the run-start `inFlight` writer/clear (R1/R11), **replacing** the
    current "INDEX never uses `in-progress`" statement. Lifecycle/reconciler INDEX semantics, `living-status`,
    and `.sw/layout.md` path authority remain PRD 033/031-owned. Fixture `inflight-doc-currency`: a hard-block
    on drift across the five surfaces.
  - **R-IDs:** R15

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 1, 2 |
| 5 | 1 |
| 6 | 1, 2, 3, 4, 5 |
| 7 | 1, 3, 4 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | inflight-write-read-clear |
| R2 | 1.2 | cross-clone-cas-takeover-failclosed |
| R3 | 2.1 | branch-absence-alone-no-clear |
| R4 | 2.2 | inflight-ttl-autoclear-audit / clear-inflight-manual |
| R5 | 3.1 | authoring-guard-inline-reconcile-then-failclosed |
| R6 | 3.3 | handoff-artifact-surfaced-in-status |
| R7 | 4.1 | amend-refuses-complete-allows-planned |
| R8 | 4.2 | complete-change-routes-to-new-unit |
| R9 | 4.3 | complete-unit-folder-mutation-rejected / complete-flip-toctou-caught |
| R10 | 5.1 | migration-bridge-backfill-no-desync |
| R11 | 1.3 | runstart-writer-inflight-region-only |
| R12 | 4.4 | completed-hook-graceful-degrade-warns |
| R13 | 1.4 | inflight-opaque-token-slot-reserved |
| R14 | 3.2 | authoring-guard-shared-across-commands |
| R15 | 7.1 | inflight-doc-currency |
| R16 | 6.1 | inflight-guards-copy-to-core-parity / inflight-guards-emitter-freshness |
| R17 | 1.5 | override-logged-who-when-why |
| R18 | 1.6 | inflight-tuple-no-secret |

## Notes

- Intra-PRD dependencies only. Program-level sequencing (031 substrate prerequisites validating first; the
  one-commit atomic cutover shipping 031 Phase B + 032 + 033 together) is external and owned by the 031 release
  train (PRD 031 R27/R28, D11), not these edges.
- New guard surfaces depend on PRD-031 substrate: the `inFlight` INDEX region + region-integrity hook (031 R9/
  R24), the `planning_paths` helper (031 R23), and the type-conditioned lifecycle status enum (031 R4).
- Existing surfaces touched (not new): `core/scripts/wave_deliver_loop.py`, `core/skills/deliver/SKILL.md`,
  `core/hooks/pre-commit`, `core/hooks/pre-commit-frozen.sh`, `core/scripts/reconcile-status.py`.
- All new fixtures register in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.
