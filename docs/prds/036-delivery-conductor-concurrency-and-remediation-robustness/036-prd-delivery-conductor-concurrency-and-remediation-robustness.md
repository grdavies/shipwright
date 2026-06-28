---
brainstorm: docs/brainstorms/2026-06-28-delivery-conductor-concurrency-and-remediation-robustness-requirements.md
date: 2026-06-28
topic: delivery-conductor-concurrency-and-remediation-robustness
---
# PRD 036 — Delivery-Conductor Concurrency & Remediation Robustness

## Overview

This is a PRD 027 follow-on that hardens the delivery conductor / wave-merge / phase-ship engine against four
failure classes observed in a single `/sw-deliver` run under `orchestration.planPolicy: proposed`
(`feat/planning-feedback-lifecycle`): a concurrent dual-ship duplicate-PR race (GAP-048), a post-merge
regression that could not reach remediation (GAP-049), premature partial merges before parallel-batch
completion plus an unautomated deterministic merge conflict (GAP-050 / GAP-051), and a non-terminal
hand-authored `status.json` that stalled the driver (GAP-052).

Critically, these recurred **even though PRD 013 (deliver concurrency / locks) and PRD 027 (terminal
finalization) already shipped**. The architectural through-line of the fix is **single-flight,
evidence-derived advancement**: ship dispatch, regression remediation, and terminal-status acceptance all
become single-flight and are derived from verified evidence (locks, CI/PR signals, provenance markers)
rather than from trusted artifacts or hand-authored state. Because the classes recurred past prior fixes,
every finding also ships a regression guard that asserts *why* the earlier fix did not cover it, so the
class cannot silently reopen.

All advancement state continues to flow through the existing `wave_*.py` primitives behind
`scripts/wave.sh`; the conductor never maintains parallel state. The human merge-to-`main` gate is unchanged.

## Goals

- Make phase-ship single-flight so a concurrent parent + sub-agent ship on one phase head can never produce
  more than one PR, and that PR is always based on the integration branch.
- Make a genuine post-merge regression (`verify:failed`) reach bounded `/sw-stabilize` remediation
  autonomously, without tripping the no-progress breaker before the first attempt and without a manual
  `noProgressStreak` reset.
- Prevent avoidable parallel-merge collisions, enforce strict whole-batch completion before any member
  merges, and auto-resolve *deterministic* (golden-manifest / `dist` / generated-mirror) merge conflicts
  while still halting on semantic/source conflicts.
- Guarantee terminal `status.json` is provenance-stamped and validity-checked so a hand-authored status is
  never accepted (closing both the stall and the faked-`merge-ready-green` holes), with budget-bounded
  canonical re-emit recovery and a blessed recovery command.
- Ship a regression fixture per finding that fails on the pre-fix behavior and encodes why PRD 013 / PRD 027
  missed it.

## Non-Goals

- Re-architecting the wave/conductor execution engine wholesale.
- Changing or weakening the human merge-to-`main` gate, the secret-scan push chokepoint, or the
  single-flight merge-queue invariants.
- The planning-doc lifecycle program (PRDs 031–035), which explicitly non-goals the delivery conductor / wave
  engine; this PRD is the delivery-side complement, not part of that program.
- Auto-resolving semantic or source-code merge conflicts — only deterministic regeneration conflicts
  (golden manifest, `dist/**`, generated mirrors) are auto-resolved.
- Changing plan-policy (`canonical` / `proposed`) semantics — these findings are policy-agnostic conductor
  defects; the incident merely surfaced them under `proposed`.
- Broadening the deterministic-conflict auto-resolve set beyond golden-manifest / `dist` / generated mirrors
  without evidence (deferred).

## Requirements

- **R1** A single *phase* `dispatch-ship` runs in-turn/inline in the conductor; a background sub-agent is used
  only for `dispatch-batch` parallel waves, where each sub-agent owns a distinct phase head — the conductor
  never both backgrounds a single ship and progresses it in the parent.
- **R2** A per-phase-head single-shipper lease (reusing the `wave.sh lock` O_EXCL primitive) is acquired
  before ship work touches the head; a non-holder must no-op, and the lease carries a TTL plus stale-steal so
  a crashed/abandoned shipper cannot deadlock the head.
- **R3** Phase-mode PR creation is idempotent: the ship path runs `pr-list --head <phase-branch>` filtered by
  the integration base and reuses an existing open PR instead of creating a second one (no `gh pr create`
  TOCTOU duplicate).
- **R4** Phase-mode PR creation always pins `--base` to the integration branch from deliver state /
  `SW_INTEGRATION_BRANCH` and fails closed when `SW_PHASE_MODE` is set and the base would not be the
  integration branch (no orphan-`main` PR), extending PRD 026 R20 to the racing path.
- **R5** When the parent conductor takes over from a dispatched sub-agent, the orphaned sub-agent is cancelled
  or otherwise prevented from reaching `sw-pr`; when duplicate PRs nonetheless exist, the canonical PR is the
  one whose base matches the integration branch (not whichever finished last), and superseded duplicates are
  closed by branch identity (consistent with PRD 026 R21).
- **R6** `merge-run-next` routes a post-merge `verify:failed` regression (exit 20) to bounded remediation
  (`/sw-stabilize`) within `deliver.remediation.maxAttempts`, not only `verify:environmental` (exit 10).
- **R7** A freshly-`blocked`-with-remediation-budget phase produces a *distinct* durable state signature so
  the `conductor:no-progress` circuit breaker cannot trip before the first remediation attempt is made.
- **R8** When the remediation budget for a regression is exhausted, the driver emits a single consolidated
  legitimate halt (with `resumeCommand`), never a silent spin or bare continuation prompt.
- **R9** Plan-time contention injection treats golden-manifest, `dist/**`, and generated-mirror touches as
  contention edges, forcing phases that share those artifacts into different waves (prevention of avoidable
  merge collisions).
- **R10** No member of a parallel wave batch is merged until **all** batch members have published a terminal
  `status.json` (`merge-ready-green` or `blocked`); the conductor never merges a single ready member early
  (strict R44).
- **R11** Within a batch, ready members are enqueued and merged in deterministic phase-id order
  (`collect-all-ready`), and members sharing a contended artifact are serialized rather than merged on
  first-ready.
- **R12** A `merge-queue:conflict` whose conflicting paths are entirely within the deterministic-regeneration
  set (golden manifest, `dist/**`, generated mirrors) is auto-resolved by regenerate-and-restage within a
  bounded attempt count; any conflict touching source/semantic paths remains a legitimate human halt.
- **R13** `ship-phase-status.sh` writes a verifiable provenance marker into `status.json`, and the driver
  rejects any `status.json` lacking a valid marker (a hand-authored status is never accepted as terminal,
  closing both the stall and the faked-`merge-ready-green` holes).
- **R14** The driver validates a terminal `status.json` for: terminal `verdict`, a full 40-char head SHA equal
  to the phase branch tip (`git rev-parse`), and a parseable gate JSON — rejecting abbreviated-SHA / stale /
  malformed status.
- **R15** When a phase is `await-in-flight` but independent evidence (open phase PR + green CI, or branch tip
  with a green gate) indicates it is done while `status.json` is non-terminal/invalid, the driver classifies
  it `stuck-stale` rather than continuing to wait.
- **R16** A `stuck-stale` phase routes to a budget-bounded auto re-emit that re-derives the verdict via the
  canonical `/sw-ship --phase-mode` terminal steps / `sw-ready` (or `/sw-stabilize` + ship terminal) — never
  by trusting or hand-editing `status.json`; the re-emit action changes the state signature (per R7) so it
  cannot instantly trip the no-progress breaker, and exhaustion is a legitimate halt.
- **R17** A single blessed operator/agent recovery command re-emits canonical terminal status for a phase, so
  hand-editing `status.json` is never the path of least resistance; `rules/sw-conductor.mdc` is updated to
  point to it.
- **R18** Each finding (R1–R17 groups) ships a regression fixture that both reproduces the original failure
  and asserts the specific reason the prior PRD 013 / PRD 027 fix did not cover it, so the class cannot
  silently reopen.
- **R19** All advancement remains mechanically sourced through `scripts/wave.sh` / `wave_*.py` and durable
  `status.json` / state — no new parallel state store, and no conductor prose that re-implements state
  transitions.
- **R20** New scripts/config keys land in `core/` and propagate to both dist trees; `copy-to-core` parity and
  emitter-freshness fixtures cover them.
- **R21** Operator-facing docs are updated as acceptance criteria where behavior changes: `sw-deliver.md`,
  `sw-ship.md`, `skills/conductor/SKILL.md`, `rules/sw-conductor.mdc`, and the relevant `docs/guides/*`
  sections (single-flight ship, regression remediation routing, R44 strictness + deterministic-conflict
  auto-resolve, status provenance + recovery command).
- **R22** No regression to the human merge-to-`main` gate, secret-scan push chokepoint, scoped-lock /
  single-flight merge invariants, or frozen-doc/CI gates.

## Technical Requirements

- **Ship single-flight (R1–R5).** Extend the phase-ship path (`scripts/wave.sh` ship verbs, `wave_phase_pr.py`,
  `ship-phase-status.sh`, and the `/sw-ship --phase-mode` chain) with: (a) a per-head lease built on the
  existing `wave.sh lock` O_EXCL primitive (TTL + stale-steal); (b) a `pr-list --head <branch>`
  read-before-create idempotency check filtered by integration base; (c) base pinning via deliver state /
  `SW_INTEGRATION_BRANCH` with fail-closed when `SW_PHASE_MODE` is set. Conductor dispatch discipline
  (`skills/conductor/SKILL.md`, `rules/sw-conductor.mdc`, `sw-dispatch-background-phase` rule) is updated so a
  single ship is in-turn and only `dispatch-batch` backgrounds sub-agents on distinct heads.
- **Regression remediation routing (R6–R8).** `wave_deliver_loop.py merge-run-next` and `wave_failure.py`
  gain a `verify:failed` (exit 20) → bounded `remediate`/`/sw-stabilize` route distinct from
  `verify:environmental` (exit 10); the durable state-signature computation incorporates remediation
  attempt/budget so a freshly-`blocked` phase changes signature; `check_budget_halt` must not pre-empt an
  unattempted remediation. Budget single-sourced from `deliver.remediation.maxAttempts`.
- **Parallel merge safety (R9–R12).** Plan-time contention injection (kernel/plan-validation + wave
  derivation in `wave_deliver.py`) adds golden-manifest / `dist/**` / generated-mirror paths as contention
  edges. The merge queue (`wave_merge.py` / merge-queue primitives) enforces strict whole-batch terminal
  completion before any member merges, deterministic phase-id ordering, and a bounded
  regenerate-and-restage auto-resolution for conflicts confined to the deterministic-regeneration path set
  (e.g. `scripts/copy-to-core.sh` + `python3 -m sw generate --all` + golden re-snapshot), halting otherwise.
- **Terminal-status integrity (R13–R17).** `ship-phase-status.sh` emits a deterministic, offline-regenerable
  provenance marker over canonical status fields; the driver validates terminal `verdict`, full 40-char head
  SHA vs `git rev-parse`, and gate-JSON parseability, and adds a `stuck-stale` classifier driven by
  independent CI/PR evidence with budget-bounded canonical re-emit. A blessed recovery command (atomic or a
  documented `/sw-ship --phase-mode` terminal-step invocation, per OQ4) re-emits canonical status.
- **Mechanical sourcing & propagation (R19–R20).** No new parallel state store; all transitions stay in
  `wave_*.py` + durable state. New scripts/config keys land under `core/` and propagate to `dist/cursor` and
  `dist/claude-code`, covered by `copy-to-core` parity and emitter-freshness fixtures.

## Security & Compliance

- **No weakening of trust boundaries.** The human merge-to-`main` gate, secret-scan push chokepoint, and
  memory redaction/preflight chokepoints are unchanged (R22). Auto-resolve (R12) and auto re-emit (R16) never
  bypass the secret-scan push gate or merge work to `main`.
- **Provenance marker is integrity-only, not a secret.** The R13 marker must be deterministic, offline, and
  regenerable by a fresh resumed agent (no stored secret, no network). It authenticates *that the canonical
  ship path produced the status*, not identity; it must not embed tokens, transcripts, or PII, and any
  diagnostic logging routes through redaction.
- **Lease safety (R2).** The single-shipper lease must fail safe: a crashed holder cannot permanently deadlock
  a head (TTL + stale-steal), and a non-holder must no-op rather than force-acquire.
- **Fail-closed posture.** Base-pin (R4), provenance validation (R13/R14), and conflict classification (R12)
  all fail closed — an unverifiable base, marker, or conflict path set halts rather than proceeds.

## Testing Strategy

- **Regression-guard fixtures (R18), one per finding, each encoding why 013/027 missed it:**
  - *Dual-ship (R1–R5):* a concurrent parent + sub-agent ship attempt on one head yields exactly one PR based
    on the integration branch, no orphan-`main` PR; asserts the lease + idempotency + base-pin and that PRD
    026 R20/R21 (single-PR only) did not cover the racing path.
  - *Regression remediation (R6–R8):* `merge-run-next` on a `verify:failed` (exit 20) reaches
    `remediate`/`/sw-stabilize` on the next `deliver-loop` tick within budget without a manual reset; a
    freshly-`blocked` phase changes the state signature; budget exhaustion emits one consolidated halt.
  - *Parallel merge (R9–R12):* a batch sharing a golden-manifest touch never merges a member early, merges in
    deterministic order, avoids the collision via contention, and auto-resolves a deterministic conflict while
    halting on a seeded semantic conflict.
  - *Status integrity (R13–R17):* a non-terminal hand-authored `status.json` with green CI is detected
    `stuck-stale` and recovered by canonical re-emit (not a `conductor:no-progress` / heartbeat-stale stall);
    a faked `merge-ready-green` lacking a valid provenance marker is rejected; an abbreviated/stale head SHA is
    rejected.
- **Determinism / offline.** All fixtures run offline and deterministically for reproducible CI (no live
  GitHub); host interactions are stubbed via the existing host-fixture harness.
- **Propagation coverage (R20).** `copy-to-core` parity, emitter-freshness, and golden-manifest parity
  fixtures cover any new `core/` scripts/keys.
- **CI enforcement.** New fixtures are registered in `core/sw-reference/pr-test-plan.manifest.json` (regenerating
  `.github/workflows/pr-test-plan-ci.yml`) as `required`, so the guards are CI-blocking (PRD 016).

## Rollout Plan

- **Phasing.** Independent, separately shippable workstreams, sequenced to retire the highest-recurrence-risk
  classes first: (1) ship single-flight (R1–R5); (2) regression remediation routing (R6–R8); (3) parallel
  merge safety (R9–R12); (4) terminal-status integrity + recovery (R13–R17). Cross-cutting requirements
  (R18–R22) are satisfied within each phase rather than as a separate phase.
- **Compatibility.** Behavior changes are conductor-internal; no config migration is required. New
  `deliver.*` keys (if any beyond `deliver.remediation.maxAttempts`) default to current behavior when absent.
- **Docs-as-acceptance (R21).** Each phase updates its operator-facing docs as part of the phase's acceptance,
  not afterward.
- **Validation.** Land behind the existing fixture gates; no flag-gated runtime toggle is planned (the fixes
  are corrections, not opt-in features). A follow-on dogfood `/sw-deliver` run under `proposed` confirms the
  four classes no longer recur.

## Decision Log

- **D1** Phase-ship is made single-flight via defense-in-depth (process discipline + a per-head lease +
  idempotency/base-pin), symmetric with the already single-flight merge queue. Idempotency-only (TOCTOU-racy)
  and no-background-only (misses crash/resume leftovers and concurrent-push corruption) were rejected as
  partial; the layered approach is the only one that also prevents concurrent pushes on one head. (K1 → R1–R5)
- **D2** `verify:failed` regressions route to bounded `/sw-stabilize` within `deliver.remediation.maxAttempts`,
  and the no-progress breaker is fixed so a freshly-`blocked`-with-budget phase yields a distinct signature and
  cannot pre-empt the first remediation. A separate stricter regression budget and treating every regression
  as an immediate human halt were rejected (added complexity / needless autonomy loss). (K2 → R6–R8)
- **D3** Parallel-merge safety is prevent-then-enforce-then-auto-resolve: contention-edge prevention, strict
  R44 whole-batch completion + deterministic ordering, and bounded auto-regen for deterministic conflicts only.
  Reactive-only (lets the avoidable collision recur) and enforce-only-with-all-conflicts-as-halts (autonomy
  loss for mechanical regen) were rejected. (K3 → R9–R12)
- **D4** Terminal-status integrity combines a ship-emitted provenance marker + validity check, reactive
  `stuck-stale` detection from CI/PR evidence, and budget-bounded canonical re-emit, plus a blessed recovery
  command. Provenance closes both the stall and the faked-`merge-ready-green` holes; auto re-emit is safe
  because it re-derives the verdict from the real ship/gate path. Provenance-only (halt) and reactive-only
  (misses the fake-green hole) were rejected as partial. (K4 → R13–R17)
- **D5** Because GAP-049/050/052 recurred despite PRD 013/027, every finding ships a regression fixture that
  reproduces the gap and asserts why the earlier fix did not cover it, so the class cannot silently reopen.
  (K5 → R18)
- **D6** This is a follow-on PRD, not an amendment to PRD 013/017/026/027 (all complete and frozen); it
  consumes and hardens them. Amending a frozen, shipped PRD was rejected in favor of a traceable new unit.

## Open Questions

- **OQ1** Should the per-phase-head lease (R2) be a new keyed lease file or an extension of the existing scoped
  `sw-deliver-<slug>.lock` namespace? Proposed lean: a per-head keyed lease file under the existing lock
  namespace/dir (reuses the O_EXCL primitive and cleanup paths); confirm at design.
- **OQ2** What is the bounded attempt count for deterministic-conflict auto-regen (R12) — reuse
  `deliver.remediation.maxAttempts`, or a dedicated small ceiling? Proposed lean: a dedicated small ceiling
  (e.g. 1–2) since regen is deterministic and should converge in one pass; confirm at design.
- **OQ3** Provenance-marker mechanism (R13): a content hash over canonical fields vs an HMAC/signed token.
  Constraint: must stay deterministic/offline for CI and regenerable by a fresh resumed agent. Proposed lean: a
  content hash over canonical status fields (deterministic, no key management); revisit only if tamper
  resistance beyond integrity is required.
- **OQ4** Should the blessed recovery command (R17) be a new `/sw-*` atomic or a documented `/sw-ship
  --phase-mode --from <terminal-step>` invocation? Resolve at design per `sw-naming` (prefer reusing
  `/sw-ship --phase-mode` terminal steps over minting a new command unless a distinct surface is warranted).
