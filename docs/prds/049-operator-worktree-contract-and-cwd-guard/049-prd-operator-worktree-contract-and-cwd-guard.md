---
date: 2026-07-01
topic: operator-worktree-contract-and-cwd-guard
absorbs: [GAP-056, gap-006-prd-033-marked-complete-but-a3-r37-r39-r40-r42-r]
frozen: true
frozen_at: 2026-07-01
visibility: public
---

# PRD 049 — Operator worktree contract & in-flight cwd guard

## Overview

`gap-006` found that `docs/prds/033-lifecycle-dependencies-and-scheduler/amendments/A3-operator-worktree-contract.md`
is frozen and shows in `docs/prds/INDEX.md` as shipped (PRD 033 — main + A1 + A2 + A3 — `complete`), but 5 of
its 6 substantive requirements (R37, R38, R39, R40, R42) were never implemented — verified by direct
code/doc search on 2026-06-30 and re-verified while drafting this PRD on 2026-07-01 (`deliver_cwd_guard`/
`cwd_guard` still has zero matches anywhere in `scripts/`/`core/`; `sync_canonical_state_read` still has zero
matches; the `deliver-worktree-contract` fixture is still absent from `pr-test-plan.manifest.json`). Only R41
incidentally passes, and only because its dependency (PRD 027 R4) had already landed independently of A3.

Because PRD 033 (parent and all three amendments) is `complete`, `/sw-amend`'s authoring-guard (PRD 032 R7/R8)
mechanically refuses any further in-place amendment — confirmed as the systemic dead-end-dispatch pattern
this repo has now hit twice (gap-016; the full gap-to-open-PRD sweep in memory #2290, which found no other
open PRD is a scope fit for this work either). Per explicit operator direction, this PRD re-hosts A3's
already-frozen, already-reviewed requirements as a fresh standalone PRD rather than a new amendment, so the
work is trackable and implementable through the normal `/sw-tasks` → `/sw-deliver` path.

**This PRD does not re-design anything.** A3's Overview, Goals, and requirement intent are carried forward
verbatim in substance; the only substantive change is R7's implementation vehicle correction (A3's
TR-A3-1 named a `.sh` script; R7 corrects this to a `.py` module), because `rules/sw-python-first.mdc`
(repo-wide, always-applied) prohibits new `.sh`/`.bash` files under enforced trees — a policy that either
postdates A3's 2026-06-29 freeze or was simply not caught before freeze; either way, the correction is
mechanical, not a design change. A3's own Goal 4 (phase-ship `SW_REPO_ROOT` mirror, tied to A3 R41) is
intentionally not restated as a Goal here because A3's own text already noted that mirror was independently
satisfied by PRD 027 R4 before A3 froze — see TR3's restatement-only note.

**Operator impact (why this matters day-to-day):** the concrete trigger for GAP-056/gap-006 was operators
observing repo-root `.cursor/` file activity during a deliver run and — reasonably, in the absence of a
published contract — assuming tracked files on `main` were being mutated. Real footguns this PRD closes:
(1) an operator or script running a work-performing command from the primary checkout has no mechanical
signal telling them to stop while a deliver run for the repo is active (R3); (2) terminal deliver steps
(retrospective, ship, all-phases-complete) can read stale cwd-relative state instead of the canonical
repo-root copy, silently acting on outdated data (R4); (3) there is no single place operators can read to
learn which directories are safe to treat as "implementation" versus "conductor runtime" (R1/R2). Shipping
R1–R5 with green, registered fixtures — not merely flipping GAP-056/gap-006 to `resolved` — is what closes
this gap; see the Rollout Plan completion gate below.

## Goals

1. Operators can distinguish **repo-root runtime state** (gitignored `.cursor/`) from **tracked
   implementation** on worktrees, via a published contract in `.sw/layout.md`.
2. Work-performing commands fail closed when run from the primary checkout on `defaultBaseBranch` during an
   in-flight deliver run for the repo — no undocumented escape (see R3's explicit escape enumeration).
3. Canonical deliver state is always read via `resolve_state_path(git_toplevel)` before terminal steps, never
   a cwd-relative path, with a skew check against any repo-root mirror copy.
4. A registered fixture proves the contract end-to-end: after orchestrator provision + one deliver-loop tick,
   repo-root scoped state updates, the primary checkout stays on `defaultBaseBranch`, and no tracked files on
   `main` change, **and** an attempted guarded surface invoked from the primary checkout during that same
   in-flight run is refused (not merely observed as absent).
5. `GAP-056` (and this PRD's own `gap-006`) flip to genuinely `resolved` **only after** Goals 1–4 are
   independently, mechanically verified (Definition of done below) — never as a standalone narrative step.

### Definition of done (anti narrative-closure gate)

This PRD exists because PRD 033 A3 reached `complete` in `docs/prds/INDEX.md` with zero shipped code for
5 of 6 requirements. To prevent a repeat, INDEX `complete` for PRD 049 (and the R6 gap flips) MUST NOT
happen until **all** of the following are independently true, not merely asserted in a PR description:

- `deliver-cwd-guard-blocks-main-living-doc` (R3) is registered and green.
- `terminal-reads-repo-root-state-from-orchestrator-cwd` (R4) is registered and green.
- `deliver-worktree-contract` (R5) is registered and green, **including** the negative guard-refusal
  assertion added to R5 below (not just the absence-of-mutation assertions A3's version had).
- `doc-currency-049-contract-sections` (R1/R2) is registered and green.
- `gap-backlog-flip-schedule-force-reschedule` (TR4) is registered and green — the `GAP-056` reschedule in R6
  depends on this fix; do not attempt a manual/hand-edited workaround on `GAP-BACKLOG.md` as a substitute.
- A repo-wide search for `deliver_cwd_guard`/`cwd_guard` and `sync_canonical_state_read` returns positive
  matches (mirroring the negative-search evidence this PRD's Overview used to prove A3 was unbuilt).

See Rollout Plan step 4a for the mechanical gate that enforces this before R6 fires.

## Non-Goals

- Re-designing the worktree/state-sync architecture — this PRD implements A3's already-reviewed design; it
  does not re-open A3's own Decision Log (DL-A3-1 through DL-A3-4 stand as rationale for this design).
- Re-opening or editing `docs/prds/033-lifecycle-dependencies-and-scheduler/` or its amendments in place —
  they remain frozen and untouched; this PRD is additive, standalone.
- Resolving the overlap between this guard and gap-002's "remediation #4" upstream-primitive fix or the PRD
  036 unconditional default-branch-commit guard. A3's own Overview (§"Why this matters", point 3) already
  flags that re-evaluation as a **follow-up** action once this ships, not a prerequisite — out of scope here.
- Auditing other `complete` PRDs/amendments for the same "frozen but unbuilt" pattern (A3's own suggested
  remediation #3) — a separate, unscoped investigation, not part of implementing this one guard.
- Moving canonical `.cursor/` state into worktrees — repo-root state remains canonical per PRD 013 R28
  (unchanged, restated for context only).
- The deliver-loop-concurrency / worktree-cwd-safety / terminal-finalize-robustness gap cluster (gap-005,
  gap-009 through gap-015, GAP-077 through GAP-080) — confirmed in memory #2290 as a distinct, larger surface
  needing its own brainstorm; this PRD is scoped to A3's R37–R43 requirements plus the R7 vehicle correction,
  not that broader cluster.
- Unifying `deliver_cwd_guard.py`'s in-flight-run detection with PRD 046 A3's `inflight_signal.py` primitive.
  These are different signals for different questions — resolved during `/sw-doc-review` (D5 below) rather
  than left as an implementer judgment call: R3 answers "is a **concurrent local deliver run** active on this
  repo", while PRD 046 A3
  answers "is the planning INDEX `inFlight` region safe to commit". `deliver_cwd_guard.py` MUST NOT depend on
  `inflight_signal.py`; a future PRD may explicitly scope convergence if warranted.
- **What remains unprotected after this ships** (explicit, so this PRD is not mistaken for closing the full
  footgun surface): gap-002's "remediation #4" upstream-primitive fix, PRD 036's unconditional
  default-branch-commit guard, and any work-performing surface not enumerated in R3's minimum list (e.g.
  `/sw-freeze`'s own commit paths) remain exposed to the same class of primary-checkout risk. This PRD closes
  the in-flight-deliver-run-gated subset only.

## Requirements

- **R1** (origin: PRD 033 A3 R37) — `.sw/layout.md` MUST publish an **operator worktree contract**
  diagram/table covering: primary checkout (usually `defaultBaseBranch` after orchestrator provision),
  orchestrator worktree (`.sw-worktrees/<slug>-orchestrator` owns `<type>/<slug>`), phase worktrees
  (`.sw-worktrees/<slug>-phase-*`), and repo-root gitignored `.cursor/` (canonical deliver state, locks, run
  logs). MUST state explicitly: `.cursor/` at repo root is **conductor runtime**, not feature implementation;
  copy direction for `status.json` is **phase worktree → repo root** (mirror), never a general root→worktree
  sync.
- **R2** (origin: A3 R38) — `core/skills/conductor/SKILL.md` and `core/skills/deliver/SKILL.md` MUST echo the
  R1 contract: which checkout agents should run ship/execute in, that repo-root `.cursor/` updates during
  deliver are expected, and that tracked `main` must not accumulate implementation commits during a run.
  **MUST also remove or reconcile** `core/skills/conductor/SKILL.md`'s existing "run `deliver-loop` from
  `.sw-worktrees/<slug>-orchestrator` (**or repo root with state synced**)" language (flagged by GAP-078 as
  contradicting mandatory orchestrator provisioning): the R1 contract names the orchestrator worktree as the
  conductor-loop cwd, not repo root as an alternate option, so R2's implementation must not leave both
  statements standing.
- **R3** (origin: A3 R39) — A fail-closed **in-flight cwd guard** MUST refuse (exit non-zero with remediation)
  when a work-performing surface runs from the primary checkout on `defaultBaseBranch` while a deliver run
  for the repo is `verdict: running` (read from repo-root canonical state index). Surfaces (minimum):
  `wave_living_docs --commit`, `reconcile.py reconcile`, `/sw-retrospective` write paths, and
  `wave_deliver_loop` manual living-doc reconcile suggestions. Extends PRD 033 A1 R31 (reconciler
  default-branch refuse) to **operator command entry**, not only the reconciler script. **Fail-closed
  precisely defined:** a missing, corrupt, or unreadable in-flight index/state file MUST be treated as "an
  in-flight run cannot be ruled out" (refuse with remediation), never as "no run detected" (proceed) — the
  guard MUST NOT rely solely on a cached `.cursor/sw-deliver-runs/index.json` snapshot; it MUST perform (or
  trigger) a live scan of scoped deliver-state files when the index is stale or absent, consistent with the
  existing `enumerate_scoped_runs` primitive. **Escape hatch:** none for operator-invoked paths; the only
  sanctioned bypass is CI/fixture-only `--allow-default-branch` (inherited from A1 R31), which MUST log its
  use and MUST NOT be reachable from an interactive operator command.
- **R4** (origin: A3 R40) — Before `retrospective`, `terminal-ship`, or `all-phases-complete`, deliver MUST
  call a `sync_canonical_state_read()` helper — load state via `resolve_state_path(git_toplevel)` (already
  implemented in `wave_state.py`; callers MUST hoist to `git_toplevel` themselves before calling it, since
  `resolve_state_path` does not do this hoist on its own), not a cwd-relative path; on `save_state`, mirror to
  repo-root when `orchestratorWorktree.path` is set. **Skew threshold (resolved, D6):** terminal steps refuse
  when the dual-copy `updatedAt` skew is **strictly greater than 300 seconds** (5 minutes; single-sourced as a
  named constant, not re-derived per call-site); equality (exactly 300s) passes. **Conflict precedence:** when
  repo-root and orchestrator-mirror copies disagree on `verdict` (not just `updatedAt`), the **repo-root
  canonical copy is authoritative**; the orchestrator mirror is advisory only and never overrides a
  `verdict: running` read from repo-root.
- **R5** (origin: A3 R42) — A fixture `deliver-worktree-contract` MUST prove: after orchestrator provision +
  one `deliver-loop` tick, repo-root scoped state is updated, the primary checkout remains on
  `defaultBaseBranch`, and no tracked files on `main` are modified. Registered in
  `core/sw-reference/pr-test-plan.manifest.json`. **Negative assertion (new, closes an adversarial-review
  gap):** the fixture MUST also attempt at least one R3-guarded surface from the primary checkout while the
  simulated run is `verdict: running` and assert **non-zero exit with remediation text** — proving the guard
  is wired, not merely that state/branch/main happened to look clean. A fixture that only asserts the
  absence-of-mutation outcomes (as A3's original text specified) can pass without R3 ever firing, which is
  exactly the false-closure pattern gap-006 documents; the negative assertion closes that hole.
- **R6** (origin: A3 R43) — On ship, `GAP-056` flips to `resolved — PRD 049` via `gap_backlog.py flip
  --resolve` (per R4/R1 of the sibling wiring PRD 048, if shipped first — otherwise via the existing manual
  invocation). **Prerequisite (new, closes a verified mechanical bug — see TR4):** `GAP-BACKLOG.md`'s
  `GAP-056` row is currently scheduled to `PRD 033 A3`, not `PRD 049`. Both `flip --resolve --prd 049` (matches
  only rows already scheduled to `PRD 049`) and the freeze-time auto-schedule flip (`flip --schedule
  --from-artifact`, which — per current `flip_schedule()` — only rewrites a row's schedule when it is `open`,
  or leaves it untouched when already `scheduled` to a **different** label) silently no-op on this row as
  written today; **TR4 fixes the underlying script** so an explicit reschedule succeeds. After TR4 lands, run
  `python3 scripts/gap_backlog.py flip --schedule --gaps GAP-056 --prd 049 --force` to move the pointer from
  `PRD 033 A3` to `PRD 049` before relying on `--resolve`. Verify with `python3 scripts/gap_backlog.py list`
  showing `GAP-056 | scheduled | PRD 049` before ship. **`gap-006` is a separate planning-graph gap unit**
  (`docs/prds/gap/gap-006-.../` frontmatter, `status: open`) — distinct from the `GAP-BACKLOG.md` row
  mechanism above. `gap_backlog.py` does not touch it. Close it via the planning-graph reconciler
  (`python3 scripts/planning-graph.py reconcile --commit`) after this PRD's frontmatter/INDEX status
  legitimately reaches `complete`, so the unit's `status` flips to `resolved` with a reference back to this
  PRD — not by hand-editing the unit file. **Ship gate:** neither flip fires until the Definition of done
  (Goals) checklist is green — see Rollout Plan step 4a.
- **R7** (new, not in A3) — The R3 guard implementation MUST be a `.py` module
  (`scripts/deliver_cwd_guard.py`), not the `.sh` script A3's TR-A3-1 named — per `rules/sw-python-first.mdc`
  (repo-wide, always-applied, prohibits new `.sh`/`.bash` files under enforced trees). This is the one
  substantive delta from A3's original text; everything else in R1–R6 is A3 verbatim (with the R5 negative
  assertion, R4 threshold, and R6 reschedule step above added by this doc-review pass to close verified
  spec gaps — not new design scope, but precision needed to avoid repeating A3's false-closure pattern).

## Technical Requirements

- **TR1** (R3/R7) — Implement `scripts/deliver_cwd_guard.py` (module + thin CLI entrypoint, matching this
  repo's existing `scripts/<name>.py` + `_sw.cli.run_module_main` convention — see
  `scripts/living-status-gap-resolve.py` for the pattern), called from guarded entrypoints; detects an
  in-flight run via `.cursor/sw-deliver-runs/index.json` + repo-root canonical state. Fixture:
  `deliver-cwd-guard-blocks-main-living-doc`.
- **TR2** (R4) — Add `sync_canonical_state_read()` to `scripts/wave_state.py`, calling the existing
  `resolve_state_path(git_toplevel)` (line ~285) rather than any cwd-relative read; wire it into
  `wave_deliver_loop.py`'s `retrospective`, `terminal-ship`, and `all-phases-complete` actions before their
  existing logic. Fixture: `terminal-reads-repo-root-state-from-orchestrator-cwd`.
- **TR3** (R1/R2/R5) — Doc-currency fixtures for `.sw/layout.md` (R1) and the conductor/deliver skills (R2).
  **Register every fixture this PRD introduces** in `core/sw-reference/pr-test-plan.manifest.json` — not only
  `deliver-worktree-contract` (R5), but also `deliver-cwd-guard-blocks-main-living-doc` (TR1),
  `terminal-reads-repo-root-state-from-orchestrator-cwd` (TR2), `gap-backlog-flip-schedule-force-reschedule`
  (TR4), and `doc-currency-049-contract-sections` (this TR). An unregistered-but-passing fixture does not
  satisfy the Definition of done gate — "registered and green" is two conditions, not one. R41
  (`SW_REPO_ROOT` read in `scripts/ship-phase-status.py:53`) already exists — no TR needed for it; it is
  restated in Requirements only for traceability to A3's original numbering, not re-implemented.
- **TR4** (R6, new — discovered by doc-review, not A3) — Extend `scripts/gap_backlog.py`'s `flip_schedule()`:
  today it only rewrites `row.schedule` when the row `is_open`; a row already `scheduled` to a **different**
  label is left untouched (silent no-op) rather than rescheduled. Add an explicit `--force` flag to the
  `flip --schedule` subcommand that, when set, rewrites `schedule` (and leaves `status: scheduled`) for a
  matched row regardless of its current label; without `--force`, current no-op-on-mismatch behavior is
  preserved (no accidental reschedule of unrelated in-flight schedules). This is a prerequisite for R6's
  `GAP-056` reschedule, not a design change to R6 itself — the bug exists independent of this PRD and would
  block any future PRD trying to reschedule an already-scheduled gap. Fixture:
  `gap-backlog-flip-schedule-force-reschedule`.
- Emitter parity: changes to `core/skills/conductor/SKILL.md` / `core/skills/deliver/SKILL.md` require
  `python3 scripts/build-chain-sync.py` before freeze (R32 Python entrypoint model / build-chain SoT).

## Security & Compliance

- Guards operate on local paths and git state only; no new network or credential surface (restated from A3
  R44 — unchanged).
- `scripts/deliver_cwd_guard.py` must fail closed (refuse, not warn) on ambiguous state-read errors, matching
  the fail-closed posture of every other guard in this codebase (PRD 032 R6, PRD 046 A1's shared guard).
- **Known limitation, not fixed by this PRD:** the guard is a point-in-time check, not a lock — a deliver run
  could start in the window between the guard's read and the guarded command's action (TOCTOU). This PRD
  accepts that residual risk (consistent with every other advisory state-read guard in this codebase; none
  take a mutex) rather than introducing new locking infrastructure, which would be a design change beyond
  A3's original scope. Documented here so it is a known, accepted trade-off — not a silent gap.

## Testing Strategy

- `deliver-worktree-contract` (R5) — end-to-end operator contract, registered fixture, including the R5
  negative assertion (guarded surface refuses while a run is `verdict: running`).
- `deliver-cwd-guard-blocks-main-living-doc` (R3), including the fail-closed-on-corrupt-index case.
- `terminal-reads-repo-root-state-from-orchestrator-cwd` (R4), including a skew-boundary case (>300s refuses,
  =300s passes) and a repo-root-vs-mirror `verdict` conflict case (repo-root wins).
- `gap-backlog-flip-schedule-force-reschedule` (TR4) — proves `--force` reschedules a row already scheduled
  to a different label, and that omitting `--force` still no-ops (no accidental cross-PRD reschedule).
- `doc-currency-049-contract-sections` (R1, R2) — renamed from A3's `doc-currency-033-a3-sections` since the
  content now lives under this PRD's ownership.
- No regression to PRD 033 A1's default-branch reconcile refusal (R31) or A2's finalize chokepoint.
- Re-run `docs-currency-gate.py` and `gap_backlog.py check` after R6 to confirm `GAP-056` and `gap-006` both
  show `resolved`, not merely narratively closed.

## Rollout Plan

1. Implement R1–R2 (documentation) first — low risk, unblocks R3/R4 review context.
2. Implement R3 (`deliver_cwd_guard.py`) and R4 (`sync_canonical_state_read`) together, since both gate on
   the same in-flight-run detection primitive; land with fixtures (including the fail-closed/skew/conflict
   cases above) in the same PR.
3. Register and pass R5's `deliver-worktree-contract` fixture — including its negative assertion — before
   requesting review; it is the end-to-end proof this PRD actually closes gap-006, not just adds more unbuilt
   spec text.
4. Land TR4 (`gap_backlog.py flip --schedule --force`) and its fixture before step 4a — R6's reschedule step
   depends on it.
4a. **Definition-of-done gate (see Goals section above):** verify every mechanical criterion in that checklist
   is green before proceeding to step 5. Do not flip `GAP-056`/`gap-006` or mark this PRD `complete` on
   narrative confidence alone.
5. On ship, reschedule `GAP-056` (TR4-backed `--force` call, R6) then run R6's `--resolve` flip for
   `GAP-056`; close `gap-006` via the planning-graph reconciler. Attach `gap_backlog.py check` /
   `docs-currency-gate.py` output to the PR showing both close cleanly.
6. If PRD 048 (gap-016 wiring: automatic gap-resolve-on-complete) has already shipped, the `--resolve` half of
   R6 happens automatically when this PRD's INDEX row flips to `complete` — no manual step (the TR4 reschedule
   in step 5 still runs manually first, since 048's automation covers resolve, not reschedule). If 048 has not
   yet shipped, both halves of R6 remain manual as described above.

## Decision Log

- **D1 (2026-07-01):** Re-host A3's unimplemented requirements as a new standalone PRD (049) rather than
  amend PRD 033 further or route to an existing not-started PRD (003/010/040/044/045/046/047 — all confirmed
  scope-mismatched in memory #2290). Rationale: PRD 033 is `complete`, so `/sw-amend` refuses in-place
  mutation (PRD 032 R7/R8); the operator explicitly directed a new PRD; A3's spec is already frozen,
  reviewed, and uncontested, so re-authoring it as a fresh PRD is transcription, not new design work.
- **D2 (2026-07-01):** Preserve A3's requirement text and numbering intent via `(origin: PRD 033 A<n> R<n>)`
  annotations on each requirement rather than silently renumbering with no back-reference, so traceability to
  the original review/freeze (and to `gap-006`'s evidence table) is not lost.
- **D3 (2026-07-01):** Correct A3 TR-A3-1's `scripts/deliver_cwd_guard.sh` to `scripts/deliver_cwd_guard.py`
  (R7) to comply with `rules/sw-python-first.mdc`. This is the only substantive deviation from A3's frozen
  text in this PRD; everything else is carried forward as-specified.
- **D4 (2026-07-01):** Do not attempt to resolve the gap-002/PRD-036-guard overlap A3's own Overview flagged
  as a follow-up — kept as a Non-Goal here, consistent with A3's own sequencing ("after R39 ships,
  re-evaluate...").
- **D5 (2026-07-01, resolved during `/sw-doc-review`):** `scripts/deliver_cwd_guard.py`'s in-flight-run
  detection (R3) does **not** reuse or unify with PRD 046 A3's `inflight_signal.py`. They answer different
  questions — R3: "is a concurrent local deliver run active on this repo"; PRD 046 A3: "is the planning INDEX
  `inFlight` region safe to commit" — and conflating them risks a guard that's right for the wrong reason.
  Captured as a Non-Goal (see above) rather than left as an implementer judgment call.
- **D6 (2026-07-01, resolved during `/sw-doc-review`):** R4's dual-copy `updatedAt` skew threshold is fixed at
  **300 seconds** (strictly-greater-than refuses; equal-to passes), single-sourced as a named constant. A3's
  original text left this undefined (P0 finding); 300s was chosen as a round, generous margin comfortably
  above normal mirror-write latency while still catching a genuinely stale copy — not derived from a
  measured production distribution, since none exists yet. Revisit if fixture data from TR2 shows false
  positives/negatives at this value.

## Open Questions

- A3's suggested remediation #3 ("audit whether other `complete` PRDs/amendments have similarly unimplemented
  requirements") is explicitly out of scope for this PRD (Non-Goals) — should it be captured as its own gap
  so it isn't lost entirely? Recommend a follow-up gap-capture via `/sw-feedback`, not blocking this PRD.
