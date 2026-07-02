---
date: 2026-07-02
topic: unit-testing-strategy
prd: docs/prds/054-unit-testing-strategy/054-prd-unit-testing-strategy.md
amendments: [docs/prds/054-unit-testing-strategy/amendments/A1-full-pytest-migration.md]
visibility: public
frozen: true
frozen_at: 2026-07-02
---

# Tasks — PRD 054 Unit testing strategy (A1 full pytest migration)

Task list from PRD 054 + amendment A1 (R1–R18). Single pytest pattern; legacy `run_*_fixtures.py` harness retired
after migration waves W1–W4.

## Relevant Files

- `scripts/_sw/depmanifest.json` — vendored pytest (+ optional plugins)
- `scripts/unit_tests/` — sole test tree with subsystem packages + conftest chain
- `scripts/test/run_pytest.py`, `scripts/test_scope.py`, `scripts/test/_runner.py`
- `core/sw-reference/suite-registry.json` — `pytestMarker` / `pytestPath` replaces `script`
- `core/sw-reference/pr-test-plan.manifest.json`, `.github/workflows/pr-test-plan-ci.yml`
- `core/scripts/wave_failure.py`, `core/scripts/wave_deliver_loop.py`
- `.cursor/workflow.config.json`, `core/commands/sw-verify.md`
- `docs/guides/testing.md`

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |
| 5 | 4 |
| 6 | 5 |
| 7 | 6 |
| 8 | 7 |

## Tasks

### 1. Pytest foundation + conftest scaffolding (medium)

- [x] 1.1 Pin/vendor pytest in depmanifest (R1, TR10)
  - **File:** `scripts/_sw/depmanifest.json`, `scripts/_sw/vendor/`
  - **Expected:** pytest importable; zero-shell-guard passes
  - **R-IDs:** R1, TR10
- [ ] 1.2 Pytest config + markers policy (R1, R17, TR10)
  - **File:** `pytest.ini` or `pyproject.toml`, `scripts/unit_tests/conftest.py`
  - **Expected:** markers `integration`, `git`, `slow` registered; `testpaths` = `scripts/unit_tests`
  - **R-IDs:** R1, R17, TR10
- [ ] 1.3 Shared fixtures: tmp_git_repo, env, repo_root (R15, TR10)
  - **File:** `scripts/unit_tests/conftest.py`
  - **Expected:** replaces `_fixture_lib` patterns for W1; documented in testing.md
  - **R-IDs:** R15, TR10
- [ ] 1.4 Unified `run_pytest.py` entry + `_runner.py` stub (R17, TR10)
  - **File:** `scripts/test/run_pytest.py`, `scripts/test/_runner.py` (skeleton scope dispatch)
  - **Expected:** `pytest` collection runs green on empty/minimal tree
  - **R-IDs:** R17, TR10

### 2. Scope selection infrastructure (medium)

- [x] 2.1 Registry schema: pytestMarker/pytestPath + pathTriggers (R7, TR12)
  - **File:** `core/sw-reference/suite-registry.schema.json`, `suite-registry.json`
  - **Expected:** schema validates; dual `script` field deprecated with migration shim
  - **R-IDs:** R7, TR12
- [x] 2.2 Implement `scripts/test_scope.py` for pytest collection (R7, parent TR3)
  - **File:** `scripts/test_scope.py`
  - **Expected:** JSON plan → pytest args; widen list; marker closure
  - **R-IDs:** R5, R7
- [x] 2.3 Wire `_runner.py` scopes fast|phase|full to pytest (R4, R17)
  - **File:** `scripts/test/_runner.py`
  - **Expected:** full scope runs entire collection; phase narrows; fast skips integration marker
  - **R-IDs:** R4, R17
- [x] 2.4 `run_test_scope_fixtures.py` (R10)
  - **File:** `scripts/test/run_test_scope_fixtures.py` → port to `scripts/unit_tests/scope/`
  - **Expected:** selection + widen tests pass under pytest
  - **R-IDs:** R10

### 3. Migration wave W1 — pure-logic suites (~30) (large)

- [x] 3.1 Port W1 suite list to pytest modules (R13, R15, R16, TR11)
  - **File:** `scripts/unit_tests/doc/`, `scripts/unit_tests/model_tier/`, etc.
  - **Expected:** parametrized + negative cases; legacy W1 `run_*_fixtures.py` still present (shadow)
  - **R-IDs:** R13, R15, R16, TR11
- [ ] 3.2 `run_migration_parity_fixtures.py` for W1 shadow (TR14)
  - **File:** `scripts/test/run_migration_parity_fixtures.py` (temporary)
  - **Expected:** legacy vs pytest parity green for W1 inventory
  - **R-IDs:** TR14
- [ ] 3.3 Delete W1 legacy scripts + update registry (R14, TR12)
  - **File:** remove ported `run_*_fixtures.py`; update `suite-registry.json`, manifest, workflow regen
  - **Expected:** no W1 legacy files on disk; CI jobs point at pytest shards/markers
  - **R-IDs:** R14, TR12

### 4. Migration wave W2 — single-repo git suites (~40) (large)

- [x] 4.1 Port W2 suites with `tmp_git_repo` fixtures (R13, R15, R16, TR11)
  - **File:** `scripts/unit_tests/git/`, `scripts/unit_tests/workflow/`
  - **Expected:** git init/commit/branch scenarios under pytest; negative paths covered
  - **R-IDs:** R13, R15, R16, TR11
- [ ] 4.2 W2 parity shadow + delete legacy (R14, TR14)
  - **File:** W2 `run_*_fixtures.py` removals; registry/manifest update
  - **Expected:** parity green; legacy deleted
  - **R-IDs:** R14, TR14

### 5. Migration wave W3 — deliver / multi-worktree suites (~35) (large)

- [ ] 5.1 Port W3 deliver/wave/concurrency suites (R13, R15, R16, TR11)
  - **File:** `scripts/unit_tests/deliver/`, `scripts/unit_tests/hooks/`
  - **Expected:** multi-repo/worktree fixtures; SW_DELIVER_VERIFY ephemeral patterns preserved
  - **R-IDs:** R13, R15, R16, TR11
- [ ] 5.2 W3 parity shadow + delete legacy (R14, TR14)
  - **File:** W3 legacy removals; extend `run_deliver_fixtures` coverage under pytest
  - **Expected:** deliver phase verify scenarios pass under pytest collection
  - **R-IDs:** R14, TR14

### 6. Migration wave W4 — meta / registry / parity (~22) (medium)

- [ ] 6.1 Port W4 meta suites (suite-registry, pr-test-plan, emitter, golden) (R13, TR11)
  - **File:** `scripts/unit_tests/meta/`
  - **Expected:** registry drift checks run under pytest
  - **R-IDs:** R13, TR11
- [ ] 6.2 Final parity + delete `run_migration_parity_fixtures.py` (R14, TR18, TR14)
  - **File:** remove all remaining `run_*_fixtures.py`; delete parity runner
  - **Expected:** zero `run_*_fixtures.py` on disk; `run_suite_registry_fixtures` asserts no legacy scripts
  - **R-IDs:** R14, R18, TR12

### 7. Harness teardown + loop wiring (medium)

- [ ] 7.1 Delete legacy harness (`_fixture_lib`, `_harness_patch`, `run_verify_bundle.py`) (R18)
  - **File:** `scripts/test/_fixture_lib.py`, `scripts/test/run_verify_bundle.py`, bash `.test` shims
  - **Expected:** grep finds no consumers; full pytest collection is sole verify path
  - **R-IDs:** R18
- [ ] 7.2 workflow.config + deliver verify scope defaults (R6, R12, parent TR6)
  - **File:** `.cursor/workflow.config.json`, `core/scripts/wave_failure.py`, `wave_deliver_loop.py`
  - **Expected:** phase scope default; pre-merge full widen
  - **R-IDs:** R6, R12
- [ ] 7.3 `/sw-verify` doc + dist propagation (R5, R9, TR9)
  - **File:** `core/commands/sw-verify.md`, `python3 -m sw generate --all`
  - **Expected:** docs match scoped pytest invocation
  - **R-IDs:** R5, R9

### 8. CI shards + operator docs (small)

- [ ] 8.1 CI: pytest shards or marker groups preserving required/advisory (R8, TR13)
  - **File:** `.github/workflows/pr-test-plan-ci.yml`, `ci.yml`
  - **Expected:** classifications preserved; optional consolidated full job on main/nightly
  - **R-IDs:** R8, TR13
- [ ] 8.2 `docs/guides/testing.md` — single-pattern guide (R9, R11)
  - **File:** `docs/guides/testing.md`
  - **Expected:** pytest-only authoring; tier matrix; fixtures/parametrize/negative patterns
  - **R-IDs:** R9, R11
- [ ] 8.3 INDEX amendment link + close program (R9)
  - **File:** `docs/prds/INDEX.md`
  - **Expected:** row 054 lists A1 amendment
  - **R-IDs:** R9

## Traceability

| R-ID | Task refs | Test scenario | ZOMBIES |
|------|-----------|---------------|---------|
| R1 | 1.1, 1.2 | pytest collects | Zero — vendored deps |
| R4 | 2.3 | scope narrows collection | Boundary — bad scope |
| R5 | 2.2, 7.3 | widen to full | Obvious — infra path |
| R6 | 7.2 | deliver phase scope | Meandering — pre-merge full |
| R7 | 2.1, 2.2 | pathTriggers → markers | Zero — empty diff |
| R8 | 8.1 | CI shards green | Interface — workflow |
| R9 | 7.3, 8.2, 8.3 | testing.md | Simple — doc review |
| R10 | 2.4 | scope tests | Boundary — missing tags |
| R11 | 8.2 | mock-realism doc | Interface — edge patches |
| R12 | 7.2 | verify.test scoped | Obvious — config |
| R13 | 3.1, 4.1, 5.1, 6.1 | all suites ported | Interface — parity |
| R14 | 3.3, 4.2, 5.2, 6.2 | no legacy scripts | Obvious — glob empty |
| R15 | 1.3, 3.1 | conftest fixtures | Simple — tmp git |
| R16 | 3.1+ | negative parametrized | Boundary — error paths |
| R17 | 1.4, 2.3 | pytest sole runner | Zero — no bash runner |
| R18 | 6.2, 7.1 | harness deleted | Interface — import fail |
