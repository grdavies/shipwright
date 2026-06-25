---
description: Enumerate and remove merged branches, stale worktrees, and terminal deliver run-state with dry-run default and explicit confirm. Does not delete unmerged work, in-flight deliver runs, or use rm -rf on worktrees.
alwaysApply: false
---

# `/sw-cleanup`

Standalone pruning for merged local/remote branches, stale worktrees, and completed deliver run-state.
Dry-run by default; deletions only after explicit confirmation.

## Scope

- Input: optional `--confirm --yes` to apply removals.
- Output: JSON report of `wouldRemove`, `protected`, and (on confirm) `removed` with reasons.
- Does **not** touch unmerged branches, the current/default branch, active worktrees, or in-flight deliver runs.

## Procedure

1. From repo root, run enumeration (default dry-run):

   ```bash
   bash scripts/cleanup.sh
   ```

2. Review the report: each protected item includes a reason (current/default, unmerged, indeterminate
   squash status, deliver lock, open merge journal, etc.).

3. To apply removals:

   ```bash
   bash scripts/cleanup.sh --confirm --yes
   ```

   Or set `SW_CLEANUP_CONFIRM=1` for non-interactive agent runs after human ack.

4. Worktree teardown uses `git worktree remove` + `git worktree prune` only — never `rm -rf`.

5. Remote branch deletion is guarded: indeterminate squash-merge status fails closed (branch protected).

## Merge detection (R56)

Branches are classified via, in order:

- `merge-base --is-ancestor` (regular merge / ff)
- empty `default..branch` log
- `git cherry` minus-only lines (squash-aware)
- `gh pr list --state merged` when `gh` is available
- otherwise **indeterminate** → protected (no delete)

## Guardrails

- Protects: current branch, default branch, unmerged branches, indeterminate merges, cwd worktree,
  orchestrator worktree during in-flight deliver (`verdict: running`, lock, or open merge journal).
- Never `rm -rf` worktree directories.
- Emit full report every run (`wouldRemove` + `protected` + `errors`).
- The deliver loop may suggest `/sw-cleanup` after detecting a merged feature branch — suggestion only;
  the human runs and confirms this command.
