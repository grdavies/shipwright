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
    gateRef: check-gate.py
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


## Planning / issue-store routing (PRD 043 / PRD 047 D25)

Bitbucket Cloud **does not** ship a first-class issues adapter in core — **never** route to native
Bitbucket issues for planning.

| Path | When | Config |
| --- | --- | --- |
| **Separate GitHub/GitLab planning project** (default) | Bitbucket code repo + issue-store without `issuesProvider` | `storeLocation.mode: separate-project` + `issuesProvider: github-issues` or `gitlab-issues` |
| **Jira** (opt-in; Cloud first) | Jira-standardized org on Bitbucket host | `issuesProvider: jira` + `planning.store.issues.*` keys (PRD 047) |

When `host.provider == bitbucket` and `planning.store.backend == issue-store` with unset/`none`
`issuesProvider`, `python3 scripts/planning_store.py resolve-backend` falls back to `in-repo-public` and
emits structured guidance via `bitbucket-issue-store-guidance` — separate-project default, Jira opt-in,
never native Bitbucket issues.

Host PR/CI verbs remain on this adapter; issue-store credentials use `planning.store.issues.tokenEnv`, not
`host.tokenEnv`.
