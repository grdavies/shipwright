---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: phase_default
        selectionFamily: providers
        scope: planning-store-contract
    metadata:
      providerFamily: planning-store
      selectionFamily: providers
      matrixVersion: "2.0.0"
---

# Planning store capabilities (PRD 034 / PRD 333 phase 6)

Neutral contract for planning unit body storage. Consumers call `scripts/planning_store.py`
routed by `planning.store.backend` in `workflow.config.json`.

**Matrix version:** `2.0.0` — authoritative for semantic-parity conformance evidence
(`scripts/planning/provider_conformance.py`). Parity claims MUST cite this version and bind
eval-corpus scenario identifiers; unsupported claims fail closed.

## Mandatory verb contract (R2, R16)

| Verb | Purpose | Revision semantics |
| --- | --- | --- |
| `put` | Persist a unit body | File-backed: content-hash txn id; issue-store: optimistic `if_match` etag |
| `get` | Read a unit body | Read-only; no revision mutation |
| `exists` | Probe body presence | Read-only |
| `materialize` | Copy a body into a worktree destination | May resync when store revision advances (issue-store) |
| `freeze` | Lock unit + record authoritative hash | Issue-store: etag + `sw-freeze-record` comment; file-backed: frontmatter status + hash marker |

Every shipped backend MUST implement all five verbs or declare an **explicit degradation** from the
allowlist below. Undeclared partial behavior is a conformance failure.

## Normalized error codes (R16)

| Code | Meaning | Typical verbs |
| --- | --- | --- |
| `revision-conflict` | Optimistic concurrency mismatch (`expected` vs `actual` etag) | `put`, `freeze` |
| `freeze-incomplete` | Freeze record missing or digest mismatch | `freeze`, `verify_frozen_hash` |
| `lifecycle-tombstone` | Unit archived/transferred/tombstoned | `get`, `freeze` |
| `issues-capability` | Provider lacks required issue verb | `put`, `freeze` |
| `not-found` | Body absent at canonical path | `get`, `exists`, `materialize` |
| `materialize:missing-frozen-body` | Frozen unit has no materializable body | `materialize` |
| `backend-deferred` | Backend id is present-but-inert | all |
| `authority-blocked` | Kill-switch / read-only / identity mismatch | all writes |

Errors surface as typed JSON (`verdict: fail`, `code: <normalized>`) — never silent downgrade.

## Per-backend capability and degradation matrix (R2, R11, R13, R16)

Selector requires the verb; absent capability without a declared degradation → fail-closed halt.

| Verb / feature | in-repo-public | local-synced | planning-cache | issue-store | private-repo | encryption-at-rest |
| --- | --- | --- | --- | --- | --- | --- |
| `put` | file txn | local folder txn | cache round-trip | issue CRUD + etag | **deferred** | **deferred** |
| `get` | file read | local folder read | cache round-trip | issue read | **deferred** | **deferred** |
| `exists` | `is_file` | `is_file` | cache probe | issue search | **deferred** | **deferred** |
| `materialize` | `copy2` | `copy2` | cache → dest | issue body → dest | **deferred** | **deferred** |
| `freeze` | **degraded** frontmatter-hash | **degraded** frontmatter-hash | **degraded** projection-mirror | etag + freeze record | **deferred** | **deferred** |
| Optimistic revision | content-hash txn | content-hash txn | provider etag | issue etag | — | — |
| Redaction chokepoint | — | — | memory adapter | issue write guard | — | — |
| Separate-project mode | n/a | n/a | n/a | store projection skip | — | — |

### Explicit degradation allowlist (exhaustive)

| Degradation id | Backend(s) | Verb | Operator notice |
| --- | --- | --- | --- |
| `frontmatter-hash-authoritative` | `in-repo-public`, `local-synced` | `freeze` | Freeze hash lives in frontmatter; no issue lock |
| `projection-mirror-not-authority` | `planning-cache` | `freeze` | Projection mirrors freeze; canonical hash remains store-backed |
| `resync-on-stale-revision` | `issue-store` | `materialize` | Re-materialize when etag advances after deliver resync |
| `backend-deferred-inert` | `private-repo`, `encryption-at-rest` | all | Seam present; returns `backend-deferred` without mutation |

Undeclared degradations MUST NOT be used to claim semantic parity. Conformance evidence binds
eval-corpus scenario ids (`issue-store-materialize`, `cross-mode-reconcile`, `planning-freeze`, …)
via `scripts/planning/provider_conformance.py`.

## Interface (legacy summary)

| Op | Purpose |
| --- | --- |
| `put` | Persist a unit body |
| `get` | Read a unit body |
| `exists` | Probe body presence |
| `materialize` | Copy a body into a worktree destination |
| `freeze` | Lock unit + freeze record |

## Shipped backends

| Backend | Id | Notes |
| --- | --- | --- |
| In-repo public | `in-repo-public` | Default; bodies live at tracked repo paths |
| Local/synced | `local-synced` | Bodies in operator-local folder (convenience-not-security) |
| Planning cache | `planning-cache` | Replicated cache with optional remote sync (PRD 091) |
| Issue store | `issue-store` | Opt-in; issue-backed bodies with etag revision (PRD 043) |

Deferred seam backends (`private-repo`, `encryption-at-rest`) are present-but-inert — they return
`backend-deferred` for every verb and cannot claim parity.

## Authority states (PRD 082 R26)

Resolution via `scripts/planning_authority.py` reports only the **configured** backend. There is **no silent fallback** to a substitute backend id — unavailable or mismatched authority yields a typed refusal instead of routing writes elsewhere.

| `authorityState` | Typical `writeDisposition` | Operator effect |
| --- | --- | --- |
| `online` | `accept` | Reads and substantive writes proceed when policy permits |
| `read-only` | `refuse-substantive` | Reads allowed; substantive writes refused (e.g. kill-switch / `planning_backend_control.py disable`) |
| `blocked` | `refuse-substantive` | Reads and writes blocked with typed reason and guidance (issues provider unavailable, identity mismatch, ambiguous authority, store unavailable) |

Projection-only writes may map to `refuse-ledger` under policy — substantive refusals are recorded in the
operator-local refusal ledger (`.cursor/sw-refusal-ledger` by default). Reconciling a refused write remains a
human decision.

**Fail-closed remote sync (PRD 091 R2):** `has_configured_remote_planning_authority` detects a configured remote sync endpoint for the planning-cache backend. Sync failure then surfaces via the projection outbox as blocking dirty/refused state; absence of remote authority preserves local-only behavior with no new failure.

Authority mutations drain the durable projection **outbox** (`planning_projection_ledger.py`, PRD 090 R5):
pending destination events carry derived dirty state and retry across outages without silent fallback to
another backend.

## Document-review transport (PRD 341 R28 / R29)

Issue-store document review is a **facade** on `scripts/planning_store_facade.py` (`post_review_finding`,
`open_review_manifest`, `read_review_manifest`, `verify_review_manifest`, `complete_review_round`).
Provider-specific parsing and HTTP transport stay inside issue-provider adapters
(`core/providers/issues/*`, `scripts/planning/providers/*`). Marker validation, identity policy,
revision fallback, manifest lifecycle, drift detection, and idempotency remain provider-neutral.

| Backend / issues provider | Document-review posture |
| --- | --- |
| `issue-store` + `github-issues` (conformance-green) | Enabled after `docReviewComments` preflight |
| `issue-store` + any other issues provider | `doc-review-provider-unsupported` at preflight |
| Non-`issue-store` backends | In-IDE file-store transport unchanged (R33) — no issue comment facade |

Request budget: listing and revalidation charge `planning.store.requestBudget` under class
`document-review`. Pagination-depth or call-ceiling exhaustion is typed (`doc-review-budget-exhausted`).
Local `.cursor/doc-review-runs/` cache is non-authoritative — it cannot authorize open or complete.

## Logging contract (R18)

Store operations log `unitId`, content hash, and backend id only — never body bytes.
