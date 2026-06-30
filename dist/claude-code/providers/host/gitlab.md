---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: host.provider
      equals: "gitlab"
  metadata:
    providerFamily: host
    adapterId: gitlab
    selectionFamily: providers
    gateRef: check-gate.py
---

# GitLab host adapter

Markdown companion to `scripts/host.py` (Phase 4). Selected when `workflow.config.json` → `host.provider` is
`gitlab` or auto-detected from a `gitlab.com` remote.

## Capability flags

```json
{
  "pullRequests": true,
  "reviewThreads": true,
  "checksApi": true,
  "ciWatch": true,
  "serverSideMerge": true,
  "rateLimitRetryAfter": true,
  "rateLimitReset": false,
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

## Verb mapping (REST)

| Verb | Transport |
| --- | --- |
| `pr-create` | `POST /projects/:id/merge_requests` |
| `pr-view` | `GET /projects/:id/merge_requests/:iid` |
| `pr-list` | `GET /projects/:id/merge_requests` |
| `pr-close` | `PUT /projects/:id/merge_requests/:iid` (`state_event: close`) |
| `pr-head` | `GET /projects/:id/merge_requests/:iid` → `sha` |
| `checks` | `GET /projects/:id/repository/commits/:sha/statuses` |
| `review-threads` | `GET /projects/:id/merge_requests/:iid/discussions` |
| `repo-meta` | `GET /projects/:id` |
| `merge` | `PUT /projects/:id/merge_requests/:iid/merge` |

## Auth

Token from `host.tokenEnv` (default `GITLAB_TOKEN`). Personal access token with `api` scope.
Never stored in config.

## Rate limits

GitLab: `429` with `Retry-After` when present; near-limit via remaining headers when available.
Mutating requests paced ≥ 1s apart (R39).
