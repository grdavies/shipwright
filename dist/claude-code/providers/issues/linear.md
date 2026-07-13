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

## Stage-1 dogfood acceptance (R25)

Normative operator-surface acceptance before the stage-1 ship increment. The stage-1 gate asserts
this checklist via `python3 scripts/planning_linear_client.py <root> stage1-dogfood-gate`.

### Volume floors

On a dedicated dogfood Team (recommended; shared Teams allowed with coexistence rules below):

| Floor | Requirement |
| --- | --- |
| PRDs | ≥3 PRD Projects |
| Brainstorms | Each PRD Project has ≥1 attached Brainstorm Document |
| Gaps | Each PRD Project has ≥1 absorbed Gap Issue (Gap label + Project membership) |
| Tasks | ≥20 task Issues across ≥2 phase Milestones |

### R1 saved views

Ship (or document as required operator setup) saved views/filters that answer R1(1)–(4) from
list/board metadata **without opening markdown bodies** (R31 browse contract):

| R1 question | Minimum browse metadata |
| --- | --- |
| (1) Gaps a PRD absorbs | Gap Issues linked to the PRD Project + Gap label/field |
| (2) Brainstorms feeding a PRD | Document attachment/membership on the PRD Project |
| (3) Task/phase completion | Issue status + Milestone (phase) membership |
| (4) Program backlog/in-flight/done | Initiative membership **or** documented Team/Project substitute view + program discriminator; Cycle is wave enrichment only |

When Initiative is unavailable, the substitute view contract in the capability matrix is required —
silent skip is prohibited (R7).

### Naming and archival

| Convention | Rule |
| --- | --- |
| Project prefix | `[<projectKey>]` or `sw:project:<key>` marker in Project name |
| Issue title prefix | `[<projectKey>]` on LCD Issues (PRD 043 convention) |
| Type labels | `sw:prd`, `sw:brainstorm`, `sw:gap`, `sw:task`, `sw:frozen` flat labels |
| Superseded projections | Close or archive Projects/Issues when a unit is superseded/absorbed; rebuild must not leave unbounded duplicate Projects for the same `unit-id` |
| Tombstone hooks | Use `mark_tombstone` / `mark_archived_project` lifecycle hooks on fixture/live paths when retiring projections |

### Coexistence (shared Teams)

When dogfooding on a Team that already has human Linear Projects/Cycles:

- Shipwright projection Projects **must** be distinguishable via the naming prefix/marker above.
- **Cycles (R8 / M13/B):** assign Shipwright-owned issues into the Team's existing Cycle; do **not**
  rename or reschedule Cycle definition (dates/name). Probe/doctor emits a loud shared-cadence notice
  when the Team already has an active human Cycle cadence.
- Milestone phase membership remains authoritative for phase completion (R1(3)); Cycle is wave
  time-box only and does not replace Milestone membership.

**MVP dogfood auth:** stage-1 dogfood uses `authMode: api-key` (Team-restricted personal API key) —
OAuth is not required for stage-1 promotion (R23).

## OAuth secondary auth mode (R23)

OAuth 2.0 is a **documented secondary** auth mode on the same adapter surface. Default remains
`authMode: api-key` (R11). OAuth changes token acquisition and `Authorization` header shape only —
verb set, Team scope probe, dual budgets, and canonicalization are unchanged.

### MVP dogfood vs stage-4 gate

| Stage | Auth posture |
| --- | --- |
| Stage-1 dogfood (R25) | `api-key` only — Team-restricted personal API key |
| Stage-4 promotion | OAuth docs gate must pass **before** advertising `authMode: oauth` or promoting Linear to `SHIPPED_ISSUES_PROVIDERS` with oauth enabled |

Linear MUST NOT enter `SHIPPED_ISSUES_PROVIDERS` until conformance **and** the OAuth docs gate
(`python3 scripts/planning_linear_client.py <root> oauth-docs-gate`) pass (D7a / M1).

### OAuth scopes

Minimum Linear OAuth scopes for the adapter surface (read/write Team-scoped work):

| Scope | Purpose |
| --- | --- |
| `read` | Team/project/issue browse, probe, R1 views |
| `write` | Issue/comment/label mutations, projection upsert |
| `issues:create` | LCD `issue-create` / task Issue creation |
| `comments:create` | LCD `issue-comment` / chunk overflow comments |

Init/probe fails closed when the token cannot read/write the configured Team (R11). Over-scoped
workspace-admin tokens should be rotated to Team-restricted credentials when detectable (G8).

### Token storage and refresh (operator-local)

| Rule | Detail |
| --- | --- |
| Storage | Access **and** refresh tokens are **operator-local only** (OS keychain or local secret store) |
| Planning repo | Tokens MUST NOT be committed to the planning repo or checked into `workflow.config.json` |
| Refresh | Operators are responsible for refresh before expiry; the thin client reads the current access token from `tokenEnv` — no automatic refresh loop ships in MVP |
| CI / shared secrets | Doctor refuses `authMode: oauth` wired through a shared CI secret unless `oauthSharedCiException: true` is set for an explicit documented exception path |
| Header shape | `Authorization: Bearer <ACCESS_TOKEN>` (contrast: api-key has no Bearer prefix) |

Probe OAuth docs gate:

```bash
python3 scripts/planning_linear_client.py . oauth-docs-gate
python3 scripts/planning_linear_client.py . doctor-oauth
```
