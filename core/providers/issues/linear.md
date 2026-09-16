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

Linear GraphQL `Issue.description` and `Comment.body` are GraphQL `String` fields
(Unicode characters, not UTF-8 bytes). Linear developer docs do not publish a maximum
length for either field ([GraphQL getting started](https://linear.app/developers/graphql);
[GraphQL String](https://spec.graphql.org/October2021/#sec-String)). Recorded pin
(`planning_canonical.LINEAR_SIZE_PIN`): conservative operational cap is `BODY_SIZE_LIMIT`
(60_000 UTF-8 bytes) for **both** description and comment until a live-probe receipt
records a tighter distinct cap. Linear-aware splitter work must not ship without this pin.

Linear descriptions chunk via `planning_canonical.chunk_body_if_needed(provider="linear")`,
which delegates to `planning_linear_canonical.chunk_body_for_linear` after
`require_linear_size_pin()`. Oversized bodies are split into:

1. Head description with `<!-- sw-chunk-manifest: … -->`
2. Ordered overflow comments marked `<!-- sw-chunk-overflow -->` plus
   `<!-- sw-chunk-token:<writeToken> -->` in the comment body (R11 actor binding)

There is no ADF-style tighter cap (unlike Jira Cloud). Reassembly uses immutable comment IDs in the
manifest (positional fallback only when ids are synthetic placeholders).

## Dual budgets (R13)

Request-count and GraphQL complexity points are tracked in `planning_request_budget`.
GraphQL `extensions.code: RATELIMITED` is handled in addition to HTTP 429.
Complexity-aware query planner splits work under the ~10k points/query cap.

## Batch create foot-gun (R14)

`issueBatchCreate` inputs MUST use `{ "issues": [ ... ] }`. A bare issues array silently
creates zero issues and is rejected by `validate_batch_create_input`.

## Operator projection contract (PRD 061 prerequisite, R33, R34)

Linear is both the LCD issue-store **and** the operator browse projection for planning units.
Implementation MUST consume the merged-green PRD 061 facade/projection contract — it does not
recreate or bypass that surface.

### Setup

| Step | Action |
| --- | --- |
| 1 | Set `planning.store.issuesProvider: linear` with `teamKey` or `teamId` |
| 2 | Configure `planning.store.operatorProjection.linear` (`enabled`, `initiativeSubstitute`, `budget`) |
| 3 | Probe readiness: `python3 scripts/planning_linear_client.py . prd061-readiness-gate` |
| 4 | Activate Team-scoped token via `planning.store.issues.credentialRef` (broker-only; never commit tokens) |

Preflight reports `prd061-readiness-gate` `verdict: ready` when plugin-owned PRD 061 tests pass **or** packaged Linear conformance is green. Consumer repos are not required to vendor Shipwright `unit_tests`. Hermetic fixture harnesses (`SW_ISSUES_FIXTURE=1` or injected fixture
store) may skip the live gate for unit tests only.

### PRD 061 prerequisite (R34)

| Gate | Acceptance test (plugin/source tree) |
| --- | --- |
| Facade contract | `scripts/unit_tests/planning/harness_planning_061_facade.py` |
| Projection contract | `scripts/unit_tests/planning/test_planning_061_github_projects.py` |

In-repo Shipwright checkouts run those tests from the plugin/source tree. Packaged installs omit `unit_tests` and treat green Linear conformance (`core/sw-reference/provider-conformance/linear.ok.json`) as sufficient. Partial readiness (one test present and red) still blocks with `prd061-readiness-blocked`.

## Semantic entity mapping

Portable semantic graph is the **semantic-store authority**; Linear entities are rebuildable
projection mirrors (`semantic-store authority`). LCD Issues remain the canonical body/hash path
for freeze when Linear is the issue-store.

| Artifact | Linear entity | Browse role |
| --- | --- | --- |
| PRD | **Project** | Program/PRD status, requirements summary, absorbed gaps, attached brainstorms |
| Brainstorm | **Document** | Linked to PRD Project; not freeze authority |
| Gap | **Issue** + `Gap` label | Project membership + lifecycle/prerequisite metadata |
| Phase | **Milestone** | Phase delivery status and dependency order on PRD Project |
| Task | **Issue** (sub-issue) | Milestone membership, task ref, R-IDs, completion status |
| Program | **Initiative** (or substitute views) | Cross-PRD backlog/in-flight/done (R1 question 4) |
| Cycle wave | **Cycle** (issue assignment only) | Wave time-box; orthogonal to Milestone membership |

**LCD issue+labels-only is explicitly insufficient (gap-079).** Mapping every planning unit to a
flat Issue with labels only — without Project/Document/Milestone hierarchy — fails
`gap079-linear-ui-answerability` with `linear-lcd-labels-only-rejected`.

Edge encodings (no stub Issue endpoints for non-Issue sources):

| Edge | Encoding |
| --- | --- |
| `absorbs` | Project membership + Gap label/field |
| `feeds` | Document attachment + project metadata |
| `depends` | Native IssueRelation between Issue endpoints |

## Rebuild semantics and semantic authority

| Rule | Detail |
| --- | --- |
| Authority | Portable semantic graph / semantic store (`freezeAuthority: portable-graph`) |
| Projection | Rebuildable; `isSourceOfTruth: false` on Project/Document/Milestone/Initiative/Cycle |
| Freeze/hash | LCD Issue or explicit Document-backed body only — never projection mirrors |
| Rebuild entry | `reconcile_linear_operator_projection_from_semantic_store` (resumable steps: prd-brainstorm-gap → phases → tasks → tombstone) |
| Drift | `owned_fields_digest` compare; fail closed unless `overwrite_drift: true` with audit |
| Tombstone | Entities absent from semantic authority are tombstoned; no duplicate Projects per `unit-id` |
| Split brain | `projection-prefer` and projection-mirror freeze claims fail closed |

CLI/schema surfaces:

```bash
python3 scripts/planning_store.py linear-projection-schema
python3 scripts/planning_linear_client.py . operator-browse-checklist-gate
```

## Linear UI operator browse checklist (R33)

Operator browse questions MUST be answerable from Linear list/board/card metadata **without
opening markdown bodies** (`body-open-is-failure`). Saved views below are required operator
setup (or documented equivalents).

### PRD browse questions (no markdown body)

| Question | Linear surface | Saved view / filter | Card-visible fields |
| --- | --- | --- | --- |
| Which gaps does this PRD absorb? | Project detail + linked Gap Issues | `gap-by-prd-project` | `projectMembership`, `gapLabelOrField`, `gapIssueIdentity` |
| Which brainstorms feed this PRD? | Project detail + attached Documents | `documents-by-project` | `documentAttachmentOrMembership`, `brainstormIdentity`, `prdProjectLink` |
| What is task/phase completion? | Project Milestones + task Issues | `tasks-by-milestone` | `issueSemanticStatus`, `milestonePhaseMembership`, `milestoneProgress` |
| Program backlog / in-flight / done? | Initiative **or** substitute Team/Project views | `program-backlog`, `program-in-flight`, `program-done` | `initiativeOrProgramDiscriminator`, `programSemanticStatus`, `substituteViewsOrFilters` |

### Gap browse questions (no markdown body)

| Question | Linear surface | Saved view / filter | Card-visible fields |
| --- | --- | --- | --- |
| Which PRD absorbs this gap? | Gap Issue on PRD Project | `gap-by-prd-project` | `projectMembership`, `gapLabelOrField`, `gapIssueIdentity` |
| Gap lifecycle and prerequisites? | Gap Issue list | `gaps-open` / `gaps-absorbed` | `lifecycle`, `prerequisites`, `absorbs` |
| Is this gap blocked on another unit? | Gap Issue relations | `gap-depends` | `issueRelation`, `prerequisiteUnitIds` |

### Task browse questions (no markdown body)

| Question | Linear surface | Saved view / filter | Card-visible fields |
| --- | --- | --- | --- |
| Which phase owns this task? | Task sub-issue Milestone membership | `tasks-by-milestone` | `milestonePhaseMembership`, `taskRef`, `phaseId` |
| Task completion and traceability? | Task Issue board by status | `tasks-by-status` | `issueSemanticStatus`, `completionStatus`, `rIds`, `scenarios` |
| Sub-task hierarchy? | Parent/child Issue tree | `task-subissues` | `parentIssueId`, `subIssue`, `taskRef` |

Acceptance gate:

```bash
python3 scripts/test/run_pytest.py scripts/unit_tests/planning/test_prd339_linear_operator_browse.py
```

Live probe (after PRD 061 green):

```bash
python3 scripts/planning_linear_client.py . operator-browse-checklist-gate
```

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

## Community-triage promotion (PRD 086 R2 / D1)

Linear was promoted to `SHIPPED_ISSUES_PROVIDERS` without a full local dogfood pass across every
Linear Team/workspace permutation. The maintainer relies on community-reported issues triaged and
fixed as they surface against real Linear workspaces, rather than blocking promotion on exhaustive
pre-ship coverage of all Team/Cycle/Initiative combinations.

Recorded gate evidence for this promotion lives in committed fixtures under
`scripts/test/fixtures/planning-linear-stage1-promotion/` (`stage1-dogfood-gate.ok.json`,
`oauth-docs-gate.ok.json`). Re-check live gates via:

```bash
python3 scripts/planning_linear_client.py . promotion-gate-evidence
```

Both recorded fixtures and live `stage1-dogfood-gate` / `oauth-docs-gate` runs must return
`verdict: ok` before promotion or re-promotion.

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
