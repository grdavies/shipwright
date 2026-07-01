---
date: 2026-07-01
topic: gap-lifecycle-flip-and-feedback-route-guard
absorbs: [GAP-088]
frozen: true
frozen_at: 2026-07-01
visibility: public
---

# PRD 048 — Gap-lifecycle flip automation & feedback route guard

## Overview

`gap-016` (`GAP-088`) found that PRD 035's A2 R51 "mechanical" gap-resolve flip
(`scripts/living-status-gap-resolve.py`) requires manual invocation and is called from nowhere in the
ship/completion pipeline, so the 34 gaps its own amendments claim to resolve (GAP-012, 016, 021, 022,
024–027, 029, 030, 041–046, 048–052, 054, 057–062, 064, 068, 071–074) never actually flipped in
`docs/prds/GAP-BACKLOG.md`. The existing `docs-currency-gate.py` drift check that should have caught this
only flags rows whose status string is literally `open`, but the current three-state model (decision:
GAP-BACKLOG status simplification, 2026-06-30) records absorbed-and-pending rows as `scheduled | PRD <n> A<k>`
— so the gate silently passes while the rows it should catch are exactly the ones it never inspects. The
gate's `gap-still-open` block also has an independent, more severe defect discovered during `/sw-doc-review`
(see Decision Log D5): it requires at least 5 pipe-delimited columns and reads status from the last column,
but `GAP-BACKLOG.md`'s live table is exactly 4 columns (`ID | Status | Schedule | Title`) — so every row is
skipped outright today, regardless of status string. Fixing only the `open`-vs-`scheduled` vocabulary without
also fixing the column parsing would leave the check just as dead as before.

A related, separately-diagnosed defect compounds the confusion this causes: `/sw-feedback` Phase 3 names an
`/sw-amend` handoff target without first checking the candidate unit's consumer status, even though the
primitive that answers that question already exists (`scripts/authoring_guard.py` `preflight`/
`propose_complete_change_route`, built for PRD 032 R7/R8). `/sw-amend` then mechanically refuses on `complete`
units, so the operator is handed a dead-end dispatch.

This PRD closes gap-016 by wiring the existing mechanical primitives together at their natural call sites
(INDEX status-write, the currency gate's own drift model, and the feedback router's existing amend branch) —
it does not invent a new gap-lifecycle framework; PRD 035 A2 and PRD 032 already built the pieces this PRD is
wiring up.

## Goals

- Make the R51 gap-resolve flip run automatically and idempotently whenever a PRD's `docs/prds/INDEX.md` row
  is set to `complete`, with no separate manual step for the author to remember.
- Fix `docs-currency-gate.py` so its "gap-still-open" check matches the actual GAP-BACKLOG status vocabulary
  (`open` *and* `scheduled`), so drift against a newly-`complete` absorbing PRD is caught in CI/gate output
  instead of discovered months later by an operator.
- Stop `/sw-feedback` from naming `/sw-amend` as a handoff target for a `complete` consumer-status unit;
  reuse the existing `authoring_guard.py` consumer-status primitive at routing time and route to the
  `extends:`/`supersedes:`/gap path instead when the target is `complete`.
- Provide a one-time retroactive backfill so PRD 035's own already-`complete` absorbed rows (and any other
  `complete` PRD with unresolved absorbed rows) are reconciled as part of shipping this fix.
- When a fix ships narrower than the gap's original description, let the resolved annotation say so, instead
  of a bare `resolved` that erases the scope difference.

## Non-Goals

- Re-running or re-litigating the full gap-to-open-PRD mapping sweep — already completed and recorded
  (canvas `gap-to-open-prd-mapping.canvas.tsx`, memory #2290): confirmed no other open gap shares this PRD's
  scope.
- PRD 046 A2's separate wiring of `living-docs reconcile --commit` into deliver-loop `finalize-completion`
  (`gap-007`) — a different call site (derived-status region vs. this PRD's structural-status
  `set-index-status` write) owned by a different, already-frozen amendment; not re-specified here.
- A general-purpose gap-lifecycle mechanization framework (already designed in memory #2204 / superseded PRD
  028) — this PRD wires two existing scripts together, it does not redesign the backlog lifecycle.
- The deliver-loop-concurrency / worktree-cwd-safety / terminal-finalize-robustness gap cluster
  (gap-005, gap-009 through gap-015, GAP-077 through GAP-080) — a distinct, larger surface flagged in memory
  #2290 as needing its own brainstorm/PRD; out of scope here.
- `gap-006` (PRD 033 A3 operator-worktree-contract requirements unimplemented) — pure implementation work
  against an already-frozen, unrelated spec; not touched by this PRD.
- Changing the GAP-BACKLOG three-state status vocabulary itself (`open`/`scheduled`/`resolved`) — that model
  is settled (memory #2259); this PRD makes tooling honor it correctly, not redefine it.

## Requirements

- **R1** — When `scripts/reconcile_lib.py` `set_index_status()` sets a PRD's `docs/prds/INDEX.md` row status
  to `complete`, it MUST, in the same process (no subprocess shell-out), resolve and flip any GAP-BACKLOG rows
  absorbed by that PRD using the shared resolver described in Technical Requirements R1. The call is
  idempotent: rows already `resolved` for that PRD are left untouched, and a run with no matching
  `scheduled`/`open` rows is a no-op, not a failure. If the flip step raises, `set_index_status()` MUST NOT
  roll back the INDEX write that already succeeded, but MUST return `{"verdict": "partial", ...}` with an
  error detail instead of `{"verdict": "pass", ...}`, so the CLI caller (`scripts/reconcile.py set-index-status`)
  can detect it and exit non-zero for retry.
- **R2** — `set_index_status()` currently has no default-branch guard at all (confirmed during
  `/sw-doc-review`; PRD 046 A1 explicitly deferred hardening this primitive as a Non-Goal, see Decision Log
  D4). This PRD MUST wire the existing shared helper (`worktree_lib.refuse_default_branch()`, introduced by
  PRD 046 A1 R96 for exactly this purpose) into `set_index_status()` before its write, refusing on
  `defaultBaseBranch` — not hand-rolling a second guard, and not assuming a guard already exists there.
- **R3** — `scripts/docs-currency-gate.py`'s `gap-still-open` check MUST be rewritten to reuse
  `gap_backlog.parse_gap_backlog()` (the same row parser `gap_backlog.py check`/`flip` already use) instead of
  ad hoc `parts[]` indexing, so it correctly reads the real 4-column `ID | Status | Schedule | Title` table
  (today's `len(parts) < 5` guard and `parts[-1]`/`parts[-2]` indexing skip every row outright — see Decision
  Log D5). For each row, treat it as drifted when `row.status` is `open`, or `row.status` is `scheduled` and
  `row.schedule` matches the absorbing PRD (reuse `gap_backlog.flip_resolve`'s `sched_re` pattern rather than
  re-deriving a new regex) and the absorbing PRD's INDEX status is `complete`. Fixture coverage must include a
  `scheduled | PRD <n> A<k>` row against a `complete` PRD as the primary regression case (this is the exact
  shape that shipped silently broken for PRD 035) — and a fixture proving the pre-fix 4-column skip bug is
  also closed, not just the vocabulary gap.
- **R4** — `scripts/gap_backlog.py flip --resolve` MUST accept an optional `--scope-note <text>` argument.
  `flip_resolve()` currently sets `row.status = "resolved"` and `row.schedule = "—"` with no annotation
  anywhere (confirmed during `/sw-doc-review` — there is no `"resolved — PRD <n> <amendment>"` string in the
  real `GAP-BACKLOG.md`; that phrasing only appears in amendment outcome tables, a different artifact — see
  Decision Log D6). When `--scope-note` is supplied, `flip_resolve()` MUST instead write
  `row.schedule = f"— ({note})"` (e.g. `— (remediate-pending phases only)`); omitting the flag preserves
  today's bare `"—"` byte-for-byte. This keeps the ternary status vocabulary unchanged (R7).
- **R5** — `core/skills/feedback/SKILL.md` Phase 3 "Substantial → `/sw-amend`" branch MUST resolve the candidate
  unit's consumer status via `scripts/authoring-guard.py preflight --path <unit-artifact> --command sw-amend
  --no-commit` (the same dry probe `/sw-amend` step 0 already uses) before naming `/sw-amend` in the handoff
  summary. This is a deliberate correction from an earlier draft that specified `--command sw-feedback`: only
  `--command sw-amend` causes `authoring_guard.py` to resolve and return `consumerStatus`/route information at
  all (confirmed during `/sw-doc-review` — see Decision Log D7); `--no-commit` is required so this read-only
  routing check never commits `inFlight`/INDEX state during a triage decision. When the preflight call exits
  21 (`consumerStatus: complete`), the handoff summary MUST surface the returned `propose_complete_change_route`
  payload (extends/supersedes/gap-only) instead of `/sw-amend`, and the route-record entry MUST capture which
  branch fired. This requires zero changes to `authoring_guard.py`'s resolution logic (R7 unchanged).
- **R6** — One-time retroactive backfill, run once against the current repo state as part of shipping this
  PRD, from a non-`defaultBaseBranch` worktree (same branch-safety posture as R2 — never on bare `main`):
  invoke the R1-fixed flip for PRD 035, passing `--scope-note` for any row already known to be a
  narrower-than-described fix at backfill time (at minimum GAP-062, per gap-016's own evidence that its A1 fix
  only covers `remediate`-pending phases, not `provision-phase`/`merge-enqueue` no-progress loops). Also run
  the R3-corrected gate as a one-time sweep across all other `complete` PRDs. If that sweep finds unresolved
  absorbed rows against **5 or fewer** additional `complete` PRDs, backfill those too in this same PR; if it
  finds more than 5, backfill PRD 035 only in this PR and file a follow-up gap for the remainder (see Decision
  Log D9) rather than blocking merge. Record before/after row counts and the sweep's full PRD list in the
  Rollout Plan evidence.
- **R7** — None of R1–R6 change the GAP-BACKLOG status vocabulary, the `authoring_guard.py` consumer-status
  resolution logic itself, or PRD 032's R7/R8 complete-unit refusal semantics — this PRD is additive wiring
  only.

## Technical Requirements

- **R1 implementation:** extract a shared function (e.g. `gap_backlog.resolve_for_prd(root, prd, *,
  scope_note=None) -> dict` in `scripts/gap_backlog.py`, or an equivalent in `scripts/reconcile_lib.py`) that
  parses the backlog via `parse_gap_backlog()`, calls `flip_resolve()`, writes the file if changed, and
  returns a real verdict dict (`{"verdict": "pass"|"partial", "flipped": [...], "error": ...}`). Both
  `scripts/reconcile_lib.py::set_index_status()` (currently `docs/prds/INDEX.md` string-table mutation only,
  line ~245) and `scripts/living-status-gap-resolve.py` (kept as a standalone manual-retry CLI entry point,
  currently a thin subprocess-shaped wrapper around `gap_backlog.py flip --resolve` with its own `git_root()`
  derived from `Path.cwd()` rather than a passed root, and an unconditional `return 0`) call this same shared
  function in-process — `set_index_status()` after a successful `status == "complete"` write, passing its own
  `root` parameter (fixing the CWD-vs-worktree-root mismatch); `living-status-gap-resolve.py`'s CLI passes
  through to the same function for manual retries. `scripts/wave_living_docs.py` (lines ~289-301) already
  chains a `gap-resolve` step after `living-docs reconcile` on `index_status == "complete"` — this PRD does
  not remove that call (kept as a redundant, idempotent safety net for the `finalize-completion` path this PRD
  explicitly excludes per Non-Goals), but the new in-process call inside `set_index_status()` is the
  authoritative fix for the `gap-016` failure mode (single-unit `set-index-status` CLI path, which
  `wave_living_docs.py` does not cover).
- **R2 implementation:** wire `worktree_lib.refuse_default_branch(branch, cfg["defaultBaseBranch"])` into
  `set_index_status()` before its write — this is a **new** guard on this primitive (PRD 046 A1 deferred it as
  a Non-Goal; do not describe this as reusing an existing guard on `set_index_status` itself). Determine
  `branch` via the same `git rev-parse --abbrev-ref HEAD` pattern already used in
  `reconcile_lib.reconcile_prd_index()`.
- **R3 implementation:** `scripts/docs-currency-gate.py` lines ~76-88 (`gap-still-open` block) — replace the
  ad hoc `parts[]` indexing (and its `len(parts) < 5` skip, which discards every real 4-column row) with
  `gap_backlog.parse_gap_backlog()` + the row-level check described in Requirements R3.
- **R4 implementation:** `scripts/gap_backlog.py` — add `--scope-note` to the `flip --resolve` argparse
  subparser (~lines 203-210) and thread it into `flip_resolve()` (~lines 162-173) per Requirements R4's
  `schedule` column target.
- **R5 implementation:** `core/skills/feedback/SKILL.md` Phase 3 table + `core/commands/sw-feedback.md`
  step 5 (substantial-signal handoff, the step that names `/sw-amend`) — call
  `authoring-guard.py preflight --path <candidate-unit> --command sw-amend --no-commit` per Requirements R5;
  no new flags or logic needed in `authoring_guard.py` itself.
- **R6 implementation:** one-shot invocation recorded in this PRD's task list / rollout evidence, not new
  product code — run the fixed shared resolver against PRD 035 (with `--scope-note` for GAP-062) and re-run
  `docs-currency-gate.py` to confirm the drift list empties; sweep all other `complete` PRDs with the corrected
  gate per the R6 threshold.
- **Documentation surface (folded in from `/sw-doc-review` docs-currency findings, see Decision Log D8):**
  update `core/skills/living-status/SKILL.md` (GAP-BACKLOG protocol section: state that `set-index-status
  --status complete` now auto-invokes the shared gap-resolver idempotently, and document the corrected
  `gap-still-open` drift coverage and the `--scope-note` annotation), `core/skills/deliver/SKILL.md`
  (living-docs section ~L476-492: clarify that absorbed-gap resolution on `complete` is now triggered by
  `set_index_status`'s post-write hook, distinct from the out-of-scope PRD 046 A2 `finalize-completion`
  path), and `core/commands/sw-status.md` (post-merge playbook: note the auto-flip and its `verdict: partial`
  retry signal).
- Emitter parity: changes to `core/commands/sw-feedback.md` / `core/skills/feedback/SKILL.md` require
  `python3 scripts/build-chain-sync.py` before freeze (R32 Python entrypoint model / build-chain SoT).

## Security & Compliance

- No new secrets, tokens, or external calls — all changes operate on already-tracked repo files
  (`docs/prds/INDEX.md`, `docs/prds/GAP-BACKLOG.md`) and existing local scripts.
- R2's default-branch-commit-safety guard reuse is a security-adjacent requirement (prevents a new bare-`main`
  commit vector) — no exceptions to the existing guard's fail-closed behavior.
- The retroactive backfill (R6) is a one-time, human-observed operation on the current repo, not an
  unattended migration — no rollback tooling beyond normal git history is required.

## Testing Strategy

- **R1/R2 fixture:** extend `scripts/test/run_planning_035_gap_lifecycle_fixtures.py` (or add a sibling
  fixture) with a case that calls `set_index_status(..., status="complete")` against a fixture INDEX +
  GAP-BACKLOG with `scheduled | PRD <n> A1` rows absorbed by that PRD, and asserts they flip to `resolved`
  in-process (no subprocess) without a separate manual `living-status-gap-resolve.py` call. A second case
  asserts `set_index_status` refuses the write on the fixture's `defaultBaseBranch` (R2 guard). A third case
  simulates a flip failure (e.g. malformed GAP-BACKLOG) and asserts the INDEX write still lands but the
  returned verdict is `partial`, not `pass`.
- **R3 fixture:** add `docs-currency-gate` fixture cases: (1) a `scheduled | PRD <n> A<k>` row (not `open`)
  against a PRD whose derived `expected` status is `complete` — assert `verdict: fail` with a
  `gap-still-open` drift entry (this is the direct regression test for the vocabulary bug); (2) a case using
  today's real 4-column row shape asserting the pre-fix `len(parts) < 5` skip no longer discards the row
  (this is the regression test for the deeper parsing bug found during `/sw-doc-review`).
- **R4 fixture:** unit test on `gap_backlog.py flip --resolve --scope-note "..."` asserting the annotation
  format; a second case confirms omitting `--scope-note` reproduces today's bare format byte-for-byte.
- **R5 fixture:** extend the `/sw-feedback` fixture suite with a Phase-3 "substantial" signal whose candidate
  unit resolves to `consumerStatus: complete` via `authoring-guard.py preflight --command sw-amend
  --no-commit` — assert the handoff summary names the routed extends/supersedes/gap path, never `/sw-amend`,
  that the preflight call made no `inFlight`/INDEX mutation (asserting `--no-commit` was honored), and that a
  second case with a `planned`/`in-progress` unit still names `/sw-amend` (no regression on the happy path).
- **R6 verification:** not a repeatable fixture — evidence is the before/after `docs-currency-gate.py` output
  attached to this PRD's shipping PR, showing the drift list for PRD 035 empties.

## Rollout Plan

1. Implement R1–R5 behind normal PR review; no feature flag needed (all changes are bug fixes /
   wiring of existing mechanisms, not new user-facing surface).
2. Land R3 (gate fix) and R1 (auto-flip) together so the fixed gate immediately validates the fixed flip in
   CI on this PR.
3. Run R6's one-time backfill against PRD 035 (with `--scope-note` for GAP-062) as part of this PR from a
   non-default-branch worktree — never on bare `main` — and attach before/after `docs-currency-gate.py` output
   to the PR/merge record.
4. Audit any other `complete` PRD for unresolved absorbed rows using the corrected R3 gate as a one-time
   sweep. Backfill in this same PR if the sweep finds unresolved rows against 5 or fewer additional `complete`
   PRDs; otherwise backfill PRD 035 only here and file a follow-up gap for the remainder (Decision Log D9).
5. Update `docs/prds/GAP-BACKLOG.md` to close `GAP-088` and flip `docs/prds/gap/gap-016-.../` frontmatter
   `status` to `resolved` referencing this PRD once shipped.

## Decision Log

- **D1 (2026-07-01):** Author this as a standalone Standard-tier PRD per explicit user direction, even though
  gap-016's own "Suggested remediation direction" text recommended a small targeted fix rather than a new
  PRD. Rationale for overriding that suggestion: the fix touches three independent call sites
  (`reconcile_lib.py`, `docs-currency-gate.py`, `/sw-feedback` routing) with distinct test fixtures each,
  which is enough surface to warrant a tracked PRD/task-list rather than an untracked ad-hoc patch, and the
  user explicitly requested a PRD.
- **D2 (2026-07-01):** Scope excludes PRD 046 A2's `finalize-completion` → `living-docs reconcile --commit`
  wiring (`gap-007`) even though both are "wire an existing script into a completion call site" fixes,
  because they target different INDEX regions (derived vs. structural) and different already-frozen owning
  amendments — combining them would blur ownership of two separate, already-scoped amendments.

- **D3 (2026-07-01, `/sw-doc-review`):** R1 runs **in-process**, not via subprocess shell-out to
  `living-status-gap-resolve.py`. Coherence and adversarial review both flagged the original draft's R1
  wording ("in-process") as contradicting its own Technical Requirements ("shells to ..."); in-process also
  fixes a real bug the adversarial persona found in the subprocess path (`living-status-gap-resolve.py`
  derives its root from `Path.cwd()`, not the caller's worktree root) and lets `set_index_status()` return a
  real `verdict: partial` on flip failure instead of relying on an always-`return 0` wrapper.
- **D4 (2026-07-01, `/sw-doc-review`):** R2 adds a **new** default-branch guard to `set_index_status()` rather
  than reusing an existing one. Coherence, feasibility, and adversarial reviewers independently found that
  PRD 046 A1 explicitly defers hardening `set_index_status`/`git_commit_living_docs` as a Non-Goal — no guard
  exists there today. This PRD wires the existing shared helper (`worktree_lib.refuse_default_branch`,
  introduced by PRD 046 A1 R96 for exactly this reuse) into the primitive PRD 046 A1 left unguarded.
- **D5 (2026-07-01, `/sw-doc-review`):** R3's fix targets a more severe defect than originally scoped.
  Feasibility and adversarial reviewers verified against the live `docs-currency-gate.py` that the
  `gap-still-open` block's `len(parts) < 5` guard skips every row of the real 4-column
  `ID | Status | Schedule | Title` table outright — fixing only the `open`-vs-`scheduled` vocabulary (the
  originally reported defect) would have shipped a gate that still never fires. R3 now requires reusing
  `gap_backlog.parse_gap_backlog()` instead of re-deriving column parsing.
- **D6 (2026-07-01, `/sw-doc-review`):** R4's `--scope-note` annotates the **Schedule** column
  (`— (note)`), not a `"resolved — PRD <n> <amendment>"` string. Feasibility and adversarial reviewers found
  that `flip_resolve()` never wrote that string anywhere in `GAP-BACKLOG.md` — the original R4 example was
  based on amendment outcome-table phrasing, a different artifact. Schedule-column annotation preserves the
  ternary status vocabulary (R7) while still surfacing the scope signal Goal 5 requires.
- **D7 (2026-07-01, `/sw-doc-review`):** R5 calls `authoring-guard.py preflight --command sw-amend
  --no-commit`, not `--command sw-feedback` as originally drafted. Feasibility and adversarial reviewers
  verified that `authoring_guard.py cmd_preflight()` only resolves and returns `consumerStatus`/route
  information when `command == "sw-amend"`; any other command value (including the originally drafted
  `sw-feedback`) takes the generic `outcome: proceed` path with no consumer-status field at all, making the
  original R5 wording unachievable via the described CLI surface. Reusing `--command sw-amend` (the same
  dry probe `/sw-amend` step 0 already uses) requires zero changes to `authoring_guard.py`'s resolution logic,
  preserving R7. `--no-commit` is required because the default `cmd_preflight` behavior commits `inFlight`
  reconcile state unless explicitly suppressed, which would violate R5's "no mutation" requirement during a
  read-only routing decision.
- **D8 (2026-07-01, `/sw-doc-review`):** the docs-currency persona found that `core/skills/living-status/SKILL.md`
  and `core/skills/deliver/SKILL.md` currently describe the manual, pre-this-PRD gap-resolve lifecycle
  (a standalone CLI step, and `living-docs reconcile --commit` as the resolver) and would go stale the moment
  R1 ships. Technical Requirements now includes updating both files plus `core/commands/sw-status.md`'s
  post-merge playbook as part of this PRD's shipped scope (not a follow-up), since leaving them stale would
  immediately reproduce the confusion `gap-016` itself documents.
- **D9 (2026-07-01, `/sw-doc-review`, resolves Open Question 2):** the R6 backfill sweep splits to a follow-up
  gap if the corrected R3 gate finds unresolved absorbed rows against **more than 5** additional `complete`
  PRDs beyond PRD 035. Product and scope-guardian reviewers agreed the original open-ended "if the count is
  large" language needed an operational threshold to avoid leaving the merge-blocking scope of this PR
  undefined until implementation time; 5 was chosen as a small, reviewable cap consistent with R19's
  small-phase-size philosophy elsewhere in the doc chain.
- **D10 (2026-07-01, `/sw-doc-review`, resolves Open Question 1):** confirmed the PRD's original default —
  the R1 auto-flip does **not** run an un-flip when a PRD's status regresses from `complete` back to
  `in-progress`. Product reviewer agreed this is the safer default (avoids un-resolving a gap on a possibly
  transient status flap) and that the residual risk (a mistakenly-`complete`-marked PRD leaves gaps
  incorrectly `resolved` until a human notices) is acceptable and already implicitly covered by normal
  INDEX-status review — no new tooling required.

## Open Questions

None outstanding — both were resolved during `/sw-doc-review` (Decision Log D9, D10).
