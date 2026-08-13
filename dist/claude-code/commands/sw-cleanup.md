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
   python3 scripts/cleanup.py
   ```

2. Review the report: each protected item includes a reason (current/default, unmerged, indeterminate
   squash status, deliver lock, open merge journal, etc.).

3. **Agent-driven confirm** (default apply path):

   - After the dry-run report, the agent presents the `wouldRemove` set and asks the user to confirm
     (e.g. yes / proceed) before applying removals.
   - On explicit ack only, the agent runs:

     ```bash
     python3 scripts/cleanup.py --confirm --yes
     ```

     Or sets `SW_CLEANUP_CONFIRM=1` for the same invocation after human ack.
   - Declined, silent, or ambiguous responses → **no apply**; dry-run report stands.

   **Manual escape hatch** — user may run confirm directly without the agent:

   ```bash
   python3 scripts/cleanup.py --confirm --yes
   ```

4. Worktree teardown uses `git worktree remove` + `git worktree prune` only — never `rm -rf`.

5. **Refusal ledger purge (PRD 082 R26)** — dry-run enumerates operator-local refusal ledger entries
   under `.cursor/sw-refusal-ledger` (or configured `planning.refusalLedger.path`) as
   `refusal-ledger-entry` candidates. Confirm applies `planning_refusal_ledger_cli.py purge` semantics
   (journaled eviction). **Reconciling a refused write is a human decision** — cleanup never replays
   refused mutations automatically.

6. **Scoped in-flight protection (PRD 062 R10/R11; PRD 094 R10–R11/R15)** — deliver run-state enumeration
   scopes inflight checks to the **active run/worktree** (`_run_in_active_scope` + `_scoped_run_inflight`).
   Unrelated scoped runs with terminal verdicts do not block orchestrator cleanup. Non-terminal verdicts
   protected: `running`, `blocked`, `halted`, `watching` (shared `RESUMABLE_DELIVER_VERDICTS` constant).

   **String-or-object `target` (R10):** scoped state may record `target` as a feature branch string
   (`"feat/<slug>"`) or an object with a `branch` field. Enumeration and inflight checks route through
   `wave_state.target_branch_from_state` — never assume dict-only shape (string targets must not raise
   `AttributeError` during cleanup dry-run).

   **Breadcrumb fail-closed (R11/R15):** legacy migration breadcrumbs (`migrated: true` on
   `sw-deliver-state.json` with `scopedPath`) widen protection when the followed scoped file is missing,
   still a breadcrumb, or points at a stale branch while a **live** non-terminal scoped run exists on another
   target. Unresolvable breadcrumb scoped files are protected as `run-state` candidates rather than pruned
   silently.

   Dry-run is **terminal-class only** for `cleanup.autonomy: auto` — autonomous apply deletes only when
   deliver `verdict` ∈ `{complete, rejected}` and merge detection is not `indeterminate`.

7. **Autonomous apply (R25/R26)** — when `cleanup.autonomy` is `auto` in
   `.cursor/workflow.config.json`, a deterministic post-merge path may apply the dry-run `wouldRemove` set
   without human confirm when: no in-flight **scoped** deliver run, merge status is not `indeterminate`, and
   targets are not the current/default branch. Invocation:

   ```bash
   python3 scripts/cleanup_lib.py "$(git rev-parse --show-toplevel)" --autonomous
   ```

   `indeterminate` merge status always falls back to the human gate (step 3).

8. Remote branch deletion is guarded: indeterminate squash-merge status fails closed (branch protected).

## Merge detection (R56)

Branches are classified via, in order:

- `merge-base --is-ancestor` (regular merge / ff)
- empty `default..branch` log
- `git cherry` minus-only lines (squash-aware)
- `python3 scripts/sw_bootstrap.py host.py -- pr-list --state closed` when host token is available
- otherwise **indeterminate** → protected (no delete)

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-cleanup`.

## Guardrails

- Protects: current branch, default branch, unmerged branches, indeterminate merges, cwd worktree,
  orchestrator worktree during in-flight deliver (`verdict: running`, lock, or open merge journal).
  When an orchestrator worktree is provisioned, cleanup reads deliver state from that worktree when it
  is newer or terminal — stale `verdict: running` copies at repo root do not block pruning.
- Never `rm -rf` worktree directories.
- Emit full report every run (`wouldRemove` + `protected` + `errors`).
- The deliver loop may suggest `/sw-cleanup` after detecting a merged feature branch — suggestion only;
  the agent runs dry-run then applies on explicit user ack (or the user runs the manual escape hatch).
