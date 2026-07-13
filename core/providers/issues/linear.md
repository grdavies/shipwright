---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: planning.store.issuesProvider
        equals: linear
    metadata:
      providerFamily: issues
      adapterId: linear
      selectionFamily: providers
      gateRef: check-gate.py
---

# Linear Issues adapter (PRD 066)

Selected when `planning.store.issuesProvider` is `linear` (independent of `host.provider`).
Live GraphQL client: `scripts/planning_linear_client.py` (R9/R12). Recognized in
`ISSUES_PROVIDERS` when the live client is wired; promotion to `SHIPPED_ISSUES_PROVIDERS`
requires conformance + OAuth docs gate (R20/R23).

## Configuration keys

| Key | Purpose |
| --- | --- |
| `planning.store.issues.teamKey` | Human Team key/name (e.g. `ENG`) — preferred |
| `planning.store.issues.teamId` | Linear GraphQL Team id |
| `planning.store.issues.tokenEnv` | Dedicated token env (default `ISSUES_LINEAR_TOKEN`; **never** `host.tokenEnv`) |
| `planning.store.issues.authMode` | `api-key` (default) or `oauth` (secondary, R23) |
| `planning.store.issues.oauthSharedCiException` | Explicit exception for oauth via shared CI secret |

At least one of `teamKey` or `teamId` is required. Init/probe fails closed on mismatch or
missing Team scope (R11). Prefer a Team-restricted personal API key.

## Auth headers

| Mode | Header |
| --- | --- |
| `api-key` (default) | `Authorization: <API_KEY>` (no Bearer prefix) |
| `oauth` | `Authorization: Bearer <ACCESS_TOKEN>` |

OAuth changes token acquisition/header only — verb set, Team probe, budgets, and
canonicalization are unchanged (R23).

## OAuth token storage (operator-local hooks)

- Access/refresh tokens are **operator-local only** (machine keychain or local secret store).
- Must **not** be committed to the planning repo.
- Doctor refuses `authMode: oauth` wired through a shared CI secret unless
  `oauthSharedCiException: true` is set for an explicit documented exception path.

## Dual budgets (R13)

Request-count and GraphQL complexity points are tracked in `planning_request_budget`.
GraphQL `extensions.code: RATELIMITED` is handled in addition to HTTP 429.
Complexity-aware query planner splits work under the ~10k points/query cap.

## Batch create foot-gun (R14)

`issueBatchCreate` inputs MUST use `{ "issues": [ ... ] }`. A bare issues array silently
creates zero issues and is rejected by `validate_batch_create_input`.
