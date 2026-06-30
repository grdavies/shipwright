---
prd: docs/prds/039-loop-quality-gates/039-prd-loop-quality-gates.md
date: 2026-06-30
topic: loop-quality-gates
frozen: true
frozen_at: 2026-06-30
visibility: public
---
# Tasks — PRD 039 Loop Quality Gates

Generated from the frozen PRD (effective spec union R1–R14, R30, R31). Phases mirror the PRD Rollout Plan;
phase dependencies enable `/sw-deliver` wave parallelism. No implementation starts until the `doc.afterTasks`
boundary.

## Tasks

### 1. Quality harness contract (S/M) — advisory-only scaffold, no default behavior change

- [ ] 1.1 Add `quality.*` config block + schema
  - **File:** `core/sw-reference/config.schema.json`, `workflow.config.example.json`, `docs/guides/configuration.md`
  - **Expected:** `quality.provider` (default `none`), `quality.blockingTier` (default unset/advisory) validate; `none` documented as no-op safe default.
  - **R-IDs:** R3
- [ ] 1.2 Define quality-signal schema + provider adapter contract
  - **File:** `core/sw-reference/quality-signal.schema.json`, `core/providers/quality/CAPABILITIES.md`, `providers/quality/<provider>.{md,sh}` contract
  - **Expected:** adapter consumes changed-file set; emits `{ verdict, metrics{coupling,cohesion,complexity,churn|unavailable}, perFile, refactorHints }`; values are **delta vs pre-green snapshot**; churn is diff-local only.
  - **R-IDs:** R4
- [ ] 1.3 Advisory surfacing path (non-blocking)
  - **File:** `core/skills/checks-gate/SKILL.md`, advisory wiring beside `pr-test-plan.manifest.json` / `advisoryFailingChecks`
  - **Expected:** quality verdict surfaces as advisory (non-blocking) by default; no new required check added.
  - **R-IDs:** R5
- [ ] 1.4 Register `quality.provider` in capability manifest/trust + run-state config freeze
  - **File:** `core/sw-reference/capability-index.json`, `scripts/capability_trust.py`, deliver run-state checksum writer
  - **Expected:** `quality.provider` carries `review`/`verify` trust parity; `quality.*`/triage-tier checksum frozen per deliver run (mid-run mutation fails the gate); exemptions human-only/committed/expiring.
  - **R-IDs:** R30

### 2. Refactor step + built-in provider (M/L) — enforced consideration, signal-gated action

- [ ] 2.1 Insert refactor step into execute discipline
  - **File:** `core/skills/execute-discipline/SKILL.md`, `core/commands/sw-execute.md`, `core/rules/sw-subagent-dispatch.mdc`
  - **Expected:** per-task loop becomes `red → green → tdd-gate → refactor → stage-1 → stage-2`; refactor re-runs verify + `simplify-gate.py`-style pre/post comparison; `regressed` reverts refactor edits only.
  - **R-IDs:** R1
- [ ] 2.2 Refactor outcome recording + no-silent-skip + anti-gaming bar
  - **File:** per-task execute status writer, `core/sw-reference/layout.md`
  - **Expected:** records `refactor: { ran, skipped, skipReason, signalRef, verdict, metricDelta }`; `clean` no-op recorded without justification; operational skip requires `skipReason`; `ran:true` with no metric delta on non-empty hints fails.
  - **R-IDs:** R2
- [ ] 2.3 Built-in metric provider (primary language, `auto`)
  - **File:** `providers/quality/builtin.sh`, language detection
  - **Expected:** activates only on `quality.provider: auto`/concrete id; primary-language churn + complexity proxy; coupling/cohesion best-effort or `unavailable`; `none`/unresolved → `quality:none`, loop unchanged.
  - **R-IDs:** R6
- [ ] 2.4 Refactor consumes harness signal; refactor-vs-simplify boundary docs
  - **File:** `core/skills/execute-discipline/SKILL.md`, `core/skills/simplify/SKILL.md`
  - **Expected:** refactor consumes R4 signal when present; `quality:none` records "signal: none"; docs state refactor (per-task, pre-commit, structural) vs `/sw-simplify` deslop (post-review) boundary — neither inlines the other.
  - **R-IDs:** R7

### 3. TDD hardening (M/L) — no silent skips, tamper + over-mock detection, ZOMBIES, mutation hook

- [ ] 3.1 No-silent-skip mode in tdd-gate
  - **File:** `scripts/tdd-gate.py`, `scripts/test/fixtures/tdd-gate/`
  - **Expected:** `--require-skip-reason` (default on under deliver/phase mode); `skipped` w/o `skipReason` → exit 20; `skipped` with bound `testScenario` → rejected.
  - **R-IDs:** R8
- [ ] 3.2 Baseline-anchored test-tamper check
  - **File:** `scripts/test-tamper-check.sh`, traceability-bind baseline hash writer
  - **Expected:** compares working tree + final diff against pre-red traceability-bind baseline; R9a deterministic flags (deleted test files, net-negative assertions, delete+recreate, coverage-threshold drops) block/flag; R9b advisory for ambiguous; authoritative over `testWeakened` (fail-closed on disagreement).
  - **R-IDs:** R9
- [ ] 3.3 Over-mock advisory detection + mock-realism guidance
  - **File:** over-mock scan in review surface, configured `agentsFile` (default `AGENTS.md`) block
  - **Expected:** advisory-only flags (not blocking) over defined scan scope (tests + fixtures + conftest); mock-to-SUT ratio / internal-module patching; thresholds fixture-calibrated.
  - **R-IDs:** R10
- [ ] 3.4 ZOMBIES test-list-first prompt + non-empty gate
  - **File:** `core/skills/spec-rigor/references/zombies.md`, `core/skills/tasks/SKILL.md`, `core/skills/execute-discipline/SKILL.md`, `core/commands/sw-tasks.md`
  - **Expected:** authoring prompt enumerates Zero/One/Many/Boundaries; task start with a `testScenario` gates on non-empty ZOMBIES checklist.
  - **R-IDs:** R11
- [ ] 3.5 Optional mutation-testing hook (contract-only)
  - **File:** `core/sw-reference/config.schema.json` (`verify.mutation` beside `verifyE2e`), `core/skills/verification-gate/SKILL.md`
  - **Expected:** when configured runs after green, reports surviving mutants as advisory (never default-blocking); no built-in provider; exclude-list not agent-writable without human gate.
  - **R-IDs:** R12

### 4. Review, provenance & blocking promotion (M/L)

- [ ] 4.1 Heterogeneous review providers (array) + union synthesis
  - **File:** `scripts/review-synthesize.sh`, `scripts/check-gate.py`, `core/skills/stabilize-loop/SKILL.md`, `core/commands/sw-review.md`, `core/rules/code-review-automation.mdc`
  - **Expected:** `review.providers` array supersedes scalar (scalar coerced to single-element); severity-weighted union of non-overlapping findings; provider-agnostic `reviewLanded` barrier; default single provider; Standard/Full SHOULD include ≥1 deep/external.
  - **R-IDs:** R13
- [ ] 4.2 Decision-log / provenance capture (schema-validated, redacted)
  - **File:** `core/sw-reference/decision-log.schema.json`, `core/sw-reference/templates/pr-body.md`, `scripts/git_template_lib.py`, `core/commands/sw-ship.md`, `core/commands/sw-pr.md`
  - **Expected:** `## Decision log` block with non-empty `intent`/`alternativesRuledOut`/`highRiskAreas`(auto-seeded from gate flags)/`taskRefs`; routed through `scripts/memory-redact.py` (fail-closed); `/sw-ship` fails on missing/empty record.
  - **R-IDs:** R14, R31
- [ ] 4.3 Triage-tier blocking promotion (wired last)
  - **File:** `scripts/check-gate.py` consumer, `quality.blockingTier` evaluation
  - **Expected:** when change triage tier ≥ `quality.blockingTier`, a `poor` verdict blocks commit/merge via existing gate path; never weakens an existing required check.
  - **R-IDs:** R5
- [ ] 4.4 User-facing loop docs for red→green→refactor
  - **File:** `docs/guides/workflows.md`, `README.md`
  - **Expected:** phase chain + verify→review→ship docs updated to show the refactor step (Phase 2 landing).
  - **R-IDs:** R1, R7

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
| R1 | 2.1 | `run-refactor-step-fixtures.sh` — red→green→refactor ordering |
| R2 | 2.2 | `run-refactor-step-fixtures.sh` — no-silent-skip + `clean` no-op recorded + anti-gaming (no metric delta on non-empty hints fails) |
| R3 | 1.1 | `run-quality-provider-fixtures.sh` — `none` default proceeds unchanged (`quality:none`) |
| R4 | 1.2 | `run-quality-provider-fixtures.sh` — signal schema + `unavailable` metrics + delta-vs-snapshot |
| R5 | 1.3, 4.3 | `run-quality-provider-fixtures.sh` — advisory surfacing vs triage-tier blocking promotion |
| R6 | 2.3 | `run-quality-provider-fixtures.sh` — `auto` built-in language auto-selection |
| R7 | 2.4 | `run-refactor-step-fixtures.sh` — refactor consumes signal; `quality:none` records "signal: none" |
| R8 | 3.1 | `run-tdd-hardening-fixtures.sh` — silent skip rejected; `skipped` with bound scenario rejected |
| R9 | 3.2 | `run-tdd-hardening-fixtures.sh` — baseline-anchored tamper flags; `testWeakened` disagreement fails closed |
| R10 | 3.3 | `run-tdd-hardening-fixtures.sh` — over-mock advisory flags (defined scan scope) |
| R11 | 3.4 | `run-tdd-hardening-fixtures.sh` — ZOMBIES non-empty checklist gate |
| R12 | 3.5 | `run-tdd-hardening-fixtures.sh` — mutation hook advisory (configured) |
| R13 | 4.1 | `run-heterogeneous-review-fixtures.sh` — union of non-overlapping findings; scalar back-compat |
| R14 | 4.2 | `run-provenance-fixtures.sh` — decision-log schema-valid + redacted; missing record fails ship |
| R30 | 1.4 | `run-quality-provider-fixtures.sh` — config-mutation-mid-run fails (run-state checksum freeze) |
| R31 | 4.2 | `run-provenance-fixtures.sh` — redaction fail-closed on decision-log persist |

## Relevant Files

- `core/skills/execute-discipline/SKILL.md` — refactor step insertion (Phase 2).
- `scripts/tdd-gate.py`, `scripts/test-tamper-check.sh` — TDD hardening (Phase 3).
- `scripts/check-gate.py`, `scripts/review-synthesize.sh` — heterogeneous review + blocking promotion (Phase 4).
- `core/sw-reference/{config.schema.json,quality-signal.schema.json,decision-log.schema.json,capability-index.json,layout.md}` — contracts.
- `providers/quality/` — adapter contract + built-in provider.

## Notes

- Backward compatibility (SC5): defaults (`quality.provider: none`, scalar `review.provider`, advisory-only)
  reproduce today's loop behavior byte-for-byte; only opt-in changes behavior.
- R30/R31 are cross-cutting invariants verified by explicit invariant fixtures (config-freeze mid-run fails;
  redaction fail-closed), not inherited-only coverage.
- Open Questions (over-mock thresholds, coupling/cohesion fidelity, decision-log fallback storage) resolve at
  the spec-rigor clarify gate / Phase-3 calibration before the relevant sub-task is implemented.
