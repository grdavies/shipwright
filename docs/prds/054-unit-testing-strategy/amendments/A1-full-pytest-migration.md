---
date: 2026-07-02
amends: docs/prds/054-unit-testing-strategy/054-prd-unit-testing-strategy.md
signal: operator-full-pytest-migration-2026-07-02
visibility: public
frozen: true
frozen_at: 2026-07-02
supersedes: [R2, R3, TR8]
retracts: []
---

# Amendment A1: Full pytest migration (single test pattern)

## Overview

Operator decision (2026-07-02): replace the parent PRD's **hybrid** model (pytest layer + retained
`run_*_fixtures.py` harness) with a **single pytest-based test system**. All ~127 legacy fixture-suite modules
SHALL be ported to pytest and removed; `_fixture_lib`, embedded-bash `_SOURCE` harnesses, and per-suite
`main()` orchestrators are retired when migration completes. Tiered scopes (`fast` / `phase` / `full`) and
registry-driven selection from the parent PRD remain — only the execution substrate changes.

Parent goals 1, 3, 4 and R1, R4–R12 stand unless superseded below.

## Goals

1. **Single test pattern** — pytest is the only authoring and execution model; legacy `run_*_fixtures.py` removed.
2. **Behavioral parity** — every ported suite matches legacy assertions (shadow parity per wave until legacy deleted).
3. **Preserve scoped verify** — parent tiered `fast` / `phase` / `full` scopes map to pytest markers/collection.
4. **Preserve CI gate semantics** — required/advisory classifications unchanged unless explicitly reclassified later.

## Context

**Parent hybrid rationale (superseded):** incremental migration reduced blast radius while shipping scoped
verify quickly.

**Operator rationale:** maintaining two authoring models (pytest + bash-embedded fixture suites) indefinitely
costs more than a one-time port; a single pattern simplifies onboarding, scope selection, and CI alignment.

**Validated constraints (unchanged):**

- Git/worktree/deliver integration tests remain **realistic** — pytest `tmp_path` fixtures spin ephemeral
  repos; AGENTS.md mock-realism still applies (patch edges, not unit under test).
- PRD 052 `suite-registry.json` remains authoritative; entries map to pytest markers/modules instead of
  `run_*_fixtures.py` scripts.
- `checks-gate` required/advisory classifications per manifest entry are preserved (parent Non-Goal).

## Requirements

Carried forward from parent unless superseded. New and amended requirements:

- **R13** All existing `scripts/test/run_*_fixtures.py` suites SHALL be ported to pytest modules under
  `scripts/unit_tests/` (organized by subsystem: `deliver/`, `git/`, `doc/`, `planning/`, etc.) with
  behavioral parity proven by porting fixtures or dual-run shadow period per wave.
- **R14** Upon port completion for a suite, the legacy `run_*_fixtures.py` file SHALL be deleted and
  `suite-registry.json` + `pr-test-plan.manifest.json` SHALL reference the pytest marker or module path
  instead — no dual registration.
- **R15** Shared pytest fixtures SHALL replace `_fixture_lib.FixtureContext` and embedded bash `_SOURCE`:
  - `conftest.py` at `scripts/unit_tests/` root for `repo_root`, `tmp_git_repo`, `fixture_context` env
  - Submodule `conftest.py` files for deliver/worktree-heavy trees
  - Parametrized scenarios for matricies currently duplicated as sequential `ok`/`bad` blocks
- **R16** Negative-outcome tests SHALL be first-class in every ported module: at least one parametrized or
  dedicated test per public error path that the legacy suite asserted.
- **R17** `_runner.py` SHALL invoke pytest as the sole test runner for all scopes:
  - `fast` — `pytest -m "not integration"` (or equivalent marker policy)
  - `phase` — `test_scope.py` → `pytest` collection narrowed to selected markers/paths
  - `full` — full pytest collection equivalent to today's verify + manifest coverage
- **R18** Legacy harness deletion SHALL include: `scripts/test/_fixture_lib.py` (after port),
  `scripts/test/_harness_patch.py`, `run_verify_bundle.py` sequential suite loader (replaced by pytest
  collection or thin marker runner), and bash `.test` shims where ported.

## Technical Requirements (amendment)

### TR10 — Pytest layout (replaces TR1 discovery-only scope)

- `scripts/unit_tests/` is the **sole** test tree; discovery via `pytest.ini` / `pyproject.toml`.
- Vendored: `pytest` + minimal plugins if required (`pytest-subtests` only if justified in Decision Log).
- Markers: `@pytest.mark.integration`, `@pytest.mark.git`, `@pytest.mark.slow` for scope selection.
- `scripts/test/run_pytest.py` — unified entry invoked by `_runner.py` (replaces `run_pytest_unit.py`).

### TR11 — Migration waves (ordered)

| Wave | Suites (approx) | Focus |
|------|-----------------|--------|
| W1 | Pure-logic / no git (~30) | doc-format, spec-rigor, model-tier, capability-lint class |
| W2 | Single-repo git (~40) | git-workflow, branch guards, commit-msg |
| W3 | Multi-worktree / deliver (~35) | deliver, wave, concurrency, hook |
| W4 | Meta / parity / registry (~22) | suite-registry, pr-test-plan, emitter, golden parity |

Each wave: port → green full pytest → delete legacy files → update registry → regen CI workflow.

### TR12 — Registry schema (extends parent TR4)

- Replace `script: scripts/test/run_*_fixtures.py` with `pytestMarker` or `pytestPath` on registry entries.
- `pathTriggers` map to `scripts/**/*.py` and `scripts/unit_tests/**` globs.
- `run_suite_registry_fixtures.py` extended: no on-disk `run_*_fixtures.py` without registry pytest mapping.

### TR13 — CI alignment

- Parallel `pr-test-plan-ci.yml` jobs MAY collapse to marker-based shards (e.g. 4 pytest shards) **only if**
  wall-clock does not regress >20% vs current parallel manifest; required/advisory classification preserved
  per shard or per marker group — not a checks-gate semantic change.
- Consolidated `full` job runs `pytest` full collection (parent TR7).

### TR14 — Shadow parity (fail-closed per wave)

During each wave, a temporary `run_migration_parity_fixtures.py` (deleted in W4) MAY dual-invoke legacy +
pytest for that wave's suites; exit non-zero on divergence. Removed before program close.

## Superseded parent text

| Parent | Effect |
|--------|--------|
| **R2** (prefer pytest for new only) | **Superseded** — all suites port to pytest |
| **R3** (retain fixture harness) | **Superseded** — harness retired after W4 |
| **TR8** (single exemplar) | **Superseded** — W1 delivers first full subsystem port as exemplar |
| **Non-Goal** "incremental migration only" | **Withdrawn** |
| Overview "hybrid testing model" | Read as "pytest-only testing model" via this amendment |

## Non-Goals

- Changing `checks-gate` required/advisory semantics or auto-merge (unchanged from parent).
- Dropping integration realism — git/worktree tests port to pytest fixtures, not deleted.
- Mandatory coverage percentage gates (PRD 051 informational trace remains).
- Incremental hybrid coexistence of legacy harness and pytest (withdrawn — full port per D7).

## Testing Strategy

| Artifact | Asserts |
|----------|---------|
| `run_migration_parity_fixtures.py` (W1–W3 only) | legacy vs pytest parity per wave |
| `run_test_scope_fixtures.py` | marker/path selection, widen rules |
| `run_suite_registry_fixtures.py` | no legacy scripts; pytest mapping complete |
| Ported modules | parametrized + negative per R16 |

## Rollout Plan (replaces parent 4-phase plan)

1. **W0 — Foundation:** depmanifest, pytest config, conftest scaffolding, `run_pytest.py`, scope wiring.
2. **W1–W4 — Migration waves** per TR11 (parallel deliver phases allowed within wave boundaries).
3. **W5 — Harness teardown:** delete `_fixture_lib`, `run_verify_bundle.py`, remaining `run_*_fixtures.py`.
4. **W6 — CI + docs:** shard strategy, consolidated full job, `docs/guides/testing.md`.

## Decision Log

- **D7 (2026-07-02):** Operator chose full migration over hybrid (this amendment).
- **D8 (2026-07-02):** Wave-ordered port with temporary parity shadow — avoids big-bang without permanent
  dual maintenance.
- **D9 (2026-07-02):** CI shard collapse is optional and gated on wall-clock — preserves checks-gate job
  semantics unless explicitly reclassified in a future PRD.

## Open Questions

None.
