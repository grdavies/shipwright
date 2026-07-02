---
id: gap-010-durable-deliver-state-loss-blocks-finalize-compl
type: gap
status: resolved
schedule: PRD 050
resolvedBy: PRD 050
title: Durable deliver state loss blocks finalize-completion resume on bare main
visibility: public
tags: [source:feedback, signal:feedback-prd-041-retro-state-loss-finalize-2026-07-01, prd-041, plugin-self]
source_pr: 284
absorbs: []
---

# Durable deliver state loss blocks finalize-completion resume on bare main

_Captured from PRD 041 post-merge retrospective (`feedback-prd-041-retro-state-loss-finalize-2026-07-01`)._

## Summary

After terminal PR #284 merged to `main`, `.cursor/sw-deliver-state.self-improving-loop.json` was absent.
Resuming `/sw-deliver run` from bare `main` failed with:

```json
{ "verdict": "fail", "error": "cannot save deliver state without feature target branch" }
```

`completion finalize-if-merged` also failed (`completion not in completed-pending-merge state`).
Operators had to run post-merge INDEX bookkeeping manually (docs PR #285).

## PRD 041 evidence

- All four phase PRs (#280–#283) merged; terminal #284 merged at `8cf2e91`.
- Durable state and run logs cleared before `finalize-completion` completed.
- `completion check-merge` returned `no-target-branch` with no state file present.

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **gap-007** | `finalize-completion` omits terminal `living-docs reconcile` — INDEX stayed stale until manual docs PR |
| **GAP-055** / **GAP-065** (scheduled, PRD 033 A1) | Post-merge finalize guard + squash detection — scheduled but not shipped |
| **GAP-063** (resolved) | Orchestrator vs repo-root state skew — different failure mode (state **gone**, not stale) |
| **PRD 046 A2** | Amendment for terminal INDEX reconcile on finalize — not yet implemented |

## Remediation direction

1. **Terminal finalize must be idempotent:** after merge detection via host API (`terminalPr.number`),
   `finalize-completion` succeeds even when scoped state was cleared, as long as merge is confirmed.
2. **Never require feature branch to persist terminal bookkeeping** on resume from `main`.
3. Wire **PRD 046 A2** (`living-docs reconcile --commit`) into `finalize-completion` so INDEX/COMPLETION-LOG
   do not depend on a follow-on docs PR.
4. Fixture: `finalize-resume-after-state-cleared-post-merge`.

## Schedule

Triage to **PRD 046 A2** + **PRD 027** (finalize robustness); cross-link gap-007.
