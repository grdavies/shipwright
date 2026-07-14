# Contributing to Shipwright

Thank you for contributing to [Shipwright](https://github.com/grdavies/shipwright).

**Using the plugin?** See [docs/guides/](docs/guides/getting-started.md) for adopters ([getting started](docs/guides/getting-started.md)). This file is for plugin development
only. Internal planning artifacts (brainstorms, PRDs) live in gitignored `docs/`; they are not user
documentation.

## Development setup

Authoring lives under `core/`; installable plugin trees are **generated** and committed under `dist/`.

```bash
# After editing core/, regenerate install trees
python3 -m sw generate --all

# Install to local Cursor plugin directory (default: ~/.cursor/plugins/local/shipwright)
python3 scripts/install.py

# Or do both in one step
python3 -m sw generate --all --install
```

Then run **Developer: Reload Window** in Cursor.

For Claude Code, point your plugin path at `dist/claude-code/` (or copy it to your Claude plugins directory).

## Pull requests

This repo uses **squash merge**. The PR **title** becomes the squash commit subject, so it must follow
[Conventional Commits](https://www.conventionalcommits.org/):

| Change type | Example PR title |
|-------------|------------------|
| Feature | `feat: add sw-watch-ci timeout flag` |
| Fix | `fix: guard empty recallium project slug` |
| Breaking change | `feat!: rename command prefix to sw-` |

Use the `!` form (e.g. `feat!:`) for breaking changes — the exclamation survives squash merge and signals
release-please to bump the major version.

PR bodies should note whether `dist/` was regenerated when `core/` changed.

## Running tests locally

Run the fixture suites before opening a PR:

```bash
python3 scripts/test/run_pytest.py scripts/unit_tests/meta -q
python3 scripts/test/run_pytest.py scripts/unit_tests/w4 -q
python3 scripts/test/run_pytest.py scripts/unit_tests/capability -q
python3 scripts/test/run_pytest.py scripts/unit_tests/dispatch -q
python3 scripts/test/run_pytest.py scripts/unit_tests/model_tier -q
python3 scripts/test/run_pytest.py scripts/unit_tests/guidelines -q
python3 scripts/test/run_pytest.py scripts/unit_tests/planning -q
python3 scripts/test/run_pytest.py scripts/unit_tests/git -q
```

**PRD 024 fan-out fixtures** (pytest: `scripts/unit_tests/dispatch`): program gate (R35), consistency-only probe (R36),
per-orchestrator canonical parity, debug/doc/feedback halts, R21 surfacing, budget trip, 022-parity subset.

**A2 dispatch binding** (`run_dispatch_foundation_fixtures.py`, R38/R39):

| Fixture | R-ID |
| --- | --- |
| `dispatch-preflight-parallel-n-personas` | R38 |
| `dispatch-preflight-ambiguous-agent-fail-closed` | R38 |
| `dispatch-command-tier-inherits-routing` | R39 |
| `dispatch-command-tier-sw-tasks` | R39 |
| `dispatch-agent-explicit-override-wins` | R39b |
| `dispatch-preflight-command-model-parity` | R39 |
| `doc-review-parallel-panel-binding` (in fanout suite) | R38, R39 |
```

**After editing `core/`** (commands, skills, rules, `kernel-classification.*`, `guidelines.*`, or
`capability` frontmatter), regenerate both dist trees before opening a PR:

```bash
python3 -m sw generate --all
python3 scripts/test/run_pytest.py scripts/unit_tests/meta -q
```

The emitter freshness gate (`emitter-stale-classification-fails`, capability-index parity) fails when
committed `dist/` drifts from `core/`.

Additional domain suites live under `scripts/unit_tests/` and are run via `scripts/test/run_pytest.py`.

## Code style

- Match existing patterns in the area you are editing.
- Keep user-facing command names under the `sw-` prefix.
- Do not commit secrets, API keys, or raw session transcripts.

## Questions

Open a [discussion](https://github.com/grdavies/shipwright/discussions) or file an issue if something is
unclear before starting large changes.
