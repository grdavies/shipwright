---
id: gap-006-prd-033-marked-complete-but-a3-r37-r39-r40-r42-r
type: gap
status: resolved
title: PRD 033 marked complete but A3 R37/R39/R40/R42/R43 (operator worktree contract, in-flight cwd guard) are unimplemented
visibility: public
tags: [source:feedback, signal:feedback-prd033-a3-r39-unimplemented-2026-06-30]
---

# PRD 033 marked complete but A3 R37/R39/R40/R42/R43 (operator worktree contract, in-flight cwd guard) are unimplemented

_Captured from feedback signal `feedback-prd033-a3-r39-unimplemented-2026-06-30`._

## Found while drafting a PRD 036 amendment for gap-002/gap-005

While drafting an amendment to close gap-002's "remediation #4" (the unguarded `reconcile_lib.py:set_index_status`
/ `wave_living_docs.py:git_commit_living_docs` primitives) and gap-005 (cwd-dependent `check-frozen.py
freeze-commit` / `wave_spec_seed.py` resolution), the natural-seeming fix already exists as a **frozen,
"complete"** amendment: `docs/prds/033-lifecycle-dependencies-and-scheduler/amendments/A3-operator-worktree-contract.md`
(frozen 2026-06-29, absorbs GAP-056). Its R39 requires exactly this:

> A fail-closed **in-flight cwd guard** MUST refuse (exit non-zero with remediation) when a work-performing
> surface runs from the primary checkout on `defaultBaseBranch` while a deliver run for the repo is
> `verdict: running`... Surfaces (minimum): `wave_living_docs --commit`, `reconcile-status.py reconcile`,
> `/sw-retrospective` write paths, and `wave_deliver_loop` manual living-doc reconcile suggestions. Extends A1
> R31 (reconciler default-branch refuse) to **operator command entry**, not only the reconciler script.

`INDEX.md` shows PRD 033 — main + A1 + A2 + **A3** — as `complete`. It is not.

## Evidence (verified by direct code/file search, 2026-06-30)

| A3 requirement | Required artifact | Search result |
|---|---|---|
| R37 (worktree contract in `.sw/layout.md`) | An "operator worktree contract" diagram/table section in `.sw/layout.md` | **Missing** — `.sw/layout.md`'s section list has no such heading (checked full `^##` heading list) |
| R38 (skill docs echo contract) | Contract language in `core/skills/conductor/SKILL.md` / `core/skills/deliver/SKILL.md` | **Missing** — zero matches for the contract language in either file |
| R39 (in-flight cwd guard) | `scripts/deliver_cwd_guard.sh` (TR-A3-1, "or equivalent module") wired into `wave_living_docs --commit`, `reconcile-status.py reconcile`, `/sw-retrospective` write paths | **Missing entirely** — `grep -rn "deliver_cwd_guard\|cwd_guard" scripts/ core/` returns zero matches anywhere in the repo; `wave_living_docs.py:git_commit_living_docs` (read directly) has no guard call of any kind before its unconditional `git -C <top> commit` |
| R40 (`sync_canonical_state_read()`) | A function of that name in `wave_state.py` / `wave_deliver_loop.py` | **Missing** — zero matches |
| R41 (`SW_REPO_ROOT` mirror) | `ship-phase-status.py` reads `SW_REPO_ROOT` | **Present** — `scripts/ship-phase-status.py:53` already reads `SW_REPO_ROOT` (per A3's own framing, this "extends PRD 027 R4," which had already landed; not independent evidence A3 itself was implemented) |
| R42 (`deliver-worktree-contract` fixture) | Fixture registered in `core/sw-reference/pr-test-plan.manifest.json` | **Missing** — manifest has 50 fixture entries, none matching `worktree-contract` or `cwd-guard` |
| R43 (gap-resolve GAP-056 on ship) | N/A — depends on R39 actually shipping | Moot — R39 never shipped |

**Net: 5 of 6 substantive A3 requirements (R37–R40, R42) are unimplemented; only R41 incidentally passes because
its dependency (PRD 027 R4) had already landed independently.** This is the exact primitive gap-002's own
addendum (and the original signal) needed — it was already speced, frozen, and marked `complete` without ever
being built.

## Why this matters beyond PRD 033 itself

1. **INDEX `complete` is not a reliable signal of implementation status** for at least this one frozen
   amendment — a broader question (is this systemic across other "complete" PRDs/amendments, or specific to
   A3?) is open and not investigated here; scoping that audit is out of this gap's reach.
2. **gap-002's "remediation #4" should not re-spec R39's intended fix from scratch** — the correct move is
   either (a) implement the already-frozen A3 R37–R40/R42 as written, or (b) explicitly supersede/narrow R39's
   scope if it's found insufficient (it is deliver-run-state-gated; gap-002's evidence and gap-005 are not
   necessarily tied to an active deliver run) and amend PRD 033 itself rather than starting over elsewhere.
3. A companion PRD 036 amendment (drafted alongside this gap) deliberately scopes itself to the **residual**
   gap-002/gap-005 evidence not covered by R39 even if R39 *were* implemented — an **unconditional**,
   primitive-level default-branch-commit guard (not gated on "is a deliver run currently `running`"), and the
   `/sw-freeze` (`check-frozen.py`/`wave_spec_seed.py`) surface R39 never named at all (`/sw-deliver` was the
   only orchestrator in R39's surface list; `/sw-doc`/`/sw-amend` freeze was not). It is explicitly
   complementary to R39, not a duplicate or a replacement — implementing R39 as already spec'd remains a
   separate, still-needed action this gap tracks.

## Suggested remediation

1. Implement PRD 033 A3 R37, R38, R39, R40, R42 (and flip R43/GAP-056 resolution to actually true) as already
   frozen and specified — no new spec authoring needed, this is a pure implementation gap.
2. After R39 ships, re-evaluate whether gap-002's "remediation #4" upstream-primitive fix and the companion
   PRD 036 amendment's unconditional guard are still both necessary, or whether R39 (once real) subsumes part
   of them — do not let three overlapping specs (033 A3, gap-002, PRD 036 amendment) drift independently.
3. Flag to the operator: audit whether other PRDs/amendments marked `complete` in `INDEX.md` have similarly
   unimplemented requirements — this gap found one by accident while researching an unrelated amendment, not
   via systematic audit; the population of "complete but not actually done" entries is unknown.
4. Consider whether `INDEX.md`'s `complete` status should require (or be cross-checked against) an explicit
   per-requirement implementation manifest, rather than being set by narrative/operator judgment at ship time
   with no mechanical link back to which `R`-IDs actually shipped.
