---
date: 2026-06-26
topic: kernel-classification-and-plan-validation
prd: docs/prds/022-kernel-classification-and-plan-validation/022-prd-kernel-classification-and-plan-validation.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 022 Kernel classification, guidelines, and plan-validation gate

Generated from the frozen PRD spec union (R1–R8, R23, R24, R25, R26, R28, R29, R30, R32, R33, R34 — no
amendments). Phases are dependency-ordered per the Rollout Plan: single-sourced kernel classification →
guidelines + floor → plan-validation gate + schemas → two-tier persist + deterministic step driver →
`orchestration.planPolicy` flag → safety-invariant parity fixtures → docs/dist/call-site map. The entire
mechanism ships **dark** (`planPolicy: canonical` default, byte-identical to today); `proposed` is exercised
only in fixtures.

## Tasks

### 1. Single-sourced kernel classification + canonical chain source — L

- [ ] 1.1 Author the kernel-vs-plan-policy classification artifact (R1, R2, R3, R28)
  - **File:** `core/sw-reference/kernel-classification.md`, `core/sw-reference/kernel-classification.json`
  - **Expected:** single-sourced, version-controlled, one owner of record; enumerates kernel-step **membership** (state transitions + scoped run identity; `check-gate.sh`/`verification-gate`; merge queue journal + `O_EXCL` lock + gate-check barrier; no-`main`-auto-merge + human terminal gate; push/secret-scan `git-push.sh`; redaction chokepoint + range-scoped guard; `memory-preflight` routing; `beforeSubmitPrompt` guardrails hook non-selectable; orchestrator/living-doc locks), **ordering invariants**, the **plan-policy step enumeration**, and the signal-conditional **floor matrix** (R33). Anything off the surface is kernel-owned by default.
  - **R-IDs:** R1, R2, R3, R28
- [ ] 1.2 Single-source `SHIP_CHAIN` / canonical chain from the classification (R28, R4)
  - **File:** `scripts/ship_phase_steps.py`, `core/commands/sw-ship.md`, emitter
  - **Expected:** `SHIP_CHAIN` and the `sw-ship.md` prose chain are emitted/derived from the classification artifact (ends today's duplication); `canonical` kernel behavior unchanged and still pinned by existing fixture suites.
  - **R-IDs:** R4, R28
- [ ] 1.3 Kernel completeness + ordering + full-trace reachability fixtures (R2, R3, R25, R28)
  - **File:** `scripts/test/run-kernel-classification-fixtures.sh`
  - **Expected:** `kernel-membership-complete` (every chokepoint present + reachable in the driver-transition log before any dependent merge/push), `kernel-ordering-inversion-rejected`, and `kernel-classification-completeness-lint` (an orchestrator-referenced step absent from both enumerations fails CI); failing-before / passing-after.
  - **R-IDs:** R2, R3, R25, R28

### 2. Guidelines artifact + floor + harness reuse — M

- [ ] 2.1 Author the guidelines schema + artifact (R30)
  - **File:** `core/sw-reference/guidelines.schema.json`, `core/sw-reference/guidelines.md`
  - **Expected:** per-phase-type candidate step set, required vs optional, allowed reorderings, forbidden deviations, floor refs; bounded to deliver/ship phase types exercised by 022 fixtures (debug/doc/feedback packs land with PRD-024). Separate artifact type from the PRD-021 manifest.
  - **R-IDs:** R30
- [ ] 2.2 Ride the PRD-021 manifest lint/harness (extend, not rewrite) (R30)
  - **File:** `scripts/capability-manifest-lint.sh` (extended) / shared validation harness
  - **Expected:** guideline schema validation reuses the PRD-021 lint/harness; `guidelines-harness-reuse` fixture proves the shared harness (SC7).
  - **R-IDs:** R30
- [ ] 2.3 Tamper-resistant signal-conditional floor (R33)
  - **File:** `core/sw-reference/kernel-classification.json` (floor matrix) + gate floor evaluator
  - **Expected:** floor triggers fire from immutable task-list metadata + path globs (`auth/**`, `payments/**`, kernel scripts/providers, `hooks.json`) **and** the persisted PRD-021 `signal_context` — not triage tags alone; floor steps (e.g. `sw-review` when security-relevant) cannot be dropped/reordered past their constraint; `floor-mistagging-forces-review` fixture.
  - **R-IDs:** R33

### 3. Plan-validation gate + schemas + rejection breaker — L

- [ ] 3.1 Phase-step-plan + wave-batching plan schemas (R5)
  - **File:** `core/sw-reference/phase-step-plan.schema.json`
  - **Expected:** versioned phase step plan (ordered step ids, optional flags, kernel-injected non-droppable steps, `planPolicy`/`kernelVersion`/`guidelineVersion` stamps); plus the wave-batching plan shape persisted in shared run-state. The phase executor proposes within guideline latitude only (R5).
  - **R-IDs:** R5
- [ ] 3.2 `wave.sh plan validate` primitive (two-tier, closed-world) (R6, R32)
  - **File:** `scripts/wave_plan_validate.py`, `scripts/wave.sh` (nested `plan validate` routing)
  - **Expected:** takes a proposed plan + persisted PRD-021 `signal_context` (fail-closed if absent when a floor predicate needs it); returns stable canonical `{verdict: pass|reject|ambiguous, reasons[]}`. **Phase tier:** kernel envelope (all required steps present + reachable, no gate skipped, ordering satisfied) + guideline (R30) + floor (R33). **Wave tier:** contention edges + `worktree.parallelCeiling` (R32). Closed-world: unknown/extraneous step id rejected; "ambiguous" = multiple valid topo orders / partial order missing a kernel pair / duplicate-no-op. Rejects proposal-embedded signals diverging from persisted `signal_context`.
  - **R-IDs:** R6, R32
- [ ] 3.3 Fail-closed fallbacks (phase + wave) (R6, R32)
  - **File:** `scripts/wave_plan_validate.py`, `scripts/wave_deliver.py`
  - **Expected:** phase reject → canonical chain (from TR1/1.2); wave contention/dependency violation → **canonical waves** re-derived from the frozen plan; wave over-ceiling → `wave.sh schedule`; undeclared `**File:**` overlaps auto-serialized (PRD-013 R14 precedent). Fixtures: `plan-validate-unknown-step-rejected`, `plan-validate-ambiguous-rejected`, `plan-validate-signal-divergence-rejected`, `phase-fallback-canonical-chain`, `wave-fallback-canonical-waves`, `wave-fallback-schedule-overceiling`, `wave-undeclared-overlap-serialized`.
  - **R-IDs:** R6, R32
- [ ] 3.4 Rejection observability + minimal in-slice breaker (R6)
  - **File:** durable `planRejectionLog` schema + run-log events (`scripts/wave_plan_validate.py`)
  - **Expected:** per-phase rejection counter + run-log events; N consecutive rejections for a phase trip a consolidated halt and feed the no-progress / budget signal surface (budget *enforcement* owned by PRD-023). Does not silently burn model calls.
  - **R-IDs:** R6

### 4. Two-tier persist + deterministic step driver + lifecycle — L

- [x] 4.1 Persist validated plans to correct durable owners (atomic, stamped) (R7)
  - **File:** `scripts/ship_phase_steps.py` (per-phase run dir), shared run-state writer
  - **Expected:** phase step plan → per-phase run dir (executor-owned, alongside `status.json`/`ship-steps.json`); wave-batching plan → shared run-state (conductor only); each stamped with `planPolicy` + `kernelVersion` + `guidelineVersion`, written atomically (temp-file + rename).
  - **R-IDs:** R7
- [x] 4.2 Conductor-only single-writer guard (mechanical) (R7)
  - **File:** shared run-state writer + `scripts/test/run-plan-persist-fixtures.sh`
  - **Expected:** shared run-state writes accept conductor role/caller identity only; phase writes scoped to the phase slug's run dir; `single-writer-phase-refused` (simulated phase sub-agent write refused, exit 20) while conductor write succeeds.
  - **R-IDs:** R7
- [x] 4.3 Deterministic per-phase step driver (sole-authority + ordering re-check) (R26)
  - **File:** `scripts/ship_phase_steps.py` (`advance`/`resolve-resume` → `nextStep`)
  - **Expected:** driver reads the persisted phase plan's step list as the **sole authority** (not the hardcoded `SHIP_CHAIN`, which becomes the canonical fallback only); **re-checks kernel ordering at each `advance`** and **refuses an out-of-order / not-in-plan step** → hard halt; distinct from the conductor deliver-loop `nextAction`; stays deterministic so resume needs no model. Fixture `exec-fidelity-out-of-order-halt`.
  - **R-IDs:** R26
- [x] 4.4 Two-tier lifecycle states + crash-between-tiers recovery (R8, R34)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/ship_phase_steps.py`, `.sw/layout.md`
  - **Expected:** lifecycle `wave-validated` → `phase-plan-pending` → `phase-plan-validated`; conductor drives the stored wave layer, the step driver the stored phase layer; crash with a validated wave but missing/`pending` phase plan re-runs the **phase** proposal+validate only; corrupt/partial/stale-version plan fails closed (halt or canonical replacement) — never partial execution. Fixtures `resume-two-tier-deterministic`, `resume-corrupt-plan-fail-closed`, `resume-between-tiers-rerun-phase-only`. Resolve the wave-authority single-source-of-truth in `.sw/layout.md`.
  - **R-IDs:** R8, R34

### 5. `orchestration.planPolicy` flag definition + resume semantics — M

- [ ] 5.1 Define the flag in config schema + seeding (R29)
  - **File:** `.sw/config.schema.json`, `core/sw-reference/config.schema.json`, `workflow.config.example.json`, `core/commands/sw-init.md`
  - **Expected:** `orchestration.planPolicy: enum[canonical, proposed], default canonical`; single kill-switch spanning all orchestrators (definition only — per-orchestrator consumption is 023/024); `/sw-init` seeding + doctor surfaces current vs default and never overwrites an explicit `proposed` without confirm; composes orthogonally with `deliver.autonomy.mode` / `phaseAckCadence`.
  - **R-IDs:** R29
- [ ] 5.2 Read at proposal time, stamp + honor recorded mode on resume (R29)
  - **File:** `scripts/wave_plan_validate.py` / persistence + resume path
  - **Expected:** flag read at plan-proposal time; resolved mode + `kernelVersion`/`guidelineVersion` stamped on each persisted plan; a run persisted under `proposed` completes under its **recorded** mode (honored over live config) and is **re-validated** against the current kernel envelope on resume → fail-closed per R8; a mid-run flip after wave persistence but before phase entry leaves the recorded wave mode authoritative. Fixtures `killswitch-canonical-parity`, `killswitch-flip-midrun-recorded-mode`.
  - **R-IDs:** R29

### 6. Safety-invariant parity fixtures (proposed) + cross-cutting — M

- [ ] 6.1 Named kernel-chokepoint parity fixtures under `proposed` (R2, R23)
  - **File:** `scripts/test/run-plan-proposed-parity-fixtures.sh`
  - **Expected:** `plan-proposed-memory-preflight-required`, `plan-proposed-memory-redact-fail-closed`, `plan-proposed-secret-scan-before-push`, `plan-proposed-no-main-auto-merge`, `plan-proposed-merge-single-flight`, `plan-proposed-redaction-guard-range-scope`, `plan-proposed-guardrails-hook-non-selectable` — each asserts the chokepoint is unchanged when `planPolicy: proposed`.
  - **R-IDs:** R2, R23
- [ ] 6.2 Wire all kernel/gate/floor/killswitch fixtures into the test gate (R25)
  - **File:** `workflow.config.json` `verify.test`, `scripts/test/run-*-fixtures.sh`
  - **Expected:** kernel invariants (membership + ordering), the plan-validation gate, the guideline floor, and the kill-switch in-flight semantics each ship paired failing-before / passing-after fixtures wired into `verify.test`.
  - **R-IDs:** R25

### 7. Docs + emitter propagation + freshness + call-site map — M

- [ ] 7.1 Orchestration prose + layout updates (R24)
  - **File:** `core/skills/conductor/SKILL.md`, `core/rules/sw-conductor.mdc`, `core/skills/deliver/SKILL.md`, `core/commands/sw-deliver.md`, `core/commands/sw-ship.md`, `core/rules/sw-workflow-sequencing.mdc`, `core/skills/parallelism/SKILL.md`, `core/rules/sw-subagent-dispatch.mdc`, `.sw/layout.md`, `core/sw-reference/layout.md`
  - **Expected:** `wave.sh plan validate` added to the conductor mechanical-source table + two-tier lifecycle + durable owners; proposals routed through the gate (no hand-authored plan JSON); driver reads stored plan; layout records kernel-classification artifact, guidelines artifact, validated phase-step-plan path, wave-batching field (conductor-only), and the primitive. Canonical default unchanged; `kernel-classification.md` is the single invariants home (no duplicate enumeration).
  - **R-IDs:** R24
- [ ] 7.2 Config + guides + CONTRIBUTING (R24)
  - **File:** `docs/guides/configuration.md`, `docs/guides/workflows.md`, `docs/guides/commands.md`, `docs/guides/getting-started.md`, `CONTRIBUTING.md`, `.sw/models-tiering.md`
  - **Expected:** Orchestration-plan-policy subsection + all-keys-table entry; plan-policy overview + `plan validate` command entry; default-canonical disclosure; new fixture suites + regenerate-dist reminder; one-line model-tiering orthogonality note.
  - **R-IDs:** R24
- [ ] 7.3 Call-site / integration map (TR9) (R24)
  - **File:** `docs/prds/022-kernel-classification-and-plan-validation/` (map) / `core/sw-reference/layout.md`
  - **Expected:** enumerate every orchestrator proposal entrypoint reading the flag (deliver/phase dispatch, `/sw-doc`, `/sw-debug`, `/sw-feedback`, interactive `/sw-ship`), its canonical fallback, and its parity-fixture scope — even where `proposed` is fixture-only until 023/024 — so a flag read is not silently missed.
  - **R-IDs:** R24
- [ ] 7.4 Regenerate both dist trees; freshness gate green (R24)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** classification, guidelines, schemas, and config propagated; `emitter-stale-classification-fails` passes; `dist/` parity with `core/`.
  - **R-IDs:** R24

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 3 |
| 5 | 4 |
| 6 | 4, 5 |
| 7 | 6 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | `kernel-classification-completeness-lint` |
| R2 | 1.1, 1.3, 6.1 | `kernel-membership-complete`; `plan-proposed-memory-preflight-required` |
| R3 | 1.1, 1.3 | `kernel-classification-completeness-lint`; `plan-validate-unknown-step-rejected` |
| R4 | 1.2 | `killswitch-canonical-parity` |
| R5 | 3.1 | `phase-fallback-canonical-chain` |
| R6 | 3.2, 3.3, 3.4 | `plan-validate-unknown-step-rejected`; `plan-validate-ambiguous-rejected`; `plan-validate-signal-divergence-rejected` |
| R7 | 4.1, 4.2 | `single-writer-phase-refused`; `resume-two-tier-deterministic` |
| R8 | 4.4 | `resume-corrupt-plan-fail-closed` |
| R23 | 6.1 | `plan-proposed-secret-scan-before-push`; `plan-proposed-no-main-auto-merge`; `plan-proposed-redaction-guard-range-scope` |
| R24 | 7.1, 7.2, 7.3, 7.4 | `emitter-stale-classification-fails` |
| R25 | 1.3, 3.3, 6.2 | failing-before/passing-after across kernel/gate/floor/killswitch fixtures |
| R26 | 4.3 | `exec-fidelity-out-of-order-halt` |
| R28 | 1.1, 1.3 | `kernel-membership-complete`; `kernel-ordering-inversion-rejected`; `kernel-classification-completeness-lint` |
| R29 | 5.1, 5.2 | `killswitch-canonical-parity`; `killswitch-flip-midrun-recorded-mode` |
| R30 | 2.1, 2.2 | `guidelines-harness-reuse` |
| R32 | 3.2, 3.3 | `wave-fallback-canonical-waves`; `wave-fallback-schedule-overceiling`; `wave-undeclared-overlap-serialized` |
| R33 | 2.3 | `floor-mistagging-forces-review` |
| R34 | 4.4 | `resume-between-tiers-rerun-phase-only` |

## Relevant Files

- `core/sw-reference/kernel-classification.{md,json}` — single-sourced kernel/plan-policy classification + floor matrix (canonical-chain source)
- `core/sw-reference/guidelines.{schema.json,md}` — per-phase-type guideline artifact (rides 021 harness)
- `core/sw-reference/phase-step-plan.schema.json` — versioned phase step plan shape
- `scripts/wave_plan_validate.py`, `scripts/wave.sh` — `wave.sh plan validate` primitive (two-tier, closed-world)
- `scripts/ship_phase_steps.py` — deterministic per-phase step driver + per-phase plan persistence
- `scripts/wave_deliver_loop.py`, `scripts/wave_deliver.py` — wave-layer drive + canonical-wave fallback
- `.sw/config.schema.json`, `core/sw-reference/config.schema.json`, `workflow.config.example.json`, `core/commands/sw-init.md` — `orchestration.planPolicy` definition + seeding
- `.sw/layout.md`, `core/sw-reference/layout.md` — durable-owner + primitive layout
- `scripts/test/run-*-fixtures.sh` — kernel, gate, persist, parity, killswitch suites

## Notes

- **Dark by default.** With `planPolicy: canonical` nothing observable changes; `proposed` is fixture-only in
  this slice. The canonical-path kill-switch is the parity fixtures (failing CI), not the flag (SC1).
- **Execution fidelity is the P0.** Validating the plan document is insufficient — the deterministic step
  driver (4.3) reads the stored plan as sole authority and re-checks ordering at each `advance` (R26/TR4).
- **Flag definition only.** Per-orchestrator consumption is PRD-023 (`/sw-deliver` pilot) and PRD-024
  (debug/doc/feedback); the call-site map (7.3) records every entrypoint so a flag read is never silently missed.
- **Harness reuse, not fork.** Guidelines extend the PRD-021 manifest lint/harness (SC7) — do not build a
  second validation harness.
