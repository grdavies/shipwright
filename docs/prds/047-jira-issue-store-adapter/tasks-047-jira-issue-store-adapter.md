---
date: 2026-06-30
topic: jira-issue-store-adapter
prd: docs/prds/047-jira-issue-store-adapter/047-prd-jira-issue-store-adapter.md
program: issue-backed-planning-store
frozen: true
frozen_at: 2026-06-30
visibility: public
---

# Tasks — PRD 047 Jira issue-store adapter

Single-pass task list from the frozen PRD 047 spec union (R100–R109 band; decisions D25–D27) plus the owned
core carry-forward R32a/R32b. Phases mirror the PRD Rollout Plan (Cloud-first, DC/Server gated on demand)
with a per-phase documentation-impact gate backed by `run-planning-047-doc-impact-fixtures.sh` (PRD 043 R49).
Satisfies the PRD 043 contracts (LCD, capability matrix, canonical hash, tamper-evidence, budget, token
model) without re-specifying them; inert for non-issue-store users.

## Tasks

### 1. Jira Cloud adapter, canonicalization, placement, freeze-decoupling (L)

REST-primary Cloud adapter implementing the PRD 043 `issues.*` verbs with render-independent freeze hashing.

- [x] 1.1 Jira `issues.*` adapter + LCD mapping (R32a)
  - **File:** `core/providers/issues/jira.md`, `core/providers/issues/CAPABILITIES.md`
  - **Expected:** Jira REST implements PRD 043 `issues.*` verbs; LCD mapping (title→summary, body→description, comments, open/closed→status category, flat labels→labels); `issue-lock` registered as degraded (hash-authoritative, R104)
  - **R-IDs:** R32a
- [x] 1.2 Cloud-vs-DC parity/degradation matrix (R100)
  - **File:** `core/providers/issues/CAPABILITIES.md`, `core/sw-reference/capability-index.json`
  - **Expected:** per-verb Cloud-vs-DC/Server parity matrix (endpoint/auth/serialization/capability splits) behind a Jira-flavor capability flag; Jira links/sub-tasks mapped to PRD 043 R29 edges + PRD 046 R23 hierarchy (consumed, not owned)
  - **R-IDs:** R100
- [x] 1.3 Canonical hash for ADF/wiki, post-refetch (R102, D27)
  - **File:** `core/providers/issues/jira.md`, `scripts/tests/fixtures/canonical/jira/`
  - **Expected:** ADF (Cloud)/wiki (DC) normalized to canonical markdown subset; freeze hash over post-write re-fetched canonical form so benign server re-serialization is absorbed (no false PRD 043 R37 tamper); out-of-subset drift classified distinctly + fails closed; secret-scan (PRD 043 R45) on post-normalization plaintext; Jira golden vectors incl. server-mutated-ADF round-trip
  - **R-IDs:** R102
- [x] 1.4 Artifact placement for single description field (R103)
  - **File:** `core/providers/issues/jira.md`
  - **Expected:** description carries artifact markdown + PRD 043 R29 `sw-edges` + R42 body marker in ADF-safe fence; PRD 043 R13 freeze-record in write-once custom field/description footer (reserved marker, excluded from canonicalization); R46 overflow in ordered comments pinned by immutable comment IDs; missing freeze-record/deleted overflow = PRD 043 R40 tombstone, not hash mismatch
  - **R-IDs:** R103
- [x] 1.5 Freeze decoupled from Jira status (R104, D26)
  - **File:** `core/providers/issues/jira.md`, `core/commands/sw-freeze.md`
  - **Expected:** `sw:frozen` label + content-hash authoritative for immutability; status read for display + probed for workflow constraint; external/automation transition of a frozen issue = `lifecycle-drift` halt (distinct from PRD 043 R37); `issue-lock` degrades to hash-authoritative tamper-evidence
  - **R-IDs:** R104
- [x] 1.6 Phase-1 documentation exit-gate (PRD 043 R49)
  - **File:** `docs/guides/configuration.md`, `core/providers/planning-store/issue-store.md`
  - **Expected:** doc-impact fixture asserts Jira config keys + canonicalization/placement docs updated before phase ship
  - **R-IDs:** R32a

### 2. DC/Server variant + auth, visibility, field, budget, lifecycle probes (L)

Self-hosted variant and fail-closed init/create probes for auth, privacy, required fields, budget, and lifecycle edges.

- [x] 2.1 Auth + min-scope init probe (R101)
  - **File:** `core/providers/issues/jira.md`, `core/commands/sw-init.md`
  - **Expected:** dedicated PRD 043 R44 `issues.tokenEnv` (never `host.tokenEnv`); Cloud email+API-token, DC/Server PAT required + password/basic rejected; min project+write scopes documented and probed at init (fail-closed)
  - **R-IDs:** R101
- [x] 2.2 No per-issue privacy → reject/reroute (R105)
  - **File:** `core/providers/issues/jira.md`, `scripts/planning_store.py`
  - **Expected:** init probe rejects a multi-tenant shared Jira project when any unit resolves `private`/`memory`; matrix marks per-issue privacy unsupported; private/`memory` require a separate Jira project per tier or reroute per PRD 043 R28/R43 (fail-closed on create, not only init)
  - **R-IDs:** R105
- [x] 2.3 Jira request-budget binding (R106)
  - **File:** `core/providers/issues/jira.md`, `scripts/planning_store.py`
  - **Expected:** Cloud vs DC rate-limit ceilings, JQL pagination caps, 429 handling without `Retry-After` reliance (exponential backoff + jitter); per-run/per-CI budgets; partial-page abort → `deliver-aborted-inconsistent`; resilience fixtures for 429 exhaustion + partial-page abort
  - **R-IDs:** R106
- [x] 2.4 Lifecycle edge detection (R107)
  - **File:** `core/providers/issues/jira.md`, `scripts/planning_store.py`
  - **Expected:** issue move/key change (via changelog), archived-project 404/410, issue-type conversion each classified as distinct tombstone/transfer halt codes with recovery path, keyed on stable provider id + project key (PRD 043 R40)
  - **R-IDs:** R107
- [x] 2.5 Createmeta / field-schema probe (R108)
  - **File:** `core/providers/issues/jira.md`, `core/commands/sw-init.md`
  - **Expected:** init createmeta/field-schema probe per mapped issue type; required custom fields blocking `issue-create` fail closed with field manifest + admin remediation, or satisfied by allowlisted configured defaults; never a runtime 400 mid-pipeline
  - **R-IDs:** R108
- [x] 2.6 Label degradation ladder (R109)
  - **File:** `core/providers/issues/jira.md`, `core/providers/issues/CAPABILITIES.md`
  - **Expected:** labels (primary) → components (degraded) → optional configured custom field; init probe validates label-write permission; PRD 043 R42 body marker authoritative for isolation regardless of label surface
  - **R-IDs:** R109
- [x] 2.7 Phase-2 documentation exit-gate (PRD 043 R49)
  - **File:** `core/sw-reference/capability-index.json`, `core/commands/sw-init.md`
  - **Expected:** doc-impact fixture asserts DC/Server + probe behavior docs + capability-index regen before phase ship
  - **R-IDs:** R101

### 3. Bitbucket guidance + acceptance suite + doc-impact gate (M)

End-to-end Bitbucket→Jira (and Bitbucket→separate-project) acceptance and the cross-provider conformance gate.

- [x] 3.1 Bitbucket guidance wiring + end-to-end acceptance (R32b, D25)
  - **File:** `core/providers/host/bitbucket.md`, `scripts/tests/run-planning-047-doc-impact-fixtures.sh`
  - **Expected:** `host.provider == bitbucket` with unset `issuesProvider` emits Jira / separate-planning-project guidance (PRD 043 Phase 1) and never falls back to native Bitbucket issues; Bitbucket→Jira and Bitbucket→separate-project paths work end to end; default = separate GH/GL project, Jira opt-in, Cloud first (D25)
  - **R-IDs:** R32b
- [x] 3.2 Cross-provider conformance against Jira fixtures
  - **File:** `scripts/tests/run-planning-047-conformance.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** PRD 043 cross-provider acceptance suite passes against recorded Jira Cloud + DC/Server fixtures; verb mapping + degradation (incl. degraded `issue-lock`) asserted
  - **R-IDs:** R32b
- [x] 3.3 Phase-3 documentation exit-gate (PRD 043 R49)
  - **File:** `docs/guides/workflows.md`, `docs/guides/commands.md`
  - **Expected:** doc-impact fixture asserts Bitbucket EOL/routing + Jira workflow notes updated before phase ship
  - **R-IDs:** R32b

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R32a | 1.1 | PRD 043 cross-provider suite runs against Jira Cloud/DC fixtures; degraded `issue-lock` asserted |
| R32b | 3.1, 3.2 | Bitbucket + unset issuesProvider emits Jira/separate-project guidance; Bitbucket→Jira end to end |
| R100 | 1.2 | per-verb Cloud-vs-DC parity matrix behind Jira-flavor flag; links/sub-tasks → R29/R23 |
| R101 | 2.1 | missing scope / DC password-only auth fails closed at init; dedicated issues.tokenEnv |
| R102 | 1.3 | freeze→server re-serializes ADF→re-fetch→hash stable (no false tamper); out-of-subset edit fails closed |
| R103 | 1.4 | freeze-record in custom field/footer survives comment purge; overflow reassembles by immutable comment ID; deleted overflow = tombstone |
| R104 | 1.5 | external automation transition of `sw:frozen` issue → `lifecycle-drift` (distinct from R37); hash authoritative |
| R105 | 2.2 | shared Jira project with a private unit refused + rerouted at init and create |
| R106 | 2.3 | 429 exhaustion + partial-page abort fail closed without `Retry-After` reliance |
| R107 | 2.4 | issue move/archive/type-conversion classified as correct tombstone/transfer code |
| R108 | 2.5 | required custom field fails closed at init with manifest + remediation; never runtime 400 |
| R109 | 2.6 | label degradation ladder; body marker authoritative for isolation regardless of label surface |
| D25 | 3.1 | Bitbucket default = separate GH/GL planning project; Jira opt-in; Cloud-first, DC on validated demand |
| D26 | 1.5 | freeze decoupled from Jira status; `sw:frozen` + hash authoritative; issue-lock degrades |
| D27 | 1.3 | freeze hash over post-write re-fetched canonical form; Jira golden vectors (server-mutated ADF) |
