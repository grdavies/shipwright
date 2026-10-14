---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: host.provider
        equals: github
    metadata:
      providerFamily: host
      adapterId: github
      selectionFamily: providers
      gateRef: check-gate.py
---

# GitHub host adapter

Markdown companion to `scripts/host.py` (Phase 2). Selected when `workflow.config.json` → `host.provider` is
`github` or auto-detected from a `github.com` remote.

## Capability flags

```json
{
  "pullRequests": true,
  "reviewThreads": true,
  "checksApi": true,
  "ciWatch": true,
  "serverSideMerge": true,
  "rateLimitRetryAfter": true,
  "rateLimitReset": true,
  "rateLimitNearLimit": true,
  "verbs": {
    "resolve-pr-for-branch": true,
    "pr-create": true,
    "pr-view": true,
    "pr-list": true,
    "pr-head": true,
    "pr-close": true,
    "checks": true,
    "review-threads": true,
    "repo-meta": true,
    "merge": true
  }
}
```

## Verb mapping (REST + GraphQL)

| Verb | Transport |
| --- | --- |
| `pr-create` | `POST /repos/{owner}/{repo}/pulls` |
| `pr-view` | `GET /repos/{owner}/{repo}/pulls/{n}` |
| `pr-list` | `GET /repos/{owner}/{repo}/pulls` |
| `pr-close` | `PATCH /repos/{owner}/{repo}/pulls/{n}` (`state: closed`) |
| `pr-head` | `GET /repos/{owner}/{repo}/pulls/{n}` → `head.sha` |
| `checks` | `GET /repos/{owner}/{repo}/commits/{sha}/check-runs` |
| `review-threads` | GraphQL `reviewThreads` (resolution state is GraphQL-only) |
| `repo-meta` | `GET /repos/{owner}/{repo}` |
| `merge` | `PUT /repos/{owner}/{repo}/pulls/{n}/merge` |

## Auth

Host transport resolves through committed `host.credentialRef` and the machine-local credential
selector (or `.sw/credential-ci-selector.json` in CI) — never from config bodies or ambient env
outside an explicitly declared `environment` backend entry. `scripts/host_lib.py` calls
`credentials.resolver` with `purpose: host`; secret material is delivered only via
`credentials.send_path` after scope checks pass.

Selector entries for this adapter must declare non-empty `allowedRepos`, `allowedProjectIds` (must
include committed `projectId`), and `allowedEndpoints` (for example `https://api.github.com` or your
enterprise API base). The broker **refuses** resolution when the destination host is off the allowlist,
the repository remote is out of `allowedRepos`, or pairing is unapproved — scope enforcement is
fail-closed, not advisory.

During the one-release alias window, `host.tokenEnv` (default `GITHUB_TOKEN`) may name the presence
env var for an `environment` backend — `credentialRef` wins when both are set.

For CI check and workflow-run visibility, prefer a **fine-grained PAT** scoped to this repository
with at least:

- **Actions: Read** — read workflow runs and check-run status (primary path for CI evidence)
- **Workflows: Write** — when the token must dispatch or update workflows (optional; omit when
  read-only CI watch is sufficient)
- **Contents: Read** and **Pull requests: Read** — typical minimums for host PR and merge flows

GitHub's fine-grained PAT UI does not expose a standalone **Checks** permission; lead with **Actions:
Read** (and **Workflows: Write** when dispatch is required) rather than **Checks: Read** as the sole
instruction. Classic PAT `repo` grants far broader access than required and is a **legacy** fallback only;
do not grant invalid OAuth scope strings for check reads.

Remediation when check status cannot be read:
`core/providers/host/remediation-checks.md` (github section) — unblocks checklist step
`verification` (`python3 scripts/credentials-doctor.py`).

Diagnose: `python3 scripts/credentials-doctor.py --root .` (never prints secret values). See
[configuration — Credential references](../../docs/guides/configuration.md#credential-references-and-machine-local-selector).

## Rate limits

GitHub: `403`/`429` with `x-ratelimit-remaining: 0` or secondary-rate-limit message. Honor `retry-after`,
then `x-ratelimit-reset` (UTC epoch). Pre-emptive pause when `x-ratelimit-remaining` ≤ `host.rateLimit.nearLimitThreshold`.
Mutating requests paced ≥ 1s apart (R39).
