# Checks evidence remediation (PRD 079 R13–R14)

Canonical operator guidance for unavailable CI/check-status reads. Consumed by gate runtime
messages and host provider docs — do not duplicate prose elsewhere.

Each row names the credential checklist step it unblocks (see `core/commands/sw-init.md` §5c).

## github

Host token cannot read CI check status for this repository. Grant a fine-grained PAT scoped to
this repository with **Actions: Read** (workflow runs and check-run visibility — primary
remediation path). Add **Workflows: Write** when the token must dispatch workflows; include
**Contents: Read** and **Pull requests: Read** for typical host PR flows. GitHub's fine-grained
PAT UI does not expose a standalone **Checks** permission — do not treat **Checks** as the sole
instruction. Classic PAT `repo` grants far broader access than required and is a legacy fallback
only; prefer fine-grained **Actions: Read** over classic `repo`.

**Unblocks checklist step:** `verification` — re-run
`python3 scripts/credentials-doctor.py --root .` after updating the token.

## gitlab

Host token cannot read commit statuses or pipelines. Grant an access token with API read access
to the project so commit statuses and pipelines are visible.

**Unblocks checklist step:** `verification` — re-run
`python3 scripts/credentials-doctor.py --root .` after updating the token.

## bitbucket

Host token cannot read commit build statuses. Grant an access token with repository read access
so commit statuses are visible.

**Unblocks checklist step:** `verification` — re-run
`python3 scripts/credentials-doctor.py --root .` after updating the token.

## default

Host token cannot read CI/check status. Configure a host token with check-status read capability
for your forge provider.

**Unblocks checklist step:** `verification` — re-run
`python3 scripts/credentials-doctor.py --root .` after updating the token.
