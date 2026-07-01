---
brainstorm: docs/brainstorms/2026-06-30-loop-hardening-requirements.md
date: 2026-06-30
topic: self-improving-loop
frozen: true
frozen_at: 2026-06-30
visibility: public
---
# PRD 041 — Self-Improving Loop

## Overview

PRD C of the **loop-hardening** program — the capstone. Today, signals that *Shipwright itself* needs
improvement flow through the same retro→feedback→GAP channels as product work; recurring failures are
re-fixed at the surface (in-run RCA rule-of-three + the conductor circuit breaker exist, but there is no
**cross-run** failure-signature store); and process inefficiencies (long single-threaded tests, slow CI,
serialized-but-parallelizable phases, repeated manual steps) are captured only qualitatively in retro.

This PRD delivers a **deterministic capture + prioritized, evidence-backed proposal** loop — **humans own
merge, rule/PRD promotion, and every dispatch**. Concretely it adds: a dedicated **meta/dogfood capture
channel** (distinct from product gaps), a **cross-run recurring-failure detector** that escalates repeated
surface-fixes to a **captured root-cause record**, an **anomaly-pattern catalog** (recognition only), an
**inefficiency scanner**, **behavioral-anomaly guardrails** with trust-anchored evidence, **downstream-cost
loop-health metrics**, and a **capture → RCA → auto-propose** pipeline that *drafts* gap units / PRDs. What
the loop automates: signature normalization, cross-run counting, RCA annotation, draft proposal text, and
inefficiency surfacing. What humans always do: triage, prioritize, confirm, dispatch, merge, and promote.

Per the program's permanent invariants, the loop **proposes** but **never** auto-merges, auto-promotes rules,
auto-dispatches, or nests orchestrator dispatch — and these invariants are **mechanically enforced**
(fail-closed), not prose-asserted. The loop respects `planning.autonomy` (default `maintenance-only`) and
meta/plugin-self units are **always propose-only even under `full-conductor`**.

Scope traces to brainstorm requirements **R20–R29** (plus cross-cutting **R30–R31**). It builds on PRD A's
quality/TDD signals and PRD B's sizing data where present, but its capture/RCA/scan surfaces are independent
and **degrade gracefully** when A/B are unconfigured.

## Goals

- Give "the workflow tool itself needs fixing" a **first-class, distinctly-tagged channel** that lands in a
  triage **inbox** and is materialized into a gap unit only after human confirmation — never auto-dispatched.
- Detect **recurring failure signatures across runs/PRs** (on host-attested artifacts, not free-text) and
  escalate from "fix the symptom again" to a **captured, fed-back root cause** with a distinct escalation
  class.
- Detect **process inefficiencies** (test/CI timing, parallelizability, repeated manual steps) and emit
  **action-linked** improvement items, reusing existing `benefitMetric`/run-state data and degrading when a
  source is absent.
- Extend evidence-over-claims into **trust-anchored behavioral-anomaly guardrails** (unauthorized file ops,
  false success, failed rollback, silent skips) that resist gaming.
- Track **downstream-cost loop-health metrics** (review effort, rework/defect, post-merge incidents) and tie
  them to triage prioritization — not vanity dashboards.
- Make the loop **deterministic-capture + human-improving**: capture → RCA → auto-**propose** (drafts only),
  with merge, promotion, and dispatch always human-owned and mechanically gated.

## Non-Goals

- **No auto-merge to `main`, no autonomous rule/PRD promotion, no autonomous dispatch** — permanent program
  invariant (R27, R30), mechanically enforced.
- **No nested orchestrator dispatch** from the self-improving/automation loop: the auto-propose driver
  produces **drafts and inert handoff-queue entries only**; nothing in the queue executes without a persisted
  human ack, and the driver MUST NOT invoke `/sw-deliver`, `/sw-doc`, `/sw-ship`, `/sw-debug`, `/sw-feedback`,
  `/sw-cleanup`, or `/sw-retrospective`, nor enqueue any command that can *reach* an orchestrator (including
  `/sw-prd` under `doc.afterTasks ≠ stop`).
- **TDD and refactor skip enforcement remain PRD A (R2/R8); test-tampering detection remains PRD A (R9).**
  R28 silent-skip detection here applies only to verification-gate and other workflow gates **outside** the
  execute-discipline/TDD surfaces, and delegates TDD/refactor skip verdicts to PRD A — no second enforcement
  path. R24 recognition cross-references PRD A R9 as the authoritative test-tamper detector.
- **No phase sizing heuristic or pre-freeze split suggestions (PRD B R15–R19);** parallelizability detection
  here is **retrospective/advisory only**, consuming `wave_deliver` helpers when present and skipping with a
  notice when absent.
- **No full behavioral-fuzzing / adversarial-input harness** (ABTest-style) — v1 ships a **static,
  repo-curated seed catalog**; automated pattern mining and fuzzing are deferred.
- **No cross-repo / org-wide dashboards** — single-repo loop-health signals first.
- **No replacement of in-run RCA** (`rca-core`) or the conductor circuit breaker — this PRD adds the
  *cross-run* layer above them.
- **No re-implementation of shipped predecessor items** (`feedback-closure`, `rca-core`, `verification-gate`,
  retro/compound chain) — this PRD extends them.
- Quality/refactor/TDD gates (PRD A, R1–R14) and authoring-time phase sizing (PRD B, R15–R19) are out of
  scope here.

## Requirements

Carried forward from the brainstorm (stable R-IDs).

- **R20** A dedicated **meta/dogfood signal channel** SHALL distinguish "the workflow tool itself needs
  improvement" signals (destination tag `meta-shipwright`) from product gaps during any workflow run.
- **R21** Meta signals SHALL land in a **triage inbox** as redacted drafts and be materialized into **tagged
  gap units** (`planning_gap_capture`, plugin-self class) **only after human confirmation** — capture and
  annotation may be automatic, but no gap-unit materialization or dispatch occurs without a persisted ack.
- **R22** A **recurring-failure detector** SHALL track check/failure signatures across attempts **and across
  runs/PRs**, keyed on **host-attested fields** (check/job name + exit code + stable job id), with message
  text normalized only as a secondary discriminator; when a signature recurs ≥ a configurable threshold
  (≥2 distinct runs) it SHALL escalate from surface-fix to root-cause analysis.
- **R23** On recurrence escalation, the loop SHALL produce a **captured root-cause record** with a distinct
  escalation class/status (fed back as a gap unit / debug entry) rather than only re-fixing the symptom; a
  `signatureClass` (`flake` | `regression` | `infra`) governs escalation policy (flakes require a
  human-acknowledged waiver before the remediation loop is considered closed).
- **R24** RCA for workflow/behavioral failures SHALL reuse a **static, repo-curated anomaly-pattern catalog**
  (Interaction Patterns / Action Types, per ABTest) to *recognize* known workflow/behavioral classes and
  annotate the root-cause record; recognition never auto-acts and never duplicates PRD A R9 test-tamper
  detection.
- **R25** An **inefficiency scanner** SHALL detect at least: long-running single-threaded tests, **slow CI
  jobs**, serialized-but-parallelizable phases, and repeated manual steps; and emit action-linked
  improvement items.
- **R26** The inefficiency scanner SHALL reuse existing `benefitMetric` / deliver run-state data where
  available; per-test and CI-job timing detection SHALL use a host-attested capture surface where one exists
  and **degrade with a notice** where it does not.
- **R27** The self-improving loop SHALL **capture → RCA → auto-propose** Shipwright changes as **drafts**
  (gap units / PRDs), optionally on a schedule (automation), while **merge, rule/PRD promotion, and dispatch
  remain human-gated**; it SHALL NOT auto-merge, auto-promote rules, auto-dispatch, or nest orchestrator
  dispatch, and SHALL respect `planning.autonomy`. v1 default scheduler substrate is **manual invocation**.
- **R28** **Behavioral-anomaly guardrails** SHALL detect unauthorized file create/delete, false success
  claims, failed rollback, and silent skips during workflow runs using **trust-anchored evidence**
  (pre-agent diff snapshot, re-exec/verify-hash checks), extending `verification-gate`'s evidence-over-claims
  posture; evidence-integrity mismatch promotes the anomaly to an inconclusive/blocking verdict.
- **R29** The loop SHALL track **downstream-cost metrics** (review effort, defect/rework rate, post-merge
  incidents) as loop-health signals in preference to raw volume/velocity, and tie them to triage
  prioritization; the incident dimension reports `unknown` (not zero) when no host signal exists.
- **R30** All new gates/signals SHALL preserve human-owns-merge, human-gated promotion, human-owned dispatch,
  and no nested orchestrator dispatch; automation may propose (draft) but never merge, promote, or dispatch.
- **R31** All new commands/skills SHALL obey `sw-` naming, orchestrator/atomic boundaries, and the
  model-tier floor, and route external/provider context through the redaction chokepoint.

## Technical Requirements

### Shared state writer + redaction chokepoint (R31)

A single helper — `scripts/sw-state-write.sh` (Python-backed) — is the **sole writer** for all new
`.cursor/sw-*` stores: it pipes content through `scripts/memory-redact.py`, validates against the relevant
schema, and performs an atomic append/write, **failing closed** on any redaction or schema error. Direct
`write_json` to these store paths is banned (fixture lint). This removes the multi-writer redaction risk.

### Cross-worktree store authority (R22/R29)

Cross-run stores must be visible across worktrees/PRs. They live at a **shared git-dir authority** in parity
with `scripts/shipwright-state.py` (`${GIT_DIR}/shipwright-failure-signatures.json`,
`${GIT_DIR}/shipwright-loop-health.json`), with a `*-index` merge subcommand for linked worktrees. The
repo-root `.cursor/sw-*` paths are per-checkout projections only. The meta-inbox (`.cursor/sw-meta-inbox/`)
is per-checkout run-state (drafts), reconciled at materialization.

### Meta/dogfood channel (R20/R21)

Extend the feedback normalizer (`core/skills/feedback/SKILL.md` + `core/skills/feedback/references/signal-schema.md`)
and `scripts/planning_gap_capture.py` with a `meta-shipwright` destination class (plugin-self). Capture is
**two-phase**: (1) `capture` writes a redacted draft to `.cursor/sw-meta-inbox/` only (no tracked planning
mutation); (2) `materialize` creates the gap unit under the canonical planning tree (`planning_paths.py`,
plugin-self tag) **only after** `planning_gap_capture confirm --signal-id <id>` records a persisted human
ack. A fixture proves capture-without-confirm leaves **zero** tracked planning files. Distinct tag keeps meta
separate from product GAP routing in `feedback-closure`.

### Recurring-failure detector (R22/R23)

A **cross-run failure-signature store** (shared git-dir authority above, redacted, append-only) keyed by
`{check_id, exit_code, job_id}` (host-attested) with normalized message class as a secondary discriminator
(strip temp paths, UUIDs, line numbers, timestamps — algorithm pinned in `failure-signature.schema.json`).
**Writers are pinned** at deterministic surfaces: `scripts/check-gate.py` on red (`failingChecks[]`),
`scripts/wave_failure.py` on blocked verify/remediation, `scripts/verify-evidence.py` on `not-verified`, and
the conductor `noProgressStreak` trip — all via `scripts/failure-signature-record.sh` → `sw-state-write.sh`.
Threshold escalation (config `recurrence.threshold`, ≥2 distinct runs) invokes
`scripts/failure-signature-escalate.sh`, which runs the `rca-core` debug-entry procedure on **redacted**
failure text and files an escalated root-cause record (distinct `signatureClass` + status). This is
**net-new cross-run wiring** layered above in-run `rca-core` (no cross-run entry today) and the conductor
circuit breaker (session-scoped) — neither is replaced.

### Pattern reuse for RCA (R24)

A **static, repo-curated** anomaly-pattern catalog (`core/sw-reference/anomaly-patterns.json`, seeded with a
small set of workflow/behavioral classes — false-green, unauthorized-delete, failed-rollback, silent-skip —
derived from ABTest research) that `rca-core` consults to *recognize* known classes and annotate the
root-cause record. Test-tampering is **not** in this catalog: R24 cross-references PRD A R9 as the
authoritative detector and only annotates when A's flags exist. No mining/fuzzing pipeline in v1.

### Inefficiency scanner (R25/R26)

A scanner (`scripts/inefficiency-scan.sh`) that reads existing `benefitMetric` + deliver run-state and emits
**action-linked** improvement items (each item names a concrete next step, e.g. "split phase X" linking to
PRD B split-suggestion, "parallelize test Y" linking to `verify` config). Detection classes:

- **Long single-threaded tests / slow CI jobs:** threshold on per-test / CI-job timing **where a
  host-attested capture surface exists**; otherwise skip with a notice (graceful degradation, R26). Per-test
  timing parses the configured `verify`/test command's machine-readable output (e.g. JUnit XML) when present.
- **Serialized-but-parallelizable phases (retrospective):** compare the realized wave width from
  `waveBatchingPlan` against a **simulated** width from `wave_deliver.py` (`apply_contention` +
  `greedy_wave_batches`) over the frozen task graph; flag when `parallelCeiling > 1` but executed waves were
  width-1 without mandatory contention edges. Skips with a notice when PRD B sizing/`wave_deliver` data is
  absent.
- **Repeated manual steps:** recurring operator commands in run-state, with a false-positive allowlist.

Items route through the R20/R21 inbox path (drafts, human-confirmed); never auto-applied.

### Behavioral-anomaly guardrails (R28)

A new `scripts/behavioral-anomaly-check.sh` (called from the ship chain after execute/verify) consumes
**trust-anchored** inputs: a **pre-agent git diff snapshot** (hook-captured baseline), `git diff --name-status`,
the frozen task-list declared scope (`**File:**` + Relevant Files), `sw-verify` status, and phase skip
records. Detectors: unauthorized create/delete (diff outside declared scope vs the pre-agent baseline),
false success (claimed pass whose evidence artifact fails a re-exec/hash check), failed rollback (revert left
tree dirty), and silent skips (gate `skipped` without recorded reason — delegating TDD/refactor skips to PRD
A). Anomalies emit an advisory high-risk flag **and** feed the failure-signature store; **evidence-integrity
mismatch** (e.g. fabricated status file) promotes the verdict to `inconclusive`/blocking within the existing
verification-gate contract — anomalies are evidence-based, not assertion-based.

### Downstream-cost metrics (R29)

A loop-health record (shared git-dir authority, redacted) aggregating review effort (review rounds /
stabilize re-entries from deliver run-state + `benefitMetric.stabilizeReentries`), rework/defect rate
(re-opened phases, post-merge reverts), and post-merge incidents (optional `host.sh` revert detection /
issue-label query; `unknown` when no source). Surfaced in `/sw-retrospective` and `living-status`, and used
to **rank the meta-inbox** (e.g. recurrence count × review-rounds). Read-only signals (no gating); documented
as diagnostic-only and excluded as autonomous optimization targets.

### Auto-propose driver (R27/R30)

A **bounded planning driver** — `scripts/loop-autonomy.py` (separate from, but parity with,
`scripts/planning_autonomy.py`; reusing its `FORBIDDEN_ORCHESTRATORS` enforcement) — that under
`planning.autonomy` runs capture → RCA → **draft proposal** and produces **inert handoff-queue entries
only**. Enforcement (fail-closed, mechanical):

- **Closed allowlist:** `enqueue_handoff` rejects any command not matching an exact allowlist prefix
  (`planning_gap_capture`, `/sw-prd` *draft-only*, `planning-graph.sh reconcile`); substring forbidding is
  insufficient — allowlist membership is **required**, and wrapper/indirection attempts fail closed.
- **No reach-to-orchestrator:** entries that can reach `/sw-deliver`/`/sw-doc`/`/sw-ship` (directly or via
  `doc.afterTasks` continuation) are forbidden; `/sw-prd` is enqueued only as a **draft artifact**, never as
  an executable dispatch.
- **Human-ack to execute:** nothing in `handoffQueue` runs without a persisted human ack (same contract as
  `/sw-feedback` `human-confirm-halt`, keyed by signal id).
- **Meta units always propose-only:** `plugin-self` / `meta-shipwright` units are added to a refuse-auto list
  in the autonomy driver — never `eligible-auto`, **even under `full-conductor`**.
- **Runaway containment:** config `loop.autoPropose.{maxPerDay,dedupWindow,cooldownMinutes,maxOpenMetaUnits}`
  with fail-closed defaults; scheduled runs operate `maintenance-only` only (full-conductor forbidden for the
  scheduled substrate). v1 default substrate is manual invocation.

### Documentation deliverables

- **Config/schema:** `core/sw-reference/config.schema.json` (+`recurrence.threshold`, `inefficiency.*`,
  `loopHealth.*`, `loop.autoPropose.*`, meta-channel keys), `core/sw-reference/workflow.config.example.json`
  (+ `.sw/workflow.config.example.json` via copy-to-core sync), `docs/guides/configuration.md`,
  `core/sw-reference/{anomaly-patterns.json,failure-signature.schema.json,loop-health.schema.json}`.
- **Scripts:** `scripts/sw-state-write.sh`, `scripts/failure-signature-record.sh`,
  `scripts/failure-signature-escalate.sh`, `scripts/inefficiency-scan.sh`,
  `scripts/behavioral-anomaly-check.sh`, `scripts/loop-autonomy.py`; plus extensions to
  `scripts/planning_gap_capture.py` (plugin-self/`meta-shipwright` tags, two-phase capture/confirm),
  `scripts/planning_paths.py` (plugin-self unit placement), `scripts/memory-redact.py` (new store coverage).
- **Skills/commands/rules:** `core/skills/feedback/SKILL.md` + `core/skills/feedback/references/signal-schema.md`
  + `core/commands/sw-feedback.md` (meta channel), `core/skills/feedback-closure/SKILL.md` (meta vs product
  routing), `core/skills/rca-core/SKILL.md` (cross-run escalation + pattern catalog — **read-only consumer
  note in `core/commands/sw-debug.md`; no orchestrator-step expansion**), `core/skills/verification-gate/SKILL.md`
  (behavioral anomalies), `core/skills/retro/SKILL.md` + `core/skills/living-status/SKILL.md` (loop-health +
  inbox staleness), `core/commands/sw-retrospective.md`, `core/rules/{sw-conductor.mdc,sw-naming.mdc,memory-guardrails.mdc}`
  (auto-propose enqueue-only/no-dispatch contract, store paths + redaction chokepoint coverage — delta clauses
  only).
- **Reference/guides:** `core/sw-reference/layout.md` (+`.sw/layout.md`) explicitly enumerating
  `.cursor/sw-meta-inbox/`, the shared-git-dir `shipwright-failure-signatures.json` and
  `shipwright-loop-health.json` (writer, redaction, append-only semantics); `docs/guides/workflows.md`
  (self-improving loop section: meta channel, cross-run escalation vs in-run RCA, proposal-only auto-propose).

## Security & Compliance

- All captured signatures, root-cause records, inefficiency items, loop-health data, and meta-inbox content
  are written **only** through `scripts/sw-state-write.sh` → `scripts/memory-redact.py` (R31, fail-closed) —
  no secrets/transcripts in any store; a negative fixture proves secret-bearing input never lands on disk.
- The auto-propose driver is **proposal-only**: mechanically enforced no-merge / no-promote / no-dispatch /
  no-nested-dispatch (R27/R30) via closed allowlist + human-ack-to-execute; attempts to dispatch or reach an
  orchestrator (including wrapper/indirection) fail closed.
- Meta/plugin-self units never auto-absorb even under `full-conductor`.
- Failure-signature normalization keys on host-attested fields (not agent-authored free text) and requires
  ≥2 distinct runs, resisting suppression/forced-escalation gaming; raw hash is logged separately for audit.
- External/provider context (e.g. Sentry enrich in `/sw-debug`) stays in fenced `untrusted_payload` blocks;
  the pattern catalog is repo-curated, not provider-mutable at runtime.

## Success Criteria

- **SC1** A workflow run that reveals a Shipwright defect produces a `meta-shipwright`-tagged **inbox draft**;
  the gap unit is materialized only after human confirm — capture-without-confirm leaves zero tracked
  planning files (R20/R21).
- **SC2** A repeated CI-failure signature (≥ threshold across ≥2 runs on a fixture) triggers escalation to a
  captured root-cause record instead of another surface fix (R22/R23); paraphrased same-cause errors match,
  intentionally varied messages for one job do not split, and unrelated failures do not collide.
- **SC3** A known catalog class (e.g. false-green) on an escalated fixture **annotates** the root-cause record
  without auto-acting, and test-tampering defers to PRD A R9 (R24).
- **SC4** The inefficiency scanner reports each required class on fixtures — long single-threaded test, **slow
  CI job**, serialized-but-parallelizable phase, repeated manual step — emits an action-linked improvement
  item, and skips with a notice when a timing/sizing source is absent (R25/R26).
- **SC5** Behavioral-anomaly guardrails flag **all four** R28 classes (unauthorized create, unauthorized
  delete, false success, failed rollback) plus silent skip on fixtures, and an evidence-integrity mismatch
  (fabricated status file) is promoted to inconclusive/blocking (R28).
- **SC6** The auto-propose driver files a **draft** gap unit / PRD **without ever** merging, promoting a rule,
  dispatching, or reaching an orchestrator — proven **behaviorally**: (a) `handoffQueue` entries cannot
  execute without persisted human ack; (b) no tracked planning files mutate under `maintenance-only` without
  confirm; (c) wrapper-script / env-indirection dispatch attempts fail closed; (d) `doc.afterTasks:auto` is
  never triggered from the auto-propose path; (e) a `full-conductor` + meta-unit proposal yields `propose`
  only (R27/R30).
- **SC7** Loop-health record aggregates review-effort / rework / incident (`unknown` when no source) signals,
  surfaces in `/sw-retrospective`, ranks the meta-inbox, and adds no gating (R29).
- **SC8** Invariant fixtures prove `sw-` naming, orchestrator/atomic boundary, model-tier floor, and
  redaction fail-closed across all new stores (R30/R31).

## Testing Strategy

Fixture-driven. New suites:

- `run-meta-channel-fixtures.sh` — `meta-shipwright` tagging; two-phase capture/confirm; capture-without-confirm
  yields zero tracked planning files; human-confirm gate (R20/R21).
- `run-recurring-failure-fixtures.sh` — host-attested signature keying; normalization matrix (paraphrase →
  match; varied-message-same-job → no split; unrelated → no collision); cross-run count increment; threshold
  escalation → captured root-cause record + `signatureClass` policy (R22/R23); pattern-catalog recognition,
  test-tamper deferral to PRD A (R24).
- `run-inefficiency-scan-fixtures.sh` — long single-threaded test, slow CI job, serialized-but-parallelizable
  phase, repeated manual step detection; action-linked emission; graceful skip-with-notice when a source is
  absent (R25/R26).
- `run-behavioral-anomaly-fixtures.sh` — unauthorized create/delete, false success, failed rollback, silent
  skip flagged against the pre-agent baseline; evidence-integrity mismatch promoted to inconclusive/blocking;
  composition with verification-gate verdict (R28).
- `run-loop-health-fixtures.sh` — downstream-cost aggregation, `unknown` incident dimension, inbox ranking,
  retrospective surfacing, no gating (R29).
- `run-loop-autonomy-invariant-fixtures.sh` — **behavioral** proposal-only checks (SC6 a–e): closed-allowlist
  enforcement (allowlist-required, not substring), wrapper/indirection fail-closed, no-reach-to-orchestrator,
  human-ack-to-execute, meta-unit propose-only under full-conductor, runaway containment (simulated N-cycle
  schedule halts via dedup/cooldown, not N distinct units) (R27/R30).

Each requirement **R20–R29** maps to a named fixture scenario; **R30** (no-merge/no-promote/no-dispatch/
no-nested behavioral proofs) and **R31** (naming/boundary/model-tier + redaction fail-closed across all
stores via the single writer) carry explicit invariant fixtures (SC8).

## Rollout Plan

1. **Phase 1 — Capture surfaces + shared writer.** `sw-state-write.sh` + redaction chokepoint; meta channel +
   inbox + two-phase capture/confirm (R20/R21); cross-run failure-signature store + host-attested
   normalization + pinned writers (R22 capture half). Human-confirmed; standalone value = dogfood capture.
2. **Phase 2 — Recurrence escalation + pattern reuse.** Threshold escalation → captured root-cause record via
   `rca-core` + `signatureClass` policy; static anomaly-pattern catalog recognition (R23/R24). *Shipped with
   Phase 1 as the "recurring-failure loop" milestone — escalation is the user's top pain (repeated CI
   failures) and Phase 1 alone does not close it.*
3. **Phase 3 — Inefficiency scanner + behavioral anomalies.** Scanner reusing `benefitMetric`/run-state +
   retrospective parallelizability + graceful degradation (R25/R26); trust-anchored verification-gate anomaly
   detectors (R28). Phase 3 behavioral silent-skip composition requires PRD A skip-recording fields — gate
   accordingly.
4. **Phase 4 (optional, v1.1) — Loop-health + auto-propose driver.** Downstream-cost record + retrospective
   surfacing + inbox ranking (R29); bounded `loop-autonomy.py` driver (draft-only, closed allowlist,
   human-ack-to-execute, runaway containment) + manual scheduler default (R27). Behavioral invariant fixtures
   (SC6) wired here. *Auto-propose is acceleration, not foundation: v1 MVP (Phases 1–3) closes the loop via
   human triage + manual `/sw-prd`; Phase 4 ships once inbox consumption is proven.*

Backward compatible: every surface is opt-in/advisory; with the loop unconfigured no new capture, scan, or
propose behavior runs, and the conductor/merge/dispatch invariants are unchanged.

## Decision Log

- **2026-06-30** Reframed the value proposition to **deterministic capture + prioritized, evidence-backed
  proposals** with humans owning merge/promotion/dispatch — the loop automates capture/normalization/RCA-annotation/
  draft text, not action. Reconciles the "full self-improving loop" intent with Shipwright's permanent
  invariants (R27/R30).
- **2026-06-30** All autonomy invariants are **mechanically enforced** (closed allowlist, human-ack-to-execute,
  meta propose-only under full-conductor, single redacting writer), not prose-asserted — closes the
  adversarial self-dispatch / ungated-capture / spoofable-evidence findings.
- **2026-06-30** Meta capture is **two-phase** (inbox draft → human-confirmed materialize); auto-propose never
  materializes or dispatches, and `plugin-self` units never auto-absorb even under `full-conductor`.
- **2026-06-30** Recurring-failure signatures key on **host-attested fields** (not agent free text) with ≥2
  distinct runs and a `signatureClass` (flake/regression/infra) to resist suppression and forced-escalation
  gaming; cross-run detection is net-new wiring layered above in-run `rca-core` and the conductor circuit
  breaker, replacing neither.
- **2026-06-30** Behavioral anomalies use **trust-anchored evidence** (pre-agent diff snapshot, re-exec/hash);
  evidence-integrity mismatch is promoted to inconclusive/blocking — evidence-based, not assertion-based.
- **2026-06-30** Cross-run stores use a **shared git-dir authority** (parity with `shipwright-state.py`) so
  signatures/loop-health are visible across worktrees/PRs; `.cursor/sw-*` are per-checkout projections.
- **2026-06-30** Inefficiency parallelizability detection is **retrospective** (realized vs simulated wave
  width), explicitly fenced off from PRD B authoring-time sizing; degrades with a notice when sizing is
  absent.
- **2026-06-30** R24 ships a **static repo-curated seed catalog** (no mining/fuzzing) and defers test-tamper
  detection to PRD A R9; `/sw-debug` is a read-only consumer (no orchestrator-step expansion).
- **2026-06-30** Auto-propose (R27 Phase 4) is **optional/v1.1**, manual-scheduler default with runaway
  containment caps; v1 MVP closes the loop via human triage + manual `/sw-prd`.

## Open Questions

1. **Recurrence threshold default (R22):** how many repeats across how many runs before escalation
   (proposal: ≥3 occurrences across ≥2 distinct runs)? — resolve at spec-rigor clarify gate with adversarial
   fixture bounds, not only a conservative default.
2. **Scheduled auto-propose substrate (R27):** host-native scheduler (e.g. GitHub Actions) vs a Shipwright
   automation primitive — v1 standardizes on **manual/opt-in**; which substrate becomes the v1.1 default?
3. **Post-merge incident signal source (R29):** which host signal (revert detection, issue label, CI
   post-merge) is authoritative for the incident dimension; v1 degrades to `unknown` when none exists.
