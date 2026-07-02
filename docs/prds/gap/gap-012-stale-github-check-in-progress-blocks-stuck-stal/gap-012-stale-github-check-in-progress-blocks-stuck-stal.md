---
id: gap-012-stale-github-check-in-progress-blocks-stuck-stal
type: gap
status: resolved
schedule: PRD 050
resolvedBy: PRD 050
title: Stale GitHub check IN_PROGRESS blocks stuck-stale while UI shows green
visibility: public
tags: [source:feedback, signal:feedback-prd-041-stale-ci-yellow-2026-07-01, prd-041, plugin-self]
source_pr: 280
absorbs: []
---

# Stale GitHub check IN_PROGRESS blocks stuck-stale while UI shows green

_Captured from PRD 041 deliver observation (`feedback-prd-041-stale-ci-yellow-2026-07-01`)._

## Summary

Phase 1 PR #280 showed **53 successful checks** in the GitHub UI while `check-gate.py` reported **yellow**
because `feat-test-plan-doc-format-fixtures` remained `IN_PROGRESS` with workflow `conclusion: success`.
Deliver blocked with `status.json` `ci:yellow-pending-*` despite effective green CI.

`classify_stuck_stale` (`status_integrity.py`) requires `merge_authorizing(gate_ec, gate)` — gate must be
**green** before stuck-stale classification runs. Yellow gate → `live-evidence-not-green` → no auto-recovery
path except manual empty-commit push or `/sw-stabilize`.

## PRD 041 evidence

- Sub-agent `/sw-ship --phase-mode` ran `gh pr checks 280 --watch --interval 25` (blocking watch).
- Agent noted chicken-and-egg: stale API prevents stuck-stale; stuck-stale cannot run until gate green.
- Workaround: empty commit push refreshed check state; risked remediation budget exhaustion (2/2).

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **PRD 036** task on `stuck-stale` SHA equality | Covers classification preconditions, not stale `IN_PROGRESS`+`success` |
| **gap-011** / GAP-083 | no-progress during merge-enqueue — symptom when yellow persists |
| **GAP-049** | verify:failed vs remediate routing — adjacent |

## Remediation direction

1. **Stale-check detector in `check-gate.py`:** when workflow run `conclusion == success` but check status
   `IN_PROGRESS` beyond TTL → treat as green or `environmental` (exit 10), not blocking yellow.
2. **Allow stuck-stale on yellow** when workflow conclusion + head SHA quiescence prove tip is settled.
3. **Ban blocking `gh pr checks --watch`** in phase ship; use `check-gate.py` poll with backoff (host.py).
4. Fixture: `stale-in-progress-success-check-gate-green`.

## Schedule

Triage to **PRD 036** (delivery conductor remediation) or **PRD 016** (CI enforcement).
