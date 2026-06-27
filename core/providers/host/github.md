---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: host.provider
      equals: "github"
  metadata:
    providerFamily: host
    adapterId: github
    selectionFamily: providers
    gateRef: check-gate.sh
---

# GitHub host adapter

Markdown companion to `host_github.sh` (Phase 2). Selected when `workflow.config.json` → `host.provider` is
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

Token from `host.tokenEnv` (default `GITHUB_TOKEN`). Classic or fine-grained PAT with repo read + PR write.
Never stored in config.

## Rate limits

GitHub: `403`/`429` with `x-ratelimit-remaining: 0` or secondary-rate-limit message. Honor `retry-after`,
then `x-ratelimit-reset` (UTC epoch). Pre-emptive pause when `x-ratelimit-remaining` ≤ `host.rateLimit.nearLimitThreshold`.
Mutating requests paced ≥ 1s apart (R39).
