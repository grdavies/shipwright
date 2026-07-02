---
id: gap-009-failed-phase-provision-leaves-orphan-worktree-wi
type: gap
status: resolved
schedule: PRD 050
resolvedBy: PRD 050
title: Failed phase provision leaves orphan worktree without phaseWorktrees state
visibility: public
tags: [source:feedback, signal:feedback-prd-041-retro-orphan-worktree-2026-07-01, prd-041, plugin-self]
source_pr: 284
absorbs: []
---

# Failed phase provision leaves orphan worktree without phaseWorktrees state

_Captured from PRD 041 post-merge retrospective (`feedback-prd-041-retro-orphan-worktree-2026-07-01`)._

## Summary

When `phase provision` fails after creating a worktree path on disk but before persisting
`phaseWorktrees[<id>]` in durable deliver state, the next `provision-phase` iteration hits
`worktree path already exists`. The driver repeats the same `nextAction`, tripping
`conductor:no-progress` (`budgetHalt`) until manual teardown and state patch.

## PRD 041 evidence

- Phase 1 (`shared-writer-capture-surfaces`) left
  `.sw-worktrees/self-improving-loop-phase-shared-writer-capture-surfaces` and branch
  `feat/self-improving-loop-phase-shared-writer-capture-surfaces` without a `phaseWorktrees` entry.
- Recovery required: `worktree.py teardown`, `git branch -D` on orphan branch, manual state reset
  (`verdict: running`, `noProgressStreak: 0`), then resume `/sw-deliver run`.

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **PRD 027** task 4.1 | Asserts canonical `phaseWorktrees` on repo-root state — does not cover orphan-on-partial-provision |
| **GAP-042** (scheduled) | `status.json` path skew under background dispatch — related but distinct |
| **GAP-062** (scheduled) | `no-progress` symptom — this gap is a **root cause** for one recurrence class |

## Remediation direction

1. **Fail-closed provision:** if worktree path exists but state lacks `phaseWorktrees[id]`, auto-reconcile
   (adopt existing path into state) or deterministic teardown-before-retry — never loop identical `nextAction`.
2. **Pre-dispatch guard:** refuse `dispatch-ship` until `phaseWorktrees` records the provisioned path.
3. Fixture: `orphan-phase-worktree-adopt-or-teardown` under deliver suite.

## Schedule

Triage to **PRD 027** (terminal finalization robustness) or a focused amendment if 027 scope is frozen.
