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
- `host.provider` is `none` (local/no-remote)

Fallback emits a notice and never blocks work.

Jira adapter (PRD 047): see `core/providers/issues/jira.md` for Cloud/DC configuration, canonical
hash (ADF/wiki post-refetch), artifact placement, and freeze decoupled from Jira status.



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

### Provider-native labels + human-readable titles (R11)

Structural frontmatter keys (`type` / `unit-id` / `status` / `topic` / `depends` / `absorbs` / `amends` /
`visibility`) are promoted to provider-native labels on every `put()`
(`planning_canonical.structural_labels_from_content`), in addition to the artifact `sw:<type>` and
`sw:project:<key>` labels above:

| Key | Label prefix |
| --- | --- |
| `unit-id` | `sw:unit:<url-encoded-unit-id>` |
| `topic` | `sw:topic:<url-encoded-topic>` |
| `visibility` | `sw:visibility:<value>` |
| `depends` / `absorbs` / `amends` | `sw:<rel>:<url-encoded-target>` (capped at `MAX_EDGE_LABELS_PER_RELATION` = 20 labels/relation per provider) |

Issue titles are human-readable (`planning_canonical.human_readable_title`): the doc's frontmatter `title:`
key, else its first H1 heading, else a plain `<type>: <unit-id>` fallback — never the legacy
`[project] type:unit-id` bracketed prefix. The provider-assigned issue id/number is a storage pointer only;
`unit-id` (from the `sw-unit-id` body marker, or the `sw:unit:*` label) remains authoritative for identity.

**Body stays authoritative for content.** Labels are an *additive* discovery/read-performance projection —
the doc's own frontmatter block and the authoritative `sw-edges` body fence are unchanged and still fully
embedded in the issue body (edge labels are a search aid only; `sw-edges` is the source of truth for edge
reads, same precedence as native links above). Read/discover paths (`planning_github_client.py`,
`planning_jira_client.py`, `planning_discover.py`) prefer the label projection and fall back to the pre-R11
body-marker/frontmatter parse for one release, so issues written before R11 remain fully readable without a
migration step.

**Backfill.** `IssueStoreBackend._maybe_backfill_labels` opportunistically adds the missing `sw:unit:*` /
`sw:<type>` labels to a pre-R11 issue the first time it is resolved through `get`/`put` (best-effort — a
frozen or put-incomplete issue, a stale etag, or a provider error leaves the issue untouched and is simply
retried on a later read).

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


## Phase 2 — derived INDEX scheduler + budget + cache (R25, R81–R86, R93)

| Component | Script | Contract |
| --- | --- | --- |
| Scheduler | `planning_scheduler.py next` | `/sw-deliver next` schedules from issue labels (`sw:tier:*`, `sw:priority:*`); refuses `index-incomplete` |
| Request budget | `planning_request_budget.py` | Shared ledger; composes with R39/R74; scheduler reserve |
| Query cache | `planning_query_cache.py` | Post-redaction projections only; key `projectKey + fingerprint + generationEpoch` |
| Redaction | `planning_index_gen.index_row_dict` | Private/memory opaque at ingest (`{id}: [private]`) per R82 |

Per-provider `cacheTtlSeconds` (default 300) bounds query-cache TTL floor (R85). Poll-on-reconcile invalidation runs at deliver run-start and `/sw-deliver next` (R85). Secret-scan runs on
issue ingest before cache write (R45/R84). Pagination ceiling with remaining results → `index-incomplete`
fail-closed (R86).


## Native provider links (PRD 056 R1–R4)

When `issue-store` is effective, issues adapters forward `native_links` on create/update and return them on
read for `planning_canonical.reconcile_edges`. The canonical `sw-edges` block in the issue body remains
authoritative on conflict; native links are UI projections only.

| Provider | Client | Capability probe |
| --- | --- | --- |
| `github-issues` | `planning_github_client.py` | `probe-issues-token` → `nativeLinksCapable`; sub-issue REST or comment `cross-reference` fallback |
| `gitlab-issues` | `planning_gitlab_client.py` | Same probe field; GitLab issue-link API |
| `jira` | `planning_jira_client.py` | Issue-link create; default link name from createmeta / `planning.store.issues.linkDefaults` |

`planning_canonical.native_links_from_edges(edge_list, index, project_key=…)` resolves unit ids to issue ids.
Wired on migration create, gap capture, hierarchy sub-issue create, and edge reconciliation.

**Degradation (R3):** missing link capability or API 403/404 → one stderr JSON notice per run
(`notice: native-links-degraded`); mutations that do not require links continue. Never blocks deliver on link
failure alone.

```bash
python3 scripts/planning_store.py probe-issues-token
```


## Deliver progress sync (PRD 056 R5–R7)

Requires issue-store effective and a prior hierarchy apply (non-dry-run `planning_hierarchy`).

| Step | Entry | Behavior |
| --- | --- | --- |
| Provision | `planning_progress.provision_deliver_hierarchy` (from `wave_deliver_loop` phase provision) | Creates epic + phase sub-issues; stores `hierarchyMap` on deliver state |
| Phase green | `planning_progress.sync_phase_done` (from `wave_merge.py` status collect) | Adds `sw:phase:<phaseId>:done` label to mapped sub-issue |
| Checkbox | `planning_progress.propagate_checkbox_to_issue_store` (from acceptance / execute status) | Rewrites sub-issue body from frozen task-list phase section |

Skipped entirely when `resolve_effective_backend` ≠ `issue-store`. Label/body capability gaps emit
`progress-label-degraded` / `progress-body-degraded` once per run (deliver continues).

Deliver state field: `hierarchyMap` with `epicIssueId`, `phases`, `unitId`, `provider`, `projectKey`.


## Living-docs derived projection (PRD 056 R8)

When cutover authority for region `derived` is `issue`, `planning_index_issue.project_index_status` writes
PRD INDEX status to the planning store (`planning-index-derived` unit) instead of mutating
`docs/prds/INDEX.md`. Invoked from `wave_living_docs.py reconcile`. File-store repos and `derived=file`
authority are unchanged (R9).

```bash
python3 scripts/planning_index_issue.py project-index-status --prd <n> --status <not-started|in-progress|complete>
```
