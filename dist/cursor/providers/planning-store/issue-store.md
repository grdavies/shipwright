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



## Phase 2 — artifact CRUD (R6–R12, R18, R29, R35–R36, R47)

When `issue-store` is the effective backend (no fallback), `put`/`get`/`exists`/`materialize` route to
issues — **no planning stub files** are written under `docs/` in the code repo (R7). Runtime indices live
under `.cursor/hooks/state/` only.

| Artifact | Type marker | Label |
| --- | --- | --- |
| PRD | `sw:prd` | `sw:project:<key>` |
| Gap | `sw:gap` | `sw:project:<key>` |
| Task list | `sw:tasks` | `sw:project:<key>` |
| Brainstorm | `sw:brainstorm` | `sw:project:<key>` |

Decision-class artifacts remain file-native (D8) — not routed to issue-store.

### Hermetic fixtures

Set `SW_ISSUES_FIXTURE=1` for in-memory issue adapter (CI). Clear with
`python3 scripts/planning_store.py clear-issue-fixture`.

### Concurrency (R36)

Mutations require matching `etag` preconditions; conflicts return `revision-conflict` (fail-closed).

### Canonical hash CLI

`python3 scripts/planning_store.py canonical-hash --fixture <path>`


## Phase 3 — freeze, tamper detection, materialization (R8, R13–R15, R19, R37–R41, R45–R48)

### Freeze (`freeze` CLI)

```bash
python3 scripts/planning_store.py freeze --unit-id <id> --body-path <path> [--no-distill]
```

Ordered steps (fail-closed):

1. Lock issue (`issue-lock`)
2. Apply `sw:frozen` label
3. Compute canonical content-hash (includes `sw:frozen`, excludes `sw-freeze-record` comments)
4. Write `sw-freeze-record` comment with `sw-freeze-hash: <sha256>`
5. On PRD freeze with linked brainstorm: distill rationale to memory (`research`) via
   `memory-redact`, close+link brainstorm issue (retain, never delete)
6. Distillation failure → `sw:freeze-incomplete` label; blocks `/sw-deliver`

### Tamper detection (R37)

Every `get`/`verify-frozen-hash` on a frozen issue recomputes the canonical hash and compares
to the freeze-record comment. Mismatch → `tamper-detected` (distinct from auth/outage).

```bash
python3 scripts/planning_store.py verify-frozen-hash --unit-id <id> --body-path <path>
```

`/sw-deliver` materialization calls `verify-frozen-hash` before consuming frozen task lists
(`scripts/planning_materialize.py`).

### Materialization (R8)

Frozen task-list issues materialize to `.cursor/planning-materialized/` (gitignored) with hash
verification and post-materialize `secret-scan`.

### Visibility + secret-scan (R28, R45)

All issue-store writes resolve visibility via `planning_visibility` before API calls.
`private`/`memory` units are refused against the public issue store. Every body/comment write
runs `secret-scan` (shared deny patterns with `memory-redact`).

Emission points: `issue-store-put`, `issue-store-comment`, `issue-store-freeze-record`,
`issue-store-memory-pointer`.

### Resilience (R15, R39, R41)

- Per-run API call budget: `SW_ISSUES_CALL_BUDGET` (default 500); exhaustion →
  `deliver-aborted-inconsistent`
- Exponential backoff with jitter between retries (no `Retry-After` reliance)
- Lifecycle: `IssueNotFound` / tombstone / transferred distinguished from `tamper-detected`

Issue-store mode requires network connectivity for planning operations; outages fail closed with
idempotent retry on reconnect.


## discover_units (PRD 046 R83)

`scripts/planning_discover.py` provides backend-pluggable discovery (`file` | `issue`) shared by `planning_index_gen`, `planning_graph`, `inflight_signal`, and `authoring_guard`. Issue source feeds the same visibility-resolution path before issue-mode INDEX behavior is enabled.
