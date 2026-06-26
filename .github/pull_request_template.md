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
| `feat-test-plan-doc-fixtures` | required |
| `feat-test-plan-docs-link-check` | required |
| `feat-test-plan-cleanup-fixtures` | advisory |
| `feat-test-plan-ux-polish-fixtures` | advisory |

Open the PR **Checks** tab for live status. Required jobs must pass before merge; advisory jobs surface under the all-checks policy but do not block merge.

Source: `core/sw-reference/pr-test-plan.manifest.json` (regenerate workflow via `bash scripts/generate-pr-test-plan-ci-workflow.sh`).

## Test plan (advisory)

<!-- Optional human notes only — CI jobs above are the gate. -->
