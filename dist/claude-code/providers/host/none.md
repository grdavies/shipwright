---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: host.provider
        equals: none
    metadata:
      providerFamily: host
      adapterId: none
      selectionFamily: providers
      gateRef: check-gate.py
---

# Local / no-remote host adapter

Selected when `host.provider` is `none` or no git remote is detected. PR-oriented verbs degrade to
local-evidence equivalents (Phase 3) or explicit no-ops.

## Capability flags

```json
{
  "pullRequests": false,
  "reviewThreads": false,
  "checksApi": false,
  "ciWatch": false,
  "serverSideMerge": false,
  "rateLimitRetryAfter": false,
  "rateLimitReset": false,
  "rateLimitNearLimit": false,
  "verbs": {
    "resolve-pr-for-branch": false,
    "pr-create": false,
    "pr-view": false,
    "pr-list": false,
    "pr-head": false,
    "checks": false,
    "review-threads": false,
    "repo-meta": true,
    "merge": false
  }
}
```

`repo-meta` resolves from local git only (default branch via `resolve_base_branch.py`).

## Degraded verb contract

Unsupported verbs return:

```json
{
  "verdict": "degraded",
  "verb": "<verb>",
  "provider": "none",
  "reason": "capability-missing",
  "retryable": false
}
```

The gate uses local-evidence authorization when `host.provider` is `none` (R9–R13, Phase 3).
