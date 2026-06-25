---
name: sw-living-status
description: Derive PRD status from git (merged PRs, branches, task checkboxes); reconcile INDEX; append-only completion log.
---

# Living status (R13/R14)

Status is **derived from git**, never hand-set on frozen artifacts.


**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --skill living-status`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

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

## Active PR review echo (R29)

When `/sw-status` or any living-status summary covers an open PR, run `scripts/check-gate.sh` and echo review
state from `coderabbitState` in the human summary:

| `coderabbitState` | Echo |
| --- | --- |
| `off` | `review: off` |
| `unconfigured` | `review: not configured` |
| other | `review: <state>` |

Goal: a green gate with no external review is not mistaken for a reviewed change. `/sw-ready` uses the same
mapping in its terminal report.

## Guardrails

- Never modify frozen PRD/amendment files.
- Re-running derive → reconcile is idempotent for same git facts.
