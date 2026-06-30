---
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: providers
      scope: host-contract
  metadata:
    providerFamily: host
    selectionFamily: providers
    notes: neutral host/forge capability contract doc
---

# Host provider capabilities (PRD 026)

Neutral contract for git-host / forge adapters. Deterministic consumers (`scripts/check-gate.py`,
`scripts/wave_terminal.py`, `scripts/stabilize-merge-sync.py`) call host verbs through
`scripts/host.py <verb>` (Phase 2+) routed by `host.provider` via capability-manifest selection.
Agent-mediated consumers read markdown adapters (`providers/host/<id>.md`).

## Verb set (R3)

| Verb | Purpose |
| --- | --- |
| `resolve-pr-for-branch` | Map current branch → open PR/MR number (if any) |
| `pr-create` | Create PR/MR with standardized body |
| `pr-view` | Fetch PR/MR metadata (head, base, state, mergeable) |
| `pr-list` | List open PRs/MRs (filterable) |
| `pr-head` | Resolve PR head SHA for gate binding |
| `pr-close` | Close superseded PR/MR by number |
| `checks` | CI/check-run status for a PR head |
| `review-threads` | Unresolved review thread count / bodies |
| `repo-meta` | Repository identity (owner/name, default branch) |
| `merge` | Server-side merge (when supported; terminal still human-gated) |

Each adapter declares per-verb capability flags. Unsupported verbs return a typed **degraded** JSON result
(`verdict: degraded`, `reason: capability-missing`) — never an unhandled crash.

## Capability flags (TR2)

| Flag | Meaning |
| --- | --- |
| `pullRequests` | Host exposes PR/MR APIs |
| `reviewThreads` | Review-thread resolution available |
| `checksApi` | CI/check status via host API |
| `ciWatch` | Pollable CI status for `/sw-watch-ci` |
| `serverSideMerge` | API merge endpoint available |
| `rateLimitRetryAfter` | Host reliably sends `Retry-After` |
| `rateLimitReset` | Host sends reset epoch/date header |
| `rateLimitNearLimit` | Host sends near-limit signal header |

The local (`none`) adapter sets `pullRequests: false` and routes the gate to local-evidence equivalents
(Phase 3).

## Executable JSON shape (stdout)

```json
{
  "verdict": "ok",
  "verb": "pr-view",
  "provider": "github",
  "data": {}
}
```

Degraded / rate-limited outcomes:

```json
{
  "verdict": "degraded",
  "verb": "checks",
  "reason": "missing-token",
  "retryable": false
}
```

```json
{
  "verdict": "rate-limited",
  "verb": "pr-view",
  "reason": "retry-exhausted",
  "retryable": true,
  "attempts": 5,
  "cumulativeWaitMs": 300000
}
```

## Config

`host.provider` in `workflow.config.json` selects `providers/host/<id>.md` (+ `<id>.py` when present) via
`config_flag` triggers (`selectionFamily: providers`). `host.remote` (default `origin`) names the git remote.
`host.tokenEnv` names the environment variable holding the API token — never the secret value.
`host.rateLimit` configures retry/backoff (see `scripts/host_ratelimit.py`).

## Transport

All HTTP calls route through `scripts/scripts/_sw/host_transport.py` → `scripts/host_ratelimit.py` (R35–R42). Tokens
are read at call time via `scripts/host_token.py` and passed to `host HTTP transport` through a header file — never argv or
logs.
