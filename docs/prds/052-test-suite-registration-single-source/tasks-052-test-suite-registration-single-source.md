---
date: 2026-07-01
topic: test-suite-registration-single-source
prd: docs/prds/052-test-suite-registration-single-source/052-prd-test-suite-registration-single-source.md
frozen: true
frozen_at: 2026-07-01
---
frozen: true
frozen_at: 2026-07-01

# Tasks — PRD 052 Test-suite registration single-source

Single-pass task list from PRD 052 (R1–R8). Closes `GAP-075` by introducing `suite-registry.json` and
deriving verify/manifest/workflow consumer lists with fail-closed drift fixtures.

## Relevant Files

- `core/sw-reference/suite-registry.json`, `core/sw-reference/suite-registry.schema.json` — authoritative classification
- `scripts/suite_registry.py` — discovery + lane projection helpers
- `scripts/test/run_verify_bundle.py` — verify bundle (derive suites from registry)
- `core/sw-reference/pr-test-plan.manifest.json`, `.github/workflows/pr-test-plan-ci.yml` — PR CI surface
- `scripts/generate-pr-test-plan-ci-workflow.py`, `scripts/test/run_pr_test_plan_fixtures.py` — generator + drift
- `scripts/test/run_suite_registry_fixtures.py` — new parity fixture (R5)
- `docs/guides/configuration.md`, `CONTRIBUTING.md` — operator docs + drift guard
- `docs/prds/GAP-BACKLOG.md` — `GAP-075` → `resolved` on ship

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |

## Tasks

### 1. Suite registry schema + full classification (medium)

Land the registry with every on-disk `run_*_fixtures.py` classified; helper module for lane projection.

- [ ] 1.1 Add `suite-registry.schema.json` and initial `suite-registry.json` (R1, TR1)
  - **File:** `core/sw-reference/suite-registry.schema.json`, `core/sw-reference/suite-registry.json`
  - **Expected:** every `scripts/test/run_*_fixtures.py` has exactly one entry; lanes subset of pr-ci, verify, ci-yml, doc, internal; six GAP-075 orphans classified with at least verify lane
  - **R-IDs:** R1, R3
- [ ] 1.2 Implement `scripts/suite_registry.py` projection helpers (R1, TR2)
  - **File:** `scripts/suite_registry.py`
  - **Expected:** discover_suites, load_registry, verify_bundle_entries, manifest_entries, pr_ci_entries; reuses `_runner.discover_suites` for discovery
  - **R-IDs:** R1, R2, TR2
- [ ] 1.3 Add `run_suite_registry_fixtures.py` skeleton (R5)
  - **File:** `scripts/test/run_suite_registry_fixtures.py`
  - **Expected:** asserts disk-registry bijection; manifest pr-ci subset of registry; workflow matches generator; verify order matches registry
  - **R-IDs:** R5

### 2. Verify bundle derivation + orphan wiring (medium)

Remove hand-maintained SUITES; wire six orphans into verify lane.

- [ ] 2.1 Derive verify bundle from registry (R2, TR3)
  - **File:** `scripts/test/run_verify_bundle.py`
  - **Expected:** hardcoded SUITES removed; loads suite_registry.verify_bundle_entries(root) in stable order; verify.test green after registry populated
  - **R-IDs:** R2, TR3
- [ ] 2.2 Register six orphans in verify lane with classifications (R3)
  - **File:** `core/sw-reference/suite-registry.json`
  - **Expected:** build_chain_sot, hook, guardrail_matrix required; capability, fanout, relocation advisory; all six execute under verify bundle
  - **R-IDs:** R3
- [ ] 2.3 Extend suite-registry fixture for verify lane parity (R5)
  - **File:** `scripts/test/run_suite_registry_fixtures.py`
  - **Expected:** verify bundle module list matches registry verify lane projection
  - **R-IDs:** R5

### 3. PR test-plan CI alignment + generator fix (medium)

Validate manifest against registry; fix workflow generator drift check; regen CI workflow.

- [ ] 3.1 Assert manifest matches registry pr-ci projection (R4, TR4)
  - **File:** `scripts/test/run_suite_registry_fixtures.py`, `core/sw-reference/suite-registry.json`
  - **Expected:** fail-closed if manifest entries diverge from registry pr-ci rows
  - **R-IDs:** R4, TR4
- [ ] 3.2 Fix run_pr_test_plan_fixtures.py generator invocation (R6)
  - **File:** `scripts/test/run_pr_test_plan_fixtures.py`
  - **Expected:** calls generate-pr-test-plan-ci-workflow.py three-arg CLI instead of missing .sh shim
  - **R-IDs:** R6
- [ ] 3.3 Register suite-registry-fixtures in pr-test-plan manifest + regen workflow (R4, TR5, TR6)
  - **File:** `core/sw-reference/pr-test-plan.manifest.json`, `.github/workflows/pr-test-plan-ci.yml`
  - **Expected:** required manifest entry for run_suite_registry_fixtures.py; workflow regen; CI job feat-test-plan-suite-registry-fixtures
  - **R-IDs:** R4, R5, TR5, TR6

### 4. Docs, CONTRIBUTING drift guard, GAP close (small)

Document derivation chain; resolve GAP-075 on ship.

- [ ] 4.1 Update configuration guide PR test-plan section (R8, TR7)
  - **File:** `docs/guides/configuration.md`
  - **Expected:** documents suite-registry.json lanes, manifest-workflow regen command with full args, verify derivation
  - **R-IDs:** R8, TR7
- [ ] 4.2 CONTRIBUTING drift guard for doc lane (R7)
  - **File:** `CONTRIBUTING.md`, `scripts/test/run_suite_registry_fixtures.py`
  - **Expected:** fixture asserts CONTRIBUTING-mentioned suites match registry doc lane
  - **R-IDs:** R7
- [ ] 4.3 Flip GAP-075 to resolved in GAP-BACKLOG (Rollout)
  - **File:** `docs/prds/GAP-BACKLOG.md`
  - **Expected:** row status resolved; schedule em-dash; notes reference PRD 052 ship PR
  - **R-IDs:** R1

## Traceability

| R-ID | Task refs | Fixture |
|------|-----------|---------|
| R1 | 1.1, 1.2 | run_suite_registry_fixtures.py |
| R2 | 2.1 | run_suite_registry_fixtures.py |
| R3 | 1.1, 2.2 | six orphan suites under verify |
| R4 | 3.1, 3.3 | run_suite_registry_fixtures.py, run_pr_test_plan_fixtures.py |
| R5 | 1.3, 2.3, 3.3 | run_suite_registry_fixtures.py |
| R6 | 3.2 | run_pr_test_plan_fixtures.py |
| R7 | 4.2 | run_suite_registry_fixtures.py |
| R8 | 4.1 | manual doc review |
