---
brainstorm: docs/brainstorms/2026-06-28-delivery-conductor-concurrency-and-remediation-robustness-requirements.md
date: 2026-06-28
topic: delivery-conductor-concurrency-and-remediation-robustness
frozen: true
frozen_at: 2026-06-28
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

`proposed` plan-policy was the **stress test, not the root cause**: these are policy-agnostic conductor
defects that parallel waves + agent-proposed plans surface more readily than `canonical` mode does (see the
PRD 023 pilot framing). The four findings carry **equal weight** as distinct workstreams — dual-ship
single-flight (R1–R5), regression-remediation routing (R6–R8), parallel-merge batch safety (R9–R12), and
terminal-status provenance/recovery (R13–R17) — not a single "concurrency + remediation" pair.

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
- Ship a regression fixture per failure class (R1–R17 groups) that fails on the pre-fix behavior and encodes
  why the prior shipped PRD for that class (PRD 026 for dual-ship; PRD 013 / PRD 027 for the others) did not
  cover it.

## Success Criteria

Each criterion is fixture-backed (offline/deterministic per the Testing Strategy) and re-confirmed by the
follow-on dogfood `/sw-deliver` run under `proposed`:

- **SC1** A concurrent parent + sub-agent ship on one phase head yields **exactly one** open PR, always based
  on the integration branch — zero duplicate or orphan-`main` phase PRs per deliver run. (R1–R5)
- **SC2** A post-merge `verify:failed` regression reaches `/sw-stabilize` within
  `deliver.remediation.maxAttempts` on the next `deliver-loop` tick **with no manual `noProgressStreak`
  reset**; the no-progress breaker never pre-empts an unattempted remediation. (R6–R8)
- **SC3** No member of a parallel wave batch merges before every member is terminal — zero premature-merge
  golden-manifest conflicts on a later batch sibling. (R9–R11)
- **SC4** A deterministic golden-manifest / `dist` conflict auto-resolves within the regen ceiling, while a
  seeded semantic/multi-preimage conflict halts for human review. (R12)
- **SC5** A non-terminal / hand-authored `status.json` with green CI recovers via canonical re-emit instead of
  stalling on `conductor:no-progress` / heartbeat-stale, and a forged `merge-ready-green` is rejected by the
  live-host-evidence check. (R13–R17)
- **SC6** End-to-end: a single `/sw-deliver` run under `proposed` reaches its terminal gate with **zero manual
  `status.json` edits and zero duplicate phase PRs**.
- **Pilot gate.** SC1–SC6 (per-class fixtures green + the SC6 dogfood run) are the explicit **go/no-go for
  widening `orchestration.planPolicy: proposed`** beyond the hermetic dogfood. The default stays `canonical`
  (unchanged — see Non-Goals); this PRD does not relax that default.

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
- Autonomous terminal-ship automation (GAP-022: terminal PR + CI watch + stabilize at deliver end) and
  multi-PRD parallel deliver-loop scoping (GAP-017) — out of scope; R6–R8 phase-level remediation does not
  expand into terminal-ship automation, and concurrency stays within the existing per-branch locks.
- Re-implementing or amending PRD 027 status path discovery (R4–R6) or proactive status collection; R13–R17
  add provenance, validity, stuck-stale classification, and bounded re-emit only — not a new path layer.
- General plan-kernel work: R9 plan-validation changes are limited to golden-manifest / `dist` / generated-mirror
  contention edges; no PRD 013 R13–R16 deferrals (cross-feature waves, file-set inference, durable `/sw-tasks`
  contention feedback), no plan-policy semantics change, and no automatic `/sw-tasks` re-run.
- General conductor self-healing: autonomous re-emit (R16) applies only to `stuck-stale` / invalid-or-non-terminal
  `status.json` recovery; it does not generalize to other halt classes or bypass any legitimate human gate.

## Requirements

- **R1** A single *phase* `dispatch-ship` runs in-turn/inline in the conductor; a background sub-agent is used
  only for `dispatch-batch` parallel waves, where each sub-agent owns a distinct phase head — the conductor
  never both backgrounds a single ship and progresses it in the parent.
- **R2** A per-phase-head single-shipper lease (reusing the `wave.sh lock` O_EXCL primitive) is acquired
  before ship work touches the head; a non-holder must no-op, and the lease carries a TTL plus stale-steal so
  a crashed/abandoned shipper cannot deadlock the head. The ship-lease TTL is shorter than, and distinct from,
  the orchestrator-lock stale policy (`SW_LOCK_STALE_SECONDS`, default 3600s) so a crashed shipper cannot block
  a head for a full hour.
- **R3** Phase-mode PR creation is idempotent: the ship path runs `pr-list --head <phase-branch>` filtered by
  the integration base and reuses an existing open PR instead of creating a second one. The
  `pr-list`→`pr-create` window is held under the per-head lease (R2) so the read-then-create cannot interleave
  with another shipper, and the resulting `openPrNumber` is persisted to durable wave state immediately after
  the first successful create; a second create attempt for a head that already records an open PR is fatal and
  routes to the supersede/close flow (R5) rather than opening a duplicate.
- **R4** Phase-mode PR creation always pins `--base` to the integration branch, sourced from **durable deliver
  state as the sole authority**; `SW_INTEGRATION_BRANCH` is test-harness-only and a disagreement with state
  fails closed (so a poisoned env var cannot redirect the base). The integration stamp is re-validated
  immediately before `pr-create`, and the create fails closed when `SW_PHASE_MODE` is set and the base would
  not be the current integration branch (no orphan-`main` PR), extending PRD 026 R20 to the racing path. PRs
  whose base ≠ the current integration branch are closed before merge enqueue.
- **R5** When the parent conductor takes over from a dispatched sub-agent, the orphaned sub-agent is cancelled
  or otherwise prevented from reaching `sw-pr`; when duplicate PRs nonetheless exist, the canonical PR is the
  one whose base matches the integration branch (not whichever finished last), and superseded duplicates are
  closed by branch identity (consistent with PRD 026 R21).
- **R6** `merge-run-next` routes a post-merge `verify:failed` regression (exit 20) to bounded remediation
  (`/sw-stabilize`) within `deliver.remediation.maxAttempts`, not only `verify:environmental` (exit 10).
  Regression vs environmental is classified from **structured exit codes + `check-gate` JSON verdicts first**,
  with substring markers used only as a tie-breaker, and the two paths carry **separate remediation budgets**
  so environmental flakes cannot exhaust the regression budget (or vice versa).
- **R7** A freshly-`blocked`-with-remediation-budget phase produces a *distinct* durable state signature so
  the `conductor:no-progress` circuit breaker cannot trip before the first remediation attempt is made.
  `build_state_signature` incorporates per-phase `remediationAttempts`, `lastRemediationAt`, and the stabilize
  pass id (commit SHA + gate verdict) so the signature changes on each remediate dispatch and each stabilize
  completion regardless of the phase status string.
- **R8** When the remediation budget for a regression is exhausted, the driver emits a single consolidated
  legitimate halt (with `resumeCommand`), never a silent spin or bare continuation prompt. The driver also
  escalates to a human halt early when the **same verify-failure cause repeats** across attempts (a
  non-converging stabilize loop) even if budget remains; a single environmental re-verify does not count
  against the regression budget.
- **R9** Plan-time contention injection treats golden-manifest, `dist/**`, and generated-mirror touches as
  contention edges, forcing phases that share those artifacts into different waves (prevention of avoidable
  merge collisions). Because a phase's *declared* `phase_files` may omit generator outputs it touches only at
  ship time, any phase that invokes `generate` is treated as touching the full declared generator-output set
  (`dist/**`, golden-manifest globs) for contention purposes.
- **R10** No member of a parallel wave batch is merged until **all** batch members have published a *validated*
  terminal `status.json` (per R13–R14: provenance marker + full 40-char head SHA + parseable gate JSON) with
  verdict `merge-ready-green` or `blocked`; the conductor never merges a single ready member early (strict R44).
  A bare verdict string is insufficient — batch completeness is the R13–R14 validity check, not the enum alone.
  The batch merge is **atomic with respect to the integration tip**: integration HEAD is frozen at
  `collect-all-ready` and all ready members merge without interleaved integration updates, **or** each phase
  head is rebased to the current integration tip before its merge exec; if integration moves mid-batch the
  driver halts rather than merging against a superseded base.
- **R11** Within a batch, ready members are enqueued and merged in deterministic phase-id order
  (`collect-all-ready`). Because R9 separates artifact-contended phases into different waves, R11 is primarily
  deterministic phase-id ordering; if co-waving of contended phases remains possible, the merge queue performs
  a pre-enqueue contended-artifact check and serializes those members rather than merging on first-ready.
- **R12** A `merge-queue:conflict` whose conflicting paths are entirely within the deterministic-regeneration
  set (golden manifest, `dist/**`, generated mirrors) is auto-resolved by regenerate-and-restage within a
  bounded attempt count; any conflict touching source/semantic paths remains a legitimate human halt.
  Auto-resolve fires **only** when the conflicting generated paths trace to a **single source preimage** —
  if multiple parent source commits in the batch contributed to the same generated path, the conflict is
  semantic-by-proxy and **halts**. Regeneration runs scoped to the orchestrator worktree (never staging source
  paths outside the allowlist), and a **determinism gate** (identical hash on a repeated regen run + golden
  parity pass) must hold before the resolved result is restaged; non-convergence halts.
- **R13** `ship-phase-status.py` writes a verifiable provenance marker into `status.json`, and the driver
  rejects any `status.json` lacking a valid marker (a hand-authored status is never accepted as terminal,
  closing both the stall and the faked-`merge-ready-green` holes).
- **R14** The driver validates a terminal `status.json` for: terminal `verdict`, a full 40-char head SHA equal
  to the phase branch tip (`git rev-parse`), and a parseable gate JSON — rejecting abbreviated-SHA / stale /
  malformed status. Because the provenance marker (R13) proves *canonical emission shape, not authenticity*
  and is forgeable by anything that can run the ship path, terminal-status acceptance and merge enqueue (R10)
  **re-verify live host evidence** — an open PR plus `check-gate`/`checks-status` green on the current head
  SHA — before advancing. Embedded gate JSON is **diagnostic metadata only, never authorization**; a forged
  `merge-ready-green` carrying a valid head SHA, a valid marker, and a fabricated gate object is rejected when
  it disagrees with live host evidence.
- **R15** When a phase is `await-in-flight` but independent evidence indicates it is done while `status.json`
  is non-terminal/invalid, the driver classifies it `stuck-stale` rather than continuing to wait. To avoid
  killing a healthy long-running phase, `stuck-stale` requires **head-SHA equality across the branch tip, the
  PR head, the gate-checked SHA, and `status.json` (if present)** — not merely "open PR + green CI on an older
  tip" — plus tip quiescence (no push within a debounce window) so a phase still advancing its head is never
  misclassified.
- **R16** A `stuck-stale` phase routes to a budget-bounded auto re-emit that re-derives the verdict via the
  canonical `/sw-ship --phase-mode` terminal steps / `sw-ready` (or `/sw-stabilize` + ship terminal) — never
  by trusting or hand-editing `status.json`; the re-emit action changes the durable state signature (via a
  re-emit/recovery counter, with the same no-progress-breaker semantics as R7) so it cannot instantly trip the
  no-progress breaker, and exhaustion is a legitimate halt. Re-emit must **acquire the per-head lease (R2) and
  confirm no in-flight ship Task** (`backgroundDispatchedAt` cleared or Task dead) before writing, and writes
  atomically (temp-write + rename) so it can never clobber or interleave with a concurrent legitimate writer.
- **R17** A single blessed operator/agent recovery command re-emits canonical terminal status for a phase, so
  hand-editing `status.json` is never the path of least resistance; `rules/sw-conductor.mdc` is updated to
  point to it.
- **R18** Each finding (R1–R17 groups) ships a regression fixture that both reproduces the original failure
  and asserts the specific reason the prior shipped PRD fix for that class (PRD 026 for dual-ship; PRD 013 /
  PRD 027 for the others) did not cover it, so the class cannot silently reopen.
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
  `ship-phase-status.py`, and the `/sw-ship --phase-mode` chain) with: (a) a per-head lease built on the
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
- **Terminal-status integrity (R13–R17).** `ship-phase-status.py` emits a deterministic, offline-regenerable
  provenance marker over canonical status fields; the driver validates terminal `verdict`, full 40-char head
  SHA vs `git rev-parse`, and gate-JSON parseability, and adds a `stuck-stale` classifier driven by
  independent CI/PR evidence with budget-bounded canonical re-emit. A blessed recovery command (atomic or a
  documented `/sw-ship --phase-mode` terminal-step invocation, per OQ4) re-emits canonical status. When
  multiple `status.json` copies exist (canonical root, worktree-local, glob fallback), the winning candidate
  is resolved by head SHA matching the branch tip (then most-recent `writtenAt`) — **not** by path-probe
  precedence — and a newer worktree copy invalidates a stale canonical mirror before validation runs.
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
- **Redaction of durable remediation payloads.** All durable remediation/halt payloads (`run.log`,
  `blocker-report.json`, `resumeCommand` context, and state `cause` fields from the R6–R8 routing) pass the
  memory redaction chokepoint before write and fail closed on a redaction error, per the workspace guardrail
  that raw transcripts/secrets are never persisted.
- **Status field data surface.** The compliance boundary covers *all* persisted `status.json` fields, not just
  the provenance marker: gate objects, `cause` strings, and any `shipSteps` are constrained to a documented
  allowlist schema, must not embed raw transcripts/tokens/PII, and are redacted before any mirror-to-canonical
  write.
- **Branch-name validation before host calls.** Phase branch and integration base must pass the existing
  `branch-name-guard` before any host `pr-list` / `pr-create` (defense-in-depth atop the JSON-encoded,
  shell-injection-safe host argument path).

## Testing Strategy

- **Regression-guard fixtures (R18), one per finding, each encoding why the prior shipped PRD for that class
  (PRD 026 for dual-ship; PRD 013 / PRD 027 for the others) missed it:**
  - *Dual-ship (R1–R5):* modeled as a **deterministic simulation** — two concurrent `lock acquire` /
    `host_pr_create` callers on one head with host-fixture stubs (no live Cursor Task spawn) — asserting exactly
    one PR based on the integration branch, no orphan-`main` PR, and lease-holder success; asserts the lease +
    idempotency + base-pin and that PRD 026 R20/R21 (single-PR only) did not cover the racing path. Live Task
    concurrency is dogfood-validated, not CI-blocking.
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

- **D1 — Single-flight phase-ship via layered defense.** Phase-ship is made single-flight via defense-in-depth
  (process discipline + a per-head lease + idempotency/base-pin), symmetric with the already single-flight
  merge queue. Idempotency-only (TOCTOU-racy) and no-background-only (misses crash/resume leftovers and
  concurrent-push corruption) were rejected as partial; the layered approach is the only one that also prevents
  concurrent pushes on one head. (K1 → R1–R5)
- **D2 — Bounded regression remediation.** `verify:failed` regressions route to bounded `/sw-stabilize` within
  `deliver.remediation.maxAttempts`, and the no-progress breaker is fixed so a freshly-`blocked`-with-budget
  phase yields a distinct signature and cannot pre-empt the first remediation. A separate stricter regression
  budget and treating every regression as an immediate human halt were rejected (added complexity / needless
  autonomy loss). (K2 → R6–R8)
- **D3 — Prevent-then-enforce-then-auto-resolve merge safety.** Parallel-merge safety is
  prevent-then-enforce-then-auto-resolve: contention-edge prevention, strict R44 whole-batch completion +
  deterministic ordering, and bounded auto-regen for deterministic conflicts only. Reactive-only (lets the
  avoidable collision recur) and enforce-only-with-all-conflicts-as-halts (autonomy loss for mechanical regen)
  were rejected. (K3 → R9–R12)
- **D4 — Provenance + reactive status integrity.** Terminal-status integrity combines a ship-emitted
  provenance marker + validity check, reactive `stuck-stale` detection from CI/PR evidence, and budget-bounded
  canonical re-emit, plus a blessed recovery command. Provenance closes both the stall and the
  faked-`merge-ready-green` holes; auto re-emit is safe because it re-derives the verdict from the real
  ship/gate path. Provenance-only (halt) and reactive-only (misses the fake-green hole) were rejected as
  partial. (K4 → R13–R17)
- **D5 — Per-class regression fixtures.** Because GAP-048–052 recurred despite their prior shipped fixes
  (GAP-048 despite PRD 026 R20/R21; GAP-049/050/052 despite PRD 013/027), every finding ships a regression
  fixture that reproduces the gap and asserts why the earlier fix did not cover it, so the class cannot
  silently reopen. (K5 → R18)
- **D6 — Follow-on PRD, not an amendment.** This is a follow-on PRD, not an amendment to PRD 013/017/026/027
  (all complete and frozen); it consumes and hardens them. Amending a frozen, shipped PRD was rejected in
  favor of a traceable new unit.
- **D7 — Per-head keyed lease (resolves OQ1).** The single-shipper lease (R2) is a **new keyed lease file**
  under the existing lock directory (`.cursor/sw-deliver-locks/<phaseBranchHash>.lock`), reusing the `O_EXCL` /
  `reclaim_stale_lock` internals **without** overloading the orchestrator lock. The lease key is
  `(integrationBranch, phaseBranch)`, and plan validation rejects two active slugs on one branch. Liveness is
  **heartbeat-based, not PID-based**: the holder extends `heartbeatAt` on every ship sub-step; stale-steal is
  allowed only on a stale heartbeat (short TTL) and is illegal while `shipSteps` are in-progress. Lock paths
  resolve via `realpath`, reject symlinked parents, and sanitize the slug to a safe filename alphabet. A
  PID-liveness-only steal and overloading the `sw-deliver-<slug>.lock` namespace were rejected (live-hang
  deadlock; cross-scope contention). (OQ1 → R2)
- **D8 — Dedicated regen ceiling (resolves OQ2).** Deterministic-conflict auto-regen (R12) uses a **dedicated
  small ceiling** (`deliver.deterministicConflict.maxAttempts`, default 1, max 2), separate from
  `deliver.remediation.maxAttempts`, with a determinism gate (identical re-run hash + golden parity) required
  before restage. Reusing the remediation budget was rejected — regen and stabilize are different failure
  classes and must not share an attempt pool. (OQ2 → R12)
- **D9 — Content-hash provenance marker (resolves OQ3).** The R13 marker is a **deterministic content hash**
  over an explicit canonical field set (`verdict`, `phase`, `head`, gate-subset, `shipSteps`-checksum;
  **excluding volatile `writtenAt`**) so CI and re-emit stay deterministic and key-free. The marker is treated
  as an **integrity/shape signal, not authenticity** — it is forgeable by anything that can run the ship path —
  therefore terminal acceptance and merge enqueue re-verify **live host evidence** (R14), and embedded gate
  JSON is diagnostic only. An HMAC/signed token was deferred (key-management cost) unless non-repudiation is
  later required. (OQ3 → R13/R14)
- **D10 — Recovery reuses /sw-ship --phase-mode (resolves OQ4).** The blessed recovery path (R17) **reuses
  `/sw-ship --phase-mode --from <terminal-step>`** rather than minting a new `/sw-*` atomic, per `sw-naming`
  (prefer reusing the ship terminal steps); `rules/sw-conductor.mdc` points to it, and recovery invocations
  log actor metadata to `run.log` and acquire the per-head lease (R16). A new dedicated command was rejected
  as an unwarranted surface. (OQ4 → R17)

## Open Questions

None — OQ1–OQ4 were resolved at doc-review (2026-06-28) and recorded as Decision Log D7–D10.
