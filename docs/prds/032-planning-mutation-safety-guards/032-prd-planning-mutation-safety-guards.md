---
date: 2026-06-27
topic: planning-feedback-lifecycle
brainstorm: docs/brainstorms/2026-06-27-planning-feedback-lifecycle-requirements.md
depends: [031]
frozen: true
frozen_at: 2026-06-27
---

# PRD 032 — Planning Mutation-Safety Guards (In-Flight Signal & Amendment-to-Completed)

## Overview

Ship the **safety guards** that make the unified planning graph trustworthy *before* the rest of the
program lands. This PRD is sequenced immediately after the 031 foundation (per doc-review value-sequencing
decision) so the highest-value protection — never silently mutate an in-flight spec, never lose an
amendment against completed work — is in place during the long program tail (033 lifecycle, 034 visibility,
035 autonomy). It carries the committed **in-flight signal** (subsuming cancelled PRD 030) and the
**amendment-to-completed guard**.

`depends:` on PRD 031 (it writes into the `inFlight` INDEX region that 031's schema seam defines, and reads
the type-conditioned lifecycle status). Derived from frozen brainstorm requirements R27–R28 (amendment
guard) and R36–R38 (in-flight safety). It is the answer to the user's "amendments to completed PRDs get
lost" concern and to GAP-038 silent in-flight mutation.

**Atomic cutover + substrate-first (PRD 031 D11/R27, refined by doc-review).** The 031 substrate (unit
schema, path helper, INDEX generator + dual-region seam, lifecycle stub enum, tokenizer Phase A) lands and
passes fixtures **as prerequisites first**; 032 then ships in the **one-commit cutover with 031 (Phase B
relocation) and 033** so the in-flight signal and the amendment-to-completed guard are live **at** the
migration cutover. Because 032's completed-unit guard reads 033 reconciler-owned `derived` status, 032 also
specifies a **graceful-degraded mode** (R12) so a half-applied train (033 absent/derived empty) does not
fail-closed on every guarded write. 032's migration-bridge (R8) backfills the committed in-flight signal
from legacy deliver state within that cutover, satisfying the deferral recorded in PRD 031 D7.

## Goals

- Carry a committed in-flight signal in the tracked INDEX (run id + implementing branch + lease epoch),
  readable from any session/clone, occupying the `inFlight` region of the 031 INDEX schema; the lifecycle
  `in-progress` *state* is derived by PRD 033, not stored here.
- Make authoring commands fail closed against provably in-flight units, with a handoff-artifact route, inline
  stale-marker reconcile, and a bounded staleness escape hatch so the guard never deadlocks legitimate
  authoring.
- Survive cross-clone concurrency: two clones cannot silently overwrite each other's live in-flight tuple.
- Mechanically prevent amendments to `complete` units regardless of invocation path (command or direct file
  edit) and regardless of position in the unit folder (body or `amendments/` subtree), routing change
  requests to a new superseding/extending unit or gap.
- Backfill the committed in-flight signal from legacy gitignored deliver state at first run (migration
  bridge), so the 031 cutover hands off cleanly.

## Non-Goals

- The lifecycle state machine, dependency graph, scheduler, and the reconciler that derives `in-progress`/
  `complete` (PRD 033). This PRD writes the in-flight tuple; 033 derives lifecycle from it + git.
- Visibility/store and private-body redaction of in-flight signal metadata (PRD 034). 032 only **reserves**
  the opaque-token schema slot (R13); 034 owns the redaction implementation and accepts the handoff.
- Backlog pull-in proposals, two-track edits, autonomy posture, and full-conductor (PRD 035).
- Any change to the merge-to-`main` gate or the wave engine.

## Requirements

- **R1** The tracked INDEX carries a committed in-flight signal for each active unit — **run id +
  implementing branch + lease epoch** — in the `inFlight` region defined by PRD 031 R9. It is readable from
  any session/clone (committed git state, never gitignored local deliver state) and is written only by the
  deliver run-start path (single writer, PRD 031 R24 region-integrity hook). The lifecycle `in-progress`
  status is **not** stored in the tuple; it is derived by PRD 033 from this signal + git, so there is one
  status surface (closes the coherence dual-status concern).
- **R2** Cross-clone safety: the run-start writer takes a **run-id lease** in durable deliver state and
  writes the tuple with optimistic concurrency (compare-and-set on the prior tuple). A run-start that finds
  the `inFlight` tuple naming a *different live* run-id fails closed unless `--takeover` is passed with a
  logged reason; git-merge last-writer-wins on the tuple is never the authority — the durable run-id lease
  is.
- **R3** The in-flight signal is staleness-tolerant and self-healing: a missing branch or non-live run
  degrades to a warning, and a reconcile path repairs stale/missing markers against actual runs. A tuple is
  classified **stale and clearable only when the durable run-state for its run-id is terminal/absent AND the
  branch is missing** — branch-absence alone (mid-rebase, slow CI) never clears a live tuple.
- **R4** A bounded **staleness TTL** plus an explicit escape hatch prevent permanent deadlock: if a tuple's
  run-id is absent from the registry, its branch is missing, and no porcelain deliver state exists for it
  beyond the configured TTL, reconcile auto-clears it with an audit log; an operator may also run
  `clear-inflight <unit> --reason` (logged) to clear an ambiguous tuple.
- **R5** Authoring commands (`/sw-amend`, `/sw-tasks`, `/sw-prd`, and any path that writes unit frontmatter
  or ancillary files) run an authoring-guard preflight that **first runs inline stale-marker reconcile** (or
  reads the live run registry), then fails closed (reporting run id + branch) only when the target unit is
  *provably* in-flight after reconcile; this resolves the fail-closed-vs-self-healing tension (adversarial
  panel) so a crashed run with a deleted branch does not deadlock authoring.
- **R6** A handoff route flag records a handoff artifact instead of mutating when the operator chooses not
  to wait on a genuinely in-flight unit; the artifact is **surfaced in `/sw-status` and to the PRD 035
  pull-in scan** so it is reconciled into the graph rather than orphaned (closes the product handoff-
  ergonomics gap).
- **R7** `/sw-amend` is permitted only on `planned` or `in-progress` units and refuses on `complete` units.
- **R8** A change request against a `complete` unit is mechanically routed to fork a new unit that
  `supersedes:` or `extends:` the completed one (or to append a gap unit), so amendments to completed work
  are never silently lost.
- **R9** The amendment-to-completed guard is **not command-scoped only and not body-only**: a freeze/
  pre-commit hook rejects any mutation to a `status: complete` unit — its body **or any path under the unit
  folder, including the `amendments/` subtree** — regardless of invocation path (direct file edit, agent
  write, or command). The guard binds its evaluation to a single **reconcile-generation token** (re-reading
  derived status atomically, or running inline reconcile immediately before the accept/reject) so a
  concurrent complete-flip cannot race the write (closes the adversarial TOCTOU).
- **R10** A migration-bridge reconcile, run once within the cutover, promotes legacy in-progress markers
  from gitignored deliver state into the committed `inFlight` INDEX region without desyncing any live run
  (closes the 031→032 handoff that 031 D7 defers here).

## Technical Requirements

- **R11** The in-flight signal is written through the living-doc single-writer lock at deliver run-start and
  cleared at run completion; the writer touches only the `inFlight` region, never the reconciler-owned
  `derived` region (the dual-writer contract defined in **PRD 033 R12/D5**). It is wired into the deliver
  run-start chain after lock-acquire / before orchestrator-provision (feasibility-identified insertion
  point), using read-merge-write per PRD 031 R9.
- **R12** The completed-unit immutability hook integrates with the **freeze/commit guard machinery** (the
  layer that enforces frozen immutability, **PRD 031 R17** and the existing `pre-commit-frozen` hook) so it
  fires on any write path, adding a `pre-commit-completed-unit` check chained from `core/hooks/pre-commit`
  and mirrored in CI. **Graceful-degraded mode:** when the 033 `derived` region is empty/unavailable (a
  half-applied train), the hook evaluates against structural frontmatter `status` and the committed
  `inFlight` signal and emits a warning, rather than fail-closing every guarded write (closes the adversarial
  half-applied-train scenario).
- **R13** The in-flight signal exposes run id + branch as committed metadata; for units that will later be
  `visibility: private|memory` (PRD 034), the signal schema reserves an **opaque-token form (hashed branch
  suffix)** so PRD 034 can redact sensitive branch/codename metadata without a schema change. The `inFlight`
  region is included in the PRD 034 emission-point registry and resolver coverage (handoff documented in
  034). Until 034 lands, the train commits cleartext branch metadata only for non-private units (031 R18
  keeps formerly-private bodies ignored); this interim exposure window is documented.
- **R14** An authoring-guard preflight module is shared across `/sw-amend`/`/sw-tasks`/`/sw-prd` and the
  other unit-writing paths; it invokes the inline reconcile and reads the committed signal via the PRD 031
  path helper.
- **R15** This PRD updates the operator-facing docs it changes, as **acceptance criteria** (carried forward
  from cancelled PRD 030's doc-impact, which was otherwise lost): `core/commands/sw-amend.md`,
  `core/commands/sw-tasks.md`, `core/commands/sw-prd.md` (authoring-guard preflight, `--handoff`, complete-
  unit refusal), `core/commands/sw-freeze.md` (completed-unit body/ancillary mutation hook per R9/R12), and
  `core/skills/deliver/SKILL.md` (run-start `inFlight` writer/clear per R1/R11 — replacing the current
  "INDEX never uses `in-progress`" statement). Lifecycle/reconciler INDEX semantics and the
  `living-status` skill remain PRD 033-owned; `.sw/layout.md` path authority remains PRD 031-owned.
- **R16** Guard artifacts land in `core/` and propagate to both dist trees; `copy-to-core` parity and
  emitter-freshness fixtures cover the new scripts and hooks.

## Security & Compliance

- **R17** The guards are fail-closed (except the explicit R12 graceful-degraded mode): ambiguous in-flight or
  lifecycle-freshness state blocks the mutation rather than proceeding; `--handoff`, `--takeover`, and any
  `--override` are explicit and logged to durable state (who/when/why).
- **R18** The in-flight tuple stores no body content and no secret; branch names for private units are
  redacted via the 034 handoff (R13). The migration bridge reads only gitignored deliver state and commits
  only the tuple metadata.

## Testing Strategy

- In-flight write/read fixtures (R1, R11): run-start writes the tuple to the committed INDEX `inFlight`
  region; a second clone reads it; run completion clears it; the lifecycle state is absent from the tuple.
- Cross-clone fixtures (R2): two clones start deliver on the same unit with staggered push; the second
  run-start fails closed without `--takeover`; the durable lease is authoritative over git merge.
- Self-healing + TTL fixtures (R3, R4, R5): a crashed run with a deleted branch reconciles to a warning
  inline and authoring proceeds; a genuinely live run blocks with run id + branch; branch-absence alone with
  a live run-state does not clear; an ambiguous tuple past TTL auto-clears with audit; `clear-inflight`
  works; `--handoff` records an artifact surfaced in `/sw-status`.
- Amendment-guard fixtures (R7, R8): `/sw-amend` refuses on `complete`, allows on `planned`/`in-progress`,
  routes a completed-unit request to a new superseding/extending unit or gap.
- Non-command + subtree bypass fixtures (R9, R12): a direct body edit, an agent write, and a new file under
  `amendments/` on a `complete` unit are all rejected by the freeze hook; a concurrent complete-flip racing
  an amend is caught by the reconcile-generation token.
- Graceful-degrade fixture (R12): with the 033 derived region empty, the hook warns (structural-status mode)
  instead of fail-closing every write.
- Migration-bridge fixture (R10): legacy gitignored in-progress markers promote into the committed signal
  with no live-run desync.
- Doc-currency (R15) and emitter/parity (R16) fixtures.

## Rollout Plan

1. **Prerequisite (in 031 substrate phase):** the `inFlight` region schema slot + region-integrity hook are
   available before this PRD's writer lands.
2. **In-flight schema + writer:** populate the 031 `inFlight` region from the deliver run-start path under
   the single-writer lock with the run-id lease + CAS; add the reconcile/self-heal/TTL path.
3. **Authoring guard:** land the shared preflight (inline reconcile → fail-closed) across the unit-writing
   paths, plus the `--handoff` route surfaced in `/sw-status`.
4. **Completed-unit immutability:** wire the freeze/commit hook (whole-unit-folder scope, reconcile-token
   binding, graceful-degraded mode) so completed-unit mutation is rejected on any path.
5. **Migration bridge + cutover:** run the one-time promotion of legacy in-progress markers within the
   one-commit 031+032+033 cutover.

## Decision Log

- **D1.** Guards are split out of the original autonomy PRD and sequenced right after the foundation
  (doc-review value-sequencing decision) — the highest-value protection ships before the disruptive
  lifecycle/visibility/autonomy tail rather than last.
- **D2.** The in-flight signal lives in the committed tracked INDEX, not gitignored local deliver state, so
  it is readable across sessions/clones (brainstorm R36, subsuming cancelled PRD 030).
- **D3.** The authoring guard runs inline reconcile *before* fail-closed evaluation (resolves the adversarial
  fail-closed-vs-self-healing tension) so a crashed run never deadlocks legitimate authoring while a live run
  still blocks; a bounded TTL + `clear-inflight` escape hatch prevents permanent deadlock on corrupted state.
- **D4.** The completed-unit guard is enforced by the freeze/commit hook on *any* write path and across the
  *whole unit folder* (body + `amendments/`), not only via `/sw-amend`, closing the direct-edit and
  ancillary-subtree bypasses the adversarial and docs-currency panels flagged.
- **D5.** The migration bridge (R10) absorbs the 031 D7 deferral: 031 cutover protects in-progress units via
  the deliver-freeze window; 032's first reconcile backfills the committed signal.
- **D6.** Cross-clone authority is the **durable run-id lease + tuple CAS**, not git merge resolution
  (adversarial last-writer-wins) — `--takeover` is the only sanctioned override and is logged.
- **D7.** The tuple stores run-id + branch + lease epoch only; the lifecycle `in-progress` state is derived
  by 033 (one status surface), resolving the coherence dual-status concern.
- **D8.** The completed-unit hook degrades gracefully to structural-status mode when the 033 derived region
  is empty (half-applied train), warning rather than fail-closing all writes — paired with the 031 R28
  revert-to-shim runbook for the partial-train failure mode.
- **D9.** 032 ships in the one-commit cutover with 031 (Phase B) + 033 after the 031 substrate/Phase-A
  prerequisites validate (doc-review substrate-first decision) — guards are live at cutover, but on a
  de-risked substrate.
- **D10.** 032 inherits cancelled PRD 030's documentation-update obligations as acceptance criteria (R15);
  the docs-currency panel showed these were otherwise lost in the 030→032 reframe.
