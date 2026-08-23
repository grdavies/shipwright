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

### Scripts↔dist freshness and ship auto-regen (PRD 274)

Packaged helpers under `scripts/` are mirrored into committed `dist/` zipapps. Editing `scripts/` without
regenerating `dist/` leaves CI emitter-freshness red until `dist/` is updated.

**Side-effect-free drift check** (local pre-push; does not mutate `dist/`):

```bash
python3 scripts/dist_freshness.py detect
# machine-readable: python3 scripts/dist_freshness.py json
```

On drift, stderr includes the canonical regen command: `python3 -m sw generate --all`.

**Ship path** (before `sw-commit` when scripts↔dist drift is present) — fail closed with that regen
command; when auto-fixable, regenerate and stage only this invocation's outputs:

```bash
python3 scripts/dist_freshness_ship.py regen
```

Refuses overlapping preexisting operator edits under `dist/` (`overlapping-preexisting`) and residual drift
after regen (`residual-drift`). See `skills/ship/SKILL.md` (D3).

**Operator-local deliver closeout** — closure manifests write to `.sw/deliver-closeout/` (gitignored).
`core_content_sync` denylists and purges that tree from `core/sw-reference/`; never commit closeout mirrors.

**Build-chain parity before commit** — when the phase diff touches paths in
`core/sw-reference/build-chain-paths.json`, `/sw-ship` runs `python3 scripts/ship-build-chain-check.py`
(hard block). Remediate with `python3 scripts/build-chain-sync.py` (not `copy-to-core --force`).

Additional domain suites live under `scripts/unit_tests/` and are run via `scripts/test/run_pytest.py`.

## CI topology (named plans — PRD 082 R35)

Pull-request and main CI dispatch **named plans** from `core/sw-reference/suite-registry.json`
(`plans` block) — workflows are generated (`scripts/ci_plan_gen.py`) rather than hand-edited job lists.

| Plan | When | What runs |
| --- | --- | --- |
| `pull-request-core` | Every PR | Always-on guard suites (docs link check, scripts inventory, bash/py invocation, secret-scan chokepoint, claims-audit unit, RCA fanout, skills-spec guard) |
| `changed-domain` | PR pytest leg | Path-selected domain suites plus mandatory `planning`, `memory`, and `credential` core; adds `eval` when retrieval/provider/redaction paths change |
| `main-full` | Push to `main` | Full `scripts/unit_tests` collection |
| `scheduled-full-plus-integration` | Nightly schedule | Full suite including integration-marked tests |
| `minimum-python` | Matrix leg | Inherits `pull-request-core` on the minimum supported Python version |

Required PR pytest shards also include `credentials-unit-fixtures` (`scripts/unit_tests/credentials`)
via `pr-test-plan.manifest.json` + matching `suite-registry.json` `pr-ci` row — keep those two in sync
when adding credential unit coverage.

Regenerate workflows after editing the registry:

```bash
python3 scripts/ci_plan_gen.py
python3 scripts/unit_tests/test/test_ci_plan_generation.py  # via run_pytest
```

Provider-conformance suites registered in `suite-registry.json` (for example GitHub issues provider
evidence gates) participate in the same named-plan topology — keep `pr-ci` rows and generated workflows
aligned when adding conformance coverage.

Capability-doc generation is checked as `capability-docs-fixtures` on the `ci-yml` lane (pytest under
`scripts/unit_tests/capability`, including in-place regen with no `--update` flag). It is not an
always-on `pull-request-core` job.

<!-- suite-registry.json and ci_plan_gen.py are authoritative for plan names above. -->

## Initialization and doctor checks

First-run setup and ongoing health use stable CLI entry points with **stable failure codes** (one code →
one remediation command):

| Surface | Command | Stable codes |
| --- | --- | --- |
| First-run / config | `/sw-init` → `scripts/sw-configure.py` | `verify-unconfigured`, config drift warnings |
| Credentials | `python3 scripts/credentials-doctor.py --root .` | Broker scope, selector, and resolution codes (`credentials-doctor.py remediate --code <code>`) |
| Planning + memory | `python3 scripts/planning-doctor.py --root .` | Authority state, ledger/journal integrity, `memory-source-of-truth` / `migration-required`, projection health, distribution freshness |

Re-run the matching doctor after remediation; codes are designed for CI log grep and scripted fix paths.

## Code style

- Match existing patterns in the area you are editing.
- Keep user-facing command names under the `sw-` prefix.
- Do not commit secrets, API keys, or raw session transcripts.

## Questions

Open a [discussion](https://github.com/grdavies/shipwright/discussions) or file an issue if something is
unclear before starting large changes.
<!-- currency: refreshed 2026-08-23T00:42:13Z for terminal prepare (PRD 325) -->
