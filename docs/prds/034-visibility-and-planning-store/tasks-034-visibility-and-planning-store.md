---
date: 2026-06-27
topic: planning-feedback-lifecycle
prd: docs/prds/034-visibility-and-planning-store/034-prd-visibility-and-planning-store.md
frozen: true
frozen_at: 2026-06-27
---

# Tasks — PRD 034 Per-Unit Visibility & Pluggable Planning Store

Generated from the frozen PRD spec union **R1–R27** (no amendments). Seven dependency-ordered phases mirror
the PRD rollout: the `visibility:` field + public-repo-aware resolver foundation (Phase 1) underpins the
central emission-point registry + machine-checked call-site map (Phase 2); the pluggable `planning.store`
interface + backends (Phase 3) is parallel-eligible after the resolver and feeds provision-time
materialization with the commit-boundary barrier (Phase 4); the PRD-015 reconciliation + visibility-driven
`.gitignore` + 032 in-flight handoff (Phase 5) builds on the emission registry; `/sw-init` seeding + doctor
checks (Phase 6) build on store + materialization; and emitter/dist parity + the doc-impact acceptance
criteria (Phase 7) close out. Phase Dependencies are intra-PRD only. Every phase ships behind passing
fixtures registered in `core/sw-reference/pr-test-plan.manifest.json` and is independently mergeable.

## Tasks

### 1. Visibility field + public-repo-aware resolver — M

- [ ] 1.1 Per-unit `visibility:` field + repo-level default profile (R1)
  - **File:** `scripts/planning_visibility.py`, `core/sw-reference/config.schema.json`
  - **Expected:** units accept `visibility: public|private|memory`; a repo default profile (`all-private` |
    `specs-public` | `all-public`) supplies the value when unset; schema validates the profile key
    closed-world. Fixture `visibility-field-default-profile` proves profile default applies when unset and a
    per-unit value wins.
  - **R-IDs:** R1
- [ ] 1.2 Content-class default visibility (R2)
  - **File:** `scripts/planning_visibility.py`
  - **Expected:** advisory classes (`brainstorm`, `decision`, learnings) default `private`; spec classes
    (`prd`, task lists) default `public` under `specs-public`; both overridable per unit and per profile.
    Fixture `content-class-default-visibility` asserts advisory-vs-spec defaults and override precedence.
  - **R-IDs:** R2
- [ ] 1.3 Public-repo-aware default-profile resolution (R3)
  - **File:** `scripts/planning_visibility.py` (origin-remote probe)
  - **Expected:** resolution probes the origin remote — a public remote selects `all-private` and flags the
    required pre-first-spec-commit acknowledgement; a private/absent remote selects `specs-public`; the
    resolved profile + ack are written to config + durable state. Fixture `public-remote-default-resolution`
    proves public to `all-private`+ack and private to `specs-public`.
  - **R-IDs:** R3
- [ ] 1.4 Visibility resolver = single authority module (R19)
  - **File:** `scripts/planning_visibility.py`, `scripts/visibility-resolve.sh`
  - **Expected:** one resolver module (per-unit field over the public-repo-aware profile) is consumed by the
    INDEX generator/033 reconciler, legacy projections, spec-seed, dispatch redaction, PR-diff paths, the
    `inFlight` tuple redaction, and every R14 emission point; no caller reimplements redaction. Fixture
    `resolver-single-authority` proves redaction routes through the one module at each registered point.
  - **R-IDs:** R19
- [ ] 1.5 Fail-closed posture + documented limits (R24)
  - **File:** `scripts/planning_visibility.py`, `docs/guides/configuration.md`
  - **Expected:** unknown/unresolved visibility is treated as `private`; documented limits state regex
    redaction is not semantic anonymization (steer truly sensitive specs to `all-private` + `local/synced`),
    sensitive codenames belong in the private store with a generic INDEX title, and the memory backend is
    never labeled encrypted/anonymized. Fixture `failclosed-unknown-visibility` asserts unknown to private.
  - **R-IDs:** R24

### 2. Emission-point registry + machine-checked call-site map — L

- [ ] 2.1 INDEX redaction (active + archive) + opaque title (R4)
  - **File:** `scripts/planning-graph.sh`, `scripts/planning_visibility.py`
  - **Expected:** the INDEX is always tracked but private/memory units render only id/title/status/type +
    edges (never body) in both active and archived views; a unit may opt into an opaque title (id + generic
    label) so a codename is not exposed in the tracked INDEX or PR diffs. Fixture
    `index-redaction-opaque-title` proves body redaction and that an opaque title hides a codename.
  - **R-IDs:** R4
- [ ] 2.2 Central wrapper across the emission-point registry + call-site map CI (R14)
  - **File:** `docs/prds/034-visibility-and-planning-store/call-site-map.md`, `scripts/visibility-callsite-lint.py`
  - **Expected:** a machine-checked call-site map (PRD 021/022 pattern) enumerates every planning-body
    read/write path and the registry covers INDEX (active+archive), the 033 legacy GAP-BACKLOG/INDEX
    projections, PR diffs, dispatch/subagent context, spec-seed, `list --json`/store `get`, the SUPERSEDED
    manifest, 032 handoff artifacts, 035 pull-in confirm-lists, the committed `inFlight` tuple, reconciler
    output, and run logs; CI fails on any planning-body read that bypasses the resolver or any private-body
    golden marker in a generated artifact. Fixture `emission-callsite-map-bypass-fails` adds a bypassing read
    and asserts CI fails.
  - **R-IDs:** R14
- [ ] 2.3 `spec-seed` visibility routing (R15)
  - **File:** `scripts/wave_spec_seed.py`
  - **Expected:** `spec-seed` routes through the resolver, skips `private`/`memory` bodies entirely, commits
    only public bodies plus the redacted INDEX, and aborts with remediation if a `private` body path is
    tracked. Fixture `spec-seed-visibility-route` proves private bodies are skipped and a tracked private body
    aborts the seed.
  - **R-IDs:** R15

### 3. Planning-store interface + backends — L

- [ ] 3.1 `planning.store` interface + registry + `in-repo public` default (R5)
  - **File:** `scripts/planning_store.py`, `core/providers/planning-store/in-repo.md`, `core/providers/planning-store/CAPABILITIES.md`
  - **Expected:** unit bodies are addressed through a single interface (`put`/`get`/`exists`/`materialize`)
    over a backend registry; the default backend is `in-repo public` with no behavior change. Fixture
    `store-interface-in-repo-default` asserts the default backend satisfies the interface contract.
  - **R-IDs:** R5
- [ ] 3.2 `local/synced` + `memory` backends; deferred backends inert (R6)
  - **File:** `core/providers/planning-store/local-synced.md`, `core/providers/planning-store/memory.md`, `scripts/planning_store.py`
  - **Expected:** `local/synced` folder and `memory` provider backends implement the same interface; the
    private-repo and encryption backends are seam-compatible but deferred (present-but-inert in tests).
    Fixture `store-backend-interface-parity` proves each shipped backend satisfies the interface and a
    deferred backend is inert.
  - **R-IDs:** R6
- [ ] 3.3 Config-driven selection + id/hash/backend-only logging (R18)
  - **File:** `scripts/planning_store.py`, `core/sw-reference/config.schema.json`
  - **Expected:** backend selection is config-driven (`planning.store` in `workflow.config.json`) and pinnable
    per run; `get`/`put`/`materialize` log id+hash+backend only — never body content. Fixture
    `store-log-id-hash-backend` greps store logs and asserts no body bytes appear.
  - **R-IDs:** R18
- [ ] 3.4 Memory backend adapter-only + redact on read+write + class bans (R11)
  - **File:** `scripts/planning_store.py` (memory backend), `scripts/wave_memory.py`, `scripts/memory-redact.sh`
  - **Expected:** the memory backend routes exclusively through the provider-agnostic adapter (never a direct
    provider call), passes `memory-redact.sh` on both `put` and read, degrades open when no provider exists,
    scopes writes to `memory.project`, requests body inactivation on supersede/cancel, and bans the
    `discussion`/`progress` classes. Fixture `memory-backend-adapter-only` bans direct provider MCP calls and
    proves redaction on read+write.
  - **R-IDs:** R11
- [ ] 3.5 `local/synced` path validation doctor check (R16)
  - **File:** `scripts/planning-doctor.sh`
  - **Expected:** the path must resolve inside the operator home or a configured allowlist, reject symlinks
    and `..`, and have a directory mode no looser than `0700`; known cloud-sync roots warn; the backend is
    documented as convenience-not-security and not the public-repo template default. Fixture
    `local-synced-path-validation` rejects symlink/`..`/loose-mode and warns on a cloud root.
  - **R-IDs:** R16
- [ ] 3.6 Memory chokepoint posture unchanged on read + write (R25)
  - **File:** `scripts/memory-redact.sh`, `core/rules/memory-guardrails.mdc`
  - **Expected:** the redaction chokepoint + memory guardrails posture is unchanged; memory-routed bodies pass
    `memory-redact.sh` on read and write; no raw transcript or secret is ever stored. Fixture
    `memory-chokepoint-read-write` proves both directions pass the chokepoint and a raw transcript is refused.
  - **R-IDs:** R25

### 4. Provision-time materialization + commit-boundary barrier — L

- [ ] 4.1 Materialize private spec bodies at provision + backend pinning (R7)
  - **File:** `scripts/planning_materialize.py`, `scripts/wave_lifecycle.py`
  - **Expected:** required private spec units are copied into the phase worktree after worktree creation and
    before any preflight/plan/spec-seed read; CI/host never materializes; the store backend + revision are
    pinned in deliver run-state at provision and every phase read validates against the pin; a mid-run
    `planning.store` config change halts with remediation. Fixture `materialize-provision-backend-pinned`
    proves provision-time copy, pinned-backend validation, and the backend-swap halt.
  - **R-IDs:** R7
- [ ] 4.2 Commit-boundary barrier (R8)
  - **File:** `core/hooks/pre-commit`, `core/hooks/pre-push`, `scripts/materialized-prefix-scan.sh`
  - **Expected:** materialized bodies live under a deterministic ignored prefix
    (`.cursor/planning-materialized/`) added to `.gitignore`; a post-materialize `secret-scan file` runs;
    pre-commit and pre-push reject any staged path under the prefix even with `git add -f`; a CI check scans
    PR diffs for the prefix and private-body golden markers; teardown deletes the tree; a crashed-run orphan
    tree is swept from run-state-recorded paths. Fixture `commit-boundary-barrier` proves `git add -f` is
    rejected and the diff scan catches the prefix.
  - **R-IDs:** R8
- [ ] 4.3 Materialization freshness hash validation (R9)
  - **File:** `scripts/planning_materialize.py`
  - **Expected:** the unit frontmatter carries a content hash/revision; `materialize` fails closed on a hash
    mismatch versus the store body; the reconciler warns when graph `updated_at` is newer than the store
    revision (034 owns the store-revision hash; the 033 reconciler reads it through this interface). Fixture
    `materialize-freshness-hash` proves a hash mismatch fails closed.
  - **R-IDs:** R9
- [ ] 4.4 Fail-closed missing/unreachable/doc-incapable backend (R10)
  - **File:** `scripts/planning_store.py`, `scripts/planning_materialize.py`
  - **Expected:** a missing, unreachable, or doc-incapable backend never exposes a private body and never
    silently breaks delivery — it fails closed with explicit remediation (keep the unit public, or refuse
    delivery with a message), never a partial/leaky state. Fixture `store-failclosed-remediation` proves the
    refuse-with-guidance path and no leak.
  - **R-IDs:** R10
- [ ] 4.5 Provision-path materialization hook wiring (R20)
  - **File:** `scripts/wave_lifecycle.py`, `scripts/planning_materialize.py`
  - **Expected:** the deliver provision hook (after worktree add, before preflight) copies required private
    spec bodies into the ignored prefix, runs the post-materialize secret-scan, registers materialize paths in
    run-state for orphan sweep, enforces the R8 barrier, validates R9 freshness, cleans up on teardown, and
    routes through the PRD 031 path helper. Fixture `materialize-hook-provision-teardown` proves the hook order
    and a clean teardown with no residual.
  - **R-IDs:** R20
- [ ] 4.6 Materialized bodies worktree-only + secret-scan coverage (R26)
  - **File:** `scripts/secret-scan.sh`, `scripts/planning_materialize.py`
  - **Expected:** materialized private bodies live only inside the agent worktree under the ignored prefix, are
    never committed or pushed (R8), are swept on crash, removed on teardown, and secret-scan covers
    materialize-time and store-read-time via the existing `secret-scan.sh file|stdin` chokepoints. Fixture
    `materialized-worktree-only` proves nothing is committed and secret-scan runs at both points.
  - **R-IDs:** R26

### 5. PRD-015 reconciliation + `.gitignore` generation + 032 handoff — M

- [ ] 5.1 Visibility-driven `.gitignore` generator + tracked-private reject (R13)
  - **File:** `scripts/gitignore-generate.sh`, `scripts/planning-unit-validate.sh`, `.gitignore`
  - **Expected:** `.gitignore` is generated from the visibility resolver (track frontmatter stubs + public
    bodies only), reconciling the PRD-015 committed-snapshot vs `.gitignore` conflict; the migration verifier
    asserts zero private-body bytes in the git index, and `planning-unit-validate.sh` rejects a
    `visibility: private` unit whose body path is tracked. Fixture `gitignore-visibility-no-private-bytes`
    proves zero private bytes tracked and a tracked private body is rejected.
  - **R-IDs:** R13
- [ ] 5.2 PRD-015 decision SoT + 032 in-flight redaction handoff (R12)
  - **File:** `scripts/memory-decision-snapshot.sh`, `scripts/planning_visibility.py` (inFlight tuple redaction)
  - **Expected:** the memory backend is body-storage only and does not alter source-of-truth; for
    `decision`-class units the PRD-015 always-committed redacted snapshot + pointer flow runs regardless of
    `visibility`; the resolver redacts the committed `inFlight` tuple's branch/run-id to the 032 R13
    opaque-token form for `private`/`memory` units. Fixture `decision-sot-inflight-redaction` proves a
    `visibility: memory` decision still writes the committed snapshot and the `inFlight` branch is
    opaque-token-redacted.
  - **R-IDs:** R12

### 6. `/sw-init` seeding + doctor checks — M

- [ ] 6.1 `/sw-init` profile + store + privacy-notice/ack seeding + doctor (R21)
  - **File:** `core/commands/sw-init.md`, `scripts/planning-doctor.sh`
  - **Expected:** `/sw-init` resolves and seeds the public-repo-aware default profile (R3) + default store
    backend, records the first-run privacy notice + ack, and a doctor check validates store reachability
    (degrade-open with actionable remediation when the memory backend is configured but no provider is
    present) and sweeps orphaned materialized trees. Fixture `init-profile-store-seed` proves seeding +
    degrade-open doctor verdict + orphan sweep.
  - **R-IDs:** R21
- [ ] 6.2 No new credential surface + token-safe doctor (R27)
  - **File:** `scripts/planning-doctor.sh`, `scripts/planning_store.py`
  - **Expected:** no new credential surface beyond the configured backend's own auth (via the existing
    provider-agnostic adapter); the doctor check never prints provider tokens, store config references env-var
    names only, and store operations never log body content (R18). Fixture `store-no-token-leak` proves the
    doctor output and store logs contain no token or body bytes.
  - **R-IDs:** R27

### 7. Emitter/dist parity + doc-impact acceptance — M

- [ ] 7.1 Store/visibility artifacts in `core/` + dist parity (R22)
  - **File:** `scripts/copy-to-core.sh`, `scripts/migration-parity-shadow.sh`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** the `.gitignore` generator and store/visibility artifacts land in `core/` and propagate to
    both dist trees; `copy-to-core` parity, emitter-freshness, and secret-scan fixtures cover the new scripts
    and config keys. Fixture `store-emitter-parity` asserts core to dist parity + emitter freshness for the new
    surfaces.
  - **R-IDs:** R22
- [ ] 7.2 No regression to the delivery-loop documentation (R17)
  - **File:** `core/scripts/spec-rigor-check.sh`, `core/scripts/traceability-check.sh`
  - **Expected:** public units behave exactly as today; frozen immutability, traceability, and spec-rigor
    gates are preserved; the human merge-to-`main` gate is unchanged. Fixture `public-unit-no-regression`
    proves public-unit behavior and gate preservation are unchanged.
  - **R-IDs:** R17
- [ ] 7.3 Doc-impact acceptance criteria (R23)
  - **File:** `.gitignore`, `core/skills/memory/SKILL.md`, `core/providers/recallium.md`, `core/rules/memory-guardrails.mdc`, `core/commands/sw-init.md`, `core/skills/deliver/SKILL.md`, `core/sw-reference/config.schema.json`, `core/sw-reference/workflow.config.example.json`, `docs/guides/configuration.md`
  - **Expected:** all listed docs are updated as acceptance criteria — `.gitignore` (visibility-driven
    generation), memory SKILL (decision paths under `docs/planning/`; memory store is body-only),
    `recallium.md` (decision unit paths; storage-only note), `memory-guardrails.mdc` (name the
    `planning.store` memory backend as adapter + `memory-redact.sh` chokepoint only), `sw-init.md`
    (public-repo-aware profile/store/privacy-notice + ack seeding), `deliver/SKILL.md` (provision-time
    materialization, ignored prefix, commit-boundary barrier, teardown), `config.schema.json` + both
    `workflow.config.example.json` copies (the `planning.store` + visibility-profile keys), and
    `configuration.md` (store/profile keys). Fixture `doc-impact-visibility-store` asserts each named doc
    carries the required content.
  - **R-IDs:** R23

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 3 |
| 5 | 2 |
| 6 | 3, 4 |
| 7 | 5, 6 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | visibility-field-default-profile |
| R2 | 1.2 | content-class-default-visibility |
| R3 | 1.3 | public-remote-default-resolution |
| R4 | 2.1 | index-redaction-opaque-title |
| R5 | 3.1 | store-interface-in-repo-default |
| R6 | 3.2 | store-backend-interface-parity |
| R7 | 4.1 | materialize-provision-backend-pinned |
| R8 | 4.2 | commit-boundary-barrier |
| R9 | 4.3 | materialize-freshness-hash |
| R10 | 4.4 | store-failclosed-remediation |
| R11 | 3.4 | memory-backend-adapter-only |
| R12 | 5.2 | decision-sot-inflight-redaction |
| R13 | 5.1 | gitignore-visibility-no-private-bytes |
| R14 | 2.2 | emission-callsite-map-bypass-fails |
| R15 | 2.3 | spec-seed-visibility-route |
| R16 | 3.5 | local-synced-path-validation |
| R17 | 7.2 | public-unit-no-regression |
| R18 | 3.3 | store-log-id-hash-backend |
| R19 | 1.4 | resolver-single-authority |
| R20 | 4.5 | materialize-hook-provision-teardown |
| R21 | 6.1 | init-profile-store-seed |
| R22 | 7.1 | store-emitter-parity |
| R23 | 7.3 | doc-impact-visibility-store |
| R24 | 1.5 | failclosed-unknown-visibility |
| R25 | 3.6 | memory-chokepoint-read-write |
| R26 | 4.6 | materialized-worktree-only |
| R27 | 6.2 | store-no-token-leak |

## Notes

- New module family: `scripts/planning_visibility.py` (resolver), `scripts/planning_store.py` (interface +
  registry), `scripts/planning_materialize.py` (provision-time materialization), `scripts/gitignore-generate.sh`,
  and `core/providers/planning-store/` (in-repo / local-synced / memory adapters + `CAPABILITIES.md`),
  mirroring the existing `core/providers/host/` + memory/review adapter pattern.
- Cross-PRD seams (referenced, not reimplemented here): the PRD 031 path helper, the PRD 033 reconciler
  (`scripts/planning-graph.sh`) + legacy projections (`scripts/wave_living_docs.py`), the PRD 032 `inFlight`
  writer (034 owns only the tuple redaction), and the PRD 035 pull-in confirm-lists (registered emission point).
- All new fixtures register in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`; new
  scripts land in `core/` and propagate to both dist trees under `copy-to-core` parity.
