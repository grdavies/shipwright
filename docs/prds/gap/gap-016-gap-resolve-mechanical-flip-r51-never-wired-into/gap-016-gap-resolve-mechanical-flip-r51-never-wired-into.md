---
id: gap-016-gap-resolve-mechanical-flip-r51-never-wired-into
type: gap
status: resolved
title: Gap-resolve mechanical flip (R51) never wired into PRD-ship pipeline
visibility: public
tags: [source:feedback, signal:feedback-gap-lifecycle-flip-unwired-2026-07-01, prd-035, plugin-self]
source_pr: 284
absorbs: []
---

# Gap-resolve mechanical flip (R51) never wired into PRD-ship pipeline

_Captured from feedback signal `feedback-gap-lifecycle-flip-unwired-2026-07-01`, in response to an operator
question: "why does `/sw-feedback` suggest amendments to already-complete PRDs, and are identified gaps
actually being implemented?"_

## Summary

PRD 035 (`complete`) shipped two amendments, A1 and A2, whose frontmatter `absorbs:` lists 34 gaps
(GAP-012, 016, 021–030, 041–046, 048–052, 054, 057–062, 064, 068, 071–074) with an outcome table claiming
each flips to `resolved — PRD 035 A<k> R<n>`. **None of those `GAP-BACKLOG.md` rows were ever flipped** —
they all still read `scheduled | PRD 035 A1` / `PRD 035 A2` today, even though the absorbing PRD and both
amendments are `complete`.

Root cause: A2 R51 built `scripts/living-status-gap-resolve.py` to make the flip "mechanical... when the
absorbing unit reaches `complete`," but the script requires **manual invocation**
(`--absorbing-prd <n>`) — nothing in `/sw-deliver` finalize-completion, `/sw-ship`, or INDEX
status-derivation calls it when a PRD's status flips to `complete`. The mechanism passes its own fixture
(`gap-resolve-on-prd-ship`) in isolation but was never exercised against the real repo, so it never ran for
its own parent PRD. This is the same failure mode as GAP-043/046 themselves (backlog status not
mechanically kept in sync) — the fix for that problem is itself unwired.

A second, narrower defect compounds this: even where a fix genuinely shipped, backlog rows don't record
partial coverage. GAP-062's A1 fix (R31, `remediate_pending_for_state` in `wave_deliver_loop.py`) only
suppresses no-progress preemption for phases in `blocked` status awaiting `remediate` — it does not cover
`provision-phase` / `merge-enqueue` no-progress loops (PRD 041's actual failure mode, see `gap-011`). The
backlog row gives no signal that the fix is scoped narrower than the gap's original description.

A related, separate defect: `/sw-feedback`'s own routing (`core/commands/sw-feedback.md` Phase 2,
"Substantial scope → `/sw-amend`") names a target PRD/amendment without first checking the unit's consumer
status. `/sw-amend`'s authoring-guard preflight (PRD 032 R7/R8) mechanically refuses amend on `complete`
units and routes to a new `extends:`/`supersedes:` unit or a gap instead (`core/commands/sw-amend.md` line
20) — so `/sw-feedback` can (and did, in this session) hand the operator a dead-end dispatch target for
PRDs 027, 034, 035, 036, 042, all already `complete`.

## Evidence

- `docs/prds/035-planning-autonomy-and-orchestration/amendments/A1-deliver-conductor-completion.md`
  frontmatter `absorbs:` (30 gaps) vs. `docs/prds/GAP-BACKLOG.md` rows for GAP-021, GAP-022, GAP-062 (all
  still `scheduled | PRD 035 A1`).
- `docs/prds/035-planning-autonomy-and-orchestration/amendments/A2-gap-lifecycle-and-doc-format.md` R51/R52
  outcome table claims `GAP-043 → resolved — PRD 035 A2 R51` and `GAP-046 → resolved — PRD 035 A2 R52`;
  `docs/prds/GAP-BACKLOG.md` still shows both `scheduled | PRD 035 A2`.
- `scripts/living-status-gap-resolve.py` requires `--absorbing-prd` as a required CLI arg — no caller in
  `scripts/wave_deliver_loop.py`, `scripts/wave_compound.py`, or `scripts/reconcile.py` invokes it
  automatically on PRD completion.
- `scripts/wave_deliver_loop.py` R31 fix (`remediate_pending_for_state`) gates on
  `meta.get("status") == "blocked"` — no equivalent guard exists for `provision-phase` /
  `merge-enqueue` `nextAction` repeats (confirmed via `gap-009`, `gap-011`).
- `core/commands/sw-amend.md:20` — complete-unit refusal (R7/R8) confirmed as the mechanism that would have
  rejected the amendment targets suggested for PRDs 027/034/035/036/042 in this session's prior turn.

## Relationship to existing backlog

- **Supersedes-in-effect (not formally superseded):** GAP-043 and GAP-046 remain functionally open despite
  `docs/prds/GAP-BACKLOG.md` and the A2 outcome table implying closure. This gap captures the residual —
  the fix mechanism exists but has no trigger.
- **Refines gap-011** (`conductor no-progress regression on provision and merge-enqueue loops`) — GAP-062's
  A1 fix was scoped to `remediate`-pending phases only; gap-011's "regression" framing should read as
  "uncovered edge case within the same problem class," not a regression of shipped, working code.
- **New defect, not previously captured:** `/sw-feedback` routing naming amendment targets without a
  consumer-status pre-check.

## Suggested remediation direction (not prescriptive)

1. Wire `living-status-gap-resolve.py --absorbing-prd <n>` into the point where a PRD's INDEX status is
   derived/set to `complete` (`scripts/reconcile.py set-index-status`, or `finalize-completion` in
   `scripts/wave_deliver_loop.py`) so the flip is automatic, not a step someone has to remember.
   Retroactively run it for PRD 035 (and any other `complete` PRD with unresolved absorbed rows) as a
   one-time backlog housekeeping pass.
2. Add a `docs-currency-gate.py` (or equivalent) check that flags `GAP-BACKLOG.md` rows still `scheduled`
   against an absorbing unit whose INDEX status is `complete`, so drift is caught in CI rather than
   discovered by an operator months later.
3. `/sw-feedback` Phase 2 routing: before naming an `/sw-amend` target, check the candidate unit's consumer
   status (reuse `authoring-guard.py preflight` in dry/check mode) and route directly to the
   `extends:`/`supersedes:`/gap path when the target is `complete`, instead of surfacing a target that
   `/sw-amend` will refuse.
4. When a gap's fix ships with narrower scope than the original report, record that in the backlog row
   (e.g. `resolved — PRD 035 A1 R31 (remediate-pending phases only)`) rather than a bare `resolved`, so
   future retrospectives can tell "fixed" from "partially fixed."

## Schedule

`open` — no owning PRD/amendment yet. Recommend triage to a small, targeted fix (housekeeping script wiring
+ `/sw-feedback` routing check) rather than a new PRD; scope is mechanical, not a design decision.

