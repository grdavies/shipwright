---
prd: docs/prds/041-self-improving-loop/041-prd-self-improving-loop.md
date: 2026-06-30
topic: self-improving-loop
frozen: true
frozen_at: 2026-06-30
visibility: public
---
# Tasks — PRD 041 Self-Improving Loop

Generated from the frozen PRD (effective spec union R20–R29, R30, R31). Phases mirror the PRD Rollout Plan
(Phases 1+2 ship together as the "recurring-failure loop" milestone). No implementation starts until the
`doc.afterTasks` boundary. Every surface is opt-in/advisory; merge, promotion, and dispatch stay human-owned.

## Tasks

### 1. Shared writer + capture surfaces

- [x] 1.1 Single redacting state writer (sole writer for `.cursor/sw-*` + shared-git-dir stores)
  - **File:** `scripts/sw-state-write.sh`, `core/sw-reference/layout.md`, `.sw/layout.md`
  - **Expected:** sole writer for all new stores; pipes content through `scripts/memory-redact.py`, validates against the target schema, atomic append/write; **fails closed** on redaction/schema error; direct `write_json` to these paths banned (fixture lint); layout registers writer + redaction + append-only semantics.
  - **R-IDs:** R31
- [x] 1.2 Meta/dogfood channel — two-phase capture/confirm
  - **File:** `scripts/planning_gap_capture.py`, `core/skills/feedback/SKILL.md`, `core/skills/feedback/references/signal-schema.md`, `core/commands/sw-feedback.md`, `core/skills/feedback-closure/SKILL.md`, `scripts/planning_paths.py`
  - **Expected:** `meta-shipwright` destination + `plugin-self` gap class; `capture` writes redacted draft to `.cursor/sw-meta-inbox/` only (no tracked planning mutation); `materialize` creates the gap unit only after `confirm --signal-id` records a persisted ack; meta vs product routing separated in `feedback-closure`.
  - **R-IDs:** R20, R21
- [x] 1.3 Cross-run failure-signature store (capture half) + pinned writers
  - **File:** `scripts/failure-signature-record.sh`, `core/sw-reference/failure-signature.schema.json`, `scripts/check-gate.py`, `scripts/wave_failure.py`, `scripts/verify-evidence.py`
  - **Expected:** shared-git-dir authority (`${GIT_DIR}/shipwright-failure-signatures.json`, append-only via `sw-state-write.sh`); key `{check_id, exit_code, job_id}` (host-attested) + normalized message class as secondary discriminator (algorithm pinned in schema; strip temp paths/UUIDs/line numbers/timestamps; raw hash logged separately for audit); writers pinned at check-gate red, wave_failure blocked, verify-evidence not-verified, conductor `noProgressStreak`; `*-index` merge subcommand for linked worktrees.
  - **R-IDs:** R22

### 2. Recurrence escalation + pattern reuse

- [x] 2.1 Threshold escalation → captured root-cause record + signatureClass policy
  - **File:** `scripts/failure-signature-escalate.sh`, `core/skills/rca-core/SKILL.md`, `core/sw-reference/config.schema.json` (`recurrence.threshold`)
  - **Expected:** on `count ≥ threshold` across ≥2 distinct runs, runs the `rca-core` debug-entry procedure on redacted failure text and files an escalated root-cause record (distinct class/status) instead of another surface fix; `signatureClass` (`flake`|`regression`|`infra`) governs policy — flakes require a human-acknowledged waiver before the remediation loop is considered closed; net-new cross-run layer above in-run `rca-core` + conductor circuit breaker (neither replaced).
  - **R-IDs:** R22, R23
- [x] 2.2 Static anomaly-pattern catalog (recognition only)
  - **File:** `core/sw-reference/anomaly-patterns.json`, `core/skills/rca-core/SKILL.md`, `core/commands/sw-debug.md`
  - **Expected:** static repo-curated seed catalog (false-green, unauthorized-delete, failed-rollback, silent-skip) the RCA consults to *recognize* + annotate the root-cause record; never auto-acts; test-tampering excluded — cross-references PRD A R9 as authoritative detector and annotates only when A's flags exist; `/sw-debug` is a **read-only consumer** (no orchestrator-step expansion).
  - **R-IDs:** R24

### 3. Inefficiency scanner + behavioral anomalies

- [ ] 3.1 Inefficiency scanner — action-linked items + graceful degradation
  - **File:** `scripts/inefficiency-scan.sh`, `core/sw-reference/config.schema.json` (`inefficiency.*`), `docs/guides/configuration.md`
  - **Expected:** reads `benefitMetric` + deliver run-state; detects long single-threaded tests + **slow CI jobs** (timing thresholds where a host-attested capture surface exists; per-test timing parses `verify` machine-readable output e.g. JUnit XML), serialized-but-parallelizable phases (retrospective: realized `waveBatchingPlan` width vs simulated `wave_deliver.py` `apply_contention`+`greedy_wave_batches` width; flag `parallelCeiling>1` with width-1 execution lacking mandatory edges), repeated manual steps (run-state recurrence + false-positive allowlist); each item names a concrete next step (action-linked); **skips with a notice** when a timing/sizing source is absent; items route through the inbox path (drafts, human-confirmed), never auto-applied.
  - **R-IDs:** R25, R26
- [ ] 3.2 Trust-anchored behavioral-anomaly guardrails
  - **File:** `scripts/behavioral-anomaly-check.sh`, `core/skills/verification-gate/SKILL.md`
  - **Expected:** called from ship chain after execute/verify; consumes pre-agent git diff snapshot (hook baseline), `git diff --name-status`, frozen declared scope (`**File:**` + Relevant Files), `sw-verify` status, phase skip records; detects unauthorized create/delete (diff outside declared scope vs baseline), false success (evidence artifact fails re-exec/hash check), failed rollback (revert left tree dirty), silent skip (gate `skipped` w/o reason — TDD/refactor skips delegated to PRD A); emits advisory high-risk flag + feeds failure-signature store; **evidence-integrity mismatch promoted to inconclusive/blocking** within the verification-gate contract (evidence-based, not assertion-based).
  - **R-IDs:** R28

### 4. Loop-health + auto-propose driver (optional, v1.1)

- [ ] 4.1 Downstream-cost loop-health metrics + inbox ranking
  - **File:** `scripts/sw-state-write.sh` (loop-health path), `core/sw-reference/loop-health.schema.json`, `core/skills/retro/SKILL.md`, `core/skills/living-status/SKILL.md`, `core/commands/sw-retrospective.md`, `core/sw-reference/config.schema.json` (`loopHealth.*`)
  - **Expected:** shared-git-dir record aggregating review effort (review rounds / `stabilizeReentries`), rework/defect (re-opened phases, post-merge reverts), incidents (optional `host.sh` revert/issue-label; `unknown` when no source); surfaced in `/sw-retrospective` + `living-status` (inbox staleness alerts); ranks meta-inbox (e.g. recurrence × review-rounds); read-only (no gating); documented diagnostic-only and excluded as an autonomous optimization target.
  - **R-IDs:** R29
- [ ] 4.2 Bounded auto-propose driver — draft-only, mechanically gated
  - **File:** `scripts/loop-autonomy.py`, `core/rules/sw-conductor.mdc`, `core/rules/sw-naming.mdc`, `core/sw-reference/config.schema.json` (`loop.autoPropose.*`), `core/sw-reference/workflow.config.example.json`
  - **Expected:** bounded driver (parity with `planning_autonomy.py`, reuses `FORBIDDEN_ORCHESTRATORS`); produces drafts + **inert** handoff-queue entries; `enqueue_handoff` **requires** exact allowlist-prefix membership (`planning_gap_capture`, `/sw-prd` draft-only, `planning-graph.sh reconcile`) — substring forbidding insufficient; entries that can reach `/sw-deliver`/`/sw-doc`/`/sw-ship` (incl. via `doc.afterTasks`) forbidden; nothing executes without persisted human ack; `plugin-self`/`meta-shipwright` units never `eligible-auto` even under `full-conductor`; runaway containment `loop.autoPropose.{maxPerDay,dedupWindow,cooldownMinutes,maxOpenMetaUnits}` fail-closed; scheduled runs `maintenance-only` only; v1 default = manual invocation.
  - **R-IDs:** R27, R30
- [ ] 4.3 Behavioral invariant + redaction fixtures
  - **File:** `scripts/test/run-loop-autonomy-invariant-fixtures.sh`, `scripts/memory-redact.py`
  - **Expected:** behavioral proof of proposal-only (handoffQueue inert without ack; no tracked planning mutation under `maintenance-only` without confirm; wrapper/env-indirection dispatch fails closed; `doc.afterTasks:auto` never triggered from auto-propose; full-conductor + meta-unit → `propose` only; simulated N-cycle schedule halts via dedup/cooldown); `sw-` naming + orchestrator/atomic boundary + model-tier floor checks; redaction fail-closed across all new stores (secret-bearing input never lands on disk).
  - **R-IDs:** R30, R31

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 2, 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R20 | 1.2 | `run-meta-channel-fixtures.sh` — `meta-shipwright` tagging + plugin-self gap class |
| R21 | 1.2 | `run-meta-channel-fixtures.sh` — two-phase capture/confirm; capture-without-confirm yields zero tracked planning files |
| R22 | 1.3, 2.1 | `run-recurring-failure-fixtures.sh` — host-attested keying + normalization matrix (paraphrase→match, varied-message-same-job→no split, unrelated→no collision); cross-run increment; ≥2-run threshold escalation |
| R23 | 2.1 | `run-recurring-failure-fixtures.sh` — escalation → captured root-cause record + `signatureClass` policy (flake waiver before loop-close) |
| R24 | 2.2 | `run-recurring-failure-fixtures.sh` — catalog recognition annotates record without auto-acting; test-tamper defers to PRD A R9 |
| R25 | 3.1 | `run-inefficiency-scan-fixtures.sh` — long single-threaded test + slow CI job + serialized-but-parallelizable phase + repeated manual step; action-linked emission |
| R26 | 3.1 | `run-inefficiency-scan-fixtures.sh` — reuse `benefitMetric`/run-state; graceful skip-with-notice when timing/sizing source absent |
| R28 | 3.2 | `run-behavioral-anomaly-fixtures.sh` — all four classes vs pre-agent baseline + silent skip; evidence-integrity mismatch promoted to inconclusive/blocking; verification-gate composition |
| R29 | 4.1 | `run-loop-health-fixtures.sh` — downstream-cost aggregation, `unknown` incident dimension, inbox ranking, retrospective surfacing, no gating |
| R27 | 4.2 | `run-loop-autonomy-invariant-fixtures.sh` — draft-only proposal; closed-allowlist (allowlist-required); runaway containment; manual-scheduler default |
| R30 | 4.2, 4.3 | `run-loop-autonomy-invariant-fixtures.sh` — behavioral no-merge/no-promote/no-dispatch/no-reach-to-orchestrator; meta propose-only under full-conductor; human-ack-to-execute |
| R31 | 1.1, 4.3 | `run-loop-autonomy-invariant-fixtures.sh` — single-writer redaction fail-closed across all stores; naming/boundary/model-tier invariants |

## Relevant Files

- `scripts/sw-state-write.sh` — sole redacting writer for all new stores (Phase 1).
- `scripts/{failure-signature-record.sh,failure-signature-escalate.sh,inefficiency-scan.sh,behavioral-anomaly-check.sh,loop-autonomy.py}` — capture/escalate/scan/anomaly/auto-propose (Phases 1–4).
- `scripts/planning_gap_capture.py`, `scripts/planning_paths.py` — meta channel two-phase capture + plugin-self placement.
- `scripts/{check-gate.py,wave_failure.py,verify-evidence.py}`, `scripts/wave_deliver.py` — pinned signature writers + (read-only) contention primitives.
- `core/sw-reference/{anomaly-patterns.json,failure-signature.schema.json,loop-health.schema.json,config.schema.json,workflow.config.example.json,layout.md}`, `.sw/layout.md` — contracts/stores.
- `core/skills/{feedback,feedback-closure,rca-core,verification-gate,retro,living-status}/SKILL.md`, `core/skills/feedback/references/signal-schema.md`, `core/commands/{sw-feedback,sw-debug,sw-retrospective}.md` — surfaces.
- `core/rules/{sw-conductor,sw-naming,memory-guardrails}.mdc` — auto-propose enqueue-only/no-dispatch + redaction delta clauses.
- `docs/guides/{configuration,workflows}.md` — config keys + self-improving loop section.

## Notes

- Backward compatible: with the loop unconfigured no new capture, scan, or propose behavior runs; conductor/
  merge/dispatch invariants are unchanged.
- All autonomy invariants are **mechanically enforced** (closed allowlist, human-ack-to-execute, meta
  propose-only under full-conductor, single redacting writer) — not prose-asserted.
- Cross-run stores use shared-git-dir authority (parity with `shipwright-state.py`) for cross-worktree/PR
  visibility; `.cursor/sw-*` are per-checkout projections.
- Phases 1+2 ship together as the "recurring-failure loop" milestone (the user's top pain). Phase 4
  (auto-propose) is optional/v1.1; v1 MVP closes the loop via human triage + manual `/sw-prd`.
- Recurrence threshold + flake/regression policy (R22/R23) resolved at spec-rigor clarify with adversarial
  fixture bounds; per-test/CI-job timing source (R26) and post-merge incident source (R29) degrade to
  skip-with-notice / `unknown` when absent.
