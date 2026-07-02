---
date: 2026-07-02
amends: docs/prds/050-deliver-concurrency-cwd-terminal-robustness/050-prd-deliver-concurrency-cwd-terminal-robustness.md
absorbs: [gap-018-resume-reconcile-ignores-unpushed-local-phase-me]
signal: feedback-prd-051-deliver-observations-2026-07-02
frozen: true
frozen_at: 2026-07-02
visibility: public
---

# Amendment A4: resume-reconcile unpushed local merge ground tip (gap-018)

## Overview

`gap-018` captures a deliver-loop resume defect observed during PRD 051 deliver: when a phase branch is
merged into the target feature branch **locally** but the remote tracking ref is stale (unpushed), `wave_terminal.py
resume reconcile` does not promote the phase to `green-merged`. Operators must manually patch
`.cursor/sw-deliver-state.json` and continue.

Parent PRD 050 Thread C (R13–R16) covers terminal-finalize idempotency and host-API merge authority but does
not specify **resume-reconcile ground-tip selection** when local and remote target tips diverge. PRD 027
R29/R50 establishes remote pushed tip as ground truth; the current implementation over-applies that rule when
`local_tip` is strictly ahead of `remote_tip`.

This amendment extends Thread C with **R47–R50** and closes **gap-018** when shipped with green fixtures —
not narrative closure.

## Context

**PRD 051 evidence (2026-07-02):**

- Phase 3 already merged locally into the target branch during deliver.
- `resume reconcile` left the phase `pending`; operator manually set `green-merged` and continued.
- Existing fixture `deliver-phase-resume-reconcile` passes with `--no-fetch` and no remote — it does not
  reproduce stale-remote / ahead-local divergence.

**Root cause:**

```688:735:scripts/wave_terminal.py
remote_tip = resolve_ref(top, remote_ref_name)
local_tip = resolve_ref(top, target)
ground_tip = remote_tip or local_tip
# ...
merged_on_remote = is_ancestor(phase_sha, ground_tip, top)
```

When `remote_tip` exists but does not contain a locally merged phase, `ground_tip` stays at the stale remote
SHA even though `local_tip` includes the merge.

**Relationship to PRD 027 R29/R50:** R29/R50 require remote pushed tip as authoritative for **demotion** of
stale `green-merged` rows (`resume:unpushed-local-merge`). A4 adds symmetric **promotion** when local tip
is ahead and contains the phase merge.

## Goals

1. `resume reconcile` promotes pending phases merged into `local_tip` even when `remote_tip` is behind.
2. Remote ground truth for demotion of `green-merged` rows remains unchanged (no weakening of R29/R50).
3. Pending phases blocked only by unpushed local merges surface actionable `cause` + remediation hint.
4. `gap-018` flips to `resolved` when R47–R50 ship with green fixtures.

## Non-Goals

- Replacing PRD 027's remote-authoritative demotion semantics for already-`green-merged` phases.
- Auto-pushing the target branch on behalf of the operator.
- Fixing orchestrator worktree / cwd repo-root resolution (gap-006, PRD 049/050 Thread A).

## Requirements

### Thread C extension — resume-reconcile ground tip

- **R47** (origin: gap-018 remediation #1) — `cmd_resume_reconcile` MUST compute merge ancestry for
  promotion using `local_tip` when it is an ancestor-descendant ahead of `remote_tip`, or equivalently MUST
  promote a `pending` phase when `is_ancestor(phase_sha, local_tip)` is true regardless of stale
  `remote_tip`. `ground_tip` recorded in state/log MUST reflect the tip used for promotion decisions.
- **R48** (origin: gap-018 remediation #2) — When a `pending` phase is merged into `local_tip` but not
  `remote_tip`, `resume reconcile` MUST set `cause: resume:unpushed-local-merge` on the phase metadata (or
  emit an equivalent advisory in JSON output) with remediation hint to push the target branch — not leave the
  phase silently `pending`.
- **R49** (origin: gap-018 remediation #3) — Fixture
  `resume-reconcile-unpushed-local-merge-promotes` MUST assert promotion to `green-merged` when the target
  branch contains a local-only phase merge and a stale `origin/<target>` ref exists after fetch simulation.
- **R50** (origin: gap-018 closure) — On ship, flip
  `gap-018-resume-reconcile-ignores-unpushed-local-phase-me` unit frontmatter to `resolved` referencing PRD
  050 A4 only after R47–R49 fixtures are green.

## Technical Requirements

- **TR25** (R47) — Refactor `cmd_resume_reconcile` ground-tip / ancestry logic in `scripts/wave_terminal.py`:
  separate promotion predicate (`merged_into_local`) from demotion predicate (`merged_on_remote`); preserve
  `--no-fetch` and `--dry-run` behavior; keep `remoteTargetTip` / log fields stable for operators.
- **TR26** (R48–R49) — Extend `scripts/test/run_deliver_fixtures.py` (or
  `scripts/test/fixtures/deliver-concurrency/`) with `resume-reconcile-unpushed-local-merge-promotes`; register
  in `core/sw-reference/pr-test-plan.manifest.json` as `required`.
- **TR27** (R50) — Wire gap flip into ship checklist alongside A3 gap-017 closure (task 5.2 extension).

Roll into parent Thread C (tasks 3.x) after A3 terminal gate work (Decision D-A4-2).

## Testing Strategy

Add to parent Testing Strategy:

- `resume-reconcile-unpushed-local-merge-promotes` (R49, TR26)

Preserve existing `deliver-phase-resume-reconcile` (no-remote) behavior. No regression to A3
`terminal-docs-currency-gate-invocation-valid` or R16 `terminal-pr-body-template-valid`.

## Rollout Plan

1. Implement TR25 + R47 (promotion predicate) — unblocks deliver resume without manual state edits.
2. Land TR26 + R49 fixture registration.
3. Add R48 advisory `cause` on pending→promoted unpushed-local path.
4. On ship: flip gap-018 to `resolved`; attach `gap_backlog.py check` output to PR.

## Decision Log

- **D-A4-1 (2026-07-02):** Host gap-018 on **PRD 050 A4** (Thread C extension) rather than PRD 027 because PRD
  027 is `complete` and PRD 050 is amendable with deliver-loop/terminal resume scope in `wave_terminal.py`.
- **D-A4-2 (2026-07-02):** Promotion uses `local_tip` when ahead; demotion of stale `green-merged` rows
  continues to use remote ground truth — symmetric R29/R50 semantics without auto-push.
- **D-A4-3 (2026-07-02):** Extend deliver fixtures rather than only `--no-fetch` temp-repo case so the bug
  class is CI-gated.

## Security & Compliance

- Local git ancestry checks only; no new network surface beyond existing `git fetch` in `resume reconcile`.
- Fail-closed posture preserved for missing refs and corrupt run-state.

## Open Questions

None — gap-018 remediation direction is fully specified.
