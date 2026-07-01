---
prd: docs/prds/051-spec-rigor-brainstorm-profile-and-stdlib-coverage/051-prd-spec-rigor-brainstorm-profile-and-stdlib-coverage.md
date: 2026-07-01
topic: spec-rigor-brainstorm-profile-and-stdlib-coverage
visibility: public
frozen: true
frozen_at: 2026-07-01
---
# Tasks — PRD 051 spec-rigor brainstorm artifact profile & stdlib-only coverage tooling

Single-pass task list from the frozen PRD 051 spec union (R1–R11; decisions D5–D6). Phases mirror the PRD
Rollout Plan (Thread A → Thread B parallel-eligible → manifest/gap verification). No implementation starts until
the `doc.afterTasks` boundary.

## Tasks

### 1. Thread A — spec-rigor brainstorm artifact profile (S)

`brainstorm` artifact profile, blocking `/sw-brainstorm` Phase 2 gate, and regression fixtures.

- [ ] 1.1 Add `brainstorm` branch to `spec-rigor-check.py` (R1–R3, TR1)
  - **File:** `scripts/spec-rigor-check.py`
  - **Expected:** `--artifact brainstorm` validates required sections per `skills/brainstorm/references/requirements-sections.md` and R-ID monotonicity (non-contiguous numbering permitted per D4); missing sections and R-ID violations emit `error` severity consistent with `prd`/`decision` profiles
  - **R-IDs:** R1, R2, R3
- [ ] 1.2 Wire blocking brainstorm gate in `/sw-brainstorm` (R4, TR2)
  - **File:** `core/commands/sw-brainstorm.md`, `scripts/build-chain-sync.py`
  - **Expected:** Phase 2 documents and invokes `spec-rigor-check.py --artifact brainstorm` as hard-blocking (exit `20` halts); `build-chain-sync.py` run before phase ship when `core/commands/` changes
  - **R-IDs:** R4
- [ ] 1.3 Thread A regression fixture (R5, TR3)
  - **File:** `scripts/test/fixtures/spec-rigor-brainstorm-profile-required-sections/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** negative case (missing Success Criteria) fails; positive case (compliant exemplar brainstorm) passes
  - **R-IDs:** R5

### 2. Thread B — stdlib-only coverage tooling (M)

Opt-in `trace`-based coverage mode in `_runner.py`, report aggregation, gitignored scratch, and regression fixtures.

- [ ] 2.1 Coverage subprocess swap + suite subprocess parity (R6, R7, TR4)
  - **File:** `scripts/test/_runner.py`, `.gitignore`
  - **Expected:** `--coverage` flag or `SW_COVERAGE=1` swaps `.test` and `.py` suite invocations to `python -m trace --count --coverdir=<dir>` subprocess path (no in-process importlib when coverage enabled); `coverdir` defaults to `.cursor/sw-coverage/<run-id>/`; `.gitignore` includes `.cursor/sw-coverage/`; `scripts/_sw/depmanifest.json` unchanged
  - **R-IDs:** R6, R7
- [ ] 2.2 Coverage report aggregation (R8, TR5)
  - **File:** `scripts/test/_runner.py` (or `scripts/coverage_report.py`)
  - **Expected:** post-run step parses `.cover` files under `coverdir`, prints per-script executed/total lines under `scripts/` plus aggregate percentage; stdlib-only parser
  - **R-IDs:** R8
- [ ] 2.3 Additive-behavior regression fixture (R9, TR6)
  - **File:** `scripts/test/fixtures/stdlib-coverage-mode-no-behavior-change/`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** representative `.test` run returns identical exit code with and without coverage mode
  - **R-IDs:** R9
- [ ] 2.4 Executed/unexecuted-lines regression fixture (R11, TR7)
  - **File:** `scripts/test/fixtures/stdlib-coverage-report-executed-and-unexecuted-lines/`, `scripts/test/fixtures/coverage-target-script.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** coverage mode over synthetic script reports ≥1 executed and ≥1 un-executed line
  - **R-IDs:** R11
- [ ] 2.5 Document informational-only baseline posture (R10)
  - **File:** `scripts/test/_runner.py` help text or `core/sw-reference/pr-test-plan.manifest.json` notes
  - **Expected:** no minimum coverage percentage enforced as CI gate; mechanism + baseline report only
  - **R-IDs:** R10

### 3. Manifest registration + gap verification (S)

Register all three fixtures and verify gap resolution at ship.

- [ ] 3.1 Register fixtures in pr-test-plan manifest
  - **File:** `core/sw-reference/pr-test-plan.manifest.json`, `.github/workflows/pr-test-plan-ci.yml`
  - **Expected:** `spec-rigor-brainstorm-profile-required-sections`, `stdlib-coverage-mode-no-behavior-change`, `stdlib-coverage-report-executed-and-unexecuted-lines` registered `required`; workflow regenerated if needed
  - **R-IDs:** R5, R9, R11
- [ ] 3.2 Gap flip verification at ship
  - **File:** `scripts/gap_backlog.py`, `scripts/planning-graph.py`
  - **Expected:** `GAP-076` shows `resolved` after implementation ships; planning-unit `gap-001-spec-rigor-check-sh-lacks-a-brainstorm-artifact-` edge reflects absorption/complete via reconciler
  - **R-IDs:** R1–R11

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |
| 3 | 1, 2 |

## Traceability

| R-ID | Task ref | Named test scenario | ZOMBIES checklist |
|------|----------|---------------------|-------------------|
| R1 | 1.1 | spec-rigor-brainstorm-profile-required-sections | Z, O, I, E |
| R2 | 1.1 | spec-rigor-brainstorm-profile-required-sections | O, B, I, E |
| R3 | 1.1 | spec-rigor-brainstorm-profile-required-sections | O, E, I |
| R4 | 1.2 | spec-rigor-brainstorm-profile-required-sections | O, I, E |
| R5 | 1.3, 3.1 | spec-rigor-brainstorm-profile-required-sections | Z, O, E |
| R6 | 2.1 | stdlib-coverage-report-executed-and-unexecuted-lines | O, I, E |
| R7 | 2.1 | stdlib-coverage-mode-no-behavior-change | O, I, S |
| R8 | 2.2 | stdlib-coverage-report-executed-and-unexecuted-lines | O, M, I |
| R9 | 2.3, 3.1 | stdlib-coverage-mode-no-behavior-change | Z, O, I, E |
| R10 | 2.5 | stdlib-coverage-mode-no-behavior-change | O, I |
| R11 | 2.4, 3.1 | stdlib-coverage-report-executed-and-unexecuted-lines | O, B, I, E |

## Relevant Files

- `scripts/spec-rigor-check.py` — brainstorm artifact profile (Thread A).
- `scripts/test/_runner.py` — coverage mode + report (Thread B).
- `core/commands/sw-brainstorm.md` — blocking Phase 2 gate documentation.
- `skills/brainstorm/references/requirements-sections.md` — required section source of truth.
- `scripts/_sw/depmanifest.json` — must remain `allowed: []`.
- `core/sw-reference/pr-test-plan.manifest.json` — CI fixture registration.

## Notes

- Thread A and Thread B are independent and may run in parallel (phases 1 and 2 have no mutual dependency).
- D5/D6 resolved at doc-review: brainstorm gate is hard-blocking at write; coverdir is gitignored scratch.
- R10 is a scope constraint (no CI threshold) — verified by absence of gate wiring in manifest/CI, not a dedicated fixture.
