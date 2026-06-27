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
./scripts/install.sh

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
bash scripts/test/run-emitter-fixtures.sh
bash scripts/test/run-parity-fixtures.sh
bash scripts/test/run-claude-golden-fixtures.sh
bash scripts/test/run-gate-fixtures.sh
bash scripts/test/run-capability-select-fixtures.sh
bash scripts/test/run-capability-lint-fixtures.sh
bash scripts/test/run-migration-parity-fixtures.sh
bash scripts/test/run-kernel-classification-fixtures.sh
bash scripts/test/run-guidelines-floor-fixtures.sh
bash scripts/test/run-plan-validate-fixtures.sh
bash scripts/test/run-plan-persist-fixtures.sh
bash scripts/test/run-plan-killswitch-fixtures.sh
bash scripts/test/run-plan-proposed-parity-fixtures.sh
bash scripts/test/run-pilot-fixtures.sh
bash scripts/test/run-ux-polish-fixtures.sh
```

**After editing `core/`** (commands, skills, rules, `kernel-classification.*`, `guidelines.*`, or
`capability` frontmatter), regenerate both dist trees before opening a PR:

```bash
python3 -m sw generate --all
bash scripts/test/run-emitter-fixtures.sh
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
