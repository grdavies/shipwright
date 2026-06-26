---
date: 2026-06-26
topic: pr-test-plan-ci-enforcement
prd: docs/prds/016-pr-test-plan-ci-enforcement/016-prd-pr-test-plan-ci-enforcement.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 016 PR test-plan CI enforcement

Generated from the frozen PRD `016-prd-pr-test-plan-ci-enforcement.md` (effective union R1–R7). Phases are
dependency-ordered: single-source the set first, then CI jobs + PR template, then stabilize/gate integration,
then docs/dist/fixtures.

## Tasks

### 1. Single-sourced test-plan set + classification (S/M)

- [ ] 1.1 Define the standard FEAT test-plan manifest (R1, R3)
  - **File:** `.cursor/workflow.config.json` (`verify.test`), `scripts/test/` (manifest)
  - **Expected:** the recurring fixture set is defined once and consumed by both local `verify.test` and the CI workflow generator; no drift
- [ ] 1.2 Classify each fixture required vs advisory (R2)
  - **File:** test-plan manifest, `rules/checks-gate.mdc`
  - **Expected:** every set member carries a required/advisory flag consistent with the `checks-gate` all-checks policy

### 2. CI workflow jobs + PR template (M)

- [ ] 2.1 Generate CI jobs for each set member (R1, R2)
  - **File:** `.github/workflows/*.yml` (or emitter source under `core/`)
  - **Expected:** each fixture runs as a named job on `pull_request`; required jobs gate merge, advisory jobs report only
- [ ] 2.2 PR template references CI job names (R4)
  - **File:** `.github/pull_request_template.md`
  - **Expected:** template points at CI job names as the gate; any human note is advisory, not the enforcement path

### 3. Stabilize / gate integration (S/M)

- [ ] 3.1 `check-gate.sh` enumerates promoted jobs; stabilize consumes logs (R5, R6)
  - **File:** `scripts/check-gate.sh`, `skills/stabilize-loop/SKILL.md`, `skills/checks-gate/SKILL.md`
  - **Expected:** `/sw-stabilize` remediates from the promoted job logs via the existing path; `checks-gate` verdict covers them under all-checks policy

### 4. Docs, dist, fixtures (S/M)

- [ ] 4.1 Fixture suite for enforcement behaviors (R7)
  - **File:** `scripts/test/run-pr-test-plan-fixtures.sh`, `.cursor/workflow.config.json`
  - **Expected:** fixtures named in the PRD Testing Strategy exist and pass; suite registered in `verify.test`
- [ ] 4.2 Documentation updates (R7)
  - **File:** `skills/checks-gate/SKILL.md`, `rules/checks-gate.mdc`, `docs/guides/` (CI/contributing guide)
  - **Expected:** enforcement model documented; presence asserted by a fixture
- [ ] 4.3 Emitter propagation + freshness gate (R7)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `dist/` regenerated; `scripts/test/run-emitter-fixtures.sh` passes

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 1, 2, 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1, 2.1 | pr-test-plan-set-single-source / pr-test-plan-jobs-on-pr |
| R2 | 1.2, 2.1 | pr-test-plan-blocking-classification |
| R3 | 1.1 | pr-test-plan-set-single-source |
| R4 | 2.2 | pr-template-references-jobs |
| R5 | 3.1 | pr-test-plan-stabilize-consumes |
| R6 | 3.1 | pr-test-plan-checks-gate-verdict |
| R7 | 4.1, 4.2, 4.3 | pr-test-plan-emitter-freshness / pr-test-plan-docs-presence |
