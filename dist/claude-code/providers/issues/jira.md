---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: planning.store.issuesProvider
        equals: jira
    metadata:
      providerFamily: issues
      adapterId: jira
      selectionFamily: providers
      gateRef: check-gate.py
      jiraFlavor: cloud
      issueMilestoneVerb: issue-milestone
---

# Jira Issues adapter (PRD 047)

Selected when `planning.store.issuesProvider` is `jira` (independent of `host.provider`).
Implements the PRD 043 LCD contract with REST-primary verbs, render-independent canonical hashing (R102),
and freeze decoupled from Jira workflow status (R104, D26).

## Configuration keys

| Key | Purpose |
| --- | --- |
| `planning.store.issues.endpoint` | Jira base URL (`https://<org>.atlassian.net` Cloud; `https://<host>/jira` DC/Server) |
| `planning.store.issues.flavor` | `cloud` (default) or `dc` — selects ADF vs wiki serialization and auth shape |
| `planning.store.issues.tokenEnv` | Dedicated issue API token env (default `ISSUES_JIRA_TOKEN`; **never** `host.tokenEnv`) |
| `planning.store.issues.freezeRecordField` | Custom field id for write-once freeze record (Cloud); DC may use description footer |

## Capability flags

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
    "issue-close": true,
    "issue-milestone": false
  },
  "graphql": {},
  "lcd": ["title", "body", "comments", "state", "labels"],
  "jiraFlavor": ["cloud", "dc"]
}
```

`issue-lock` is **degraded** (R104): Jira has no native conversation lock. Freeze immutability is
hash-authoritative via `sw:frozen` + `sw-freeze-record`; tamper detection uses PRD 043 R37 on-read
verification — not a provider lock verb.

## LCD mapping

| LCD field | Jira field | Notes |
| --- | --- | --- |
| `title` | `summary` | `[<projectKey>]` prefix convention preserved |
| `body` | `description` | ADF (Cloud) or wiki markup (DC); normalized to canonical markdown (R102) |
| `comments` | `comment` | Ordered thread; overflow chunks pinned by immutable comment IDs (R103/R46) |
| `state` | `status` / status category | `open`/`closed` mapped from status category; **not** authoritative for freeze (R104) |
| `labels` | `labels` | Flat labels; degradation ladder labels → components → custom field (R109) |

## REST mapping (primary)

| Verb | Transport |
| --- | --- |
| `issue-create` | `POST /rest/api/3/issue` (Cloud) / `POST /rest/api/2/issue` (DC) |
| `issue-get` | `GET /rest/api/3/issue/{key}` |
| `issue-update` | `PUT /rest/api/3/issue/{key}` |
| `issue-comment` | `POST /rest/api/3/issue/{key}/comment` |
| `issue-label` | `PUT /rest/api/3/issue/{key}` (`labels` / `update.labels`) |
| `issue-lock` | **degraded** — no-op; hash-authoritative tamper-evidence only |
| `issue-search` | `POST /rest/api/3/search` (JQL, project-scoped) |
| `issue-close` | `POST /rest/api/3/issue/{key}/transitions` (idempotent close transition) |

GraphQL is not used for Jira (R50). Selector fails closed when a required verb is absent.

## Cloud vs DC/Server matrix (R100)

| Concern | Cloud (`flavor: cloud`) | DC/Server (`flavor: dc`) |
| --- | --- | --- |
| Description serialization | ADF (Atlassian Document Format) | Wiki markup |
| Auth | Email + API token (Basic) | PAT required; password/basic **rejected** |
| REST base | `/rest/api/3/` | `/rest/api/2/` |
| Freeze-record placement | Custom field (`freezeRecordField`) preferred | Description footer or configured field |
| `issue-lock` | degraded | degraded |
| Per-issue privacy | unsupported (project-level only) | unsupported |
| Issue links / sub-tasks | maps to PRD 043 R29 `sw-edges` + PRD 046 hierarchy (consumed) | same |

## Canonical hash (R102, D27)

1. Submit description as ADF (Cloud) or wiki (DC).
2. Secret-scan runs on **post-normalization plaintext** (PRD 043 R45).
3. After write, **re-fetch** description from Jira.
4. Normalize via `scripts/planning_jira_canonical.py` (`adf_to_markdown` / `wiki_to_markdown`).
5. Compute PRD 043 R35 canonical hash over the post-write re-fetched canonical form — **not** the submit payload.

Benign server re-serialization (mention expansion, emoji node IDs, smart-link normalization) is absorbed
when both forms normalize to the same canonical markdown subset. Drift **beyond** the subset is classified
distinctly from PRD 043 R37 tamper and fails closed.

```bash
python3 scripts/planning_jira_canonical.py normalize --fixture scripts/tests/fixtures/canonical/jira/adf-roundtrip.json
```

Golden vectors live under `scripts/tests/fixtures/canonical/jira/`.

## Artifact placement (R103)

Jira exposes a single `description` field:

- **Description body** — artifact markdown + PRD 043 R42 body markers + PRD 043 R29 `sw-edges` block inside
  an ADF-safe fenced `codeBlock` (Cloud) or wiki `{code}` fence (DC).
- **Freeze record** — write-once `freezeRecordField` custom field (Cloud) or description footer (DC); carries
  `<!-- sw-freeze-record -->` marker and `sw-freeze-hash:` line; **excluded** from canonicalization.
- **Overflow** — PRD 043 R46 chunk comments with `<!-- sw-chunk-overflow -->` and immutable comment IDs in the
  chunk manifest; a deleted overflow comment is a PRD 043 R40 tombstone, not a hash mismatch.

## Freeze decoupled from Jira status (R104, D26)

- `sw:frozen` label + canonical content-hash are **authoritative** for immutability.
- Jira `status` / status category is read for display and probed for workflow constraints (no automation
  auto-transition of `sw:frozen` issues).
- An external/automation status transition on a frozen issue yields **`lifecycle-drift`** — classified
  distinctly from PRD 043 R37 `tamper-detected`.
- `issue-lock` degrades to hash-authoritative tamper-evidence (no provider lock call).

See `core/commands/sw-freeze.md` issue-store section for operator-facing freeze steps.

## Auth

Token from `planning.store.issues.tokenEnv` (default `ISSUES_JIRA_TOKEN`). Cloud: email + API token.
DC/Server: PAT only. Minimum scopes: `read:jira-work`, `write:jira-work`. Probed at init via
`python3 scripts/planning_store.py probe-issues-token`. Never stored in config.

## Phase 2 artifact CRUD (PRD 043)

Planning artifacts (PRD/gap/tasks/brainstorm) are created via `issue-create` with:

- Summary: `[<projectKey>] <type>:<unitId>`
- Labels: `sw:project:<key>` + `sw:<type>`
- Description: canonical markers + markdown + optional `sw-edges` block (ADF/wiki per flavor)

Mutations use `issue-update` with optimistic concurrency (R36). Hermetic CI uses `SW_ISSUES_FIXTURE=1` —
no live API calls.


## Auth probes (R101)

- Dedicated `planning.store.issues.tokenEnv` (default `ISSUES_JIRA_TOKEN`) — **never** `host.tokenEnv`.
- Cloud: email (`ISSUES_JIRA_EMAIL`) + API token (Basic).
- DC/Server: PAT required; password/basic auth **rejected** at init.
- Minimum scopes: `read:jira-work`, `write:jira-work`.
- Probed via `python3 scripts/planning_store.py probe-jira-init` (fail-closed).

## Per-issue privacy (R105)

Jira has **no per-issue privacy**. The init probe rejects a multi-tenant shared Jira project when any unit
resolves `private`/`memory`. Private/`memory` units require a separate Jira project per visibility tier or
reroute per PRD 043 R28/R43. Create path is fail-closed (not only init).

## Request budget (R106)

Jira composes with PRD 043 R39 and PRD 046 R81 via `planning_request_budget.py`:

| Flavor | Default max calls | JQL pagination cap |
| --- | --- | --- |
| Cloud | 300 | 5 pages |
| DC/Server | 200 | 5 pages |

429 handling uses exponential backoff + jitter — **no** `Retry-After` reliance. Partial-page abort mid-refresh
fails closed (`deliver-aborted-inconsistent`).

## Lifecycle edges (R107)

| Edge | Halt code | Recovery |
| --- | --- | --- |
| Issue move / key change (changelog) | `issue-key-changed` / `issue-transferred` | re-link by stable provider id + project key |
| Archived project (404/410) | `archived-project` | tombstone + operator remediation |
| Issue-type conversion | `issue-type-converted` | tombstone + re-create with mapped type |

Distinct from PRD 043 R37 tamper and R104 `lifecycle-drift`.

## Createmeta / field-schema probe (R108)

Init runs createmeta per mapped issue type (`planning.store.issues.issueType`, default `Task`). Required custom
fields blocking `issue-create` fail closed with a field manifest + admin remediation, or are satisfied by
allowlisted `planning.store.issues.fieldDefaults` — never a runtime 400 mid-pipeline.

## Label degradation ladder (R109)

1. **labels** (primary)
2. **components** (degraded)
3. **configured custom field** (`planning.store.issues.labelCustomField`)

Init probe validates label-write permission. PRD 043 R42 body marker remains authoritative for project
isolation regardless of label surface.
