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
---

# Planning store capabilities (PRD 034)

Neutral contract for planning unit body storage. Consumers call `scripts/planning_store.py`
routed by `planning.store.backend` in `workflow.config.json`.

## Interface

| Op | Purpose |
| --- | --- |
| `put` | Persist a unit body |
| `get` | Read a unit body |
| `exists` | Probe body presence |
| `materialize` | Copy a body into a worktree destination |

## Shipped backends

| Backend | Id | Notes |
| --- | --- | --- |
| In-repo public | `in-repo-public` | Default; bodies live at tracked repo paths |
| Local/synced | `local-synced` | Bodies in operator-local folder (convenience-not-security) |
| Memory | `memory` | Adapter-only; redaction chokepoint on read+write |
| Issue store | `issue-store` | Opt-in; PRD 043 — phase 1 delegates to in-repo-public until issue CRUD (phase 2) |

Deferred seam backends (`private-repo`, `encryption-at-rest`) are present-but-inert in v1.

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

Authority mutations drain the durable projection **outbox** (`planning_projection_ledger.py`, PRD 090 R5):
pending destination events carry derived dirty state and retry across outages without silent fallback to
another backend.

## Logging contract (R18)

Store operations log `unitId`, content hash, and backend id only — never body bytes.
