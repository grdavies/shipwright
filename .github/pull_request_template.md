## Summary

<!-- What changed and why? -->

## Checklist

- [ ] PR **title** follows [Conventional Commits](https://www.conventionalcommits.org/) (becomes the squash commit subject)
- [ ] Breaking changes use `!` in the title (e.g. `feat!: …`)
- [ ] `core/` edits include regenerated `dist/` (`python3 -m sw generate --all`)

## CI gate (authoritative)

The **PR test-plan workflow** (`.github/workflows/pr-test-plan-ci.yml`) is the enforcement path — not a manual checklist below.

| Job | Classification |
|-----|----------------|
| `feat-test-plan-pytest-required-shard-1` | required |
| `feat-test-plan-docs-link-check` | required |
| `feat-test-plan-pytest-advisory-shard-1` | advisory |

Open the PR **Checks** tab for live status. Required jobs must pass before merge; advisory jobs surface under the all-checks policy but do not block merge.

Source: `core/sw-reference/pr-test-plan.manifest.json` (regenerate workflow via `python3 scripts/generate-pr-test-plan-ci-workflow.py`).

## Test plan (advisory)

<!-- Optional human notes only — CI jobs above are the gate. -->
