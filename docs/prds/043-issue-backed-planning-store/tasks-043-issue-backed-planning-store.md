---
date: 2026-06-30
topic: issue-backed-planning-store
visibility: public
prd: docs/prds/043-issue-backed-planning-store/043-prd-issue-backed-planning-store.md
program: issue-backed-planning-store
frozen: true
frozen_at: 2026-06-30
---

# Tasks — PRD 043 Issue-backed planning store (core)

Generated in one pass from the frozen PRD 043 spec union (R1–R15, R18–R20, R27–R31, R33–R37,
R39–R50). Phases mirror the PRD Rollout Plan; every phase is default-inert and carries a documentation
exit-gate (R49). Dependent PRDs (044–047) own their own R-ID bands and task lists.

## Tasks

### 1. Foundation — config, provider abstraction, capability/token probes, region-disposition matrix (L)

Establishes the opt-in surface and provider plumbing with zero default behavior change.

- [ ] 1.1 Add `issue-store` planning-store config schema and enum (R1, R33)
  - **File:** `core/sw-reference/config.schema.json`, `core/sw-reference/workflow.config.example.json`
  - **Expected:** `planning.store.backend` accepts `issue-store`; sibling keys `issuesProvider`, `projectKey`, store-location, `issues.tokenEnv` validate; unset config validates byte-identically to today
  - **R-IDs:** R1, R33
- [ ] 1.2 Configure `issuesProvider` independent of code host (R2)
  - **File:** `core/sw-reference/config.schema.json`, `scripts/planning_store.py`
  - **Expected:** `issuesProvider` accepts `github-issues`/`gitlab-issues`/`jira`/`none`; resolution is independent of `host.provider`
  - **R-IDs:** R2
- [ ] 1.3 Fallback wiring to file-store (R3)
  - **File:** `scripts/planning_store.py`
  - **Expected:** `issuesProvider: none`/unsupported or `host.provider: none` falls back to file-store; never blocks; emits a documented notice
  - **R-IDs:** R3
- [ ] 1.4 Store-location resolution: same-repo vs separate planning project (R4)
  - **File:** `scripts/planning_store.py`, `core/providers/planning-store/issue-store.md`
  - **Expected:** store location resolves to code repo or a separate (possibly shared) planning project from config
  - **R-IDs:** R4
- [ ] 1.5 Issue-verb provider abstraction skeleton, REST-primary (R5, R50)
  - **File:** `core/providers/issues/CAPABILITIES.md`, `core/providers/issues/github-issues.md`, `core/providers/issues/gitlab-issues.md`, `core/providers/issues/none.md`
  - **Expected:** `issues.*` verb contract (`issue-create`/`issue-get`/`issue-update`/`issue-comment`/`issue-label`/`issue-lock`/`issue-search`) defined REST-primary; GraphQL only behind explicit capability flag for verbs lacking REST parity
  - **R-IDs:** R5, R50
- [ ] 1.6 Capability + degradation matrix per provider (R30, R31)
  - **File:** `core/sw-reference/capability-index.json`, `core/providers/issues/CAPABILITIES.md`
  - **Expected:** LCD contract (title/body/comments/state/flat-labels) documented; per-provider capability matrix; selector fails closed on absent capability with no silent partial
  - **R-IDs:** R30, R31
- [ ] 1.7 Region-disposition matrix (R34)
  - **File:** `core/providers/planning-store/issue-store.md`, `.sw/layout.md`
  - **Expected:** authoritative location per region (`structural`/`derived`/`inFlight`) stated; documented interim where a region is not yet issue-derived (file-store authoritative, adoption gated)
  - **R-IDs:** R34
- [ ] 1.8 Project-key uniqueness validation at init (R42)
  - **File:** `scripts/planning_store.py`
  - **Expected:** project keys validated globally-unique within a shared store at init; collisions rejected or namespaced
  - **R-IDs:** R42
- [ ] 1.9 Dedicated issue-store token + scope probe (R44)
  - **File:** `scripts/planning_store.py`, `core/providers/issues/CAPABILITIES.md`
  - **Expected:** `issues.tokenEnv` distinct from `host.tokenEnv`; minimum scopes documented and probed at init; fail-closed on missing/insufficient scope; fixtures sanitized of tokens/headers
  - **R-IDs:** R44
- [ ] 1.10 Phase-1 documentation exit-gate (R49)
  - **File:** `docs/guides/configuration.md`, `core/providers/host/bitbucket.md`, `README.md`
  - **Expected:** issue-store keys, fallback matrix, network-dependence, Bitbucket EOL/routing note, opt-in README note all updated before phase ship
  - **R-IDs:** R49

### 2. Core artifact store + identification + canonical serialization (L)

Create/read/update PRD/gap/task/brainstorm as issues with portable identity and concurrency safety.

- [ ] 2.1 Artifact CRUD as issues (R6)
  - **File:** `scripts/planning_store.py`, `core/providers/issues/github-issues.md`, `core/providers/issues/gitlab-issues.md`
  - **Expected:** PRD/gap/task-list/brainstorm created and managed as issues when issue-store configured
  - **R-IDs:** R6
- [ ] 2.2 Zero stub files in code repo (R7)
  - **File:** `scripts/planning_store.py`, `.sw/layout.md`
  - **Expected:** issue-store mode commits no planning stub files; projections governed by region-disposition matrix, not authored stubs
  - **R-IDs:** R7
- [ ] 2.3 Canonical serialization + content-hash (R35, R9)
  - **File:** `scripts/planning_store.py`, `core/sw-reference/canonical-serialization.md`, `scripts/tests/fixtures/canonical/`
  - **Expected:** versioned canonical form (metadata schema, body normalization, comment-chunk manifest + reassembly order, excluded comments, `sw-canonical-version`); SHA-256 over canonical form; cross-provider golden vectors; body-size limits handled via chunking
  - **R-IDs:** R35, R9
- [ ] 2.4 Identity labels, title prefix, type marker (R10)
  - **File:** `scripts/planning_store.py`
  - **Expected:** each artifact issue carries `sw:project:<key>` label (where labels exist), `[<key>]` title prefix, type label/marker (`sw:prd`/`sw:gap`/`sw:tasks`/`sw:brainstorm`)
  - **R-IDs:** R10
- [ ] 2.5 Project-scoped queries + body-marker isolation (R11, R12, R42)
  - **File:** `scripts/planning_store.py`
  - **Expected:** all queries/mutations scoped by project key; body-marker authoritative on read so prefix spoofing cannot leak/mutate another project; graceful degradation where labels weak/absent
  - **R-IDs:** R11, R12, R42
- [ ] 2.6 Brainstorm-as-issue durability (R18)
  - **File:** `scripts/planning_store.py`, `core/commands/sw-brainstorm.md`
  - **Expected:** brainstorms stored as `sw:brainstorm` issues, never git-ignored/dropped, linked to spawned PRD
  - **R-IDs:** R18
- [ ] 2.7 Portable `sw-edges` body block (R29, R47)
  - **File:** `scripts/planning_store.py`, `core/sw-reference/canonical-serialization.md`
  - **Expected:** body-encoded `sw-edges` block authoritative on conflict; native links/sub-issues best-effort projection reconciled on read; divergence beyond tolerance fails closed
  - **R-IDs:** R29, R47
- [ ] 2.8 Optimistic-concurrency preconditions (R36)
  - **File:** `scripts/planning_store.py`
  - **Expected:** all mutating verbs use ETag/`updated_at` preconditions; revision conflict fails closed with merge/halt; freeze establishes a revision checkpoint
  - **R-IDs:** R36
- [ ] 2.9 Phase-2 documentation exit-gate (R49)
  - **File:** `core/providers/planning-store/issue-store.md`, `core/commands/sw-brainstorm.md`, `core/commands/sw-prd.md`
  - **Expected:** dual-mode authoring procedures + canonical-serialization reference documented before phase ship
  - **R-IDs:** R49

### 3. Freeze + materialization + brainstorm durability + resilience (L)

Lock, content-hash, on-read tamper detection, CI verification, materialization, distillation, and fail-closed resilience.

- [ ] 3.1 Freeze: lock + label + hash-record comment (R13, R48)
  - **File:** `scripts/planning_store.py`, `core/commands/sw-freeze.md`
  - **Expected:** freeze locks issue via API, applies `sw:frozen`, records immutable content-hash in reserved `sw-freeze-record` comment; ordered atomic multi-step; memory-distillation failure flags `freeze-incomplete` and blocks deliver
  - **R-IDs:** R13, R48
- [ ] 3.2 On-read tamper detection (R37)
  - **File:** `scripts/planning_store.py`
  - **Expected:** every read detects post-freeze body/label/title mutation against recorded hash; `sw-freeze-record` marker excluded from canonicalization; auth/availability classified separately from hash mismatch
  - **R-IDs:** R37
- [ ] 3.3 CI + deliver hash verification (R14)
  - **File:** `scripts/check-gate.sh`, `scripts/planning_store.py`
  - **Expected:** CI/`/sw-deliver` fetch issue via API and verify recorded hash before consuming; mismatch fails closed, classified distinctly from auth/availability
  - **R-IDs:** R14
- [ ] 3.4 Task-list materialization to git-ignored temp (R8)
  - **File:** `scripts/planning_materialize.py`, `.gitignore`
  - **Expected:** frozen task-list issue materialized to `.cursor/planning-materialized/` with hash verification; cache never source of truth; inherits PRD 034 R8 hardening
  - **R-IDs:** R8
- [ ] 3.5 Brainstorm distillation to memory + retention (R19, R20, R27)
  - **File:** `core/skills/memory/SKILL.md`, `core/providers/recallium.md`, `core/commands/sw-freeze.md`
  - **Expected:** at freeze, rationale distilled to memory `research`/`decision` with bidirectional pointers via `memory-redact`; no raw transcript; brainstorm issue retained (closed+linked), not deleted; cross-project rationale discoverable via pointers
  - **R-IDs:** R19, R20, R27
- [ ] 3.6 Visibility fail-closed on all write paths (R28, R43)
  - **File:** `scripts/planning_store.py`
  - **Expected:** all create/update/migrate paths resolve visibility via PRD 034 resolver before any API write; unknown→private; private/`memory` refused or rerouted; issue-derived INDEX rows pass resolver (metadata-only opaque titles for private/`memory`)
  - **R-IDs:** R28, R43
- [ ] 3.7 Secret-scan chokepoint on issue writes (R45, R46)
  - **File:** `scripts/planning_store.py`, `core/providers/planning-store/issue-store.md`
  - **Expected:** secret-scan on every body/comment/pointer write; PRD 034 emission-point registry extended to issue-store paths; body overflow uses ordered comments only; external pointers forbidden for private/`memory`
  - **R-IDs:** R45, R46
- [ ] 3.8 Request-budget, backoff, and outage resilience (R15, R39, R41)
  - **File:** `scripts/planning_store.py`
  - **Expected:** per-run/per-CI call budgets, pagination ceilings, documented full-INDEX-refresh ceiling; partial failure → `deliver-aborted-inconsistent` halt + resume; exponential backoff with jitter (no `Retry-After` reliance); connectivity loss → explicit fail-closed + idempotent retry on reconnect; network-dependence documented
  - **R-IDs:** R15, R39, R41
- [ ] 3.9 Stable references + lifecycle-edge detection (R40)
  - **File:** `scripts/planning_store.py`
  - **Expected:** references stable (provider+repo/project+id+key); existence checks distinguish 404/410 tombstones from hash mismatch; transfer/type-conversion detected and fails closed with operator recovery path
  - **R-IDs:** R40
- [ ] 3.10 Phase-3 documentation exit-gate (R49)
  - **File:** `.sw/layout.md`, `core/commands/sw-freeze.md`, `core/commands/sw-doc.md`
  - **Expected:** freeze/materialization/distillation flows + region-disposition matrix updates documented before phase ship
  - **R-IDs:** R49

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R1 | 1.1 | default-inert golden: unconfigured doc→deliver byte-identical to today (SC1) |
| R2 | 1.2 | provider-enum: `issuesProvider` resolves independent of `host.provider` |
| R3 | 1.3 | fallback: `none`/unsupported/no-remote falls back to file-store, never blocks |
| R4 | 1.4 | store-location: same-repo vs separate planning project resolution |
| R5 | 1.5 | REST-primary contract: no CLI/UI; GraphQL gated behind capability flag |
| R6 | 2.1 | artifact CRUD: PRD/gap/task/brainstorm created and read back as issues |
| R7 | 2.2 | zero stub files: issue-store doc→deliver commits no planning files (SC2) |
| R8 | 3.4 | materialization: frozen task list cached to git-ignored temp, hash-verified |
| R9 | 2.3 | body-size: oversized body chunked per canonical manifest, reassembled |
| R10 | 2.4 | identity: label + `[<key>]` prefix + type marker present on issue |
| R11 | 2.5 | isolation: two project keys, zero cross-project surface/mutation (SC5) |
| R12 | 2.5 | label-absent fallback: title-prefix + body marker identifies artifact |
| R13 | 3.1 | freeze: lock + `sw:frozen` + hash-record comment written |
| R14 | 3.3 | CI verify: recorded-hash mismatch fails closed, distinct from auth/outage |
| R15 | 3.8 | token + network-dependence bounded by rate-limit/transaction model |
| R18 | 2.6 | brainstorm-as-issue: durable, linked to spawned PRD, survives wipe (SC3) |
| R19 | 3.5 | distillation: rationale to memory via `memory-redact`, no raw transcript |
| R20 | 3.5 | retention: PRD freeze closes+links brainstorm issue, never deletes |
| R27 | 3.5 | cross-project recall: rationale discoverable via memory pointers |
| R28 | 3.6 | privacy: private artifact refused against public store on create (SC6) |
| R29 | 2.7 | edges: `sw-edges` body block authoritative over native projection |
| R30 | 1.6 | LCD contract: portable core operates on title/body/comments/state/labels |
| R31 | 1.6 | capability degradation: absent capability fails closed per provider |
| R33 | 1.1 | planning.store backend: run-pinned, mutually exclusive, fail-closed precedence |
| R34 | 1.7 | region-disposition: authoritative location + documented interim per region |
| R35 | 2.3 | canonical hash golden vectors: round-trip equality on GitHub + GitLab (SC7) |
| R36 | 2.8 | concurrency: interleaved mutation+freeze detects conflict, fails closed |
| R37 | 3.2 | tamper-evidence: post-freeze edit detected on read, classified separately |
| R39 | 3.8 | resilience: rate-limit exhaustion → `deliver-aborted-inconsistent` + resume (SC9) |
| R40 | 3.9 | lifecycle: deleted/transferred/converted issue detected vs hash mismatch |
| R41 | 3.8 | connectivity loss: explicit fail-closed + idempotent retry on reconnect |
| R42 | 1.8, 2.5 | project-key uniqueness at init + body-marker spoof blocked on read |
| R43 | 3.6 | visibility resolver before write; INDEX metadata-only opaque private titles |
| R44 | 1.9 | token-scope probe: missing/insufficient scope fails closed at init |
| R45 | 3.7 | secret-scan chokepoint on every body/comment/pointer write |
| R46 | 3.7 | overflow: ordered comments only; external pointer forbidden for private |
| R47 | 2.7 | edge divergence beyond tolerance fails closed on read reconciliation |
| R48 | 3.1 | atomic freeze: distillation failure → `freeze-incomplete` blocks deliver |
| R49 | 1.10, 2.9, 3.10 | per-phase documentation exit-gate present before phase ship |
| R50 | 1.5 | GraphQL permitted only behind capability flag for non-REST-parity verbs |
| D1 | 2.6, 3.5 | brainstorm stored as issue + distilled memory pointer at freeze (memory-as-sole-home rejected) |
| D2 | 3.1, 3.3 | freeze = API lock + content-hash with network CI verify (snapshot-to-file rejected) |
| D3 | 2.4, 2.5 | identity = label + title-prefix + type; body marker authoritative for isolation |
| D6 | 3.6 | private artifact never reaches a public/shared store (privacy fail-closed) |
| D7 | 1.1, 2.2 | default unchanged, no stub files, REST-primary (default-inert regression) |
| D8 | 2.1 | decision-class artifacts excluded from issue-store routing; remain file-native (regression guard) |
| D9 | 1.2 | issuesProvider resolves independently of the code host |
| D10 | 1.1 | program split: 043 freezes independently; non-overlapping R-ID/D-ID bands across 043–047 (allocation-table audit) |
| D11 | 1.1 | issue-store is a planning.store.backend enum value, run-pinned and mutually exclusive |
| D12 | 2.3 | canonical serialization + content-hash specified normatively (cross-provider golden vectors) |
| D13 | 1.5 | REST-primary; GraphQL only behind capability flag for non-REST-parity verbs |
| D14 | 1.6 | naming hygiene: no bare "R32"; memory-boundary phrasing used in capability/docs |
