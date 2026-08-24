---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: planning.store.issuesProvider
        equals: notion
    metadata:
      providerFamily: issues
      adapterId: notion
      selectionFamily: providers
      gateRef: check-gate.py
---

# Notion Issues adapter (PRD 327)

Selected when `planning.store.issuesProvider` is `notion` (independent of `host.provider`).
Live REST client: `scripts/planning_notion_client.py` (R2/R10). Recognized in
`ISSUES_PROVIDERS` when the live client is wired; promotion to `SHIPPED_ISSUES_PROVIDERS`
requires conformance + docs gate (R20).

## Configuration keys

| Key | Purpose |
| --- | --- |
| `planning.store.issues.notionDatabaseId` | Primary Notion database id |
| `planning.store.issues.databaseMap` | Artifact-type → database id map |
| `planning.store.issues.workspaceId` | Optional workspace id (operator documentation) |
| `planning.store.issues.tokenEnv` | Dedicated token env (default `ISSUES_NOTION_TOKEN`; **never** `host.tokenEnv`) |
| `planning.store.issues.notionTitleProperty` | Title property (default `Name`) |
| `planning.store.issues.notionStatusProperty` | Status property (default `Status`) |
| `planning.store.issues.notionProjectProperty` | Project multi-select property (default `Project`) |
| `planning.store.issues.notionLabelProperty` | Label ladder property (defaults to `notionProjectProperty`) |
| `planning.store.issues.notionParentRelationProperty` | Parent relation for epic/sub-issue linkage (default `Parent`) |
| `planning.store.issues.labelCustomField` | Label ladder step 3 custom property name |
| `planning.store.issues.labelSurface` | Force ladder rung: `multi_select` \| `select` \| `customField` |
| `planning.store.requestBudget.notion` | Derived-view call budget overrides |

At least one of `notionDatabaseId` or `databaseMap` is required. Init/probe fails closed on
missing database scope or schema mismatch (R4).

## Auth headers

| Header | Value |
| --- | --- |
| `Authorization` | `Bearer <INTEGRATION_TOKEN>` |
| `Notion-Version` | `2022-06-28` |

Integration tokens are operator-local — must not be committed to the planning repo.

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
  "lcd": ["title", "body", "comments", "state", "labels"],
  "lock": {
    "capability": "degraded",
    "native": false,
    "mechanism": "hash-authoritative"
  },
  "overflow": {
    "bodySizeLimitBytes": 60000,
    "richTextCharLimit": 2000,
    "blockAppendLimit": 100,
    "chunkMarker": "sw-chunk-overflow"
  },
  "commentMutation": {
    "capability": "degraded",
    "update": false,
    "delete": false,
    "amendVia": "append-marked-comment"
  },
  "labelLadder": ["multi_select", "select", "labelCustomField"]
}
```

`issue-lock` is **degraded**: freeze immutability is hash-authoritative via `sw:frozen` +
`sw-freeze-record`; Notion has no native conversation lock verb.

`issue-comment` mutation (update/delete) is **degraded**: amendments append a new marked comment;
the facade reports `commentMutation: degraded`.

## LCD verb mapping (R10)

| Verb | Notion surface |
| --- | --- |
| `issue-create` | `POST /pages` |
| `issue-get` | `GET /pages/{id}` + `GET /blocks/{id}/children` |
| `issue-update` | `PATCH /pages/{id}` |
| `issue-comment` | `POST /comments` + `GET /comments` |
| `issue-label` | page `multi_select` / `select` / custom-field ladder |
| `issue-lock` | **degraded** — `sw:frozen` label + hash-authoritative freeze |
| `issue-search` | `POST /databases/{database_id}/query` (paginated) |
| `issue-close` | `PATCH /pages/{id}` archived/status transition |

Duck-type surface in `scripts/planning_notion_client.py` (`NotionIssuesClient`) matches
`FixtureIssuesStore` verbs: `create` / `get` / `update` / `add_comment` / `set_labels` / `lock` /
`search`, plus lifecycle hooks (`mark_tombstone`, …). Hermetic CI uses `SW_ISSUES_FIXTURE=1` or an
injected fixture store.

## Label degradation ladder (R9)

| Step | Surface | When |
| --- | --- | --- |
| 1 | `multi_select` | default; init probe validates write permission |
| 2 | `select` | when `multi_select` unavailable |
| 3 | custom field | `planning.store.issues.labelCustomField` |

`sw:project:<key>`, `sw:prd`, `sw:brainstorm`, `sw:gap`, `sw:task`, and `sw:frozen` round-trip
through the active rung. PRD 043 R42 body marker stays authoritative for isolation on shared
workspaces; every degradation emits exactly one operator notice.

## Epic/sub-issue hierarchy (R10)

`issue-epic-create`, `issue-sub-issue-create`, and `issue-sub-issue-link` use a parent **relation
property** (`notionParentRelationProperty`) as the linkage of record — not Notion child-page
parenting. When relation verbs are unavailable, degrade to `to_do` checkbox blocks in the epic
body with a single operator notice; deliver continues.

## Body overflow / comments (R11)

- `POST /v1/comments` + `GET /v1/comments` for ordered reads
- Hard limits: 2000 characters per `rich_text` element; 100 block children per append
- Oversized bodies: `<!-- sw-chunk-manifest: … -->` in the head page plus ordered
  `<!-- sw-chunk-overflow -->` comments; reassembly by immutable comment id (positional fallback
  for synthetic placeholder ids only)

## Rate limit + retry (R4)

- HTTP profile `notion`: ~3 requests/sec average via `mutatingMinDelayMs` pacing.
- Honors `Retry-After` on HTTP 429 with jittered backoff.
- Retries idempotently on `409 conflict_error` and `502 gateway_timeout`.
- Does **not** retry `400 validation_error`.

## Promotion gates

Notion MUST NOT enter `SHIPPED_ISSUES_PROVIDERS` until conformance **and** the docs gate
pass. Until promotion, doctor reports `notion-recognized-not-shipped` and effective backend
falls back to file-store.

See `core/providers/issues/CAPABILITIES.md` and `scripts/planning_notion_client.py` for LCD
verbs, probes, and budget semantics.
