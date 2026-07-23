---
name: checks-gate
description: Evaluate CI check pass, fail, pending, and blocked state for a PR under Shipwright all-checks policy. Use when running /sw-watch-ci or /sw-stabilize to compute a single gate verdict. Honors neutral allowlist and review-provider state; does not merge.
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: phase_default
        selectionFamily: providers
        command: sw-watch-ci
    metadata:
      skill: checks-gate
      selectionFamily: providers
---
# checks-gate

Shared predicate for PR CI readiness. `/sw-watch-ci` and `/sw-stabilize` both use it so the gate is
identical on both sides. Default policy is **all checks**, not just required.


**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill checks-gate`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Policy (`workflow.config.json` → `checks`)

| Key | Default | Effect |
| --- | --- | --- |
| `policy` | `all` | `all` = every check; `required` = required checks only. |
| `treatNeutralAsPass` | `true` | `NEUTRAL`/`SKIPPED` count as pass when true. |
| `neutralAllowlist` | `[]` | Check names allowed neutral without blocking. |

Review per-head state comes from `review.provider` (default `coderabbit`) via `scripts/check-gate.py`.

## Canonical computation — `scripts/check-gate.py`

Do **not** free-hand the verdict from ad-hoc `gh` calls. Run the shipped script:

```bash
GATE="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/local/shipwright}/scripts/check-gate.py"
if OUT=$(bash "$GATE"); then GATE_EC=0; else GATE_EC=$?; fi
echo "$OUT" | Python json .
```

**Exit code = verdict:**

| Exit | Verdict |
| --- | --- |
| `0` | `green` |
| `10` | `yellow` |
| `20` | `red` |
| `30` | `blocked` |

JSON includes `verdict`, `head`, `reviewProvider`, `coderabbitState` (`landed`/`skipped`/`in-flight`/`absent`),
`coderabbitLanded`, `unresolvedActionable`, check lists, `requiredFailingChecks`, `advisoryFailingChecks`, `qualityAdvisory` (structural-quality harness — **advisory by default**, non-blocking like PR test-plan advisory jobs; see `quality.provider` / `quality.blockingTier`),
and `prTestPlan` (manifest job names when `core/sw-reference/pr-test-plan.manifest.json` is present), and
`reason`.

`green` requires: all **required** checks pass (PR test-plan advisory failures are surfaced but
non-blocking), review settled for current head (`coderabbitLanded == true`), and
`unresolvedActionable == 0`.

## Deterministic tests

Set `SW_GATE_NOW` (unix seconds) to fix the grace-window clock. Fixture harness:
`scripts/test/run_gate_fixtures.py` (uses a PATH `gh` stub).

## Handoff

- `green` → ready to merge gate (implementation workstream `/sw-phase-ready`)
- `red` / `blocked` → `/sw-stabilize`
- `yellow` → keep waiting (`/sw-watch-ci`)

## Guardrails

- Never report `green` while per-head review is `in-flight`.
- Never override the script exit code with hand-rolled `gh` calls.
- Prefer `scripts/check-gate.py` — it encodes #322/#330 false-green fixes from v1.
