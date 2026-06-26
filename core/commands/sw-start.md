---
description: Start a child phase branch inside the current worktree and record parent context in per-worktree state. Does not push or open a PR.
alwaysApply: false
---

# `/sw-start`

Create a phase child branch from the current branch **inside the active worktree** and record context in
per-worktree state (`scripts/shipwright-state.sh`).

## Branch prefix

| Prefix | Use when |
| --- | --- |
| `feat/` | New capability (default) |
| `fix/` | Bug/regression |
| `hotfix/` | Critical production |
| `release/` | Release prep |
| `docs/` | Documentation only |

Shape: `<prefix>/<stem>-phase-<slug>` — no nested refs (`feat/foo/phase-bar` when `feat/foo` exists).

## Procedure

1. Read `workflow.config.json`; resolve state via `skills/shipwright-state`.
2. Print persisted trunk base disclosure: `bash scripts/resolve-base-branch.sh disclose --quiet` (when available).
3. Run `bash scripts/sw-assert-worktree.sh` — exit `1` blocks phase start on bare default branch without a
   linked worktree; exit `2` is a configuration error. If blocked, `/sw-worktree provision` first.
4. `git branch --show-current` — stop on detached HEAD.
5. `memory-preflight` read only on non-routine parent/prefix decisions.
6. Load `agentsFile` before choosing prefix.
7. Parent = current branch. Trunk base for forks/PRs comes from `bash scripts/resolve-base-branch.sh resolve`
   (persisted at workflow entry — distinct from integration base `<type>/<slug>` for phase stacking).
8. Confirm dirty tree belongs on the new phase branch.
9. `git checkout -b <prefix>/<stem>-phase-<slug>`.
10. `bash scripts/shipwright-state.sh write` with `parentBranch`, `currentBranch`, `phaseSlug`, `branchPrefix`, `startedAt`, optional `issueNumbers`.
11. Report branch + next `/sw-execute`.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --command sw-start`.

## Guardrails

- Branch from current branch within the worktree only.
- State is per-worktree — never a repo-global file.
- Does not push, commit, or open PR.
