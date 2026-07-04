# Testing guide (PRD 054)

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

Add one explicit test per public error path (PRD 054 R16):

```python
def test_dependency_gate_rejects_unfrozen(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run_gate(tmp_path / "tasks.md", frozen=False)
    assert exc.value.code == 2
```

### Temporary state

Use `tmp_path` or `tmp_git_repo` — never mutate the developer checkout.

## CI shards (PRD 054 TR13)

PR jobs run `.github/workflows/pr-test-plan-ci.yml`, generated from
`core/sw-reference/pr-test-plan.manifest.json`:

- **Standalone jobs** — guard scripts that are not pytest packages (`docs-link-check`, bash guards).
- **Pytest shards** — `feat-test-plan-pytest-required-shard-{1..4}` and
  `feat-test-plan-pytest-advisory-shard-1` batch registry `pytestPath` targets per shard.
- **Classification** — `required` shards block merge; `advisory` shards use `continue-on-error` (checks-gate
  semantics unchanged).

Regenerate after manifest edits:

```bash
python3 scripts/generate-pr-test-plan-ci-workflow.py \
  core/sw-reference/pr-test-plan.manifest.json \
  .github/workflows/pr-test-plan-ci.yml .
```

**Consolidated full verify** — `.github/workflows/ci.yml` `verify-full` on `main` push and nightly schedule runs
`python3 scripts/test/_runner.py verify --scope full`.

## Running tests locally

```bash
# Direct pytest entry
python3 scripts/test/run_pytest.py

# Harness runner with scope dispatch
PYTHONPATH=scripts python3 scripts/test/_runner.py run-pytest --scope phase
```

See [pytest documentation](https://docs.pytest.org/en/stable/example/index.html) for fixtures, parametrization,
and `tmp_path` usage.
## Developer test trees (repo-only)

The `scripts/unit_tests/`, `scripts/tests/`, and `scripts/test/` trees are **repo-only** harness sources. They are excluded from `core/scripts/` and from emitted `dist/*/scripts/` per `core/sw-reference/build-chain-sot.json` — never ship them in plugin install trees.

