---
id: gap-011-conductor-no-progress-regression-on-provision-an
type: gap
status: open
title: conductor no-progress regression on provision and merge-enqueue loops
visibility: public
tags: [source:feedback, signal:feedback-prd-041-retro-no-progress-regression-2026-07-01, prd-041, plugin-self]
source_pr: 284
absorbs: []
---

# conductor no-progress regression on provision and merge-enqueue loops

_Captured from PRD 041 post-merge retrospective (`feedback-prd-041-retro-no-progress-regression-2026-07-01`)._

## Summary

**Regression of GAP-062** (scheduled PRD 035 A1): during PRD 041 deliver, identical `nextAction` on
`provision-phase` and `merge-enqueue` repeated until `conductor:no-progress` halted the run. Recovery
required manual `noProgressStreak` reset, superseding `blockers.json`, and sometimes orphan worktree
teardown (see gap-009).

## PRD 041 evidence

- Multiple `conductor:no-progress` halts mid-run after phase 1 green.
- Occurred on both provision loops (orphan path) and merge-enqueue stalls (stale CI yellow on phase PRs).
- Stale CI (`feat-test-plan-doc-fixtures` stuck `IN_PROGRESS` with `conclusion: success`) blocked merge
  until empty-commit refresh — may amplify identical `nextAction` streaks.

## Relationship to existing backlog

| Item | Status |
|------|--------|
| **GAP-062** | scheduled PRD 035 A1 — **not fixed**; PRD 041 confirms recurrence |
| **GAP-049** | `no-progress` pre-empts `remediate → /sw-stabilize` — related interaction |
| **PRD 009 R38** | no-progress circuit breaker — working as designed but lacks differentiated recovery |

## Remediation direction

1. **Classify stall cause** before tripping budget halt: orphan worktree, merge-queue wait, CI external-wait
   — route to remediation path instead of identical-action streak.
2. **Auto-recover** `noProgressStreak` when underlying predicate changes (e.g. worktree adopted, CI refreshed).
3. **External-wait budget** for stale GitHub check state (distinct from true no-progress).
4. Fixture: `no-progress-differentiated-stall-causes` + `stale-ci-in-progress-success`.

## Schedule

Triage to **PRD 035 A1** deliver conductor completion or **PRD 027** phase-3 stall factors.
