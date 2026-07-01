---
date: 2026-07-01
amends: docs/prds/050-deliver-concurrency-cwd-terminal-robustness/050-prd-deliver-concurrency-cwd-terminal-robustness.md
absorbs: [gap-004-dispatch-binding-preflight-broken-bash-invokes-p]
frozen: true
frozen_at: 2026-07-01
visibility: public
---

# Amendment A2: Unregistered parent-model tier fallback & gap-004 closure

## Overview

`gap-004` captured three stacked dispatch/push defects from the PRD 042 `.sh`→`.py` migration (2026-06-30).
**Defects A and C are already fixed on `main`** (2026-06-30 direct fix + regression fixtures); **Defect B remains
open** — `scripts/dispatch-check.py` fails closed with `binding:no-model` whenever the interactive parent
session's concrete model id is not an exact value in `models.tiers`, blocking every delegated Task dispatch from
orchestrators (`/sw-doc`, `/sw-deliver`, etc.) even when no reviewer tier-floor check applies.

The natural amendment home was **PRD 024 A3** (dispatch-binding lineage from A2 R38/R39). PRD 024 is
`complete`; `authoring_guard.py` refuses in-place amend on complete units (PRD 032 R7/R8). Per operator
direction, this amendment re-hosts the preserved worked design from `gap-004` on the amendable parent **PRD
050**, which already extends dispatch-preflight robustness in **A1** (R25/R28 — `wave_preflight.py` /
`before_task_dispatch.py` worktree alignment).

This amendment adds **R34–R42** (Defect B fix + Defect A/C verification closure). It does not modify the
parent file or A1.

## Context

**Defect A (closed on `main`, verify here):** eleven `["bash", …, "<script>.py"]` call sites were corrected to
`sys.executable`; `resolve-model-tier.py` gained `argparse` parity with `resolve-intensity.py`;
`scripts/zero-shell-guard.py` `find_bash_py_invocations()` is wired into `main()`; fixture
`scripts/test/bash-py-invocation-guard.test` exists and passes — but neither fixture is registered in
`core/sw-reference/pr-test-plan.manifest.json` today.

**Defect C (closed on `main`, verify here):** `scripts/git-push.py` subprocess-invokes `secret-scan.py`
(canonical chokepoint); fixture `scripts/test/git-push-secret-scan-chokepoint.test` exists and passes — also
unregistered in the manifest.

**Defect B (open):** `dispatch-check.py` lines 50–59 treat `parent_rank is None` as unconditional failure.
Interactive IDE model picks (e.g. models outside the four `models.tiers` routing entries) therefore block all
delegated atomics, not only reviewer/native-panel tier-floor checks (lines 68–79). PRD 012 R9 and PRD 024 A2
R39 fixed command-authoritative child resolution; they did not define failure mode for unregistered *parent*
models.

## Goals

1. Delegated non-reviewer atomics (`sw-prd`, `sw-tasks`, doc-chain commands) proceed when the parent model is
   not listed in `models.tiers`, with a logged advisory — no `binding:no-model` halt.
2. Reviewer/native-panel dispatches that consume `parent_rank` for the builder-tier floor retain fail-closed
   behavior when parent tier cannot be resolved, unless `dispatch.unregisteredParentModelTier` supplies an
   explicit fallback.
3. Defect A/C regression fixtures are registered as required PR CI entries so the fixed state cannot silently
   regress.
4. `gap-004` closes to `resolved` when R34–R42 ship with green fixtures — not narrative closure.

## Non-Goals

- Re-opening or editing PRD 024, PRD 012, or PRD 042 in place.
- Extending `models.tiers` to enumerate every IDE-selectable model (Decision D-A2-3).
- Platform-metadata auto-resolution of parent tier (gap-004 Open Question option c) — deferred.
- Re-implementing PRD 024 A2 parallel preflight (R38) or command-tier binding (R39).
- Changing child `modelId`/`tier` resolution in `wave_preflight.py` beyond what A1 already owns.

## Requirements

### Thread E — gap-004 Defect A/C verification (already fixed; register + gate)

- **R34** (origin: gap-004 Defect A) — `scripts/test/bash-py-invocation-guard.test` MUST be registered as
  `required` in `core/sw-reference/pr-test-plan.manifest.json` with a stable `ciJobName`; CI workflow MUST be
  regenerated via `scripts/generate-pr-test-plan-ci-workflow.py` when the manifest changes.
- **R35** (origin: gap-004 Defect C) — `scripts/test/git-push-secret-scan-chokepoint.test` MUST be registered
  the same way (R34/R35 may land in the same manifest PR as parent Thread A fixtures or as a focused follow-on
  commit in the same deliver run).
- **R36** (origin: gap-004 Defect A) — `scripts/zero-shell-guard.py` `find_bash_py_invocations()` MUST remain
  wired into the guard's issue list (no regression to warn-only for bash-invokes-py hits in `fail` mode).

### Thread F — gap-004 Defect B (unregistered parent model tier)

- **R37** (origin: gap-004 Defect B; D-A2-1) — `scripts/dispatch-check.py` MUST NOT fail closed at
  `binding:no-model` solely because `model_to_tier(parent_model)` returned `None` when the dispatch is **not**
  reviewer-bound (`sw-*-reviewer`) and **not** native-panel-bound (the same agent set as parent lines 62–66).
  Non-bound dispatches MUST `pass` with `parentTier: null` and an advisory log line on stderr
  (`binding:unregistered-parent-advisory`).
- **R38** (origin: gap-004 Defect B; D-A2-1) — For reviewer-bound or native-panel-bound dispatches where
  `parent_rank` is required for the builder-tier floor check, when `model_to_tier(parent_model)` is `None` and
  `dispatch.unregisteredParentModelTier` is **unset**, behavior MUST remain today's fail-closed
  (`binding:no-model`, exit `20`).
- **R39** (origin: gap-004 Defect B; D-A2-1) — `core/sw-reference/config.schema.json` and
  `.cursor/workflow.config.example.json` MUST add optional `dispatch.unregisteredParentModelTier` (semantic tier
  name ∈ `{cheap, build, mid, deep}`). When set and parent model is unregistered, `dispatch-check.py` MUST
  resolve `parent_tier` from this fallback for floor checks only; an invalid value MUST fail with distinct cause
  `binding:invalid-fallback-tier` (not `binding:no-model`).
- **R40** (origin: gap-004 Defect B) — `core/rules/sw-subagent-dispatch.mdc` and
  `core/commands/sw-doc.md` delegated Task binding prose MUST document the unregistered-parent advisory path
  (R37) and the optional config fallback (R39); emitter parity via `build-chain-sync.py` when `core/` changes.
- **R41** (origin: gap-004 Defect B) — Fixture `dispatch-unregistered-parent-delegated-atomic-passes`: parent
  model id absent from `models.tiers`, agent `sw-prd` (or equivalent non-reviewer delegated atomic),
  `--command sw-prd` — assert `verdict: pass`, no exit `20`.
- **R42** (origin: gap-004 Defect B) — Fixture `dispatch-unregistered-parent-reviewer-fails-closed`: parent
  model unregistered, native-panel agent (e.g. `correctness`), fallback unset — assert `binding:no-model`; second
  case with `dispatch.unregisteredParentModelTier: deep` — assert floor check uses fallback and passes when
  parent rank satisfies builder tier.

## Technical Requirements

- **TR18** (R37–R39) — Refactor `dispatch-check.py` tier resolution into testable helpers; keep JSON stdout
  contract stable for passing cases; add `parentTierFallbackUsed: true|false` on pass payloads when fallback
  applied.
- **TR19** (R34/R35) — Register both gap-004 fixtures in manifest; regenerate workflow; no `.sh` shim in
  `run_pr_test_plan_fixtures.py` path (PRD 042 Python-first).
- **TR20** (R40) — Doc updates in `core/rules/sw-subagent-dispatch.mdc`, `core/commands/sw-doc.md`; run
  `build-chain-sync.py` before amendment ship when `core/` touched.
- **TR21** (R41/R42) — Add harness under `scripts/test/run_dispatch_binding_fixtures.py` (new) or extend
  existing dispatch foundation suite; register scenarios in manifest as `required`.

Roll into parent Phase 5 (gap verification) or ship as a focused pre-Thread-A batch when unblocking `/sw-doc`
delegation is urgent (Decision D-A2-4).

## Testing Strategy

Add to parent Testing Strategy:

- `bash-py-invocation-guard` (R34) — already implemented; registration-only in this amendment's first commit
  if code unchanged.
- `git-push-secret-scan-chokepoint` (R35)
- `dispatch-unregistered-parent-delegated-atomic-passes` (R41, TR21)
- `dispatch-unregistered-parent-reviewer-fails-closed` (R42, TR21)

No regression to PRD 024 A2 R38 keyed preflight, PRD 024 A2 R39 command-tier binding, or A1 R28 dispatch
preflight worktree alignment.

## Rollout Plan

1. Land R34–R36 (manifest registration + zero-shell guard wiring audit) — can ship immediately; closes Defect
   A/C verification gap even before R37–R39 code.
2. Implement TR18 + R37–R39 + fixtures R41/R42 (Defect B).
3. Doc pass R40 + TR20.
4. On ship: flip `gap-004` unit frontmatter to `resolved` referencing PRD 050 A2; attach `gap_backlog.py
   check` / manifest green output to PR.

## Decision Log

- **D-A2-1 (2026-07-01):** Adopt gap-004 worked design option **(b)** — optional
  `dispatch.unregisteredParentModelTier` config fallback (default unset/fail-closed for tier-floor checks) plus
  **narrow** unconditional fail removal (R37): only reviewer/native-panel paths require resolvable `parent_rank`.
  Rejects option (a) permissive-default `deep` (weakens R9 floor silently) and option (c) platform metadata
  (implementation cost; defer).
- **D-A2-2 (2026-07-01):** Host on **PRD 050 A2** rather than PRD 024 A3 because PRD 024 is `complete` and
  `authoring_guard.py` refuses amend; 050 is `not-started`, amendable, and A1 already extends dispatch
  preflight. Lineage to 024 A2 is explicit — not a redesign.
- **D-A2-3 (2026-07-01):** Keep `models.tiers` scoped to internal command/skill/agent routing (PRD 012 design);
  do not enumerate every IDE-selectable model. Interactive sessions use R37 advisory pass or operator-set R39
  fallback.
- **D-A2-4 (2026-07-01):** Thread E (R34–R36) may land before Thread F when the operator's immediate blocker
  is `/sw-doc` Task delegation — Defect B fix is the dispatch unblocker; fixture registration prevents A/C
  regression in parallel.

## Security & Compliance

- R37 advisory path applies only to non-reviewer/non-panel dispatches — tier-floor invariant for review
  personas is preserved (R38).
- R39 fallback is operator-configured only; no silent widening of reviewer tier floor without explicit config
  write.
- No new network or credential surface.

## Open Questions

None — gap-004 Defect B Open Questions resolved by D-A2-1 and D-A2-3.
