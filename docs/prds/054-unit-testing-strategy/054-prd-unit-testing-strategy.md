---
brainstorm: docs/brainstorms/2026-07-02-unit-testing-strategy-requirements.md
date: 2026-07-02
topic: unit-testing-strategy
visibility: public
frozen: true
frozen_at: 2026-07-02
---
# PRD 054 — Unit testing strategy (tiered scopes + pytest layer)

## Overview

Shipwright's test surface has grown to 127 fixture-suite modules and a ~two-minute full `verify` run, yet every deliver
phase and `/sw-verify` invocation still executes the entire sequential bundle. `/sw-verify` promises scoped checks;
`workflow.config.json` does not implement them. PRD 052 unified suite registration but not execution granularity.

This PRD introduces a **hybrid testing model**: pytest (vendored) for fast pure-Python unit tests with fixtures,
parametrization, and negative cases; the existing `run_*_fixtures.py` harness for integration/git/deliver scenarios;
and **tiered scopes** (`fast` / `phase` / `full`) selected from git diffs via registry `pathTriggers`. Deliver phase
verify defaults to `phase` scope; CI keeps parallel PR manifest jobs and adds a consolidated `full` job on `main`/nightly.

Full-tier brainstorm: `docs/brainstorms/2026-07-02-unit-testing-strategy-requirements.md`.

## Goals

1. Cut in-loop verify latency by running only affected suites during phase work while preserving a green full `verify`
   path before merge.
2. Adopt pytest for new pure-logic tests with best-practice patterns (fixtures, parametrization, negative outcomes).
3. Align `/sw-verify`, deliver phase verify, and CI with a documented tier matrix — no fifth unsynchronized suite list.
4. Extend PRD 052 `suite-registry.json` with `pathTriggers`/`tags` as the selection source of truth.

## Non-Goals

- Replacing all fixture suites with pytest (incremental migration only).
- Mandatory coverage percentage CI gates (PRD 051 stdlib `trace` remains informational).
- Changing `checks-gate` required/advisory semantics or auto-merge behavior.
- Parallelizing sequential `_runner.py verify` internally (follow-on efficiency work).
- Amending frozen PRD 016, 042, 051, or 052 in place.

## Requirements

Carried forward from brainstorm R1–R12.

- **R1** Adopt vendored pytest under `scripts/unit_tests/` with fixtures, `@pytest.mark.parametrize`, and explicit
  negative-case tests.
- **R2** New pure-logic `scripts/` tests SHALL prefer pytest over new embedded-bash fixture suites when git/network/
  multi-process orchestration is not required.
- **R3** Existing `run_*_fixtures.py` integration harness remains; pytest does not replace deliver/git/worktree suites
  in this program.
- **R4** `_runner.py` supports `--scope fast|phase|full` and env `SW_TEST_SCOPE`; `full` equals current `verify`.
- **R5** `/sw-verify` defaults to `phase` scope; auto-widens to `full` on global verify infrastructure paths (listed in
  TR2).
- **R6** `wave_failure.run_verify_suite` defaults to `phase`; supports `--scope full` and pre-merge widen hooks.
- **R7** Registry entries gain optional `tags` and `pathTriggers`; `scripts/test_scope.py` maps paths → suites + pytest
  targets.
- **R8** CI keeps parallel `pr-ci` manifest jobs; adds consolidated `_runner.py verify --scope full` on `main` push +
  nightly schedule.
- **R9** Operator docs document the fast/phase/full tier matrix across execute, verify, ship, deliver, and CI.
- **R10** `run_test_scope_fixtures.py` proves selection, widen rules, and advisory missing-tag behavior.
- **R11** Pytest tests follow AGENTS.md mock-realism: patch dependency edges only; no mocking the unit under test.
- **R12** `workflow.config.json` adds `verify.fullTest` for explicit full runs; `verify.test` invokes scoped phase run
  for `/sw-verify`.

## Technical Requirements

### TR1 — Pytest vendoring and layout

- Pin `pytest` in `scripts/_sw/depmanifest.json`; vendor wheel per existing policy.
- Discovery root: `scripts/unit_tests/` only (Phase 1); `pytest.ini` or `pyproject.toml` fragment at repo root
  declaring `testpaths = ["scripts/unit_tests"]`.
- Add `scripts/test/run_pytest_unit.py` wrapper invoked by `_runner.py` for `fast` and `phase` scopes.
- Document pytest practices in `docs/guides/testing.md` (fixtures, parametrization, negative tests, `tmp_path`) with
  references to [pytest docs](https://docs.pytest.org/en/stable/example/index.html).

### TR2 — Scope widen list (fail-closed)

When any changed path matches these globs, force `full` scope regardless of caller default:

- `core/sw-reference/suite-registry.json`
- `core/sw-reference/pr-test-plan.manifest.json`
- `.cursor/workflow.config.json`, `workflow.config.json`
- `scripts/test/_runner.py`, `scripts/test_scope.py`, `scripts/suite_registry.py`
- `.github/workflows/pr-test-plan-ci.yml`, `scripts/generate-pr-test-plan-ci-workflow.py`

### TR3 — `scripts/test_scope.py`

- Input: path list (from `git diff`), optional `--scope` override.
- Output JSON: `{ "scope": "phase", "suites": ["id", ...], "pytest": true, "widenReason": null | "global-infra" }`.
- Match logic: union of registry entries where any `pathTriggers` glob matches any changed path; include transitive
  tag expansion (suites sharing a `tag` with a matched entry) — configurable `tagClosure: true` default on.
- Fallback: if no fixture matches, run pytest for touched `scripts/**/*.py` modules only (`fast` subset).

### TR4 — Registry schema extension

- Extend `core/sw-reference/suite-registry.schema.json` with optional fields:
  - `tags`: string array
  - `pathTriggers`: string array of repo-relative globs
- Update `run_suite_registry_fixtures.py` to validate new fields and assert every `pr-ci`/`verify` suite has at least
  one `pathTrigger` OR explicit `pathTriggers: ["**"]` with documented justification (meta suites).

### TR5 — `_runner.py` scope dispatch

| Scope | Behavior |
|-------|----------|
| `fast` | `run_pytest_unit.py` + skip fixture manifest |
| `phase` | `test_scope.py` → selected suites + pytest for touched modules |
| `full` | Current `run_verify_bundle.py` + manifest (unchanged) |

- `verify` subcommand accepts `--scope`; default `full` for backward-compatible explicit `verify` invocations from
  check-gate; `workflow.config.json` `verify.test` passes `--scope phase`.

### TR6 — Deliver + `/sw-verify` wiring

- `wave_failure.run_verify_suite`: parse `--scope`; default `phase`; pass changed paths from phase worktree to
  `test_scope.py` when scope is `phase`.
- Pre-merge widen: `wave_deliver_loop.py` invokes `verify-run --scope full` before merge enqueue (existing hook point).
- `/sw-verify` command doc: step 4 runs scoped command from config.

### TR7 — CI consolidated job

- New workflow fragment or job in `.github/workflows/ci.yml`: `consolidated-verify-full` running
  `PYTHONPATH=scripts python3 scripts/test/_runner.py verify --scope full` on `push` to `main` and `schedule: nightly`.
- Job is **required** on `main` only; FEAT PRs continue using parallel `pr-test-plan-ci.yml` jobs.

### TR8 — Reference migration exemplar

- Migrate one pure-logic module (recommended: `scripts/test_scope.py` helpers or `scripts/suite_registry.py` pure
  functions) to pytest with ≥3 parametrized cases including ≥1 negative case.

### TR9 — Dist propagation

- `core/` changes propagate via `python3 -m sw generate --all`; register `run_test_scope_fixtures.py` and
  `run_pytest_unit.py` in registry (`verify` lane, `required` for scope fixtures).

## Security & Compliance

- Vendored pytest only; no runtime `pip install`.
- `test_scope.py` accepts path lists from git only — no arbitrary operator path injection in deliver driver.
- No new secrets or network calls in test selection.
- Fail-closed widen prevents silent shrink when registry or runner changes.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `run_test_scope_fixtures.py` | path→suite mapping, widen list, tag closure, missing-tag advisory | R7, R10, TR2, TR3 |
| `run_pytest_unit_fixtures.py` | wrapper invokes pytest, nonzero on failure, discovery limited to `scripts/unit_tests` | R1, TR1 |
| `run_suite_registry_fixtures.py` (extended) | schema accepts `tags`/`pathTriggers`; drift checks pass | TR4 |
| `run_deliver_fixtures.py` (extended) | phase verify uses `phase` scope by default; pre-merge `full` widen | R6, TR6 |
| Reference pytest module | parametrized positive + negative cases for exemplar | R2, R8, TR8 |

## Rollout Plan

1. **Phase 1 — Pytest foundation:** depmanifest, `scripts/unit_tests/`, wrapper, docs, exemplar tests.
2. **Phase 2 — Scope selection:** registry schema, `test_scope.py`, `_runner.py` dispatch, scope fixtures.
3. **Phase 3 — Loop wiring:** `workflow.config.json`, `/sw-verify`, deliver `run_verify_suite` defaults + widen.
4. **Phase 4 — CI + docs:** consolidated full job, `docs/guides/testing.md` tier matrix, registry tag backfill for
   top 20 suites by change frequency (remaining suites default `pathTriggers: ["scripts/test/run_<id>_fixtures.py"]`).

## Decision Log

- **D1 (2026-07-02):** Hybrid pytest + fixture harness (brainstorm D1) — not pytest-only migration.
- **D2 (2026-07-02):** Scoped pytest via `depmanifest.json` exception (brainstorm D2) — orthogonal to PRD 051 trace
  coverage for subprocess suites.
- **D3 (2026-07-02):** Three tiers `fast|phase|full` (brainstorm D3).
- **D4 (2026-07-02):** Registry `pathTriggers` over hardcoded map (brainstorm D4).
- **D5 (2026-07-02):** Keep parallel PR CI; add consolidated `main`/nightly full job (brainstorm D5).
- **D6 (2026-07-02):** Meta/`internal` suites without triggers run only on `full` scope (brainstorm open-question
  resolution).

## Open Questions

None.
