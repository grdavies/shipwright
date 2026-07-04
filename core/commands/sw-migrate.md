---
description: Bidirectional planning store migration between in-repo files and issue-store — dry-run by default; does not run deliver, reconcile, or doctor repair (PRD 044 Phase 1).
alwaysApply: false
---

# `/sw-migrate`

Operator command for **issue-store migration** (PRD 044). Wraps `scripts/planning_migrate.py` store
subcommands; default is **dry-run** (plan only).

## Scope

**Does:** `files-to-issues` and `issues-to-files` migration with journaled per-artifact state
(`pending` → `created` → `verified` → `source-removed`), content-hash idempotency
(`source_path:content_hash`), and verify-then-delete ordering.

**Does NOT:** change default planning behavior; run `/sw-deliver` or reconciler (quiesce is Phase 3);
repair half-migrated repos (`migrate doctor` is Phase 3); migrate decision-class artifacts.

## CLI

```bash
python3 scripts/planning_migrate.py <repo-root> store-files-to-issues
python3 scripts/planning_migrate.py <repo-root> store-files-to-issues --apply
python3 scripts/planning_migrate.py <repo-root> store-issues-to-files --apply
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
