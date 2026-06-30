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
