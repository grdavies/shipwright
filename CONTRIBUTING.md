# Contributing to Shipwright

Thank you for contributing to [Shipwright](https://github.com/grdavies/shipwright).

**Using the plugin?** See [documentation/](documentation/) for adopters. This file is for plugin development
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
python3 scripts/test/run_emitter_fixtures.py
python3 scripts/test/run_parity_fixtures.py
python3 scripts/test/run_claude_golden_fixtures.py
python3 scripts/test/run_gate_fixtures.py
python3 scripts/test/run_capability_select_fixtures.py
python3 scripts/test/run_capability_lint_fixtures.py
python3 scripts/test/run_migration_parity_fixtures.py
python3 scripts/test/run_kernel_classification_fixtures.py
python3 scripts/test/run_guidelines_floor_fixtures.py
python3 scripts/test/run_plan_validate_fixtures.py
python3 scripts/test/run_plan_persist_fixtures.py
python3 scripts/test/run_plan_killswitch_fixtures.py
python3 scripts/test/run_plan_proposed_parity_fixtures.py
python3 scripts/test/run_pilot_fixtures.py
python3 scripts/test/run_fanout_fixtures.py
python3 scripts/test/run_dispatch_foundation_fixtures.py
python3 scripts/test/run_ux_polish_fixtures.py
```

**PRD 024 fan-out fixtures** (`run_fanout_fixtures.py`): program gate (R35), consistency-only probe (R36),
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
python3 scripts/test/run_emitter_fixtures.py
```

The emitter freshness gate (`emitter-stale-classification-fails`, capability-index parity) fails when
committed `dist/` drifts from `core/`.

Additional domain fixtures (doc, impl, debug, feedback, etc.) live under `scripts/test/` and can be run
individually as needed.

## Code style

- Match existing patterns in the area you are editing.
- Keep user-facing command names under the `sw-` prefix.
- Do not commit secrets, API keys, or raw session transcripts.

## Questions

Open a [discussion](https://github.com/grdavies/shipwright/discussions) or file an issue if something is
unclear before starting large changes.
