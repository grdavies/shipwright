---
name: sw-living-status
description: Derive PRD status from git and deliver state; reconcile planning INDEX derived region, COMPLETION-LOG, and legacy gap projections; hard-block on drift.
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
python3 scripts/planning-graph.sh / planning_graph.py <repo> reconcile [--dry-run]
python3 scripts/planning-graph.sh / planning_graph.py <repo> doctor
python3 scripts/wave_deliver.py <repo> next
```

## INDEX reconciliation

Archived units render in `docs/prds/INDEX-archive.md`. **Planning INDEX** (`docs/planning/INDEX.md`): `planning-graph reconcile` owns the `derived` region; deliver owns `inFlight` (read-only to reconciler). **Legacy PRD INDEX** (`docs/prds/INDEX.md`): projected table during cutover; `reconcile-status.sh` may update Status column for deliver-era rows. Frozen PRD/amendment bodies untouched.
`merge run-next` invokes `living-docs reconcile --commit` after each green phase merge (R51).

## Completion log (R48)

Append-only rows in `docs/prds/COMPLETION-LOG.md`. `append-log-idempotent` keys on PRD + phase + SHA so
resume never double-appends. Terminal prepare calls `living-docs append-terminal --commit` when all phases
are green.

## Gap units and legacy GAP-BACKLOG (PRD 033 R15/R49)

Canonical gaps live under `docs/planning/gap/<unit-id>/`. Status flips are mechanical via `absorbs:` edges
and the maintenance reconciler — not manual edits to `docs/prds/GAP-BACKLOG.md`. During the cutover window
`GAP-BACKLOG.md` is a **read-only legacy projection** (frontmatter-only). Trivial `/sw-feedback` gaps use
`planning_gap_capture.py`; substantial gaps route to `/sw-amend`.

Legacy `gap-resolve --absorbing-prd` applies only before `planningDir` cutover.

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


## GAP-BACKLOG append protocol (A2 — R51–R53)

Binary status contract: `open` | `scheduled` | `resolved` with schedule in the Schedule column.
Mechanical flips route through `scripts/gap-backlog.sh` only:

- **Freeze** (`absorbs:` frontmatter) → `open` → `scheduled` (`PRD NNN` or `PRD NNN Ak`).
- **PRD ship / complete** → `scheduled` → `resolved` via `living-status-gap-resolve.sh`.

Append protocol: next ID is max(`GAP-NNN`)+1, never reuse; cross-links use `GAP-NNN` not row numbers.
`gap-backlog.sh list --json` and `gap-backlog.sh check` power the docs-currency integrity guard.

## Guardrails

- Never modify frozen PRD/amendment files.
- Re-running derive → reconcile is idempotent for same git facts.
- Living-doc file edits commit on the feature branch in-loop (R51), never only in chat.
- Manual edits to generated legacy `GAP-BACKLOG.md` / `INDEX.md` projections trigger `planning-graph doctor` warnings.

## Post-merge playbook (A1 — R29–R36)

### Derived status precedence (R29, R32)

1. **Git ancestry** on `defaultBaseBranch` (and host PR merge metadata when available) is the authoritative `complete` signal for non-gap units.
2. **Slug-scoped deliver state** is secondary corroboration only.
3. **COMPLETION-LOG** is audit-only — never the sole `complete` predicate.
4. **Stale local feature branches** MUST NOT downgrade a terminal row when git/host evidence still shows merged.

### Monotonic terminal status (R30)

`complete` and `superseded` rows in the planning INDEX `derived` region never regress during reconcile unless an explicit `--override-status <id> <from> <to> --reason <text>` names the unit.

### Default-branch reconcile refusal (R31)

`planning-graph reconcile` and legacy `reconcile-status.sh reconcile` **refuse to commit** on `defaultBaseBranch`. Allowed post-merge paths:

- **Single unit:** `set-index-status` + `append-log-idempotent` on a **docs branch**.
- **Full corpus:** reconciler on a non-default branch, or deliver `completion finalize-if-merged` — never bare full-corpus `reconcile` on `main`.

### Completion finalize chokepoint (R33–R34)

Only `bash scripts/wave.sh completion finalize-if-merged` may set `completion.status: merged-complete`. Out-of-band state writes are rejected at the save guard.

