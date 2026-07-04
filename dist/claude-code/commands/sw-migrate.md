---
description: Bidirectional planning store migration between in-repo files and issue-store — dry-run by default; quiesce, doctor, and GAP-BACKLOG shim (PRD 044).
alwaysApply: false
---

# `/sw-migrate`

Operator command for **issue-store migration** (PRD 044). Wraps `scripts/planning_migrate.py` store
subcommands; default is **dry-run** (plan only).

## Scope

**Does:** `files-to-issues` and `issues-to-files` migration with journaled per-artifact state
(`pending` → `created` → `verified` → `source-removed`), content-hash idempotency
(`source_path:content_hash`), and verify-then-delete ordering.

**Does NOT:** change default planning behavior; run while deliver or reconcile is active; migrate decision-class artifacts.

## CLI

```bash
python3 scripts/planning_migrate.py <repo-root> store-files-to-issues
python3 scripts/planning_migrate.py <repo-root> store-files-to-issues --apply
python3 scripts/planning_migrate.py <repo-root> store-issues-to-files --apply
python3 scripts/planning_migrate.py <repo-root> store-doctor
python3 scripts/planning_migrate.py <repo-root> store-doctor --apply
python3 scripts/planning_migrate.py <repo-root> store-rollback --apply
python3 scripts/planning_migrate.py <repo-root> store-scan-quiesce
```

Without `--apply`, the engine reports the full plan and **mutates nothing** (no journal, files, or issues).

## Journal

Durable run-state: `.cursor/hooks/state/issue-store-migration-journal.json` (git-ignored hook state).
Restart-safe resume uses idempotency keys; sources are removed only after hash verification.

## Directions

| Direction | Source | Target |
| --- | --- | --- |
| `files-to-issues` | `docs/planning/**`, `docs/prds/**` markdown artifacts | `issue-store` via `IssueStoreBackend` |
| `issues-to-files` | Issues in configured `projectKey` (`issue_search`) | `InRepoPublicBackend` paths |

## Testing hooks

`SW_MIGRATE_INJECT_FAIL_AFTER` — inject failure after journal reaches `created`, `verified`, or
`source-removed` (partial-failure resume tests).

**Communication intensity:** inherit

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-migrate`.


## Quiesce (PRD 044 Phase 3)

Migration acquires an exclusive lock at `.cursor/hooks/state/issue-store-migration.lock` and
**refuses to run** while a deliver run or reconciler (`sw-living-docs.lock`) is active. One direction
at a time; resume is idempotent from the journal.

## Doctor and rollback

`store-doctor` enumerates inconsistent journal states (`created-but-unverified`,
`verified-but-source-present`) and offers idempotent repair with `--apply`. `store-rollback` resets
unverified targets to `pending` and documents rollback invariants in JSON output.

## GAP-BACKLOG shim

During an incomplete migration, `GAP-BACKLOG.md` is regenerated as a **read-only projection** (marker
`issue-store-migration-gap-shim`). Capture new gaps via `planning_gap_capture.py` — never hand-edit the
projection. The shim is removed when migration completes.
