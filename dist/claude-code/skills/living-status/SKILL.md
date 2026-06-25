---
name: sw-living-status
description: Derive PRD status from git and deliver state; reconcile INDEX, COMPLETION-LOG, and GAP-BACKLOG; hard-block on drift.
---

# Living status (R47–R51)

Status is **derived from git and durable deliver state**, never hand-set on frozen artifacts.

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --skill living-status`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## INDEX status enum (R47 — single source)

| Status | Meaning |
| --- | --- |
| `not-started` | No deliver activity for this PRD |
| `in-progress` | Deliver run active or feature branch not yet merged to `main` |
| `complete` | Target branch merged to default branch (merge detection, PRD 007 R53) |

The enum is enforced by `reconcile-status.sh set-index-status` and `wave_living_docs.py reconcile`.

## Link mechanism

| Signal | How |
| --- | --- |
| PR ↔ PRD | Branch `<type>/<slug>*`; PR body `prd:<slug>`; title word-boundary match on slug |
| Task progress | Read frozen task file checkboxes (**inputs**, not written by status) |
| Deliver run | `.cursor/sw-deliver-state.json` phase statuses + `completion` block |
| Shipped predicate | Merge detection on target branch **or** `completion.status: merged-complete` |

## Commands

```bash
bash scripts/reconcile-status.sh derive [--json]
bash scripts/reconcile-status.sh reconcile [--dry-run] [--require-merge]
bash scripts/reconcile-status.sh set-index-status --prd <NNN> --status <not-started|in-progress|complete>
bash scripts/reconcile-status.sh append-log-idempotent --prd <NNN> --phase <name> [--pr N] [--sha SHA] [--notes text]
bash scripts/reconcile-status.sh gap-resolve --absorbing-prd <NNN> [--pr N]
scripts/wave.sh living-docs reconcile [--commit]
scripts/wave.sh living-docs append-terminal [--commit]
scripts/wave.sh docs-currency
```

## INDEX reconciliation

Updates **Status** column only in `docs/prds/INDEX.md`. Frozen PRD/amendment bodies untouched.
`merge run-next` invokes `living-docs reconcile --commit` after each green phase merge (R51).

## Completion log (R48)

Append-only rows in `docs/prds/COMPLETION-LOG.md`. `append-log-idempotent` keys on PRD + phase + SHA so
resume never double-appends. Terminal prepare calls `living-docs append-terminal --commit` when all phases
are green.

## GAP-BACKLOG (R49)

`docs/prds/GAP-BACKLOG.md` remains hand-appendable for new gaps. Optional **Absorbed-by** column (PRD
number) marks which deliver PRD resolves an `open` row. `gap-resolve --absorbing-prd` flips matching rows to
`resolved` when that PRD reaches `complete`; non-matching gaps are untouched.

## Documentation-currency gate (R50)

`scripts/docs-currency-gate.sh` (via `scripts/wave.sh docs-currency`) hard-blocks the terminal merge gate
when the current run's INDEX row, COMPLETION-LOG entry, or absorbed gaps disagree with durable state.
Pre-existing unrelated historical drift does not block.

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
- Living-doc file edits commit on the feature branch in-loop (R51), never only in chat.
