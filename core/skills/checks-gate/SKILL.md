---
name: checks-gate
description: Evaluate the pass/fail/pending state of a PR's CI checks under the Shipwright all-checks policy. Use from /sw-watch-ci and /sw-stabilize to compute a single gate verdict (green/red/yellow/blocked) over every check, honoring the configured neutral allowlist and the review-provider per-head state.
---

# checks-gate

Shared predicate for PR CI readiness. `/sw-watch-ci` and `/sw-stabilize` both use it so the gate is
identical on both sides. Default policy is **all checks**, not just required.


**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --skill checks-gate`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Policy (`workflow.config.json` → `checks`)

| Key | Default | Effect |
| --- | --- | --- |
| `policy` | `all` | `all` = every check; `required` = required checks only. |
| `treatNeutralAsPass` | `true` | `NEUTRAL`/`SKIPPED` count as pass when true. |
| `neutralAllowlist` | `[]` | Check names allowed neutral without blocking. |

Review per-head state comes from `review.provider` (default `coderabbit`) via `scripts/check-gate.sh`.

## Canonical computation — `scripts/check-gate.sh`

Do **not** free-hand the verdict from ad-hoc `gh` calls. Run the shipped script:

```bash
GATE="${CURSOR_PLUGIN_ROOT:-$HOME/.cursor/plugins/local/shipwright}/scripts/check-gate.sh"
if OUT=$(bash "$GATE"); then GATE_EC=0; else GATE_EC=$?; fi
echo "$OUT" | jq .
```

**Exit code = verdict:**

| Exit | Verdict |
| --- | --- |
| `0` | `green` |
| `10` | `yellow` |
| `20` | `red` |
| `30` | `blocked` |

JSON includes `verdict`, `head`, `reviewProvider`, `coderabbitState` (`landed`/`skipped`/`in-flight`/`absent`),
`coderabbitLanded`, `unresolvedActionable`, check lists, `requiredFailingChecks`, `advisoryFailingChecks`,
and `prTestPlan` (manifest job names when `core/sw-reference/pr-test-plan.manifest.json` is present), and
`reason`.

`green` requires: all **required** checks pass (PR test-plan advisory failures are surfaced but
non-blocking), review settled for current head (`coderabbitLanded == true`), and
`unresolvedActionable == 0`.

## Deterministic tests

Set `SW_GATE_NOW` (unix seconds) to fix the grace-window clock. Fixture harness:
`scripts/test/run-gate-fixtures.sh` (uses a PATH `gh` stub).

## Handoff

- `green` → ready to merge gate (implementation workstream `/sw-phase-ready`)
- `red` / `blocked` → `/sw-stabilize`
- `yellow` → keep waiting (`/sw-watch-ci`)

## Guardrails

- Never report `green` while per-head review is `in-flight`.
- Never override the script exit code with hand-rolled `gh` calls.
- Prefer `scripts/check-gate.sh` — it encodes #322/#330 false-green fixes from v1.
