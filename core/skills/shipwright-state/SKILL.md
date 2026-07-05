---
name: sw-shipwright-state
description: Per-worktree Shipwright state read/write contract. Resolves state path in the worktree gitdir; aggregates a read-only repo index from all worktrees.
---

# Per-worktree Shipwright state

Phase context lives in the **worktree gitdir**, not a shared repo-global file.


**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --skill shipwright-state`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Location

| Checkout | State path |
| --- | --- |
| Linked worktree | `.git/worktrees/<name>/shipwright.json` (via `git rev-parse --git-dir`) |
| Main / bare | `<git-dir>/shipwright.json` |

Resolve with:

```bash
python3 scripts/shipwright-state.py path
```

## Fields

| Field | Purpose |
| --- | --- |
| `parentBranch` | Real parent for diffs and PR base |
| `currentBranch` | Active phase branch |
| `phaseSlug` | Short phase identifier |
| `branchPrefix` | `feat` / `fix` / `docs` / … |
| `startedAt` | ISO timestamp |
| `issueNumbers` | Optional GitHub issues |
| `lastCommand` | Ship resume point |
| `phaseStatus` | `running` / `blocked` / `green` |
| `iteration` | Stabilize/ship iteration counter |
| `shipStartedAt` | Orchestrator start |
| `tier` | Work tier (quick/standard/heavy) |
| `workstream` | e.g. `implementation` |
| `scaffold` | Port/DB/deps from `/sw-worktree` |
| `worktreeName` / `worktreePath` | Provisioning metadata |
| `deliverIssueBatch` | **045 R74** — active deliver issue-batch journal path (under run dir) |
| `deliverRunId` | **045 R70** — original `runId` for batch resume (inherited on resume, never rotated) |

### Deliver issue-batch journal (PRD 045 R74/R70)

Multi-issue annotation and close operations persist an append-only journal under the phase run dir
(`.cursor/sw-deliver-runs/<phase>/issue-batch-journal.json`). Journal states mirror PRD 044 migration journal
(`pending` → `annotated` → `closed` | `skipped` | `failed`). Partial API failure →
`deliver-aborted-inconsistent` halt; resume inherits the original `deliverRunId` and upserts annotations
by deterministic marker hash (no duplicates).

```bash
python3 scripts/shipwright-state.py read   # inspect deliverIssueBatch + deliverRunId
```

Never commit journal files — they live under `.cursor/sw-deliver-runs/` (excluded by `/sw-commit`).

## Operations

```bash
python3 scripts/shipwright-state.py read
python3 scripts/shipwright-state.py write '{"phaseSlug":"auth-api","parentBranch":"main"}'
python3 scripts/shipwright-state.py index   # read-only aggregate — never write a shared index file
```

## Guardrails

- Commands read/write state only through this contract.
- Never commit `shipwright.json` or memory-sync markers.
- Two worktrees must never share or overwrite each other's state file.

Phase-mode deliver runs persist status under `.cursor/sw-deliver-runs/<phase-slug>/status.json` with `merge-ready-green` or `blocked` verdicts (PRD 046 phase ship).
