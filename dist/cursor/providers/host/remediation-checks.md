# Checks evidence remediation (PRD 079 R13–R14)

Canonical operator guidance for unavailable CI/check-status reads. Consumed by gate runtime
messages and host provider docs — do not duplicate prose elsewhere.

## github

Host token cannot read CI check status for this repository. Grant a fine-grained PAT with
**Checks** repository permission at read access (repository-scoped, expiring). Classic PAT
`repo` grants far broader access than required and is a legacy fallback only.

## gitlab

Host token cannot read commit statuses or pipelines. Grant an access token with API read access
to the project so commit statuses and pipelines are visible.

## bitbucket

Host token cannot read commit build statuses. Grant an access token with repository read access
so commit statuses are visible.

## default

Host token cannot read CI/check status. Configure a host token with check-status read capability
for your forge provider.
