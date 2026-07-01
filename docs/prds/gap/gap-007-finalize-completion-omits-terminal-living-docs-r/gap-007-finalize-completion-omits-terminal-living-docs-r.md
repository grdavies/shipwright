---
id: gap-007-finalize-completion-omits-terminal-living-docs-r
type: gap
status: open
title: finalize-completion omits terminal living-docs reconcile so INDEX stays in-progress
visibility: public
tags: [source:feedback, signal:feedback-index-status-stale-after-deliver-complete-2026-06-30]
---

# finalize-completion omits terminal living-docs reconcile so INDEX stays in-progress

_Captured from feedback signal `feedback-index-status-stale-after-deliver-complete-2026-06-30`._

## Relationship to PRD 009 A1 R47–R51 and PRD 033 A1 R29

PRD 009 amendment A1 requires INDEX status to reflect merge state mechanically (R47) and living-doc updates
to be committed in-loop (R51). PRD 033 A1 R29 makes git-primary `complete` derivation authoritative. The
**implementation** updates INDEX via `wave_living_docs.py reconcile` → `set-index-status`, but only from
**phase merge** (`wave_merge.py:merge-run-next`) — not from the **terminal** `finalize-completion` step.

## Evidence (validated in code, reproduced for PRDs 039 and 043)

**Merged to `main` but INDEX stale:**

| PRD | Slug | Terminal PR | INDEX on `main` (2026-06-30) |
|-----|------|-------------|------------------------------|
| 039 | loop-quality-gates | #272 (merged) | `in-progress` |
| 043 | issue-backed-planning-store | #268 (merged) | `in-progress` |

**Root cause — terminal path never reconciles INDEX:**

`wave_deliver_loop.py` `finalize-completion` runs `completion finalize-if-merged` and
`inflight_signal run-complete`, then cleanup — **no** `living-docs reconcile`:

```1975:2015:scripts/wave_deliver_loop.py
    if action == "finalize-completion":
        ec, data = run_wave(root, "completion", "finalize-if-merged")
        ...
        clear_ec, clear_data = run_inflight_signal(root, *clear_args)
        ...
        return result  # no living-docs reconcile
```

**Why phase merges are insufficient:** `living-docs reconcile` *is* invoked after each phase merge
(`wave_merge.py` ~L1259), but `derive_index_status()` only returns `complete` when
`target_merge_detected()` is true (feature branch merged to `defaultBaseBranch`):

```74:83:scripts/wave_living_docs.py
def derive_index_status(state, merged_to_main):
    ...
    if merged_to_main:
        return "complete"
    ...
    return "in-progress"
```

Before terminal merge, every phase reconcile correctly writes `in-progress`. After terminal merge,
`finalize-if-merged` sets `merged-complete` in run-state but **nothing** re-runs reconcile with
`merged_to_main=True` to flip the INDEX row to `complete`.

**Stale docs worktree corroboration:** `.sw-worktrees/docs-inflight-run-complete-main-index` (provisioned
2026-06-30 during concurrent `/sw-feedback` on a different signal) still shows PRDs 039/043 as
`in-progress` — branched before manual corrections and never receiving terminal reconcile.

## Why manual INDEX edits fail closed

Operators who patch `docs/prds/INDEX.md` on `main` directly (or leave edits uncommitted on the primary
checkout) split INDEX state across main vs docs worktrees — exactly the failure mode observed when
consolidating PR #273. The sanctioned path is `set-index-status` via `living-docs reconcile --commit` on a
docs/orchestrator worktree after merge.

## Remediation

**PRD 046 A2** (`amendments/A2-terminal-index-status-reconcile-on-finalize-completion.md`): require
`finalize-completion` to invoke `living-docs reconcile --commit` (with orchestrator worktree) immediately
after successful `finalize-if-merged`, before `inflight_signal run-complete`.

**Note:** Open PR #273 may carry a different `gap-007` / A2 on the same PRD — renumber on merge to avoid
duplicate gap ids (this unit vs inflight-signal commit guard).
