---
date: 2026-07-01
topic: gap-lifecycle-flip-and-feedback-route-guard
prd: docs/prds/048-gap-lifecycle-flip-and-feedback-route-guard/048-prd-gap-lifecycle-flip-and-feedback-route-guard.md
frozen: true
frozen_at: 2026-07-01
---

# Tasks — PRD 048 Gap-lifecycle flip automation & feedback route guard

Single-pass task list from the frozen PRD 048 spec union (R1–R7; decisions D1–D10). Wires existing gap-resolve,
currency-gate, and feedback-routing primitives at their natural call sites — no new gap-lifecycle framework.

## Relevant Files

- `scripts/gap_backlog.py` — shared `resolve_for_prd()`, `flip --resolve --scope-note`
- `scripts/reconcile_lib.py` — `set_index_status()` in-process flip + default-branch guard
- `scripts/living-status-gap-resolve.py` — manual-retry CLI delegating to shared resolver
- `scripts/docs-currency-gate.py` — `gap-still-open` drift check (~lines 76–88)
- `core/skills/feedback/SKILL.md`, `core/commands/sw-feedback.md` — Phase 3 route guard
- `core/skills/living-status/SKILL.md`, `core/skills/deliver/SKILL.md`, `core/commands/sw-status.md` — operator docs
- `scripts/test/run_planning_035_gap_lifecycle_fixtures.py` — R1/R2 fixtures
- `scripts/test/run_living_doc_fixtures.py` — R3 docs-currency-gate fixtures
- `scripts/test/run_feedback_fixtures.py` — R5 feedback routing fixtures

## Tasks

### 1. In-process gap-resolve flip + default-branch guard (medium)

Extract the shared resolver and wire it into `set_index_status()` together with the PRD 046 A1 default-branch
guard — same primitive, same call site.

- [ ] 1.1 Extract shared `resolve_for_prd()` resolver (R1)
  - **File:** `scripts/gap_backlog.py`
  - **Expected:** `resolve_for_prd(root, prd, *, scope_note=None) -> dict` parses via `parse_gap_backlog()`, calls `flip_resolve()`, writes `GAP-BACKLOG.md` when changed, returns `{"verdict": "pass"|"partial", "flipped": [...], "error": ...}`; idempotent on already-`resolved` rows
  - **R-IDs:** R1
- [ ] 1.2 Wire in-process flip into `set_index_status()` after `complete` write (R1)
  - **File:** `scripts/reconcile_lib.py` (~line 245)
  - **Expected:** after successful `status == "complete"` INDEX write, call `resolve_for_prd(root, prd, ...)` in-process (no subprocess); pass caller `root` (not CWD); on flip exception return `{"verdict": "partial", ...}` without rolling back INDEX write
  - **R-IDs:** R1
- [ ] 1.3 Delegate `living-status-gap-resolve.py` to shared resolver (R1)
  - **File:** `scripts/living-status-gap-resolve.py`
  - **Expected:** CLI entry point calls the same `resolve_for_prd()` in-process for manual retries; preserves standalone usability; redundant `wave_living_docs.py` chain unchanged (Non-Goal)
  - **R-IDs:** R1
- [ ] 1.4 Wire default-branch guard into `set_index_status()` (R2)
  - **File:** `scripts/reconcile_lib.py`
  - **Expected:** before INDEX write, call `worktree_lib.refuse_default_branch(branch, cfg["defaultBaseBranch"])` using `git rev-parse --abbrev-ref HEAD` (same pattern as `reconcile_prd_index()`); fail closed on bare default branch
  - **R-IDs:** R2
- [ ] 1.5 Extend R1/R2 lifecycle fixtures (R1, R2)
  - **File:** `scripts/test/run_planning_035_gap_lifecycle_fixtures.py`
  - **Expected:** (1) `set_index_status(..., status="complete")` flips `scheduled | PRD <n> A1` rows in-process without manual `living-status-gap-resolve.py`; (2) refuses write on fixture `defaultBaseBranch`; (3) malformed GAP-BACKLOG yields INDEX write + `verdict: partial` not `pass`
  - **R-IDs:** R1, R2

### 2. docs-currency-gate gap-still-open rewrite (small)

Replace ad hoc column indexing with the shared `gap_backlog` parser so the gate fires on real 4-column rows.

- [ ] 2.1 Rewrite `gap-still-open` block using `parse_gap_backlog()` (R3)
  - **File:** `scripts/docs-currency-gate.py` (~lines 76–88)
  - **Expected:** remove `len(parts) < 5` skip and `parts[-1]`/`parts[-2]` indexing; for each row flag drift when `row.status == "open"`, or `row.status == "scheduled"` with `row.schedule` matching absorbing PRD (reuse `flip_resolve` `sched_re`) and absorbing PRD INDEX status is `complete`
  - **R-IDs:** R3
- [ ] 2.2 Add docs-currency-gate fixture cases (R3)
  - **File:** `scripts/test/run_living_doc_fixtures.py`
  - **Expected:** (1) `scheduled | PRD <n> A<k>` row against `complete` PRD asserts `verdict: fail` with `gap-still-open` drift entry; (2) real 4-column row shape proves pre-fix `len(parts) < 5` skip no longer discards the row
  - **R-IDs:** R3

### 3. gap_backlog flip --scope-note annotation (small)

Optional schedule-column annotation for narrower-than-described fixes without changing status vocabulary.

- [ ] 3.1 Add `--scope-note` argparse to `flip --resolve` (R4)
  - **File:** `scripts/gap_backlog.py` (~lines 203–210)
  - **Expected:** `flip --resolve` subparser accepts optional `--scope-note <text>` and threads value into `flip_resolve()`
  - **R-IDs:** R4
- [ ] 3.2 Annotate schedule column in `flip_resolve()` when note supplied (R4)
  - **File:** `scripts/gap_backlog.py` (~lines 162–173)
  - **Expected:** when `--scope-note` supplied set `row.schedule = f"— ({note})"`; omitting flag preserves bare `"—"` byte-for-byte; `row.status` remains `"resolved"`
  - **R-IDs:** R4, R7
- [ ] 3.3 Unit test scope-note annotation format (R4, R7)
  - **File:** `scripts/test/run_planning_035_gap_lifecycle_fixtures.py`
  - **Expected:** `gap_backlog.py flip --resolve --scope-note "..."` writes `— (note)` in schedule column; second case confirms omitting `--scope-note` reproduces today's bare format byte-for-byte
  - **R-IDs:** R4, R7

### 4. Feedback route guard for complete units (medium)

Probe consumer status before naming `/sw-amend` in the substantial-signal handoff branch.

- [ ] 4.1 Update Phase 3 substantial branch in feedback skill (R5)
  - **File:** `core/skills/feedback/SKILL.md`
  - **Expected:** before naming `/sw-amend`, call `authoring-guard.py preflight --path <unit-artifact> --command sw-amend --no-commit`; on exit 21 surface `propose_complete_change_route` (extends/supersedes/gap-only) instead of `/sw-amend`; route-record captures which branch fired
  - **R-IDs:** R5
- [ ] 4.2 Wire preflight probe into sw-feedback step 5 (R5)
  - **File:** `core/commands/sw-feedback.md`
  - **Expected:** substantial-signal handoff step 5 invokes the same `authoring-guard.py preflight --command sw-amend --no-commit` probe; no changes to `authoring_guard.py` resolution logic
  - **R-IDs:** R5
- [ ] 4.3 Regenerate emitter parity after command/skill edits (R32)
  - **File:** `scripts/build-chain-sync.py`
  - **Expected:** `python3 scripts/build-chain-sync.py` run and dist outputs match core command/skill sources before freeze
  - **R-IDs:** R5
- [ ] 4.4 Extend feedback routing fixtures (R5)
  - **File:** `scripts/test/run_feedback_fixtures.py`
  - **Expected:** Phase-3 substantial signal with `consumerStatus: complete` asserts handoff names extends/supersedes/gap path never `/sw-amend`, preflight made no `inFlight`/INDEX mutation (`--no-commit` honored); `planned`/`in-progress` unit still names `/sw-amend`
  - **R-IDs:** R5

### 5. Documentation surface updates (small)

Update operator-facing docs to reflect auto-flip, corrected gate coverage, scope-note, and partial verdict retry.

- [ ] 5.1 Update living-status GAP-BACKLOG protocol section (R1, R3, R4)
  - **File:** `core/skills/living-status/SKILL.md`
  - **Expected:** document that `set-index-status --status complete` auto-invokes shared gap-resolver idempotently; corrected `gap-still-open` drift coverage (`open` and `scheduled`); `--scope-note` schedule annotation
  - **R-IDs:** R1, R3, R4
- [ ] 5.2 Clarify deliver living-docs completion hook (R1)
  - **File:** `core/skills/deliver/SKILL.md` (~lines 476–492)
  - **Expected:** absorbed-gap resolution on `complete` triggered by `set_index_status` post-write hook, distinct from out-of-scope PRD 046 A2 `finalize-completion` path
  - **R-IDs:** R1
- [ ] 5.3 Update sw-status post-merge playbook (R1)
  - **File:** `core/commands/sw-status.md`
  - **Expected:** note auto-flip on `complete` and `verdict: partial` retry signal for operator recovery
  - **R-IDs:** R1

### 6. Retroactive backfill and GAP closure (medium)

One-time reconciliation from a non-default-branch worktree after R1/R3 ship.

- [ ] 6.1 Backfill PRD 035 absorbed rows with scope-note for GAP-062 (R6)
  - **File:** `docs/prds/GAP-BACKLOG.md`
  - **Expected:** from non-`defaultBaseBranch` worktree invoke R1-fixed resolver for PRD 035 with `--scope-note` for GAP-062; record before/after row counts
  - **R-IDs:** R6
- [ ] 6.2 Sweep other `complete` PRDs with corrected R3 gate (R6)
  - **File:** `scripts/docs-currency-gate.py`
  - **Expected:** one-time sweep across all `complete` PRDs; if ≤5 additional PRDs have unresolved absorbed rows backfill in this PR, else backfill PRD 035 only and file follow-up gap (D9); attach full PRD list to rollout evidence
  - **R-IDs:** R6
- [ ] 6.3 Close GAP-088 and attach gate evidence (R6)
  - **File:** `docs/prds/GAP-BACKLOG.md`, `docs/prds/gap/gap-016-gap-resolve-mechanical-flip-r51-never-wired-into/`
  - **Expected:** before/after `docs-currency-gate.py` output shows PRD 035 drift list empties; flip GAP-088 to `resolved` referencing PRD 048; set gap-016 unit frontmatter `status: resolved`
  - **R-IDs:** R6

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | none |
| 4 | none |
| 5 | 1, 2, 4 |
| 6 | 1, 2 |

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R1 | 1.1, 1.2, 1.3, 1.5 | `set_index_status(..., status="complete")` flips `scheduled \| PRD <n> A1` rows in-process without manual `living-status-gap-resolve.py`; flip failure yields INDEX write + `verdict: partial` |
| R2 | 1.4, 1.5 | `set_index_status` refuses write on fixture `defaultBaseBranch` |
| R3 | 2.1, 2.2 | `scheduled \| PRD <n> A<k>` row against `complete` PRD asserts `verdict: fail` with `gap-still-open` drift; 4-column row shape proves pre-fix `len(parts) < 5` skip no longer discards the row |
| R4 | 3.1, 3.2, 3.3 | `flip --resolve --scope-note "..."` writes `— (note)` annotation format; omitting `--scope-note` reproduces bare format byte-for-byte |
| R5 | 4.1, 4.2, 4.4 | Phase-3 substantial signal with `consumerStatus: complete` routes to extends/supersedes/gap path (never `/sw-amend`, no `inFlight`/INDEX mutation); `planned`/`in-progress` unit still names `/sw-amend` |
| R6 | 6.1, 6.2, 6.3 | before/after `docs-currency-gate.py` output attached to shipping PR shows PRD 035 drift list empties |
| R7 | 3.2, 3.3 | omitting `--scope-note` reproduces today's bare `"—"` byte-for-byte; ternary status vocabulary (`open`/`scheduled`/`resolved`) unchanged |
