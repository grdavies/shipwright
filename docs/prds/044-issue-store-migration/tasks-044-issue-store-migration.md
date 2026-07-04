---
date: 2026-06-30
topic: issue-store-migration
visibility: public
prd: docs/prds/044-issue-store-migration/044-prd-issue-store-migration.md
program: issue-backed-planning-store
frozen: true
frozen_at: 2026-06-30
---

# Tasks — PRD 044 Issue-store migration

Single-pass task list from the frozen PRD 044 spec union (R16, R17, R38). Phases mirror the PRD Rollout
Plan; migration is default-inert (explicit operator command) and carries a documentation exit-gate
(PRD 043 R49). Builds on PRD 043 for the provider abstraction, canonical hash (R35), visibility resolver
(R43), and identification model (R10–R12/R42).

## Tasks

### 1. Migration engine + dry-run default (M)

Restart-safe, verify-then-delete migration with journaled state and idempotency keys; mutates nothing without `--apply`.

- [ ] 1.1 Bidirectional migration command, dry-run default (R16)
  - **File:** `core/commands/sw-migrate.md`, `scripts/planning_migrate.py`
  - **Expected:** `files→issues` and `issues→files` directions; dry-run reports full plan (creates/hash-checks/deletions) and mutates nothing without `--apply`; idempotent re-run is a no-op
  - **R-IDs:** R16
- [ ] 1.2 Durable journal + per-artifact state machine (R38)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** git-ignored run-state journal records `pending`→`created`→`verified`→`source-removed`; idempotency key = source path + content-hash (PRD 043 R35); restart-safe
  - **R-IDs:** R38
- [ ] 1.3 Verify-then-delete ordering with content-hash gate (R16, R38)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** no source artifact removed before its target is hash-verified (PRD 043 R35); interrupted run never leaves an artifact with neither verified target nor source
  - **R-IDs:** R16, R38
- [ ] 1.4 Phase-1 documentation exit-gate (PRD 043 R49)
  - **File:** `core/commands/sw-migrate.md`, `.sw/layout.md`
  - **Expected:** migration command + dry-run/apply semantics and journal location documented before phase ship
  - **R-IDs:** R38

### 2. Lifecycle preservation both directions (M)

Bodies and full lifecycle state survive migration in either direction.

- [ ] 2.1 Body + open/frozen status preservation (R17)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** artifact bodies and open/frozen lifecycle status preserved both directions; frozen artifacts remain frozen with their content-hash intact
  - **R-IDs:** R17
- [ ] 2.2 Edges/links + gap-status preservation (R17)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** PRD 043 R29 `sw-edges` block plus native link/sub-issue projections and gap status preserved both directions
  - **R-IDs:** R17
- [ ] 2.3 Visibility gate on every migration create (R17)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** every create resolves visibility via PRD 043 R43 before any API write; a private artifact targeting a public/shared store aborts that item and is reported; rest of batch unaffected
  - **R-IDs:** R17
- [ ] 2.4 Phase-2 documentation exit-gate (PRD 043 R49)
  - **File:** `docs/guides/workflows.md`
  - **Expected:** lifecycle-preservation guarantees (status/edges/gap-status) documented before phase ship
  - **R-IDs:** R17

### 3. Resilience, doctor, and quiesce (M)

Resumable, rollback-safe migration with conflict quiesce and a half-migrated repair tool.

- [x] 3.1 Idempotent resume + rollback invariants (R38)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** injected mid-migration failure resumes idempotently from journal; documented rollback invariants leave a clean final state
  - **R-IDs:** R38
- [x] 3.2 Quiesce against deliver/reconcile (R38)
  - **File:** `scripts/planning_migrate.py`
  - **Expected:** migration acquires an exclusive planning lock; refuses to run while a deliver run or reconcile is active and instructs the operator to quiesce; one direction at a time
  - **R-IDs:** R38
- [x] 3.3 `migrate doctor` half-migration repair (R38)
  - **File:** `scripts/planning_migrate.py`, `core/commands/sw-migrate.md`
  - **Expected:** `doctor` enumerates inconsistent journal states (created-but-unverified, verified-but-source-present) and offers idempotent repair or rollback with documented invariants
  - **R-IDs:** R38
- [x] 3.4 GAP-BACKLOG read-only shim during transition (R38)
  - **File:** `scripts/planning_gap_capture.py`, `core/skills/feedback/SKILL.md`
  - **Expected:** `GAP-BACKLOG.md` becomes a read-only projection of gap issues during transition; removed cleanly once a project completes migration (native gaps-as-issues is PRD 045)
  - **R-IDs:** R38
- [x] 3.5 Phase-3 documentation exit-gate (PRD 043 R49)
  - **File:** `docs/guides/commands.md`, `core/skills/feedback/SKILL.md`
  - **Expected:** doctor/quiesce/resume + GAP-BACKLOG shim transition documented before phase ship
  - **R-IDs:** R38

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R16 | 1.1, 1.3 | round-trip files→issues→files with content-hash equality (SC4); dry-run mutates nothing (SC4b) |
| R17 | 2.1, 2.2, 2.3 | lifecycle preservation: open/frozen + edges/links + gap status round-trip; private item refused mid-batch |
| R38 | 1.2, 1.3, 3.1, 3.3 | partial-failure resume with no source deleted before verification (SC4a); doctor repairs corrupted journal; quiesce refuses concurrent deliver/reconcile |
