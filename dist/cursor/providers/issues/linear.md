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

## Capability flags (R10)

```json
{
  "verbs": {
    "issue-create": true,
    "issue-get": true,
    "issue-update": true,
    "issue-comment": true,
    "issue-label": true,
    "issue-lock": "degraded",
    "issue-search": true,
    "issue-close": true
  },
  "graphql": {
    "issue-create": true,
    "issue-get": true,
    "issue-update": true,
    "issue-comment": true,
    "issue-label": true,
    "issue-lock": false,
    "issue-search": true
  },
  "lcd": ["title", "body", "comments", "state", "labels"],
  "lock": {
    "capability": "degraded",
    "native": false,
    "mechanism": "hash-authoritative"
  },
  "overflow": {
    "bodySizeLimitBytes": 60000,
    "chunkMarker": "sw-chunk-overflow"
  }
}
```

`issue-lock` is **degraded** (R10): Linear has no native conversation lock. Freeze immutability is
hash-authoritative via `sw:frozen` + `sw-freeze-record`; tamper detection uses on-read verification —
not a provider lock verb. A degraded hash-authoritative lock is conformance-complete when native
lock is absent.

## LCD verb mapping (R10)

| Verb | Linear surface |
| --- | --- |
| `issue-create` | `issueCreate` GraphQL |
| `issue-get` | `issue(id:)` GraphQL |
| `issue-update` | `issueUpdate` GraphQL |
| `issue-comment` | `commentCreate` GraphQL |
| `issue-label` | `issueUpdate` / `issueLabelCreate` (flat name → Label id) |
| `issue-lock` | **degraded** — `sw:frozen` label only (no native lock mutation) |
| `issue-search` | `issues(filter:)` GraphQL (project label scoped) |

Duck-type surface in `scripts/planning_linear_client.py` (`LinearIssuesClient`) matches
`FixtureIssuesStore` verbs: `create` / `get` / `update` / `add_comment` / `set_labels` / `lock` /
`search`, plus lifecycle hooks (`mark_tombstone`, …). Hermetic CI uses `SW_ISSUES_FIXTURE=1` or an
injected fixture store.

## Body overflow / chunking (R10)

Linear descriptions use the generic UTF-8 body limit (`BODY_SIZE_LIMIT` = 60_000 bytes) via
`planning_canonical.chunk_body_if_needed(provider="linear")`. Oversized bodies are split into:

1. Head description with `<!-- sw-chunk-manifest: … -->`
2. Ordered overflow comments marked `<!-- sw-chunk-overflow -->`

There is no ADF-style tighter cap (unlike Jira Cloud). Reassembly uses immutable comment IDs in the
manifest (positional fallback only when ids are synthetic placeholders).

## Dual budgets (R13)

Request-count and GraphQL complexity points are tracked in `planning_request_budget`.
GraphQL `extensions.code: RATELIMITED` is handled in addition to HTTP 429.
Complexity-aware query planner splits work under the ~10k points/query cap.

## Batch create foot-gun (R14)

`issueBatchCreate` inputs MUST use `{ "issues": [ ... ] }`. A bare issues array silently
creates zero issues and is rejected by `validate_batch_create_input`.
