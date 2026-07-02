# Testing guide (PRD 054)

Shipwright uses **pytest** as the sole test runner. Tests live under `scripts/unit_tests/`; discovery is
configured in `pytest.ini` at the repo root.

## Layout

| Path | Role |
|------|------|
| `scripts/unit_tests/` | Test tree (subsystem packages added in migration waves) |
| `scripts/unit_tests/conftest.py` | Shared fixtures (`repo_root`, `sw_env`, `tmp_git_repo`) |
| `scripts/test/run_pytest.py` | Unified pytest entry invoked by `_runner.py` |
| `scripts/_sw/vendor/` | Vendored pytest and runtime dependencies |

## Markers

Register markers in `pytest.ini` and apply in tests:

- `@pytest.mark.integration` — multi-component or integration setup
- `@pytest.mark.git` — requires a real git repository fixture
- `@pytest.mark.slow` — excluded from fast scope

## Shared fixtures

- **`repo_root`** — repository root (session scope)
- **`sw_env`** — subprocess environment with `PYTHONPATH`, `SW_REPO_ROOT`, and `ROOT`
- **`tmp_git_repo`** — ephemeral git repo with one commit (replaces legacy `_fixture_lib` git patterns for W1)

## Authoring practices

Follow `AGENTS.md` mock realism: patch dependency edges only; do not mock the unit under test.

- Use `@pytest.mark.parametrize` for matrix scenarios instead of sequential `ok`/`bad` blocks.
- Add explicit negative-outcome tests for each public error path.
- Prefer `tmp_path` / `tmp_git_repo` over mutating the working tree.

## Running tests

```bash
# Direct pytest entry
python3 scripts/test/run_pytest.py

# Via harness runner (skeleton scope dispatch — full scopes in phase 2)
python3 scripts/test/_runner.py run-pytest
```

See [pytest documentation](https://docs.pytest.org/en/stable/example/index.html) for fixtures, parametrization,
and `tmp_path` usage.
