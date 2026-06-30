---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: planning.store.backend
      equals: "issue-store"
  metadata:
    providerFamily: planning-store
    adapterId: issue-store
    selectionFamily: providers
---

# Issue-store planning backend (PRD 043)

Opt-in `planning.store.backend` value. Phase 1 registers the backend and resolution probes; phase 2+
wires issue CRUD. Default behavior is unchanged when unconfigured (R1).

## Configuration

| Key | Purpose |
| --- | --- |
| `planning.store.backend` | `issue-store` |
| `planning.store.issuesProvider` | `github-issues` \| `gitlab-issues` \| `jira` \| `none` |
| `planning.store.projectKey` | Project scoping key (`sw:project:<key>`) |
| `planning.store.storeLocation` | `same-repo` or `separate-project` (+ owner/repo) |
| `planning.store.issues.tokenEnv` | Dedicated issue API token env (not `host.tokenEnv`) |

Resolve helpers:

```bash
python3 scripts/planning_store.py resolve-backend
python3 scripts/planning_store.py resolve-issues
python3 scripts/planning_store.py resolve-store-location
python3 scripts/planning_store.py probe-issues-token
python3 scripts/planning_store.py validate-project-key [--register]
```

## Store location (R4)

| Mode | Authoritative repo |
| --- | --- |
| `same-repo` | Code repository (`origin` owner/repo) |
| `separate-project` | `storeLocation.owner` / `storeLocation.repo` (shared planning project) |

## Region-disposition matrix (R34)

Authoritative location per INDEX region when `issue-store` is active and fully adopted:

| Region | Phase-1 interim | Target (post-adoption) |
| --- | --- | --- |
| `structural` | file-store authoritative (gated) | issue-derived INDEX rows |
| `derived` | file-store authoritative (gated) | issue-derived lifecycle status |
| `inFlight` | deliver writer owns file tuple (PRD 032) | projected to planning store |

Until a region is issue-derived, the file-store remains authoritative and adoption is gated per phase.
Phase 1 does not migrate regions — only documents the contract.

## Fallback (R3)

Effective backend falls back to `in-repo-public` when:

- `issuesProvider` is `none`, unset, or unsupported
- `issuesProvider` is not yet shipped (`jira` until PRD 047)
- `host.provider` is `none` (local/no-remote)

Fallback emits a notice and never blocks work.

