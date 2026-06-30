---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: host.provider
      equals: "bitbucket"
  metadata:
    providerFamily: host
    adapterId: bitbucket
    selectionFamily: providers
    gateRef: check-gate.sh
---

# Bitbucket host adapter

Markdown companion to `scripts/host.py` (Phase 4). Selected when `workflow.config.json` → `host.provider` is
`bitbucket` or auto-detected from a `bitbucket.org` remote.

## Capability flags

```json
{
  "pullRequests": true,
  "reviewThreads": true,
  "checksApi": true,
  "ciWatch": true,
  "serverSideMerge": true,
  "rateLimitRetryAfter": false,
  "rateLimitReset": false,
  "rateLimitNearLimit": false,
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

Bitbucket Cloud often omits `Retry-After` and reset headers on `429`; transport falls back to jittered
exponential backoff by default (R40).

## Verb mapping (REST 2.0)

| Verb | Transport |
| --- | --- |
| `pr-create` | `POST /repositories/{workspace}/{repo}/pullrequests` |
| `pr-view` | `GET /repositories/{workspace}/{repo}/pullrequests/{id}` |
| `pr-list` | `GET /repositories/{workspace}/{repo}/pullrequests` |
| `pr-close` | `POST /repositories/{workspace}/{repo}/pullrequests/{id}/decline` |
| `pr-head` | `GET .../pullrequests/{id}` → `source.commit.hash` |
| `checks` | `GET /repositories/{workspace}/{repo}/commit/{hash}/statuses` |
| `review-threads` | `GET .../pullrequests/{id}/comments` |
| `repo-meta` | `GET /repositories/{workspace}/{repo}` |
| `merge` | `POST .../pullrequests/{id}/merge` |

## Auth

Token from `host.tokenEnv` (default `BITBUCKET_TOKEN`). Repository read/write scopes.
Never stored in config.
