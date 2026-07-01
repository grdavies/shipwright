---
absorbs: [GAP-077, GAP-078, GAP-079, GAP-080]
brainstorm: docs/brainstorms/2026-07-01-deliver-concurrency-cwd-terminal-robustness-requirements.md
date: 2026-07-01
topic: deliver-concurrency-cwd-terminal-robustness
frozen: true
frozen_at: 2026-07-01
visibility: public
---
# PRD 050 — Deliver-loop concurrency, worktree/cwd safety & terminal-finalize robustness

## Overview

Eleven open gaps — eight canonical (`gap-005`, `gap-009` through `gap-015`) and three legacy
(`GAP-077`–`GAP-079`, with `GAP-080` folded in as live-reproduction evidence rather than a distinct item) —
share one root defect class: primitives reachable from `/sw-deliver`, `/sw-doc`, and `/sw-amend` assume they
are the only live session touching the repository's single shared **primary checkout**, and do not
differentiate or guard against concurrent sessions, partial-failure states, or stale external signals.

The first sub-cluster (`gap-005`, `GAP-077`–`GAP-080`) was captured by a concurrent `/sw-feedback` session on
2026-06-30 and live-reproduced pollution of the primary checkout (an in-place uncommitted rewrite of
`.cursor/workflow.config.json` plus two untracked gap-unit directories) while ≥4 `/sw-deliver` runs were
independently live. The second sub-cluster (`gap-009` through `gap-015`) was captured by PRD 041's
post-merge retrospective on 2026-07-01 and covers deliver-loop provisioning/stall-classification defects and
terminal-finalize non-idempotency observed during that delivery.

None of the gaps' individually suggested "Schedule" targets are usable: PRD 027, 034, 035, 036, and 042 are
all `status: complete` (the completed-unit immutability guard, PRD 032 R7/R8, mechanically refuses further
amendment). PRD 046 is `not-started` and remains amendable, and its A2 amendment already covers one narrow
slice relevant here (terminal INDEX/COMPLETION-LOG reconcile on finalize) — this PRD depends on and extends
PRD 046 A2 rather than duplicating it (see R15). This is the same systemic "no open home" pattern gap-016
diagnosed and PRD 048/049 already addressed for other clusters; per explicit operator direction (following a
brainstorm pass, see `brainstorm:` above), this work ships as one new standalone PRD.

## Goals

1. No concurrent `/sw-deliver`, `/sw-doc`, `/sw-amend`, or `/sw-feedback` session can mutate the shared
   primary checkout's `HEAD` or working tree as a side effect of another session's operation.
2. `check-frozen.py freeze-commit` and `wave_spec_seed.py`'s `spec-seed` resolve their working root from the
   caller's actual `cwd`, never from script-file-derived paths, and fail closed rather than silently
   targeting the primary checkout when a dedicated worktree exists for the artifact's branch.
3. Deliver-loop phase provisioning is idempotent under partial failure: an orphaned worktree never causes an
   identical-`nextAction` loop into `conductor:no-progress`.
4. The no-progress classifier differentiates stall causes and auto-recovers when the underlying blocker
   clears, instead of treating every repeated `nextAction` as an undifferentiated budget-halt candidate.
5. Terminal finalization is idempotent against local durable-state loss: host-confirmed merge, not local
   state presence, is authoritative for `finalize-completion` and terminal PR bookkeeping.
6. `GAP-077`, `GAP-078`, `GAP-079` (and this PRD's own `gap-005`, `gap-009` through `gap-015`) flip to
   genuinely `resolved` once the above ship with passing fixtures — not narratively closed without a shipped
   guard.

## Non-Goals

- General multi-PRD parallel deliver-loop scoping (`GAP-017`) — this PRD narrows to concurrency-safety of
  the shared primary checkout and the specific stall/provisioning/finalize defects named in Requirements,
  not a full parallel-run architecture redesign.
- Implementing PRD 046 A2 itself — R15 wires `finalize-completion` to call it once it exists; PRD 046 A2's
  own implementation remains PRD 046's scope, tracked there.
- Redesigning the no-progress budget-halt circuit breaker (PRD 009 R38) wholesale — R9/R10 add stall-cause
  differentiation and auto-recovery on top of the existing breaker, not a replacement of its architecture.
- `gap-002`, `gap-003`, `gap-006`, `gap-007`, `gap-008`, `gap-016` — already scheduled elsewhere (PRD 046
  A1/A3, PRD 049, PRD 048 respectively) and outside this cluster's theme.
- Re-opening or editing any `complete` PRD (027, 034, 035, 036, 042) in place — they remain frozen and
  untouched; this PRD is additive and standalone.

## Requirements

### Thread A — Primary-checkout & cwd safety under concurrency

- **R1** (origin: `GAP-077` suggested remediation #2, `gap-005` suggested remediation #2) — A shared, reusable
  primary-checkout guard primitive (Python, per `rules/sw-python-first.mdc`) MUST be introduced and used by
  every call site that currently performs path-derived git mutations against the shared primary checkout
  under concurrency: `wave_lifecycle.py`'s `assert_primary_off_target`, `check-frozen.py`'s `freeze-commit`,
  and `wave_spec_seed.py`'s `cmd_spec_seed`. The primitive fails closed whenever the resolved root/top equals
  the primary checkout's path while a dedicated worktree exists for the target artifact's branch.
- **R2** (origin: `gap-005` suggested remediation #1) — `check-frozen.py freeze-commit` and
  `wave_spec_seed.py:cmd_spec_seed` MUST resolve their working root from the caller's actual `cwd`
  (`Path.cwd()`), never from `__file__`-derived `SCRIPT_DIR.parent` — matching the already-correct pattern in
  `wave.py:repo_root()`.
- **R3** (origin: `GAP-078`) — `skills/conductor/SKILL.md` MUST NOT sanction running the top-level conductor
  loop with `cwd` = the primary checkout; its documented contract MUST be reconciled with
  `core/commands/sw-deliver.md` R53's mandatory-provisioning framing (remove the "or repo root with state
  synced" escape hatch, or replace it with an explicit exception mechanically guarded by R1's primitive).
- **R4** (origin: `GAP-079`) — `.cursor/sw-deliver-runs/run.log` MUST be scoped per deliver run (by branch
  slug, matching the existing `sw-deliver-state.<slug>.json` / `sw-deliver-<slug>.lock` convention), not a
  single shared un-scoped path.
- **R5** (origin: `gap-005` suggested remediation #3) — A regression fixture MUST prove: invoking
  `freeze-commit`/`spec-seed` with `cwd` forced to the primary checkout, while the target artifact exists
  only in a sibling worktree, fails closed and never checks out or commits in the primary checkout.
- **R6** (origin: `GAP-077` problem statement) — A regression fixture MUST prove: provisioning a
  `/sw-deliver` orchestrator worktree for branch B does not mutate the primary checkout's `HEAD` or working
  tree while a concurrent session (human or agent) is using the primary checkout for unrelated branch A work.

### Thread B — Deliver-loop provisioning & stall classification

- **R7** (origin: `gap-009` remediation direction #1) — Phase provision MUST be fail-closed and idempotent:
  if a worktree path exists on disk but `phaseWorktrees[<id>]` is absent from durable state, provision MUST
  either adopt the existing path into state or deterministically tear it down before retry — it MUST never
  repeat an identical `nextAction`.
- **R8** (origin: `gap-009` remediation direction #2) — `dispatch-ship` MUST refuse to proceed for a phase
  until `phaseWorktrees` records that phase's provisioned path.
- **R9** (origin: `gap-011` remediation direction #1) — The no-progress classifier MUST distinguish stall
  causes (orphan-worktree-adopt-pending, merge-queue-wait, external-CI-wait) before tripping `budgetHalt`,
  rather than treating all identical-`nextAction` streaks as one undifferentiated case.
- **R10** (origin: `gap-011` remediation direction #2) — `noProgressStreak` MUST auto-recover (reset) when the
  underlying blocking predicate changes (e.g., worktree adopted, CI state refreshed) without requiring a
  manual state patch.
- **R11** (origin: `gap-012` remediation direction #1) — `check-gate.py` MUST treat a GitHub check reporting
  `IN_PROGRESS` with an underlying workflow-run `conclusion: success` beyond a bounded TTL as settled (green,
  or an explicit `environmental` exit code 10), not as blocking yellow.
- **R12** (origin: `gap-012` remediation direction #3) — Phase-mode ship MUST NOT issue a blocking
  `gh pr checks --watch` call; polling MUST go through `check-gate.py`'s existing backoff mechanism instead.

### Thread C — Terminal-finalize robustness

- **R13** (origin: `gap-010` remediation direction #1) — `finalize-completion` MUST succeed once merge is
  confirmed via the host API (`terminalPr.number` lookup), even when the branch-scoped durable deliver state
  file has been cleared or is absent — host-confirmed merge is authoritative over local state presence.
- **R14** (origin: `gap-010` remediation direction #2) — `completion check-merge` / `finalize-completion` MUST
  NOT require a live feature-branch target to persist terminal bookkeeping when resuming from `main`
  post-merge.
- **R15** (origin: `gap-010` remediation direction #3) — `finalize-completion` MUST invoke PRD 046 A2's
  `living-docs reconcile --commit` (once implemented) so INDEX/COMPLETION-LOG updates do not depend on a
  manual follow-on docs PR. This requirement depends on and extends PRD 046 A2's frozen scope rather than
  re-specifying it; if PRD 046 A2 has not landed by the time this requirement is implemented, implementation
  falls back to explicit terminal INDEX/COMPLETION-LOG update logic and records a cross-link rather than
  blocking on PRD 046.
- **R16** (origin: `gap-013` remediation direction #1/#2) — `wave_terminal.terminal_pr_body()` output MUST be
  rendered and validated through the same template pipeline (`core/sw-reference/templates/pr-body.md` +
  `git_template_lib.py` render/validate) used by phase PRs and `docs_pr.py`, failing closed on validation
  before `host_pr_create`.

### Thread D — Adjacent hygiene guards

- **R17** (origin: `gap-014` remediation direction #1) — A CI guard MUST fail the build if any
  capability-select/capability-lint fixture's `gateRef` (or equivalent script-reference field) points at a
  `.sh` path where a `.py` canonical equivalent exists (PRD 042 python-first).
- **R18** (origin: `gap-015` remediation direction #1) — `/sw-tasks` freeze and `/sw-freeze` MUST require
  `visibility: public` frontmatter on git-tracked frozen artifacts when `planning.visibilityProfile` is
  `all-private`, enforced at freeze time — not only at deliver-loop `assert-entry`.
- **R19** (origin: `gap-015` remediation direction #2) — `wave_spec_seed`'s tracked-private-body check MUST
  emit a clear remediation message pointing to the feature branch (not bare-`main` edits) when it fails at
  `spec-seed` for an `all-private`-profile artifact missing visibility frontmatter.

## Technical Requirements

- **TR1** (R1/R2/R5, D6) — Implement a new shared module `scripts/primary_checkout_guard.py` (module + thin
  CLI entrypoint, matching this repo's `scripts/<name>.py` + `_sw.cli.run_module_main` convention — see
  `scripts/deliver_cwd_guard.py` from PRD 049 for a sibling pattern). Export a single guard function taking
  `(resolved_root, artifact_branch)` and returning pass/fail-closed; import it from `wave_lifecycle.py`,
  `check-frozen.py`, and `wave_spec_seed.py` rather than reimplementing the check per call site. Document the
  convention for future call sites in `.sw/layout.md` (D6). Fixture:
  `freeze-commit-cwd-forced-primary-fails-closed`.
- **TR2** (R2) — Change `check-frozen.py`'s `freeze-commit` root resolution from
  `SCRIPT_DIR.parent` to `Path.cwd()`-derived resolution (mirroring `wave.py:repo_root()`); propagate the
  corrected `cwd` into the `wave.py spec-seed` subprocess invocation rather than the forced `root`.
- **TR3** (R6, D7) — Add a cross-run advisory lock (file-based, `.cursor/sw-deliver-runs/primary-checkout.lock`
  or equivalent — implementer selects primitive per D7) acquired by `assert_primary_off_target` before any
  `git checkout` against the primary checkout, released immediately after; a concurrent acquire attempt
  fails closed with a remediation message rather than proceeding. Fixture:
  `deliver-provision-does-not-mutate-concurrent-primary-checkout`.
- **TR4** (R3) — Update `skills/conductor/SKILL.md` to remove the "or repo root with state synced" phrasing
  and state the mandatory-provisioning contract matching `core/commands/sw-deliver.md` R53; run
  `python3 scripts/build-chain-sync.py` for emitter parity before freeze.
- **TR5** (R4, D8) — Scope `.cursor/sw-deliver-runs/run.log` writes by branch slug
  (`.cursor/sw-deliver-runs/run.<slug>.log`), migrating the existing shared `run.log` reader/writer paths in
  `wave_deliver_loop.py`/`wave.py`; document the new path in `.sw/layout.md`'s durable-artifacts table.
- **TR6** (R7/R8) — Add a state-vs-disk reconciliation check to `provision-phase`: if
  `.sw-worktrees/<phase-worktree-path>` exists but `phaseWorktrees[<id>]` is absent, adopt (register the
  existing path in state) when the worktree's branch matches the expected phase branch, else teardown and
  retry. Add the same check as a precondition to `dispatch-ship`. Fixture:
  `orphan-phase-worktree-adopt-or-teardown`.
- **TR7** (R9/R10) — Extend the no-progress classifier (`status_integrity.py` or sibling) with a stall-cause
  taxonomy and a predicate-change auto-reset hook for `noProgressStreak`. Fixture:
  `no-progress-differentiated-stall-causes`.
- **TR8** (R11/R12) — Add a stale-`IN_PROGRESS` detector to `check-gate.py` keyed on workflow-run
  `conclusion` + a bounded TTL constant; remove/replace any blocking `gh pr checks --watch` invocation in
  phase-mode ship with `check-gate.py`'s existing poll-with-backoff. Fixture:
  `stale-in-progress-success-check-gate-green`.
- **TR9** (R13/R14) — Change `finalize-completion` / `completion check-merge` to check host-API merge status
  first (`terminalPr.number` if present in any recoverable source, else discoverable via host lookup on the
  terminal branch name) and only consult local branch-scoped state as a secondary enrichment, never a
  precondition. Fixture: `finalize-resume-after-state-cleared-post-merge`.
- **TR10** (R15) — Add a call to PRD 046 A2's `living-docs reconcile --commit` entrypoint at the end of
  `finalize-completion`, guarded by a feature-detection check (call only if the entrypoint exists); fall back
  to today's manual-docs-PR path with a logged cross-link when PRD 046 A2 is not yet implemented.
- **TR11** (R16) — Route `wave_terminal.terminal_pr_body()` output through `git_template_lib.py`'s
  `render pr-body` / `validate pr-body`, mirroring `docs_pr.py`'s `_render_pr_body` / `_validate_pr_body`
  pattern; fail closed before `host_pr_create` on validation failure. Fixture:
  `terminal-pr-body-template-valid`.
- **TR12** (R17) — Add a CI check scanning `scripts/test/fixtures/capability-select/**` and
  `scripts/test/fixtures/capability-lint/**` for any `gateRef` (or equivalent) value ending in `.sh` where a
  sibling `.py` canonical script exists; restore the six fixtures identified in `gap-014`'s evidence to their
  canonical `.py` `gateRef` values. Fixture: `capability-gateref-no-shell`.
- **TR13** (R18/R19) — Add a `visibility: public` frontmatter check to `/sw-tasks` freeze and `/sw-freeze`
  when `planning.visibilityProfile: all-private` and the artifact is git-tracked; improve
  `wave_spec_seed.assert_no_tracked_private_bodies`'s error message to point at the feature branch. Fixture:
  `all-private-spec-seed-tracked-private-body`.
- Emitter parity: any change to `skills/conductor/SKILL.md` or other `core/` doc surfaces requires
  `python3 scripts/build-chain-sync.py` before freeze (R32 Python entrypoint model / build-chain SoT).

## Security & Compliance

- All guards operate on local paths, git state, and the GitHub host API only; no new network or credential
  surface beyond the existing `gh`/host-provider calls already used by `check-gate.py` and `wave_terminal.py`.
- TR3's cross-run advisory lock must fail closed (refuse the checkout) rather than silently proceed on lock
  acquisition ambiguity, matching the fail-closed posture of every other guard in this codebase (PRD 032 R6,
  PRD 046 A1's shared guard, PRD 049 TR1).
- TR9's host-API-first finalize logic must not weaken the existing merge-confirmation authority chain (`gh pr
  view MERGED` as source of truth, per memory #2179) — it removes a spurious local-state dependency, not the
  host-confirmation check itself.

## Testing Strategy

- `freeze-commit-cwd-forced-primary-fails-closed` (R2/R5, TR1/TR2).
- `deliver-provision-does-not-mutate-concurrent-primary-checkout` (R6, TR3).
- `orphan-phase-worktree-adopt-or-teardown` (R7/R8, TR6).
- `no-progress-differentiated-stall-causes` (R9/R10, TR7).
- `stale-in-progress-success-check-gate-green` (R11/R12, TR8).
- `finalize-resume-after-state-cleared-post-merge` (R13/R14, TR9).
- `terminal-pr-body-template-valid` (R16, TR11).
- `capability-gateref-no-shell` (R17, TR12).
- `all-private-spec-seed-tracked-private-body` (R18/R19, TR13).
- Register all nine fixtures in `core/sw-reference/pr-test-plan.manifest.json`.
- No regression to PRD 013 R6–R9's per-branch state/lock scoping, PRD 009 R38's no-progress circuit breaker
  architecture, or PRD 046 A2's own fixture set once TR10 lands.
- Re-run `gap_backlog.py check` / `docs-currency-gate.py` after shipping to confirm `GAP-077`, `GAP-078`,
  `GAP-079`, `gap-005`, `gap-009`–`gap-015` all show `resolved`, not merely narratively closed.

## Rollout Plan

1. Implement Thread A (R1–R6, TR1–TR4) first — it is the common root cause several Thread B/D symptoms trace
   back to (`gap-011`'s stall classification, `gap-014`'s fixture drift both occur under the same unguarded
   concurrency window).
2. Implement Thread B (R7–R12, TR6–TR8) next — deliver-loop provisioning/stall-classification hardening,
   independent of Thread C.
3. Implement Thread C (R13–R16, TR9–TR11) — terminal-finalize idempotency; TR10 checks for PRD 046 A2's
   availability at implementation time and falls back gracefully if not yet shipped.
4. Implement Thread D (R17–R19, TR12–TR13) last — narrower, independent hygiene guards; safe to parallelize
   with Thread B/C if phase capacity allows.
5. On ship, flip `GAP-077`, `GAP-078`, `GAP-079` via `gap_backlog.py flip --resolve` (or automatically if PRD
   048's mechanical flip has shipped by then) and this PRD's own `gap-005`, `gap-009`–`gap-015` via the same
   mechanism; attach `gap_backlog.py check` / `docs-currency-gate.py` output to the PR.

## Decision Log

- **D1 (2026-07-01):** Bundle all 11 gaps into one new standalone PRD rather than splitting by root-cause
  class (concurrency-safety vs. deliver-robustness) or filing several smaller PRDs. Rationale: all 11 share
  the "no open home" defect (every named schedule target is `complete` except PRD 046, which covers only one
  narrow slice); the concurrency-safety thread (A) is the root cause several Thread B/D symptoms are
  downstream of; explicit operator direction to keep this one deliverable, confirmed at the brainstorm
  synthesis checkpoint.
- **D2 (2026-07-01):** `GAP-080` is treated as live-reproduction evidence for `GAP-077`/`GAP-078`'s fixtures
  (R6), not given its own requirement — it reproduces the identical failure mode with no new remediation
  direction beyond what R1/R3/R6 already cover.
- **D3 (2026-07-01):** R15 (terminal INDEX reconcile) is scoped as a dependency on PRD 046 A2 rather than a
  duplicate implementation, since PRD 046 is `not-started` (still amendable) and A2 already carries this
  exact frozen scope — implementing it twice would create drift between two PRDs' fixtures for the same
  behavior.
- **D4 (2026-07-01):** Pre-work memory search (scoped to primary-checkout concurrency and deliver-loop/
  terminal-finalize robustness) surfaced no contradicting frozen decisions or rules; existing memories
  (#2227, #2239, #2283, #2286, #2202) independently corroborate the root causes already documented in the
  gaps — no reconciliation conflict to record beyond this note.
- **D5 (2026-07-01):** `gap-014` (capability-trust fixture `.sh` regression) and `gap-015` (all-private
  visibility spec-seed guard) are included as Thread D despite being narrower/more mechanical than Threads
  A–C, per explicit operator confirmation to keep the original 11-gap framing as one deliverable rather than
  deferring them to a separate follow-up.
- **D6 (2026-07-01):** TR1 covers the three named call sites only; new scripts performing git mutations
  against the shared primary checkout MUST follow a documented convention (`Path.cwd()` root resolution +
  `primary_checkout_guard` check). An exhaustive call-site audit is out of scope — a follow-up gap captures
  any fourth call site discovered later.
- **D7 (2026-07-01):** TR3's cross-run advisory lock primitive (file lock vs. PID-based vs.
  `.cursor/sw-deliver-runs/index.json` entry) is an implementer decision at task time; R6 constrains the
  outcome (no concurrent primary-checkout mutation), not the locking mechanism.
- **D8 (2026-07-01):** R4/TR5 scope `run.log` by branch slug (`.cursor/sw-deliver-runs/run.<slug>.log`),
  matching the existing `sw-deliver-state.<slug>.json` / `sw-deliver-<slug>.lock` convention — one growing
  file per slug, not per-invocation run id.
