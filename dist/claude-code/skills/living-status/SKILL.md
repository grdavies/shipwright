---
name: pf-living-status
description: Derive PRD status from git (merged PRs, branches, task checkboxes); reconcile INDEX; append-only completion log.
---

# Living status (R13/R14)

Status is **derived from git**, never hand-set on frozen artifacts.

## Link mechanism (R14 resolution)

| Signal | How |
| --- | --- |
| PR ↔ PRD | Branch `pf/<slug>-*` or `pf/<slug>/…`; PR body `prd:<slug>`; title word-boundary match on slug |
| Task progress | Read frozen task file checkboxes (**inputs**, not written by status) |
| Shipped predicate | All task items checked **and** ≥1 merged PR linked to slug |

## Commands

```bash
bash scripts/reconcile-status.sh derive [--json]
bash scripts/reconcile-status.sh reconcile [--dry-run]
bash scripts/reconcile-status.sh append-log <prd> <phase> "<notes>"
```

## INDEX reconciliation

Updates **Status** column only in `docs/prds/INDEX.md`. Frozen PRD/amendment bodies untouched.

## Completion log

Append-only rows in `docs/prds/COMPLETION-LOG.md` on shipped phases.

## GAP-BACKLOG

Surface `docs/prds/GAP-BACKLOG.md` in status view (read-only — hand-maintained by feedback workstream).

## Guardrails

- Never modify frozen PRD/amendment files.
- Re-running derive → reconcile is idempotent for same git facts.
