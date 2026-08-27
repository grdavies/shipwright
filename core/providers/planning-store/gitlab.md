---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: planning.store.backend
        equals: gitlab-planning-store
    metadata:
      providerFamily: planning-store
      adapterId: gitlab-planning-store
      selectionFamily: providers
      status: spec-stub
      programPriority: P2
---

# GitLab planning-store backend (PRD 333 phase 7 — P2 spec stub)

**Status:** specification + conformance stub only — **not shipped**. Selecting
`planning.store.backend: gitlab-planning-store` MUST fail closed with `not-enabled`
until green eval-corpus and planning-store conformance evidence bind every mandatory
verb, revision/error outcome, declared degradation, and credential scope below.

This backend is distinct from the deferred `gitlab-issues` issue-store provider
(`core/providers/issues/gitlab.md`). `gitlab-planning-store` is a first-class planning
store adapter targeting GitLab Issues as the authoritative body surface when GitLab is
the sole planning host.

## Capability mapping (matrix v2.0.0)

| Verb | GitLab primitive | Revision semantics | Normalized errors |
| --- | --- | --- | --- |
| `put` | Issue create/update with body + `sw:` markers | Optimistic `if_match` on issue etag (IID revision) | `revision-conflict`, `issues-capability`, `authority-blocked` |
| `get` | Issue read (description + notes) | Read-only | `not-found`, `lifecycle-tombstone` |
| `exists` | Issue search by `unitId` marker | Read-only | `not-found` |
| `materialize` | Issue body → worktree path | `resync-on-stale-revision` when etag advances | `materialize:missing-frozen-body`, `not-found` |
| `freeze` | Labels + `sw-freeze-record` comment | Etag-gated label/comment write | `revision-conflict`, `freeze-incomplete` |

Every mandatory verb from `core/providers/planning-store/CAPABILITIES.md` MUST be
implemented or covered by an **explicit degradation** from the allowlist before any
parity claim.

## Supported degradations (pre-ship declaration)

| Degradation id | Verb | Operator notice |
| --- | --- | --- |
| `gitlab-native-links-degraded` | `put` | GitLab link types map to a reduced native-link vocabulary until parity harness green |
| `resync-on-stale-revision` | `materialize` | Re-materialize when issue etag advances after deliver resync |

Undeclared partial behavior is a conformance failure (`undeclared-degradation`).

## Credential scope (broker-only)

| Scope | Purpose |
| --- | --- |
| `api` | GitLab REST Issues CRUD, search, comments, labels |
| `read_api` | Read-only probe / doctor |

Credentials resolve only through `credentials.resolver` / `planning.store.issues.credentialRef`
— never from committed config bodies or ambient env outside a declared backend entry.
`allowedEndpoints` and `allowedProjectIds` on selector entries are mandatory; resolution
refuses out-of-scope GitLab hosts and project ids.

Minimum broker scopes: `api` (read/write). Doctor and conformance suites MUST run in
`SW_ISSUES_FIXTURE=1` hermetic mode until live promotion.

## Corpus evidence prerequisites (R11, R16)

Parity claims require binding **all** eval-corpus scenarios:

| Scenario id | Exercises |
| --- | --- |
| `planning-freeze` | Etag-gated freeze record + `sw-freeze-record` comment |
| `issue-store-materialize` | Body round-trip + materialize to worktree |
| `cross-mode-reconcile` | Store revision vs projection reconcile |

Evidence records live under `scripts/test/fixtures/planning-store-conformance/` and MUST
cite `matrixVersion: "2.0.0"`. The P2 stub adapter (`scripts/planning/backends/gitlab.py`)
exposes conformance metadata only — it cannot enter `SHIPPED_BACKENDS` or claim
`parityComplete: true`.

## Enablement gates (fail closed)

1. Green `scripts/planning/provider_conformance.py` verb suite for `gitlab-planning-store`.
2. Corpus manifest includes all three planning-store scenarios with holdout isolation.
3. Recorded conformance fixture `gitlab-planning-store.ok.json` with green dimension outcomes.
4. Explicit operator promotion in a follow-on unit — no silent registry promotion.

Until all gates are green, `register_gitlab_planning_store_stub()` reports
`status: not-enabled` and every verb returns `backend-deferred` / `not-enabled`.

## Configuration (future — not active)

| Key | Purpose |
| --- | --- |
| `planning.store.backend` | `gitlab-planning-store` (blocked pre-ship) |
| `planning.store.storeLocation` | GitLab `owner/repo` or group project path |
| `planning.store.issues.credentialRef` | Broker ref for GitLab API token |
| `planning.store.projectKey` | `sw:project:<key>` scoping label |

## Operator surfaces

```bash
python3 scripts/planning_store.py resolve-backend   # MUST NOT report shipped for stub
python3 -m planning.backends.gitlab                   # conformance metadata only
```

See also: `core/providers/planning-store/CAPABILITIES.md`, `.sw/program-priorities.json`
(`gitlab-planning-store` is first in `providerFollowOn`).
