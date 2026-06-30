---
capability:
  version: 1
  triggers:
    - type: phase_default
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

## Logging contract (R18)

Store operations log `unitId`, content hash, and backend id only — never body bytes.
