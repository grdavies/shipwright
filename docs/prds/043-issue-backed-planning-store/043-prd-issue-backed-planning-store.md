---
date: 2026-06-30
topic: issue-backed-planning-store
visibility: public
brainstorm: docs/brainstorms/2026-06-30-issue-backed-planning-store-requirements.md
program: issue-backed-planning-store
depends: []
frozen: true
frozen_at: 2026-06-30
---

# PRD 043 — Issue-backed planning store (core)

## Overview

This is the **core** PRD of the issue-backed planning store program. It introduces an **optional**
planning-store mode — `issue-store` — that relocates Shipwright planning artifacts (PRDs, gap units, task
lists, brainstorms) into a git provider's **issue-management system**, reached through **REST-primary**
provider APIs, while leaving the default file-based pipeline byte-for-byte unchanged. Core covers the
foundation every dependent PRD builds on: configuration and the PRD 034 `planning.store` integration, the
provider abstraction with GitHub/GitLab adapters, the region-disposition contract, canonical body
serialization and content-hash, the core artifact store and identification, freeze and verification,
brainstorm durability and distillation, concurrency and lifecycle safety, and the security model.

Dependent PRDs extend core without re-opening it: **044** (migration), **045** (dev-tracking / workflow),
**046** (planning-graph derivation, scheduler, derived INDEX), and **047** (Jira adapter). Decision-class
artifacts remain file-native on the PRD 015 memory-boundary (D8) and are out of scope.

## Program

This PRD is part of a program (D10) split from a single program-scale draft on the recommendation of the
`/sw-doc-review` persona panel. Core R-IDs R1–R32 originate in the shared brainstorm and R33–R50 from the
panel synthesis; they are partitioned so each lives in exactly one PRD. Hardening requirements discovered
during the per-PRD panels are allocated **new R-IDs above R50** in non-overlapping per-PRD bands. This table
is the authoritative allocation for the whole program; a dependent PRD **references** a core R-ID it does not
own (e.g. PRD 046 references this PRD's R27 recall and R34 region-disposition contracts) and never restates
or re-owns it.

| PRD | Scope | Owns core R-IDs (R1–R50) | New hardening R-IDs (>R50) | Decisions | Depends on |
|-----|-------|--------------------------|----------------------------|-----------|------------|
| 043 (this) | Core foundation | R1–R15, R18–R20, R27–R31, R33–R37, R39–R50 | — | D1–D14 | — |
| 044 | Migration | R16, R17, R38 | R52–R66 | D15–D18 | 043 |
| 045 | Dev-tracking / workflow | R21, R22, R24, R26 | R67–R79 | D19–D21 | 043 |
| 046 | Planning-graph derivation | R23, R25 | R80–R99 | D22–D24 | 043, 044, 045 |
| 047 | Jira adapter | R32 | R100–R115 | D25+ | 043 |

## Goals

- Provide an opt-in `issue-store` planning-store mode that is byte-for-byte inert when unconfigured (R1; SC1).
- Author and manage PRD/gap/task/brainstorm artifacts as provider issues via REST-primary access (R5/R6/R50).
- Make brainstorms durable and never silently lost, with rationale distilled to memory (R18–R20/R27).
- Support a planning store in the code repo or a separate shared planning project without cross-project pollution (R4/R10–R12/R42).
- Preserve freeze guarantees portably via lock + a normatively specified content-hash, verified on read and in CI (R13/R14/R35/R37/R48).
- Integrate cleanly with PRD 034 `planning.store` and visibility, and define the planning-graph region-disposition contract for dependents (R33/R34/R43).
- Fail closed on privacy, missing capabilities, auth, concurrency conflicts, and connectivity loss (R28/R31/R36/R39/R41/R43).

## Non-Goals

- Changing any default behavior; the file pipeline is the default and only behavior when `issue-store` is unconfigured or unsupported (R1/R3).
- Migration between stores — owned by PRD 044.
- Dev-tracking (gaps-as-issues, commit/PR linkage, comment-based doc-review, milestones) — owned by PRD 045.
- Task hierarchy, label-driven scheduler, and issue-derived INDEX/living-status — owned by PRD 046.
- The Jira adapter — owned by PRD 047.
- Migrating decision-class artifacts; they stay on the PRD 015 memory-boundary repo-file path (D8).
- Web-UI or host-CLI integration; REST-primary with a narrow capability-gated GraphQL exception only (R5/R50).
- Unconstrained external blob storage for body overflow; overflow is comment-based in v1 (R46).

## Requirements

R-IDs carry forward from the shared brainstorm (`docs/brainstorms/2026-06-30-issue-backed-planning-store-requirements.md`); only core-owned R-IDs appear here.

### Configuration and defaults

- **R1** — A new optional planning-store mode (`issue-store`) is selectable via `workflow.config.json`; when unset, behavior is byte-for-byte the current file-based pipeline.
- **R2** — `issuesProvider` is configured independently of the code host and accepts `github-issues`, `gitlab-issues`, `jira`, or `none`.
- **R3** — When `issuesProvider` is `none` or unsupported, or `host.provider` is `none` (local/no-remote), the system falls back to the file-store and never blocks work.
- **R4** — The issue-store location is configurable as the same code repo or a separate (possibly shared, multi-project) planning repo or project.
- **R5** — Provider interactions are REST-primary; no web UI and no host CLI. A narrow GraphQL exception is permitted only behind explicit capability flags for verbs lacking REST parity (R50). Extends the PRD 026 host-provider abstraction with an issue-verb set.

### Artifact storage and materialization

- **R6** — PRD, gap, task-list, and brainstorm artifacts are created and managed as issues when issue-store is configured.
- **R7** — When issue-store is configured, the code repo contains no planning stub files; derived projections are governed by the region-disposition matrix (R34), not authored stubs.
- **R8** — At development start, the task list is materialized from its issue into a git-ignored local temp file; the temp file is a cache, never the source of truth, and inherits the PRD 034 R8 materialization hardening (R45).
- **R9** — Artifact bodies are stored as issue markdown; provider body-size limits are handled per R35 (canonical serialization) and R46 (overflow strategy).

### Identification and multi-project isolation

- **R10** — Every artifact issue carries a `sw:project:<key>` label (where labels exist), a `[<key>]` title prefix, and a type label or marker (`sw:prd`, `sw:gap`, `sw:tasks`, `sw:brainstorm`).
- **R11** — All queries and mutations are scoped by project key; operations on a shared planning store never surface, mutate, or close another project's artifacts.
- **R12** — Identification degrades gracefully where labels are weak or absent: title prefix plus a machine-parseable body marker is the portable fallback, and the body marker is authoritative for isolation (R42).

### Freeze, immutability, and verification

- **R13** — Freeze locks the issue via API, applies a `sw:frozen` label, and records an immutable content-hash in a dedicated freeze-record comment (reserved marker excluded from canonicalization per R37).
- **R14** — CI and `/sw-deliver` fetch the issue via API and verify the recorded content-hash before consuming it; a mismatch fails closed and is classified distinctly from auth/availability errors (R37/R40).
- **R15** — Issue-store auth uses a dedicated token (R44); the network-dependence of planning-artifact CI in this mode is documented and bounded by the rate-limit/transaction model (R39).

### Brainstorms

- **R18** — Brainstorms are stored as `sw:brainstorm` issues, durable by construction and never git-ignored or silently dropped, and are linked to the PRD they spawn.
- **R19** — At freeze, brainstorm rationale is distilled into a memory `research` or `decision` entry with bidirectional pointers; no raw brainstorm transcript is stored in memory (redaction pipeline per R45).
- **R20** — On PRD freeze, the brainstorm issue is retained (closed and linked), not deleted.
- **R27** — Cross-project planning rationale is discoverable across projects via the memory pointers from R19, without duplicating deliverable content into memory.

### Portability, safety, and edges

- **R28** — Private-visibility artifacts fail closed: the system refuses to write them to a public or shared issue store and routes them to a private planning repo or the local private path (visibility resolved per R43).
- **R29** — Artifact edges and links are represented portably via a machine-parseable body-encoded `sw-edges` block, mirrored to native links/sub-issues where supported; the body block is authoritative on conflict (R47).
- **R30** — A lowest-common-denominator issue contract (title, markdown body, comments, open/closed state, flat labels) is the portable core; richer features live behind capability-gated adapters with documented degradation.
- **R31** — A per-provider capability and degradation matrix is maintained; an operation requiring a capability the configured provider lacks fails closed, with no silent partial behavior.

### Integration, durability, and security hardening

- **R33** — `issue-store` is a new `planning.store.backend` value extending the PRD 034 `planning.store` interface (`put`/`get`/`exists`/`materialize`); exactly one backend is active per run, pinned for the run duration (PRD 034 R7), with documented mutual exclusion and fail-closed precedence (D11).
- **R34** — A region-disposition matrix is defined in this PRD and honored from the first phase that ships materialization: when issue-store is active, INDEX `structural`/`derived` rows and the deliver-owned `inFlight` tuple (PRD 032) are sourced from and projected to the planning store, and PRD 033 reconciler/scheduler unit discovery reads issue queries (implemented by PRD 046). The matrix states the authoritative location per region and a documented interim for any phase where a region is not yet issue-derived.
- **R35** — A normative, provider-render-independent canonical serialization is specified: metadata-block schema, body normalization, comment-chunk manifest and reassembly order, excluded comments, and a versioned `sw-canonical-version` marker. The content-hash is SHA-256 over the canonical form, with cross-provider golden-vector fixtures.
- **R36** — All mutating issue verbs use optimistic concurrency (ETag or `updated_at` preconditions); a revision conflict fails closed with a merge/halt. Freeze establishes an explicit revision checkpoint.
- **R37** — Tamper-evidence is enforced on every read: post-freeze body/label/title mutation is detected against the recorded hash; a dedicated `sw-freeze-record` comment marker is reserved and excluded from canonicalization; auth and availability errors are classified separately from hash mismatch.
- **R39** — Deliver/CI operations use a request-budget model: per-run and per-CI call counts, pagination ceilings, and a documented ceiling for a full INDEX refresh per provider; partial API failure is detected and fails closed with a `deliver-aborted-inconsistent` halt plus a resume path; backoff is exponential with jitter and does not rely on `Retry-After`.
- **R40** — Artifact references are stable (provider + repo/project + id + project key); existence checks distinguish 404/410 tombstones from hash mismatch; issue transfer/type-conversion is detected and fails closed with an operator recovery path.
- **R41** — Issue-store mode requires connectivity for planning operations; connectivity loss produces explicit operator-visible fail-closed errors (no infinite retry) and idempotent retry on reconnect for interrupted commands.
- **R42** — Project keys are globally unique within a shared store, validated at init (collisions rejected or namespaced); every read verifies the body marker (not label/title alone) so prefix spoofing cannot leak or mutate another project's artifacts.
- **R43** — All issue create/update/migrate paths resolve visibility via the PRD 034 visibility resolver before any API write; unknown resolves to private (fail-closed); private/`memory` units are refused or rerouted per R28; issue-derived INDEX rows pass through the resolver (private/`memory` units emit id/status/edges only, opaque titles per PRD 034 R4).
- **R44** — A dedicated `issues.tokenEnv` (or per-adapter token env) distinct from `host.tokenEnv` carries issue-store credentials; minimum scopes per provider are documented and probed at init (fail-closed on missing/insufficient scope); recorded test fixtures are sanitized of tokens/headers.
- **R45** — A secret-scan chokepoint runs on every issue body/comment/pointer write; the PRD 034 emission-point registry is extended to issue-store write paths; materialized temp files inherit PRD 034 R8 hardening; brainstorm distillation routes the issue excerpt through `memory-redact` before the memory adapter.
- **R46** — Body overflow in v1 uses ordered issue comments only; any future external pointer must target an allowlisted, private, auth-gated, hash-bound backend and is forbidden for private/`memory` units.
- **R47** — The body-encoded `sw-edges` block is authoritative on edge conflict; native links/sub-issues are best-effort projections reconciled on read; divergence beyond tolerance fails closed.
- **R48** — Freeze is an ordered, atomic multi-step: hash + lock are required for deliver; a memory-distillation failure flags the artifact `freeze-incomplete` and blocks `/sw-deliver` (fail-closed) rather than proceeding silently.
- **R49** — Each rollout phase updates its affected documentation surface before shipping; affected artifacts are enumerated in the Documentation Impact section and are phase exit-gates. Dependent PRDs carry their own phase-scoped documentation gates.
- **R50** — REST-primary access is the contract; GraphQL is permitted only behind an explicit capability flag for verbs lacking REST parity, recorded in the capability matrix (R31).

## Technical Requirements

- **Provider abstraction.** `issues.*` verbs (`issue-create`, `issue-get`, `issue-update`, `issue-comment`, `issue-label`, `issue-lock`, `issue-search`) plus capability and token-scope probes; adapters `github-issues` and `gitlab-issues` in core, `jira`/`none` per PRDs 047/043 fallback. GraphQL only behind capability flags (R50).
- **Planning-store integration.** `issue-store` registered as a `planning.store.backend` value implementing the PRD 034 `put`/`get`/`exists`/`materialize` contract; run-pinned, mutually exclusive (R33).
- **Region-disposition matrix (R34).** `structural`/`derived` rows issue-derived; `inFlight` (PRD 032) written to the planning store and projected, never to a code-repo file; PRD 033 discovery via project-scoped issue search; documented interim where a region is not yet issue-derived (file-store authoritative, adoption gated).
- **Capability manifest.** PRD 021 manifest/selector extended with an issue-store capability matrix per provider; selector fails closed on absent capabilities (R30/R31).
- **Canonical body + hashing (R35).** Versioned canonical form, chunk manifest, exclusion rules, SHA-256, cross-provider golden vectors.
- **Concurrency + lifecycle (R36/R37/R40).** ETag/`updated_at` preconditions; on-read tamper detection; tombstone/transfer detection distinct from hash mismatch.
- **Materialization (R8/R45).** Frozen task-list issue materialized to `.cursor/planning-materialized/` with hash verification and PRD 034 R8 hardening.
- **Edges (R47).** `sw-edges` body block authoritative; native projection reconciled on read.

## Security & Compliance

- **Visibility fail-closed (R28/R43).** All writes resolve visibility via the PRD 034 resolver before any API call; unknown → private; GitHub (no per-issue privacy) refuses private artifacts on a public store and reroutes. GitLab confidential issues are an adapter bonus, never the portable guarantee.
- **Token handling (R15/R44).** Dedicated `issues.tokenEnv`; minimum scopes documented and probed at init; tokens never in logs, bodies, comments, CI output, or fixtures.
- **Secret-scan chokepoint (R45).** Every issue body/comment/pointer write is secret-scanned; PRD 034 emission-point registry extended to issue-store paths.
- **Shared-store trust boundary (R11/R42).** Project-key scoping is application-layer convenience, not provider-enforced authorization; high-isolation tenants use separate repos or narrowly scoped tokens; body-marker verification mitigates spoofing; cross-key mutations rejected.
- **Memory trust boundary (R19/R45).** Distillation routes through `memory-redact`; raw transcripts and secrets are never stored (PRD 015 memory-boundary).
- **Tamper-evidence (R13/R14/R37).** Lock + content-hash is detective; on-read verification is authoritative and fails closed on mismatch, classified separately from auth/outage.

## Testing Strategy

- **Default-inert regression (R1; SC1).** A full doc-to-deliver cycle with `issue-store` unconfigured is byte-identical to today (golden comparison).
- **Provider adapter fixtures.** Hermetic, token-sanitized recorded REST interactions for GitHub/GitLab exercise the `issues.*` verbs, capability/scope probes, pagination, and backoff; no live network in plugin CI (R5/R31/R39/R44).
- **Canonical hash stability (R35).** Cross-provider golden vectors assert round-trip hash equality through provider rendering and comment-chunk reassembly.
- **Concurrency (R36).** Interleaved mutation + freeze on the same issue asserts conflict detection and fail-closed halt.
- **Identification isolation (R11/R42).** Two project keys in a shared store assert zero leakage on read/mutation, including a prefix-spoof attempt blocked by body-marker verification.
- **Privacy fail-closed (R28/R43).** A private artifact against a public store is refused on create; issue-derived INDEX emits metadata-only with opaque titles for private units.
- **Freeze enforcement (R13/R14/R37/R48).** A post-freeze edit is detected on read and in CI; a memory-distillation failure marks `freeze-incomplete` and blocks deliver.
- **Lifecycle edge cases (R40).** Deleted/transferred/converted issues are detected and fail closed distinctly from hash mismatch.
- **Resilience (R39/R41).** Simulated outage and rate-limit exhaustion produce documented fail-closed messages and clean resume.
- **Capability degradation (R30/R31/R50).** Operations needing absent capabilities degrade to the documented fallback or fail closed, asserted per provider.

## Rollout Plan

Default-inert at every phase, with documentation exit-gates (R49):

1. **Foundation** — config schema (`planning.store.backend: issue-store`, `issuesProvider`, `projectKey`, store location, `issues.tokenEnv`), provider abstraction skeleton, capability manifest entries, token-scope probe, `none`/fallback wiring, and the region-disposition matrix (R34). (R1–R5, R30, R31, R33, R34, R42, R44, R50)
2. **Core artifact store + identification** — create/read/update PRD/gap/task/brainstorm as issues; canonical serialization (R35); identity + isolation; concurrency preconditions (R6, R7, R9, R10–R12, R18, R29, R36, R42, R47).
3. **Freeze + materialization + brainstorm durability** — lock + content-hash, on-read tamper detection, CI verification, atomic freeze, materialization with hardening, distillation to memory (R8, R13–R15, R19, R20, R27, R35, R37, R39, R40, R41, R43, R45, R46, R48).

## Success Criteria

- **SC1 (G1: default-inert).** With `issue-store` unconfigured, the file pipeline and CI verdicts are byte-identical to today.
- **SC2 (zero stub files).** A complete doc→deliver cycle under issue-store commits no planning files to the code repo; the task list is materialized to a git-ignored temp at deliver start.
- **SC3 (brainstorm durability).** A brainstorm survives a simulated local-directory wipe — content recoverable from the issue, rationale from the linked memory pointer.
- **SC5 (isolation).** A shared store with two project keys shows zero cross-project leakage, including a blocked prefix-spoof attempt.
- **SC6 (privacy).** A private artifact is provably refused against a public store on create.
- **SC7 (freeze integrity).** A post-freeze edit is detected on read and in CI; canonical golden vectors pass on GitHub and GitLab.
- **SC8core (cross-provider core).** A representative author→freeze cycle completes on GitHub and GitLab via the LCD contract (Bitbucket via Jira is PRD 047).
- **SC9 (resilience).** Simulated outage and rate-limit exhaustion produce documented fail-closed operator messages and clean resume, never a corrupt half-state.

**Adopter (who & when).** Primary adopter: teams with a shared planning repo and label culture wanting durable, collaborative planning. Anti-personas: air-gapped/offline-first and single-developer file-only setups (keep the default). Choose a separate planning repo for multi-project orgs or private-spec-on-public-code. **MVP value checkpoint:** after core (043) plus migration (044), evaluate adoption signal before committing to the 045/046 process layer.

## Documentation Impact

Per-phase exit-gates (R49):

- `docs/guides/configuration.md` — issue-store keys, `issuesProvider`, `projectKey`, store location, `issues.tokenEnv`, fallback matrix, network-dependence, visibility interaction (Phase 1).
- `core/sw-reference/config.schema.json` + `workflow.config.example.json` — `planning.store.backend: issue-store` enum + sibling keys + commented exemplar (Phase 1).
- `.sw/layout.md` / `core/sw-reference/layout.md` — issue-store mode section: artifact identity, materialization path, region-disposition matrix, decisions-remain-file-native note (Phase 1–3).
- `core/providers/planning-store/CAPABILITIES.md` + new `issue-store.md` (Phase 1–2).
- `core/providers/host/CAPABILITIES.md` or new `core/providers/issues/CAPABILITIES.md` + `github-issues`/`gitlab-issues`/`none` adapter docs with the R31 degradation matrix; `core/providers/host/bitbucket.md` EOL + routing note (Phase 1).
- `core/sw-reference/capability-index.json` / `capability-manifest.schema.json` — issue-store triggers/flags + regeneration note (Phase 1).
- `core/skills/memory/SKILL.md` / `core/providers/recallium.md` — freeze-time brainstorm distillation flow (Phase 3).
- `core/commands/sw-brainstorm.md`, `sw-prd.md`, `sw-freeze.md`, `sw-doc.md` — dual-mode procedures (Phases 2–3).
- `README.md` — opt-in issue-store note (Phase 1).

## Decision Log

- **D1** — Brainstorm home is an issue plus a distilled memory pointer at freeze (rejected: memory-as-sole-home — collides with the no-raw-transcript guardrail and the PRD 015 memory-boundary).
- **D2** — Freeze is lock + content-hash via API with network-dependent CI verification (rejected: snapshot-to-file violates no-stub-files; lock+label-only lacks tamper-evidence).
- **D3** — Identification is label + title-prefix + type label, with the body marker authoritative for isolation.
- **D6** — Privacy fails closed; private artifacts never reach a public or shared store.
- **D7** — Default unchanged; no stub files in the code repo; REST-primary access.
- **D8** — Decision-class artifacts remain on the PRD 015 memory-boundary repo-file path (out of scope).
- **D9** — `issuesProvider` is decoupled from the code host (Jira path in PRD 047).
- **D10** — The program is split (this PRD + 044–047) on the persona-panel recommendation to keep each freeze boundary tractable; ownership table in the Program section.
- **D11** — `issue-store` extends the PRD 034 `planning.store.backend` interface as a new enum value (run-pinned, mutually exclusive), not a parallel config surface.
- **D12** — The canonical serialization and content-hash are specified normatively (R35), not deferred to implementation.
- **D13** — Access is REST-primary; GraphQL only behind capability flags for verbs lacking REST parity (R50).
- **D14** — The "R32" namespace is disambiguated: requirement R32 (PRD 047) is the Bitbucket/Jira requirement; the memory/source-of-truth policy is referred to as the PRD 015 memory-boundary, never bare "R32".

## Open Questions

None blocking. Implementation-level details are resolved during `/sw-tasks` and within the phased rollout:
the concrete capability-matrix cells per provider and the exact region-disposition interim per phase are
finalized in Phase 1; dependent-PRD scope (044–047) is tracked in those PRDs.
