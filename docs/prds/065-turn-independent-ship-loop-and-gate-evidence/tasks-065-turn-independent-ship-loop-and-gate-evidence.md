type: tasks
id: tasks-065-turn-independent-ship-loop-and-gate-evidence
unit-id: tasks-065-turn-independent-ship-loop-and-gate-evidence
prd: docs/prds/065-turn-independent-ship-loop-and-gate-evidence/065-prd-turn-independent-ship-loop-and-gate-evidence.md
date: 2026-07-11
slug: turn-independent-ship-loop-and-gate-evidence
status: draft
visibility: public
title: Tasks — PRD 065 Turn-independent ship loop and gate evidence
# Tasks — PRD 065 Turn-independent ship loop and gate evidence

## Relevant Files

- `core/sw-reference/gate-manifest.json` — declarative gate manifest (R5, R20, R29)
- `scripts/gate_manifest.py` — manifest loader + class resolution + kernel floor (R6)
- `scripts/gate_manifest_validate.py` — fail-closed lineage/divergence validator (R20)
- `core/sw-reference/gate-evidence.schema.json` — per-gate evidence record schema (R21)
- `scripts/gate_evidence.py` — evidence resolver + binding-mode + sole-writer validation (R7, R22)
- `scripts/ship_loop.py` — ship-loop driver module (R1, R2, R3, R23)
- `scripts/ship_gate_handlers.py` — mechanical gate handlers with execution proof (R9)
- `scripts/wave.py` — `ship-loop` entrypoint + interactive delegation (R23, R27)
- `scripts/wave_deliver_loop.py` — dispatch-ship/dispatch-batch + mechanical classification + halt-resume (R4, R25)
- `scripts/wave_lock.py` — lease liveness by heartbeat + watchdog re-emit (R26, R28)
- `scripts/ship-phase-status.py` — `merge-ready-green` refusal (R8)
- `scripts/wave_lifecycle.py` — run-entry auto-provision + idempotent provisioning + halt-resume (R11, R12, R25)
- `scripts/wave_deliver.py` — `resolve_type` precedence (R13)
- `scripts/planning_deliver_gate.py` — PRD-064 hard depends-on edge (R18)
- `scripts/wave_merge.py` — terminal acceptance record + report embed (R14, R24, R30)
- `scripts/wave_acceptance.py` — terminal acceptance validator (R24)
- `scripts/halt_resume.py` — standardized halt-resume schema + validator (R25)
- `scripts/phase_sizing.py` — blocking `/sw-tasks` freeze gate + logged override (R16)
- `scripts/spec-rigor-check.py` — wire sizing block into pre-freeze path (R16)
- `core/commands/`, `core/skills/`, `core/rules/`, `docs/guides/`, `.sw/layout.md`, `core/sw-reference/README.md` — documentation surfaces (R31, R32)
- `scripts/test/fixtures/ship-loop-zero-interaction/`, `scripts/unit_tests/` — fixtures + harnesses (R17, R19)

## Tasks

### 1. Gate manifest, lineage validator, and gate taxonomy (R5, R6, R20, R29)

- [ ] 1.1 Author the declarative gate manifest with stable ids, class, entrypoint, evidence contract, binding mode, failure routing, and the three-way taxonomy (R5, R29)
  - **File:** `core/sw-reference/gate-manifest.json`
  - **Expected:** Single JSON artifact; each entry references kernel/guideline lineage by id; ship-chain / external-chokepoint / advisory taxonomy encoded; `sw-simplify` marked agent-classified optional with a durable outcome artifact
  - **R-IDs:** R5, R29
- [ ] 1.2 Manifest loader with config-resolvable class resolution and a non-demotable kernel floor (R6)
  - **File:** `scripts/gate_manifest.py`
  - **Expected:** Config MAY promote optional→mandatory / adjust advisory; verification-gate, check-gate, gap-check, secret-scan chokepoint never demotable or bypassable by config or flags
  - **R-IDs:** R6
- [ ] 1.3 Manifest validator fails closed on any class/id/ordering divergence and rejects any add/reclassify beyond the R9 set (R20)
  - **File:** `scripts/gate_manifest_validate.py`
  - **Expected:** Exit non-zero on manifest-vs-lineage drift; R9-only add boundary enforced; invoked in CI and by the driver at load
  - **R-IDs:** R20
- [ ] 1.4 Bind ONLY the R9 prose-only gate ids into the kernel/guideline lineage references (no reclassification) (R5)
  - **File:** `core/sw-reference/kernel-classification.json`
  - **Expected:** behavioral-anomaly, build-chain, pre-PR smoke, decision-log, verification-gate referenced by id; no other kernel/guideline step added, removed, or reclassified
  - **R-IDs:** R5
- [ ] 1.5 Unit harness: manifest-to-lineage consistency, R9-only boundary, floor non-demotable (R5, R20)
  - **File:** `scripts/unit_tests/test_gate_manifest.py`
  - **Expected:** Fixtures assert divergence fail-closed, R9-only add rejection, and kernel-floor demotion refusal
  - **R-IDs:** R5, R20

### 2. Evidence record schema, resolver, and binding modes (R7, R21, R22)

- [ ] 2.1 Author the per-gate evidence record JSON schema with all required fields and the atomic-write contract (R21)
  - **File:** `core/sw-reference/gate-evidence.schema.json`
  - **Expected:** Requires `gateId`, `class`, `bindingMode`, `evaluationPoint`, `headSha`, `treeHash`, `verdict`, `execution` (argv/exitCode/stdoutDigest/stderrDigest/duration), `timestamp`, `artifactRefs`, provenance marker; tmp-file-plus-rename mandated; partial/truncated fails closed
  - **R-IDs:** R21
- [ ] 2.2 Evidence resolver: binding-mode resolution (tree-stable/head-exact), freshness, and supersede of stale/partial records (R22)
  - **File:** `scripts/gate_evidence.py`
  - **Expected:** `tree-stable` = `git write-tree` over tracked paths excluding run/evidence dirs; `head-exact` validates `headSha`; freshest binding-valid record authoritative; record for unknown gate id treated inert
  - **R-IDs:** R22
- [ ] 2.3 Driver-sole-writer path validation and keyless PRD-036 provenance-marker reuse (R7)
  - **File:** `scripts/gate_evidence.py`
  - **Expected:** Canonical repo-root path `.cursor/sw-deliver-runs/<phaseSlug>/gate-evidence/<gateId>.status.json`; agent-step outcome paths validated non-overlapping with evidence dir; keyless marker attached; no HMAC/keyed marker
  - **R-IDs:** R7
- [ ] 2.4 Unit harness: binding-mode/evaluation-point, atomic write, provenance integrity, sole-writer non-overlap (R7, R21, R22)
  - **File:** `scripts/unit_tests/test_gate_evidence.py`
  - **Expected:** Fixtures cover tree-stable vs head-exact, partial-file fail-closed, forged-marker fail-closed, evidence-dir overlap denial
  - **R-IDs:** R7, R21, R22

### 3. Ship-loop driver core — step classification and durable resume (R1, R2, R23)

- [ ] 3.1 Classify each chain step mechanical/agent and emit an `awaitAgent` step contract for agent steps only (R2)
  - **File:** `scripts/ship_loop.py`
  - **Expected:** Mechanical = tmp init/clean, gate invocations, commit, PR, CI watch, status writes; agent = execute/review/sw-simplify/stabilize authoring; step contract carries inputs, expected outcome-artifact path, budget; driver never spawns Tasks
  - **R-IDs:** R2
- [ ] 3.2 Durable resume from `ship-steps.json` with no chat context, reusing kernel-ordering enforcement (R1)
  - **File:** `scripts/ship_loop.py`
  - **Expected:** A fresh process resumes from durable state alone; `advance` honors `ship_phase_steps.py` kernel-ordering; no ordering bypass
  - **R-IDs:** R1
- [ ] 3.3 `wave.py ship-loop` entrypoint invoked per phase in the phase worktree with plan authority + canonical fallback (R23)
  - **File:** `scripts/wave.py`
  - **Expected:** Reads `phase-step-plan.json`, falls back to `canonicalPhaseChains.sw-ship`; cwd-isolated per phase; not folded into `wave_deliver_loop.py` process
  - **R-IDs:** R23
- [ ] 3.4 Unit harness: classification, resume-from-durable, kernel-ordering on advance (R1, R2, R23)
  - **File:** `scripts/unit_tests/test_ship_loop_core.py`
  - **Expected:** Fixtures cover mechanical/agent split, no-chat-context resume, ordering enforcement
  - **R-IDs:** R1, R2, R23

### 4. Mechanical gate handlers and evidence writers (R9)

- [x] 4.1 Mechanical gate handlers wrapping existing scripts, capturing argv/exit/stdout+stderr digest/duration (R9)
  - **File:** `scripts/ship_gate_handlers.py`
  - **Expected:** behavioral-anomaly, build-chain, pre-PR smoke, decision-log, verification-gate invoked mechanically (no re-implementation); execution proof captured per invocation
  - **R-IDs:** R9
- [x] 4.2 Wire handlers into the driver step loop as the sole evidence-record writer on completion (R9)
  - **File:** `scripts/ship_loop.py`
  - **Expected:** Driver writes one evidence record per gate at the canonical repo-root path; agent-step Tasks never write evidence
  - **R-IDs:** R9
- [x] 4.3 Unit harness: each prose-only gate invoked mechanically and evidence written with captured proof (R9)
  - **File:** `scripts/unit_tests/test_ship_gate_handlers.py`
  - **Expected:** Fixtures assert mechanical invocation + evidence-record proof fields for all five gates
  - **R-IDs:** R9

### 5. Terminal enforcement and bypass-flag constraint (R8, R10)

- [x] 5.1 Refuse `merge-ready-green` unless every mandatory gate has a binding-valid record per its mode (R8)
  - **File:** `scripts/ship-phase-status.py`
  - **Expected:** Missing/stale/head-mismatched/tree-mismatched/integrity-failing evidence fails closed with a named cause; evaluated against each gate's declared binding mode
  - **R-IDs:** R8
- [x] 5.2 Constrain bypass flags to optional/advisory gates and record actor+reason skip records (R10)
  - **File:** `scripts/ship_loop.py`
  - **Expected:** `--fast`/`--skip-local`/`--skip-simplify` skip only optional/advisory; each skip writes an explicit skip record; no flag combination suppresses a mandatory gate
  - **R-IDs:** R10
- [x] 5.3 Unit harness: refusal matrix (missing/stale/tree/head/forged/partial) + bypass constraint (R8, R10)
  - **File:** `scripts/unit_tests/test_merge_ready_enforcement.py`
  - **Expected:** Fixtures cover each refusal cause and each bypass-flag boundary incl. mandatory-suppression denial
  - **R-IDs:** R8, R10

### 6. Deliver integration — dispatch, interactive parity, watchdog, and lease liveness (R3, R4, R26, R27, R28)

- [x] 6.1 `dispatch-ship` invokes the driver inline and `dispatch-batch` runs it per phase worktree; classify the step mechanical (R4)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** Ship-loop step classified `mechanical` so the deliver loop drives it without a chat turn; background Task is the phase-scoped executor (no nested spawn); driver never spawns Tasks
  - **R-IDs:** R4
- [x] 6.2 Interactive `/sw-ship` delegates to the same driver with shared evidence enforcement, retaining the human merge pause (R27)
  - **File:** `scripts/wave.py`
  - **Expected:** No compatibility window; identical `merge-ready-green` refusal; interactive evidence to a run-scoped canonical location; interactive runs produce no terminal acceptance record
  - **R-IDs:** R27
- [x] 6.3 Consume agent-step outcomes only from durable head-bound artifacts; re-dispatch to `blocked` on budget exhaustion (R3)
  - **File:** `scripts/ship_loop.py`
  - **Expected:** Outcomes read from durable artifacts bound to the phase head SHA (never chat); exhausted per-step attempt budget transitions phase to `blocked` with a consolidated report
  - **R-IDs:** R3
- [x] 6.4 Lease liveness by heartbeat freshness alone; watchdog re-emit within the attempt budget (R26, R28)
  - **File:** `scripts/wave_lock.py`
  - **Expected:** `ship_lease_owner_live` keys off `heartbeatAt` within `SW_SHIP_LEASE_STALE_SECONDS`; `ship_steps_in_progress` no longer vetoes reclaim; stale agent-step lease re-emitted via `canonical-reemit`, exhaustion → `blocked`
  - **R-IDs:** R26, R28
- [x] 6.5 Unit harness: dispatch modes, interactive parity, re-dispatch/blocked, stale-heartbeat mid-step reclaim (R3, R4, R26, R27, R28)
  - **File:** `scripts/unit_tests/test_ship_loop_dispatch.py`
  - **Expected:** Fixtures cover inline vs background, interactive parity, budget-exhaustion blocked, and kill-mid-step reclaim-within-TTL
  - **R-IDs:** R3, R4, R26, R27, R28

### 7. Run-entry hardening and PRD-064 depends-on edge (R11, R12, R13, R18)

- [x] 7.1 `cmd_assert_entry` auto-provisions from the bare default branch instead of halting (R11)
  - **File:** `scripts/wave_lifecycle.py`
  - **Expected:** Bare-main entry provisions/adopts the orchestrator worktree mechanically; the never-implement-on-bare-main invariant is preserved
  - **R-IDs:** R11
- [x] 7.2 `cmd_orchestrator_provision` is idempotent: adopt-clean / fail-closed-dirty (R12)
  - **File:** `scripts/wave_lifecycle.py`
  - **Expected:** Clean matching worktree adopted; conflicting/dirty fails closed with a named cause + remediation hint; never a bare exit-20 requiring manual state surgery
  - **R-IDs:** R12
- [x] 7.3 `resolve_type` fixed precedence with document-kind exclusion (R13)
  - **File:** `scripts/wave_deliver.py`
  - **Expected:** `--type` → plan `target.type` → PRD-unit frontmatter `type` → `feat`; `prd`/`tasks`/`brainstorm`/`decision`/`gap` never candidates and excluded (not a validation failure); validated against changelog types
  - **R-IDs:** R13
- [x] 7.4 Hard depends-on edge to PRD 064 refuses delivery entry until 064 complete (R18)
  - **File:** `scripts/planning_deliver_gate.py`
  - **Expected:** Scheduling + dependency gate refuse entry until `064-prd-agentic-quality-patterns-and-standards-conformance` is green-merged
  - **R-IDs:** R18
- [x] 7.5 Unit harness: bare-main provision, adopt/dirty, four-source type resolution + doc-kind exclusion, 064 gate (R11, R12, R13, R18)
  - **File:** `scripts/unit_tests/test_run_entry_hardening.py`
  - **Expected:** Table-driven fixtures for each source and each provisioning outcome; 064 dependency refusal
  - **R-IDs:** R11, R12, R13, R18

### 8. Terminal acceptance record, validator, and halt-resume (R14, R15, R24, R25, R30)

- [ ] 8.1 Write the machine-checkable terminal acceptance record at run completion, capturing `green-merged` per phase at merge time (R14, R30)
  - **File:** `scripts/wave_merge.py`
  - **Expected:** Record captures per-phase merge state, terminal PR ref + live check-gate evidence, gates-run ledger rollup, and interaction count; `mergeState: green-merged` recorded at merge time
  - **R-IDs:** R14, R30
- [ ] 8.2 Terminal acceptance validator reading canonical repo-root evidence only; embedded in `report terminal` (R24)
  - **File:** `scripts/wave_acceptance.py`
  - **Expected:** Validates terminal-merged set (tolerating `teardown-pending`/`teardown-complete`), green terminal PR gate, mandatory-gate rollup, and legit-halt-only interaction count; `wave_merge.py cmd_report_terminal` embeds the validated record
  - **R-IDs:** R24
- [ ] 8.3 Standardized halt-resume schema + validator library (R25)
  - **File:** `scripts/halt_resume.py`
  - **Expected:** Object with `resumeCommand`, `haltCause`, `autonomyDirective`, `runId`, `phaseSlug`; validator rejects any legitimate-halt exit missing a required field
  - **R-IDs:** R25
- [ ] 8.4 Emit the halt-resume block from every legitimate-halt exit path (R15)
  - **File:** `scripts/wave_deliver_loop.py`
  - **Expected:** Emitted from legitimate-halt exits in `wave_deliver_loop.py`, `wave_lifecycle.py`, and the ship-loop driver; `resumeCommand` uses `/sw-deliver run <frozen-task-list-path>`; `autonomyDirective` reflects autonomous/auto config
  - **R-IDs:** R15
- [ ] 8.5 Unit harness: acceptance pass/fail matrix (incl. teardown tolerance) + resume-block completeness across exits (R14, R15, R24, R25, R30)
  - **File:** `scripts/unit_tests/test_terminal_acceptance.py`
  - **Expected:** Fixtures cover fully-evidenced pass, unmerged-phase/non-green-PR/missing-evidence fails, teardown-tolerant statuses, and every exit path emitting a complete resume block
  - **R-IDs:** R14, R15, R24, R25, R30

### 9. Phase-sizing blocking freeze gate (R16)

- [ ] 9.1 Promote `phase_sizing.py` to a blocking freeze gate that blocks on over-threshold phases with split suggestions (R16)
  - **File:** `scripts/phase_sizing.py`
  - **Expected:** A phase exceeding configured thresholds blocks task-list freeze with split suggestions emitted
  - **R-IDs:** R16
- [ ] 9.2 Wire the blocking sizing gate into the `/sw-tasks` pre-freeze path (R16)
  - **File:** `scripts/spec-rigor-check.py`
  - **Expected:** Pre-freeze tasks path invokes the sizing block; freeze refused while a phase is over-threshold without an override
  - **R-IDs:** R16
- [ ] 9.3 Human-attributed durable override (actor+reason), not agent-settable on autonomous dispatch paths (R16)
  - **File:** `scripts/phase_sizing.py`
  - **Expected:** Override records actor + reason durably; refused on autonomous `/sw-doc → /sw-tasks` dispatch paths
  - **R-IDs:** R16
- [ ] 9.4 Unit harness: block-on-oversize, override attribution required, agent-path refusal (R16)
  - **File:** `scripts/unit_tests/test_sizing_freeze_gate.py`
  - **Expected:** Fixtures cover oversize block, missing-attribution refusal, and agent-dispatch override denial
  - **R-IDs:** R16

### 10. Documentation surfaces A — commands and tasks skill (R31)

- [ ] 10.1 Update the sw-ship command doc for driver delegation, evidence enforcement, and interactive parity (R31)
  - **File:** `core/commands/sw-ship.md`
  - **Expected:** Documents shared ship-loop driver, `merge-ready-green` refusal, and retained interactive human merge pause
  - **R-IDs:** R31
- [ ] 10.2 Update the sw-deliver command doc for dispatch-ship/batch driver invocation and terminal acceptance (R31)
  - **File:** `core/commands/sw-deliver.md`
  - **Expected:** Documents inline/background driver invocation and the terminal acceptance record/report
  - **R-IDs:** R31
- [ ] 10.3 Update the sw-tasks command doc for the blocking sizing freeze gate (R31)
  - **File:** `core/commands/sw-tasks.md`
  - **Expected:** Documents blocking sizing gate and the human-attributed override boundary
  - **R-IDs:** R31
- [ ] 10.4 Update the tasks skill for the sizing freeze gate and override (R31)
  - **File:** `core/skills/tasks/SKILL.md`
  - **Expected:** Sizing promoted to blocking at freeze; override attribution + agent-path refusal documented
  - **R-IDs:** R31

### 11. Documentation surfaces B — skills and dispatch rules (R31)

- [ ] 11.1 Update the conductor skill for the reduced role and sole-Task-dispatch contract (R31)
  - **File:** `core/skills/conductor/SKILL.md`
  - **Expected:** Conductor invokes the ship-loop driver, performs bounded agent steps on `awaitAgent`, re-invokes; drivers never spawn Tasks
  - **R-IDs:** R31
- [ ] 11.2 Update the deliver skill for ship-loop integration, watchdog, and terminal acceptance (R31)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** Documents mechanical ship-loop dispatch, lease/watchdog coverage, and terminal acceptance flow
  - **R-IDs:** R31
- [ ] 11.3 Update the sw-conductor rule for envelope preservation and the lease-liveness exception (R31)
  - **File:** `core/rules/sw-conductor.mdc`
  - **Expected:** Envelopes unchanged except the named R28 lease-liveness correction
  - **R-IDs:** R31
- [ ] 11.4 Update the sw-subagent-dispatch rule (R31)
  - **File:** `core/rules/sw-subagent-dispatch.mdc`
  - **Expected:** Driver-never-spawns-Tasks and mode-specific `awaitAgent` ownership documented
  - **R-IDs:** R31
- [ ] 11.5 Update the sw-dispatch-background-phase rule for the phase-scoped inline executor (R31)
  - **File:** `core/rules/sw-dispatch-background-phase.mdc`
  - **Expected:** Background phase Task performs agent steps inline (no nested spawn)
  - **R-IDs:** R31

### 12. Documentation surfaces C, reference notes, and attestation boundary (R31, R32)

- [ ] 12.1 Update the sw-dispatch-inline-execute rule (R31)
  - **File:** `core/rules/sw-dispatch-inline-execute.mdc`
  - **Expected:** Inline `dispatch-ship` conductor-consumed handshake posture documented against the ship-loop driver
  - **R-IDs:** R31
- [ ] 12.2 Update the workflows guide for the turn-independent ship loop (R31)
  - **File:** `docs/guides/workflows.md`
  - **Expected:** End-to-end zero-interaction deliver→terminal-PR flow documented
  - **R-IDs:** R31
- [ ] 12.3 Update the configuration guide for gate classes, bypass, lease TTL, and sizing override (R31)
  - **File:** `docs/guides/configuration.md`
  - **Expected:** Config-resolvable classes + kernel floor, bypass constraints, `SW_SHIP_LEASE_STALE_SECONDS`, sizing-override attribution documented
  - **R-IDs:** R31
- [ ] 12.4 Update the layout reference for the gate-evidence dir, acceptance record, and manifest (R31)
  - **File:** `.sw/layout.md`
  - **Expected:** Canonical `.cursor/sw-deliver-runs/<phaseSlug>/gate-evidence/` path, acceptance record, and gate-manifest location documented
  - **R-IDs:** R31
- [ ] 12.5 Reference notes for gate-manifest/kernel/guidelines and the agent-gate attestation boundary (R31, R32)
  - **File:** `core/sw-reference/README.md`
  - **Expected:** Manifest/lineage notes; documents that agent-authored-gate evidence attests execution/occurrence (not judgment quality) before any config promotes such a gate to mandatory
  - **R-IDs:** R31, R32

### 13. Zero-interaction fixture, staged rollout, and regression (R17, R19)

- [ ] 13.1 Hermetic fixture repo with a multi-phase frozen task list for the zero-interaction bar (R17)
  - **File:** `scripts/test/fixtures/ship-loop-zero-interaction/README.md`
  - **Expected:** Self-contained fixture repo + frozen multi-phase task list runnable from `/sw-deliver run`
  - **R-IDs:** R17
- [ ] 13.2 Zero-interaction harness across both dispatch modes with kill-mid-step and forged/missing-evidence scenarios (R17)
  - **File:** `scripts/unit_tests/test_ship_loop_zero_interaction.py`
  - **Expected:** Zero `awaitAgent`-boundary chat prompts beyond driver-managed agent steps; inline + background; lease reclaim within TTL + re-dispatch within budget; forged/missing evidence refuses `merge-ready-green`
  - **R-IDs:** R17
- [ ] 13.3 Staged-rollout atomicity fixture proving no intermediate commit strands `/sw-ship` (R17)
  - **File:** `scripts/unit_tests/test_ship_loop_staged_rollout.py`
  - **Expected:** Enforcement + writers land together; no commit has enforcement without writers
  - **R-IDs:** R17
- [ ] 13.4 Regression: full existing guardrail suite green with no envelope regression beyond R28 (R19)
  - **File:** `scripts/unit_tests/test_deliver_envelope_regression.py`
  - **Expected:** Dual-ship, remediation, parallel merge safety, and status integrity fixtures stay green; only the named R28 lease-liveness change differs
  - **R-IDs:** R19

## Phase Dependencies

| Phase | Depends on |
| --- | --- |
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |
| 5 | 4 |
| 6 | 5 |
| 7 | none |
| 8 | 6, 7 |
| 9 | none |
| 10 | 8, 9 |
| 11 | 10 |
| 12 | 11 |
| 13 | 12 |

## Execute-tier granularity

> Frozen artifact (PRD 055 R17). Generated by `python3 scripts/tasks_generate.py apply-granularity` before `/sw-freeze`.

```json
{
  "generatedBy": "tasks_generate.py",
  "refSplits": [],
  "splitPreflight": {
    "costEstimate": {
      "estimate": 121,
      "mergeGates": 11,
      "projectedWaves": 11
    },
    "notices": [
      "phase 1: scopeUnderDeclared (28 implied path(s) not in **File:** lines)",
      "phase 2: scopeUnderDeclared (31 implied path(s) not in **File:** lines)",
      "phase 3: scopeUnderDeclared (29 implied path(s) not in **File:** lines)",
      "phase 4: scopeUnderDeclared (24 implied path(s) not in **File:** lines)",
      "phase 5: scopeUnderDeclared (24 implied path(s) not in **File:** lines)",
      "phase 6: scopeUnderDeclared (23 implied path(s) not in **File:** lines)",
      "phase 7: scopeUnderDeclared (24 implied path(s) not in **File:** lines)",
      "phase 8: scopeUnderDeclared (24 implied path(s) not in **File:** lines)",
      "phase 9: scopeUnderDeclared (23 implied path(s) not in **File:** lines)",
      "phase 10: scopeUnderDeclared (14 implied path(s) not in **File:** lines)",
      "phase 11: scopeUnderDeclared (11 implied path(s) not in **File:** lines)",
      "phase 12: scopeUnderDeclared (15 implied path(s) not in **File:** lines)",
      "phase 13: scopeUnderDeclared (29 implied path(s) not in **File:** lines)"
    ],
    "phaseCount": 13,
    "splitSuggestions": [
      {
        "phase": "1",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention: phases 1a and 2 serialized (core/**)",
            "contention injected 1 edge(s)"
          ],
          "projectedPhaseCount": 16,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "core/sw-reference/gate-manifest.json",
              "core/sw-reference/kernel-classification.json"
            ],
            "id": "1a"
          },
          {
            "files": [
              "scripts/gate_manifest.py"
            ],
            "id": "1b"
          },
          {
            "files": [
              "scripts/gate_manifest_validate.py"
            ],
            "id": "1c"
          },
          {
            "files": [
              "scripts/unit_tests/test_gate_manifest.py"
            ],
            "id": "1d"
          }
        ]
      },
      {
        "phase": "2",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention: phases 1 and 2a serialized (core/**)",
            "contention injected 1 edge(s)"
          ],
          "projectedPhaseCount": 15,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "core/sw-reference/gate-evidence.schema.json"
            ],
            "id": "2a"
          },
          {
            "files": [
              "scripts/gate_evidence.py"
            ],
            "id": "2b"
          },
          {
            "files": [
              "scripts/unit_tests/test_gate_evidence.py"
            ],
            "id": "2c"
          }
        ]
      },
      {
        "phase": "3",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention: phases 3a and 4 serialized (scripts/ship_loop.py)",
            "contention injected 1 edge(s)"
          ],
          "projectedPhaseCount": 15,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/ship_loop.py"
            ],
            "id": "3a"
          },
          {
            "files": [
              "scripts/unit_tests/test_ship_loop_core.py"
            ],
            "id": "3b"
          },
          {
            "files": [
              "scripts/wave.py"
            ],
            "id": "3c"
          }
        ]
      },
      {
        "phase": "4",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention: phases 4b and 5 serialized (scripts/ship_loop.py)",
            "contention injected 1 edge(s)"
          ],
          "projectedPhaseCount": 15,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/ship_gate_handlers.py"
            ],
            "id": "4a"
          },
          {
            "files": [
              "scripts/ship_loop.py"
            ],
            "id": "4b"
          },
          {
            "files": [
              "scripts/unit_tests/test_ship_gate_handlers.py"
            ],
            "id": "4c"
          }
        ]
      },
      {
        "phase": "5",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention: phases 5b and 6 serialized (scripts/ship_loop.py)",
            "contention injected 1 edge(s)"
          ],
          "projectedPhaseCount": 15,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/ship-phase-status.py"
            ],
            "id": "5a"
          },
          {
            "files": [
              "scripts/ship_loop.py"
            ],
            "id": "5b"
          },
          {
            "files": [
              "scripts/unit_tests/test_merge_ready_enforcement.py"
            ],
            "id": "5c"
          }
        ]
      },
      {
        "phase": "6",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention injected 0 edge(s)"
          ],
          "projectedPhaseCount": 17,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/ship_loop.py"
            ],
            "id": "6a"
          },
          {
            "files": [
              "scripts/unit_tests/test_ship_loop_dispatch.py"
            ],
            "id": "6b"
          },
          {
            "files": [
              "scripts/wave.py"
            ],
            "id": "6c"
          },
          {
            "files": [
              "scripts/wave_deliver_loop.py"
            ],
            "id": "6d"
          },
          {
            "files": [
              "scripts/wave_lock.py"
            ],
            "id": "6e"
          }
        ]
      },
      {
        "phase": "7",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention injected 0 edge(s)"
          ],
          "projectedPhaseCount": 16,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/planning_deliver_gate.py"
            ],
            "id": "7a"
          },
          {
            "files": [
              "scripts/unit_tests/test_run_entry_hardening.py"
            ],
            "id": "7b"
          },
          {
            "files": [
              "scripts/wave_deliver.py"
            ],
            "id": "7c"
          },
          {
            "files": [
              "scripts/wave_lifecycle.py"
            ],
            "id": "7d"
          }
        ]
      },
      {
        "phase": "8",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention: phases 2 and 10 serialized (core/**)",
            "contention injected 1 edge(s)"
          ],
          "projectedPhaseCount": 17,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/halt_resume.py"
            ],
            "id": "8a"
          },
          {
            "files": [
              "scripts/unit_tests/test_terminal_acceptance.py"
            ],
            "id": "8b"
          },
          {
            "files": [
              "scripts/wave_acceptance.py"
            ],
            "id": "8c"
          },
          {
            "files": [
              "scripts/wave_deliver_loop.py"
            ],
            "id": "8d"
          },
          {
            "files": [
              "scripts/wave_merge.py"
            ],
            "id": "8e"
          }
        ]
      },
      {
        "phase": "9",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention injected 0 edge(s)"
          ],
          "projectedPhaseCount": 15,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/phase_sizing.py"
            ],
            "id": "9a"
          },
          {
            "files": [
              "scripts/spec-rigor-check.py"
            ],
            "id": "9b"
          },
          {
            "files": [
              "scripts/unit_tests/test_sizing_freeze_gate.py"
            ],
            "id": "9c"
          }
        ]
      },
      {
        "phase": "12",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention: phases 1 and 12b serialized (core/**)",
            "contention injected 1 edge(s)"
          ],
          "projectedPhaseCount": 16,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              ".sw/layout.md"
            ],
            "id": "12a"
          },
          {
            "files": [
              "core/rules/sw-dispatch-inline-execute.mdc",
              "core/sw-reference/README.md"
            ],
            "id": "12b"
          },
          {
            "files": [
              "docs/guides/configuration.md"
            ],
            "id": "12c"
          },
          {
            "files": [
              "docs/guides/workflows.md"
            ],
            "id": "12d"
          }
        ]
      },
      {
        "phase": "13",
        "preflight": {
          "maxPhaseCount": 13,
          "notices": [
            "contention injected 0 edge(s)"
          ],
          "projectedPhaseCount": 16,
          "reason": "maxPhaseCount exceeded",
          "verdict": "reject"
        },
        "reason": "maxPhaseCount exceeded",
        "rejected": true,
        "units": [
          {
            "files": [
              "scripts/test/fixtures/ship-loop-zero-interaction/README.md"
            ],
            "id": "13a"
          },
          {
            "files": [
              "scripts/unit_tests/test_deliver_envelope_regression.py"
            ],
            "id": "13b"
          },
          {
            "files": [
              "scripts/unit_tests/test_ship_loop_staged_rollout.py"
            ],
            "id": "13c"
          },
          {
            "files": [
              "scripts/unit_tests/test_ship_loop_zero_interaction.py"
            ],
            "id": "13d"
          }
        ]
      }
    ]
  },
  "taskList": "/tmp/sw-tasks-065.md",
  "version": 1
}
```

## Traceability

| R-ID | Task | Test scenario | ZOMBIES checklist |
| --- | --- | --- | --- |
| R1 | 3.2 | driver-resume-no-chat-context | Z, O, I, E, S |
| R2 | 3.1 | step-classification-await-handshake | O, M, I, E |
| R3 | 6.3 | agent-outcome-durable-artifact-rebudget | O, B, I, E, S |
| R4 | 6.1 | dispatch-ship-batch-mechanical | O, M, I, E |
| R5 | 1.1 | manifest-lineage-single-source | O, M, I, E |
| R6 | 1.2 | kernel-floor-non-demotable | O, I, E |
| R7 | 2.3 | driver-sole-writer-execution-proof | O, I, E, S |
| R8 | 5.1 | merge-ready-green-refusal-matrix | Z, O, B, I, E |
| R9 | 4.1 | prose-only-gates-mechanical-evidence | O, M, I, E |
| R10 | 5.2 | bypass-flag-optional-only-skip-record | Z, O, B, I, E |
| R11 | 7.1 | bare-main-auto-provision | Z, O, I, E |
| R12 | 7.2 | orchestrator-provision-idempotent | O, B, I, E, S |
| R13 | 7.3 | branch-type-precedence-doc-kind-exclusion | Z, O, B, I, E |
| R14 | 8.1 | terminal-acceptance-record-write | O, M, I, S |
| R15 | 8.4 | halt-resume-block-every-exit | Z, O, I, E |
| R16 | 9.1 | sizing-freeze-gate-block-override | O, B, I, E, S |
| R17 | 13.1 | zero-interaction-bar-fixture | Z, O, M, B, I, E, S |
| R18 | 7.4 | prd-064-hard-depends-on | O, I, E |
| R19 | 13.4 | guardrail-suite-no-regression | O, M, I, S |
| R20 | 1.3 | manifest-validator-fail-closed | Z, O, I, E |
| R21 | 2.1 | evidence-record-schema-atomic | Z, O, B, I, E |
| R22 | 2.2 | binding-mode-tree-head-freshness | O, B, I, E, S |
| R23 | 3.3 | sibling-driver-plan-authority | O, I, E, S |
| R24 | 8.2 | acceptance-validator-terminal-merged | O, M, I, E |
| R25 | 8.3 | halt-resume-schema-validator | Z, O, I, E |
| R26 | 6.4 | watchdog-reemit-attempt-budget | O, B, I, E, S |
| R27 | 6.2 | interactive-ship-parity-merge-pause | O, I, E, S |
| R28 | 6.4 | lease-liveness-heartbeat-only | Z, O, B, I, E, S |
| R29 | 1.1 | three-way-gate-taxonomy | O, M, I |
| R30 | 8.1 | green-merged-terminal-merged-set | O, M, B, I, S |
| R31 | 10.1, 10.2, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4 | docs-currency-surfaces | O, I |
| R32 | 12.5 | agent-gate-attestation-boundary | O, I, E |
| D1 | 3.1 | full-absorb-driver-decision | O, I |
| D2 | 1.2 | manifest-ledger-decision | O, I |
| D3 | 3.3 | sibling-driver-placement-decision | O, I |
| D4 | 2.2 | binding-mode-by-position-decision | O, I |
| D5 | 5.1 | interactive-adoption-decision | O, I |
| D6 | 13.1 | depends-064-sequencing-decision | O, I |
| D7 | 7.1 | run-entry-idempotent-decision | O, I |
| D8 | 9.1 | sizing-blocking-gate-decision | O, I |
| D9 | 11.1 | conductor-role-reduced-decision | O, I |
| D10 | 2.1 | binding-mode-corrected-decision | O, I |
| D11 | 2.3 | driver-sole-writer-decision | O, I |
| D12 | 6.5 | lease-liveness-envelope-exception-decision | O, I |
| D13 | 3.2 | background-await-ownership-decision | O, I |
| D14 | 1.3 | lineage-boundary-decision | O, I |
| D15 | 12.1 | interactive-boundary-decision | O, I |
| D16 | 7.3 | branch-type-precedence-decision | O, I |
| D17 | 13.3 | rollout-atomicity-decision | O, I |
| D18 | 4.1 | three-way-taxonomy-decision | O, I |
| D19 | 8.2 | terminal-merged-set-decision | O, I |
| D20 | 10.1 | docs-currency-decision | O, I |
| D21 | 12.5 | ledger-attestation-boundary-decision | O, I |

## Notes

- Frozen PRD union includes Decision-Log D-IDs (D1–D21) because PRD 065 authors its Decision Log as `- **Dn**` bullets; both R1–R32 and D1–D21 are therefore covered here (no orphans).
- Gap traceability: gap-135/#403 (turn-independence) → phases 3, 5, 6, 13; gap-136/#404 (run-entry) → phase 7; gap-137/#405 (terminal acceptance + resume) → phases 8, 13.
- Contention: phases touching `scripts/wave_deliver_loop.py` (6, 8) and `scripts/ship_loop.py` (3, 4, 5, 6) carry serializing edges via the dependency chain; `scripts/wave_lifecycle.py` (7, 8) serialized by the 8→7 edge; `core/skills/tasks/SKILL.md` doc (10) follows the sizing-gate phase (9).
- Human merge gate to `main` is never crossed by this unit; phase-mode never merges (R19).