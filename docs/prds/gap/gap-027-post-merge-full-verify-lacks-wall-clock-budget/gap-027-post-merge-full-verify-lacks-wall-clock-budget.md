---
id: gap-027-post-merge-full-verify-lacks-wall-clock-budget
type: gap
status: scheduled
schedule: PRD 055
title: Post-merge full verify lacks wall-clock budget and progress signal
visibility: public
tags: [source:feedback, signal:feedback-prd054-verify-timeout-2026-07-04, prd-054, verify, deliver, testing]
absorbs: []
---

# Post-merge full verify lacks wall-clock budget and progress signal

_Scheduled to **PRD 055** (amendment A1, Thread F)._

_Captured from feedback signal `feedback-prd054-verify-timeout-2026-07-04` during PRD 054 terminal deliver._

## Summary

PRD 054 introduced scoped verify (`fast` / `phase` / `full`), but **post-merge and terminal integration
paths** still invoke `_runner.py verify --scope full`. During PRD 054 dogfood, post-merge verify **hung
~40 minutes** with no progress signal until the operator killed it; local full-suite runs became the
practical gate.

Unlike deliver phase work, verify has no equivalent of `deliver.watchdog.phaseTimeoutMinutes`.

## Evidence

| Path | Behavior |
|------|----------|
| `_runner.run_verify` | `run_pytest_scope(scope="full")` then sequential `run_manifest` |
| Post-merge widen | Forces `full` scope despite PRD 054 phase default |
| Manifest loop | No heartbeat between 127+ suite modules |

## Remediation direction

1. Add `verify.watchdog.maxMinutes` with consolidated halt report (mirror deliver R37).
2. Per-suite progress with elapsed wall clock in `_runner.run_manifest`.
3. Default post-merge verify to scoped path when merge-base diff allows.
4. Fixture `verify-watchdog-exhaustion` proves halt includes resume command and last suite id.

## Acceptance

- Verify exceeding budget emits consolidated halt, not silent hang.
- Operator sees running suite id and elapsed time during full verify.
- Document knob in `docs/guides/testing.md` and workflow config schema.
