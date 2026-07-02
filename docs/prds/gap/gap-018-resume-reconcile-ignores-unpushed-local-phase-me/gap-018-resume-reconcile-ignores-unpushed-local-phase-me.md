---
id: gap-018-resume-reconcile-ignores-unpushed-local-phase-me
type: gap
status: scheduled
schedule: PRD 050 A4
title: resume-reconcile ignores unpushed local phase merges when remote tip exists
visibility: public
tags: [source:feedback, prd-050-a4, signal:feedback-prd-051-deliver-observations-2026-07-02, prd-051, deliver, resume-reconcile]
source_pr: 51
absorbs: []
---

# resume-reconcile ignores unpushed local phase merges when remote tip exists


_Scheduled to PRD 050 A4 (`docs/prds/050-deliver-concurrency-cwd-terminal-robustness/amendments/A4-resume-reconcile-unpushed-local-merge-ground-tip.md`)._

_Captured from feedback signal `feedback-prd-051-deliver-observations-2026-07-02` during PRD 051 deliver._

## Summary

During PRD 051 deliver, phase 3 was already merged into the target branch **locally** but
`wave_terminal.py resume reconcile` did not promote it to `green-merged`. The operator manually
updated run-state and continued the deliver loop.

Root cause: `cmd_resume_reconcile` sets `ground_tip = remote_tip or local_tip` and tests merge
ancestry only against that tip. When a remote ref exists but is **behind** the local target branch
(unpushed local merges), `ground_tip` is the stale remote tip — not the local tip that actually
contains the phase merge.

## Evidence

`scripts/wave_terminal.py` (`cmd_resume_reconcile`, ~L688–735):

```python
remote_tip = resolve_ref(top, remote_ref_name)
local_tip = resolve_ref(top, target)
ground_tip = remote_tip or local_tip
# ...
merged_on_remote = is_ancestor(phase_sha, ground_tip, top)
# pending phases promoted only when merged_on_remote is true
```

When `remote_tip` is present but does not include a locally merged phase:

- `ground_tip` stays at the stale remote SHA.
- `merged_on_remote` is false for a phase that **is** merged into `local_tip`.
- Phase remains `pending` instead of promoting to `green-merged`.

The existing fixture `deliver-phase-resume-reconcile` passes because it uses `--no-fetch` in an
isolated temp repo with **no remote** — so `ground_tip` falls through to `local_tip`. The bug only
surfaces in real deliver runs where fetch succeeds and local target is ahead of remote.

## Operator workaround

Manually set the phase status to `green-merged` in `.cursor/sw-deliver-state.json` (or push the
target branch so remote tip catches up, then re-run `resume reconcile`).

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **PRD 027 R29/R50** | Remote pushed tip as ground truth — current implementation over-applies this when local is strictly ahead |
| **gap-006 / PRD 049 / PRD 050** | Operator worktree / cwd contract — separate from this resume logic bug |
| **gap-011** | No-progress loops — different failure mode |

## Remediation direction

1. When both tips exist, use `max(local_tip, remote_tip)` by commit time or merge-base walk — or
   promote when `is_ancestor(phase_sha, local_tip)` **or** `is_ancestor(phase_sha, remote_tip)`.
2. Surface `cause: resume:unpushed-local-merge` on **pending** phases (not only demotion of stale
   `green-merged`) with remediation hint to push target branch.
3. Extend `deliver-phase-resume-reconcile` fixture with a remote-ahead-of-local-negative case.
