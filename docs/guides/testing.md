# Testing guide

Shipwright uses **pytest** as the sole test runner. Tests live under `scripts/unit_tests/`; discovery is
configured in `pytest.ini` at the repo root.

## Layout

| Path | Role |
|------|------|
| `scripts/unit_tests/` | Test tree (subsystem packages per migration wave) |
| `scripts/unit_tests/conftest.py` | Shared fixtures (`repo_root`, `sw_env`, `tmp_git_repo`) |
| `scripts/test/run_pytest.py` | Unified pytest entry invoked by `_runner.py` and CI shards |
| `scripts/_sw/vendor/` | Vendored pytest and runtime dependencies |
| `core/sw-reference/suite-registry.json` | Authoritative suite lanes, `pytestPath`, and CI shard assignment |
| `core/sw-reference/pr-test-plan.manifest.json` | PR CI job projection (required vs advisory) |

## Tier matrix

| Scope | Invocation | Behavior |
|-------|------------|----------|
| `fast` | `SW_TEST_SCOPE=fast` or `--scope fast` | `pytest -m "not integration"` on `scripts/unit_tests` |
| `phase` | default for deliver phase verify | `test_scope.py` maps git diff → registry `pathTriggers` / markers |
| `full` | pre-merge, `main` push, nightly | entire `scripts/unit_tests` collection + pr-test-plan manifest |

Widen to `full` when changes touch global infra paths (registry, `_runner.py`, `test_scope.py`, CI workflow,
generator, etc.) — see `scripts/test_scope.py` `WIDEN_GLOBS`.

```bash
python3 scripts/test_scope.py --scope phase path/to/changed.py
PYTHONPATH=scripts python3 scripts/test/_runner.py run-pytest --scope phase
PYTHONPATH=scripts python3 scripts/test/_runner.py verify --scope full
```

## Markers

Register markers in `pytest.ini` and apply in tests:

- `@pytest.mark.integration` — multi-component or integration setup
- `@pytest.mark.git` — requires a real git repository fixture
- `@pytest.mark.slow` — excluded from fast scope

## Shared fixtures

- **`repo_root`** — repository root (session scope)
- **`sw_env`** — subprocess environment with `PYTHONPATH`, `SW_REPO_ROOT`, and `ROOT`
- **`tmp_git_repo`** — ephemeral git repo with one commit (replaces legacy harness git patterns)

## Authoring practices (pytest-only)

Follow `AGENTS.md` mock realism: patch dependency edges only; do not mock the unit under test.

### Parametrization

Prefer matrices over copy-pasted cases:

```python
@pytest.mark.parametrize(
("scope", "expected"),
[("fast", 0), ("phase", 0), ("full", 0)],
)
def test_scope_dispatch(scope, expected, repo_root):
...
```

### Negative outcomes

Add one explicit test per public error path:

```python
def test_dependency_gate_rejects_unfrozen(tmp_path):
with pytest.raises(SystemExit) as exc:
run_gate(tmp_path / "tasks.md", frozen=False)
assert exc.value.code == 2
```

### Temporary state

Use `tmp_path` or `tmp_git_repo` — never mutate the developer checkout.

## CI shards

PR jobs run `.github/workflows/pr-test-plan-ci.yml`, generated from
`core/sw-reference/pr-test-plan.manifest.json`:

- **Standalone jobs** — guard scripts that are not pytest packages (`docs-link-check`, bash guards).
- **Pytest shards** — `feat-test-plan-pytest-required-shard-{1..N}` and
`feat-test-plan-pytest-advisory-shard-1` batch registry `pytestPath` targets per shard.
- **Disjoint partition** — `scripts/ci_shard_lib.py` expands manifest directory args to
concrete `test_*.py` files (or preserves `::` node ids) and assigns each target to exactly one
required shard. Manifest order wins on overlap; the duplication factor
(`total assignments / unique files`) must stay `1.0` — no file runs in more than one required shard.
- **Classification** — `required` shards block merge; `advisory` shards use `continue-on-error` (checks-gate
semantics unchanged).

### TR13 — Auto-scaling required shard count

The number of required shards is no longer hardcoded. `scripts/ci_shard_lib.py` exports:

```python
compute_required_shard_count(
total_test_count: int,
target_per_shard: int = TARGET_PER_SHARD, # default: 40
) -> int
```

**Scaling input** — `total_test_count`: the number of collected required pytest test files (or fixture
entries) from the manifest. Callers pass the live count; `assign_shard()` accepts an optional
`shard_count` override for the same purpose.

**Target-wall-clock config knob** — `TARGET_PER_SHARD` (module-level constant, default `40`). This
represents the target number of test files per shard — tune it to hit the desired per-shard wall-clock
budget. Lower values produce more shards (shorter wall-clock); higher values produce fewer.

**Formula** — `max(4, ceil(total_test_count / target_per_shard))`

The result is monotonically non-decreasing as `total_test_count` grows. The floor (`_MIN_REQUIRED_SHARDS = 4`)
is always preserved. The shard count first exceeds `4` when:

```
total_test_count > _MIN_REQUIRED_SHARDS × TARGET_PER_SHARD
> 4 × 40 = 160 (with defaults)
```

The current manifest has fewer than 160 required pytest fixtures, so the shard count remains `4` today.
As the suite grows past 160 fixtures the scheduler will automatically allocate additional shards
without manual config changes.

**Regression** — `scripts/unit_tests/test/test_ci_shard_lib.py` verifies monotonicity, the floor,
boundary at exactly the threshold, and that the live manifest stays at the floor.

Regenerate after manifest edits:

```bash
python3 scripts/generate-pr-test-plan-ci-workflow.py \
core/sw-reference/pr-test-plan.manifest.json \
.github/workflows/pr-test-plan-ci.yml .
```

**Consolidated full verify** — `.github/workflows/ci.yml` `verify-full` on `main` push and nightly schedule runs
`python3 scripts/test/_runner.py verify --scope full`.

### Nightly failure triage-owner notification

The `verify-scheduled-full-plus-integration` scheduled job invokes
`scripts/nightly-failure-notify.py` on failure (`if: failure()`). The helper:

1. Resolves the responsible owner from `core/sw-reference/suite-registry.json`
plan metadata (`plans.scheduled-full-plus-integration.triageOwner`, default
`platform-ops` when unset).
2. Auto-files an authoritative planning-store gap via `planning_gap_capture.capture_gap`
with a stable `nightly-failure:<job>:<run-id>` signal id (deduped against open gaps).

Dry-run locally:

```bash
python3 scripts/nightly-failure-notify.py \
--payload-file /tmp/nightly-failure.json \
--dry-run --no-dedupe
```

Regression: `scripts/unit_tests/test/test_nightly_failure_notify.py`.

## Running tests locally

```bash
# Direct pytest entry
python3 scripts/test/run_pytest.py

# Harness runner with scope dispatch
PYTHONPATH=scripts python3 scripts/test/_runner.py run-pytest --scope phase
```

See [pytest documentation](https://docs.pytest.org/en/stable/example/index.html) for fixtures, parametrization,
and `tmp_path` usage.

## Build-chain freshness

After editing `scripts/`, emittable roots, or `core/`:

```bash
python3 scripts/build-chain-sync.py
```

Check-only (CI / pre-ship):

```bash
python3 scripts/build-chain-sync.py --check
```

Failures emit exact remediation `python3 scripts/build-chain-sync.py`.
`copy-to-core --force` is fixture/CI-only — never use on a real checkout.
Core-only `core/sw-reference/` edits without `.sw/` provenance are refused;
remediate in `.sw/` then re-sync.

Regression: `scripts/unit_tests/git/test_build_chain_hygiene.py`

## Harness isolation + deprecated surfaces ( –)

- `python3 scripts/deprecated_surface_freshness.py --check`
- `python3 scripts/harness_isolation_lint.py --check`
- Verify override gaps: `scripts/unit_tests/planning/test_verify_override_gap.py`
- Closure completeness: `scripts/unit_tests/planning/test_closure_completeness.py`
- Baselines: per-phase/run paths under `.cursor/sw-deliver-runs/<phase>/` — not shared `.shipwright/baseline.*`

## Developer test trees (repo-only)

The `scripts/unit_tests/`, `scripts/tests/`, and `scripts/test/` trees are **repo-only** harness sources. They are excluded from `core/scripts/` and from emitted `dist/*/scripts/` per `core/sw-reference/build-chain-sot.json` — never ship them in plugin install trees.

## Parity compare tier gate

`scripts/test/parity_compare.py` compares `dist/cursor` against `scripts/test/fixtures/parity/cursor-golden.manifest`
using pure Python (`hashlib` + tree walk). The **841-file** golden compare runs only when:

| Trigger | Full dist compare |
|---------|-------------------|
| `verify --scope full` | yes |
| CI / `build-chain-sync --check` | yes |
| `phase` / `fast` with widen-list paths | yes |
| `phase` / `fast` on typical phase diffs | **skipped** |

Widen globs are defined in `scripts/test_scope.py` (`WIDEN_GLOBS`). Post-merge verify defaults to **phase**
scope when the merge-base diff does not match the widen list.

## Verify watchdog

`verify.watchdog.maxMinutes` in `.cursor/workflow.config.json` bounds wall-clock time for the pr-test-plan
manifest loop during full verify. When exceeded, `_runner.py` emits a consolidated halt JSON with
`lastSuiteId` and `resumeCommand`. Per-suite elapsed seconds are logged during manifest execution.


### PR-test-plan manifest `args` forwarding

`scripts/test/_runner.py` `run_manifest` reads `core/sw-reference/pr-test-plan.manifest.json` and
forwards each entry's `args` array into the invoked suite `main()` (via `invoke_suite_main` in
`scripts/test/_runner_lib.py`). Scoped path args on `run_pytest.py` entries collect only the declared
paths — when `args` is present, `run_pytest.py` does **not** default to the full `scripts/unit_tests`
tree.

| Surface | Behavior |
| --- | --- |
| Manifest entry with `args` | argv tokens passed to suite `main(argv)` |
| Zero-arg `main()` suites | Unchanged — `main()` with no parameters still works |
| `verify --scope full` | One pytest collection pass, then manifest fanout honors per-entry `args` |

Regression: `scripts/unit_tests/test/test_runner_manifest_args.py`.

```bash
PYTHONPATH=scripts python3 scripts/test/_runner.py verify --scope full
```

CI shard YAML that already passes pytest path args is unaffected — this contract is for local manifest
execution and deliver verify only.

### Wave A regressions

Focused suite: `scripts/unit_tests/deliver/test_prd067_wave_a_reliability.py` covers ship-lease reclaim, preflight timeout default, materialized currency path, `tasks-debug-*` unit ids, and terminal `SW_PHASE_*` clearing.

Also: `test_finalize_does_not_outer_acquire_living_doc_lock` in `scripts/unit_tests/planning/test_closure_completeness.py` ( nested-acquire).

