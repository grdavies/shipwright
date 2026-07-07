---
prd: docs/prds/057-planning-store-hardening/057-prd-planning-store-hardening.md
unit-id: tasks-057-planning-store-hardening
topic: planning-store-hardening
status: not-started
frozen: true
visibility: public
date: 2026-07-06
---
# Tasks — PRD 057 Planning store hardening

Task list generated from the frozen PRD 057 union (30 union R-IDs: R1–R6, R8–R15, R17–R32;
the two `(BLOCKER)` requirements R7 and R16 are covered explicitly below and in Traceability).
Phases align with the PRD's five-wave Rollout Plan and honor the sequencing invariant R24
(blockers + run-unblockers first; parity-audit closure last). Every phase is independently
shippable behind the effective-backend guard and preserves file-store parity (R23).

Wave map:
- **Wave 1 — blockers + run-unblockers:** R7, R16, R18, R28, R30, R31 → phases 2–5.
- **Wave 2 — pollution stoppers + freshness + migration gates:** R1, R2, R3, R4, R5, R10, R13,
  R14, R15, R21a, R25, R29 → phases 6–12.
- **Wave 3 — store-write robustness + integrity:** R8, R9, R26, R27 → phases 13–14.
- **Wave 4 — provider-native polish + graph hygiene:** R11, R12, R17 → phases 15–16.
- **Wave 5 — workflow polish + audit closure:** R19, R20, R21b, R6 → phases 17–19.
- **Cross-cutting invariants (every wave):** R22, R23, R24, R32 → phase 1 scaffolding + per-phase
  parity/doc-impact sub-tasks.

## Tasks

### 1. Cross-cutting invariants & test scaffolding (Wave 1 · R22, R23, R24, R32)

- [x] 1.1 Extend traceability/union check to load PRD 056 union from the store and block restated 056 text (R22) (unit 1/2)
  - **File:** `scripts/spec-union.py`
  - **Expected:** the check loads the PRD 056 union from the authoritative issue store (issue #218) and fails when a new R-ID restates PRD 056 union R1–R20 text; JSON verdict.
  - **R-IDs:** R22
- [x] 1.2 Extend traceability/union check to load PRD 056 union from the store and block restated 056 text (R22) (unit 2/2)
  - **File:** `scripts/traceability-check.py`
  - **Expected:** the check loads the PRD 056 union from the authoritative issue store (issue #218) and fails when a new R-ID restates PRD 056 union R1–R20 text; JSON verdict.
  - **R-IDs:** R22
- [x] 1.3 File-store parity golden-output fixture harness (R23)
  - **File:** `scripts/test/fixtures/planning-file-store-parity/harness.py`
  - **Expected:** per-command golden outputs (gap capture, reconcile, spec-seed) are byte-identical (or structurally equivalent) before/after each guard when the effective backend is not an issue-store.
  - **R-IDs:** R23
- [x] 1.4 Per-wave incremental parity fixture + wave-sequencing assertion (R24)
  - **File:** `scripts/test/fixtures/planning-deliver-parity/wave_incremental.py`
  - **Expected:** each wave asserts no file-store-only write for the artifacts it guards; assertion that blockers (R7/R16/R18) land in the earliest wave and R6 is exempted to Wave 5.
  - **R-IDs:** R24
- [x] 1.5 Doc-impact fixture mapping each requirement to Documentation Impact paths per wave (R32)
  - **File:** `scripts/test/fixtures/planning-057-doc-impact/harness.py`
  - **Expected:** fixture maps each requirement to its doc paths and fails when a behavior change merges without its paired doc update in the same wave.
  - **R-IDs:** R32

### 2. Scheduler frontier skip + park governance (Wave 1 · R16, R28)

- [x] 2.1 File-path `cmd_next` skip-with-reasons for unrunnable units (R16)
  - **File:** `scripts/planning_deliver_gate.py`
  - **Expected:** units without a frozen task list are skipped with reasons instead of failing the whole frontier; `planning-graph.py next` delegates here via `wave_deliver.py`.
  - **R-IDs:** R16
- [x] 2.2 Issue-store frontier honors `sw:parked` label + unrunnable filtering (R16)
  - **File:** `scripts/planning_scheduler.py`
  - **Expected:** `is_schedulable` drops parked/unrunnable legacy units (e.g. `003-prd-pr-agent-review-provider`) from the frontier via the label-aware path.
  - **R-IDs:** R16
- [x] 2.3 Park governance: allowlist + reason + `scheduler-exhausted` halt (R28) (unit 1/2)
  - **File:** `scripts/planning-graph.py`
  - **Expected:** parking requires a local-config allowlist actor + park reason; an empty post-filter frontier emits an explicit `scheduler-exhausted` halt naming parked/unrunnable units and the unpark remediation.
  - **R-IDs:** R28
- [x] 2.4 Park governance: allowlist + reason + `scheduler-exhausted` halt (R28) (unit 2/2)
  - **File:** `scripts/planning_scheduler.py`
  - **Expected:** parking requires a local-config allowlist actor + park reason; an empty post-filter frontier emits an explicit `scheduler-exhausted` halt naming parked/unrunnable units and the unpark remediation.
  - **R-IDs:** R28
- [x] 2.5 Doctor over-parked-frontier drift finding + scheduler/park fixtures (R28) (unit 1/2)
  - **File:** `scripts/planning-doctor.py`
  - **Expected:** doctor surfaces an over-parked-frontier drift finding; fixture proves all-parked/unrunnable frontier yields `scheduler-exhausted`, unauthorized park is refused, and `next` skips unrunnable units with reasons.
  - **R-IDs:** R28
- [x] 2.6 Doctor over-parked-frontier drift finding + scheduler/park fixtures (R28) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-parked-governance/harness.py`
  - **Expected:** doctor surfaces an over-parked-frontier drift finding; fixture proves all-parked/unrunnable frontier yields `scheduler-exhausted`, unauthorized park is refused, and `next` skips unrunnable units with reasons.
  - **R-IDs:** R28

### 3. gitlab-issues demotion / fail-closed (Wave 1 · R7)

- [ ] 3.1 Remove `gitlab-issues` from shipped set and demote to deferred/fail-closed (R7) (unit 1/2)
  - **File:** `scripts/issues_lib.py`
  - **Expected:** `SHIPPED_ISSUES_PROVIDERS` no longer advertises `gitlab-issues`; `_live_backend` keeps a fail-closed raise for unimplemented providers with a clear operator message.
  - **R-IDs:** R7
- [ ] 3.2 Remove `gitlab-issues` from shipped set and demote to deferred/fail-closed (R7) (unit 2/2)
  - **File:** `scripts/planning_store.py`
  - **Expected:** `SHIPPED_ISSUES_PROVIDERS` no longer advertises `gitlab-issues`; `_live_backend` keeps a fail-closed raise for unimplemented providers with a clear operator message.
  - **R-IDs:** R7
- [ ] 3.3 gitlab demotion fixture (R7)
  - **File:** `scripts/test/fixtures/planning-gitlab-demotion/harness.py`
  - **Expected:** `gitlab-issues` is absent from the shipped set and selecting it fails closed with a clear message.
  - **R-IDs:** R7
- [ ] 3.4 Docs: gitlab deferred banner + shipped capability matrix (R32) (unit 1/2)
  - **File:** `CAPABILITIES.md`
  - **Expected:** deferred/fail-closed banner with operator message and follow-up-unit pointer; shipped matrix removes `gitlab-issues` and marks it deferred.
  - **R-IDs:** R7
- [ ] 3.5 Docs: gitlab deferred banner + shipped capability matrix (R32) (unit 2/2)
  - **File:** `core/providers/issues/gitlab-issues.md`
  - **Expected:** deferred/fail-closed banner with operator message and follow-up-unit pointer; shipped matrix removes `gitlab-issues` and marks it deferred.
  - **R-IDs:** R7

### 4. Dispatch-preflight concrete-model resolution (Wave 1 · R18)

- [ ] 4.1 `cmd_dispatch` fallback resolution order for inherit orchestrators (R18) (unit 1/2)
  - **File:** `scripts/resolve-model-tier.py`
  - **Expected:** for an `inherit` orchestrator with an unmapped agent, resolve agent map → `models.roles` fallback → actionable remediation; `binding:no-model` no longer fires (e.g. `--agent explore --command sw-doc`) and inline authoring is no longer forced.
  - **R-IDs:** R18
- [ ] 4.2 `cmd_dispatch` fallback resolution order for inherit orchestrators (R18) (unit 2/2)
  - **File:** `scripts/wave_preflight.py`
  - **Expected:** for an `inherit` orchestrator with an unmapped agent, resolve agent map → `models.roles` fallback → actionable remediation; `binding:no-model` no longer fires (e.g. `--agent explore --command sw-doc`) and inline authoring is no longer forced.
  - **R-IDs:** R18
- [ ] 4.3 Dispatch-preflight inherit+unmapped fixture (R18)
  - **File:** `scripts/test/fixtures/dispatch-preflight/inherit_unmapped.py`
  - **Expected:** `--agent explore --command sw-doc` resolves a concrete model or emits an actionable remediation.
  - **R-IDs:** R18
- [ ] 4.4 Docs: models-tiering resolution order (R32)
  - **File:** `core/sw-reference/models-tiering.md`
  - **Expected:** documents the `cmd_dispatch` resolution order (agent map → `models.roles` → remediation) and notes it prevents forced inline authoring.
  - **R-IDs:** R18

### 5. CI token-absent degraded mode + rollback kill-switch (Wave 1 · R30, R31)

- [ ] 5.1 Test-harness gating: skip-with-advisory when store token absent (R30)
  - **File:** `scripts/test/fixtures/planning-ci-token-absent/harness.py`
  - **Expected:** with the token env unset, issue-store integration fixtures skip-with-advisory (green) while file-store parity fixtures always run.
  - **R-IDs:** R30
- [ ] 5.2 Doctor `store-token-absent` (advisory) vs `probe-failed` (fail-closed) (R30)
  - **File:** `scripts/planning-doctor.py`
  - **Expected:** doctor distinguishes `store-token-absent` (advisory) from `probe-failed` (fail closed); a missing token is never a silent pass and never fail-closed.
  - **R-IDs:** R30
- [ ] 5.3 `effective-backend` kill-switch + materialize-from-store (R31)
  - **File:** `scripts/planning_store.py`
  - **Expected:** an `effective-backend` kill-switch restores prior behavior and re-materializes local projections from the authoritative store on demand, without loss of store data.
  - **R-IDs:** R31
- [ ] 5.4 Doctor `wave-regression` finding + per-wave rollback fixture (R31)
  - **File:** `scripts/test/fixtures/planning-wave-rollback/harness.py`
  - **Expected:** reverting a wave's code with the kill-switch set restores prior behavior; doctor emits a `wave-regression` finding on inconsistent local/store state.
  - **R-IDs:** R31

### 6. Shared predicate + gap-capture write-through guard (Wave 2 · R1)

- [ ] 6.1 Add shared `issue_store_separate_project(root)` predicate (R1)
  - **File:** `scripts/planning_migrate_issue_store.py`
  - **Expected:** predicate built on `resolve_store_location(...).mode` (issue-store effective AND `separate-project`); used across the R1–R4 pollution/currency guards.
  - **R-IDs:** R1
- [ ] 6.2 Guard `refresh_gap_backlog_projection` + `--projection` flag + sunset stub (R1) (unit 1/2)
  - **File:** `scripts/gap_backlog.py`
  - **Expected:** under issue-store `separate-project`, gap capture writes through to the store and skips the local `GAP-BACKLOG.md` write; `--projection` retains the legacy row; projection reduced to a documented sunset stub when no open gaps remain; `same-repo` unchanged.
  - **R-IDs:** R1
- [ ] 6.3 Guard `refresh_gap_backlog_projection` + `--projection` flag + sunset stub (R1) (unit 2/2)
  - **File:** `scripts/planning_migrate_issue_store.py`
  - **Expected:** under issue-store `separate-project`, gap capture writes through to the store and skips the local `GAP-BACKLOG.md` write; `--projection` retains the legacy row; projection reduced to a documented sunset stub when no open gaps remain; `same-repo` unchanged.
  - **R-IDs:** R1
- [ ] 6.4 Gap-capture parity fixture + feedback/emission-point docs (R32) (unit 1/2)
  - **File:** `core/skills/feedback/SKILL.md`
  - **Expected:** gap-capture golden output equivalent when backend ≠ issue-store; feedback skill documents store-only capture and the sunset stub; retains file-store/cutover behavior verbatim.
  - **R-IDs:** R1
- [ ] 6.5 Gap-capture parity fixture + feedback/emission-point docs (R32) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-file-store-parity/gap_capture_golden.py`
  - **Expected:** gap-capture golden output equivalent when backend ≠ issue-store; feedback skill documents store-only capture and the sunset stub; retains file-store/cutover behavior verbatim.
  - **R-IDs:** R1

### 7. spec-seed + reconcile local-write guards (Wave 2 · R2, R3)

- [ ] 7.1 Guard `docs/prds/INDEX.md` writes in `wave_spec_seed` (R2)
  - **File:** `scripts/wave_spec_seed.py`
  - **Expected:** `ensure_redacted_index` and the seed-time index write are guarded by the effective backend and skip under issue-store `separate-project`.
  - **R-IDs:** R2
- [ ] 7.2 Guard `reconcile_core` derived-artifact writes (R3)
  - **File:** `scripts/planning_reconcile.py`
  - **Expected:** no tracked `INDEX.md`/`INDEX-archive.md`/`SUPERSEDED.md`/legacy projection writes under issue-store `separate-project`; project derived status to the store (PRD 056 R8) or a gitignored cache; `same-repo` retains local writes.
  - **R-IDs:** R3
- [ ] 7.3 spec-seed + reconcile parity fixtures (R23)
  - **File:** `scripts/test/fixtures/planning-file-store-parity/spec_seed_reconcile_golden.py`
  - **Expected:** spec-seed and reconcile golden outputs equivalent when the effective backend is not an issue-store.
  - **R-IDs:** R2
- [ ] 7.4 Docs: layout + git-conventions + conductor reconcile scope (R32) (unit 1/2)
  - **File:** `.sw/layout.md`
  - **Expected:** issue-store `separate-project` writes no tracked INDEX/GAP-BACKLOG/SUPERSEDED; two-track mechanical allowlist clarified to project to store under issue-store authority.
  - **R-IDs:** R3
- [ ] 7.5 Docs: layout + git-conventions + conductor reconcile scope (R32) (unit 2/2)
  - **File:** `core/rules/sw-git-conventions.mdc`
  - **Expected:** issue-store `separate-project` writes no tracked INDEX/GAP-BACKLOG/SUPERSEDED; two-track mechanical allowlist clarified to project to store under issue-store authority.
  - **R-IDs:** R3

### 8. Gap-resolution store close + label (Wave 2 · R4)

- [ ] 8.1 `set_index_status` closes gap issue + applies resolution label (R4)
  - **File:** `scripts/reconcile_lib.py`
  - **Expected:** under issue-store `separate-project`, call shared `close_gap_issue(root, unit_id)` (issue close + resolution label) instead of the local INDEX/frontmatter edit; `resolution-partial` verdict on partial failure.
  - **R-IDs:** R4
- [ ] 8.2 `resolve_for_prd` idempotent close + label (R4)
  - **File:** `scripts/gap_backlog.py`
  - **Expected:** close the gap issue and apply the resolution label idempotently (reuse `_apply_gap_labels`/`GAP_LABEL_RESOLVED` + `issue_update(..., state="closed")`); `same-repo` retains frontmatter/row edits.
  - **R-IDs:** R4
- [ ] 8.3 Doctor resolution-partial reconciliation + living-status docs (R32) (unit 1/2)
  - **File:** `core/skills/living-status/SKILL.md`
  - **Expected:** doctor reconciles the open-issue-plus-resolved-label mismatch; living-status doc separates store authority from the file-store byte-identical path.
  - **R-IDs:** R4
- [ ] 8.4 Doctor resolution-partial reconciliation + living-status docs (R32) (unit 2/2)
  - **File:** `scripts/planning-doctor.py`
  - **Expected:** doctor reconciles the open-issue-plus-resolved-label mismatch; living-status doc separates store authority from the file-store byte-identical path.
  - **R-IDs:** R4

### 9. gitignore auto-config + committed cutover signal (Wave 2 · R5)

- [ ] 9.1 `/sw-init` gitignore-generate + committed cutover derivation (R5) (unit 1/2)
  - **File:** `core/commands/sw-init.md`
  - **Expected:** `/sw-init` runs `gitignore-generate --write` for planning-store paths; the cutover-gate signal is derived from `workflow.config.json` backend + structural markers (no new tracked file), so the gitignored state file no longer causes CI false failures.
  - **R-IDs:** R5
- [ ] 9.2 `/sw-init` gitignore-generate + committed cutover derivation (R5) (unit 2/2)
  - **File:** `scripts/planning_cutover.py`
  - **Expected:** `/sw-init` runs `gitignore-generate --write` for planning-store paths; the cutover-gate signal is derived from `workflow.config.json` backend + structural markers (no new tracked file), so the gitignored state file no longer causes CI false failures.
  - **R-IDs:** R5
- [ ] 9.3 Update `load_cutover_gate` call sites (R5) (unit 1/2)
  - **File:** `scripts/planning_discover.py`
  - **Expected:** all `load_cutover_gate` consumers stop treating `.cursor/hooks/state/planning-cutover-gate.json` as a CI authority and derive from committed state.
  - **R-IDs:** R5
- [ ] 9.4 Update `load_cutover_gate` call sites (R5) (unit 2/2)
  - **File:** `scripts/planning_region_disposition.py`
  - **Expected:** all `load_cutover_gate` consumers stop treating `.cursor/hooks/state/planning-cutover-gate.json` as a CI authority and derive from committed state.
  - **R-IDs:** R5
- [ ] 9.5 Docs: configuration guide committed cutover (R32)
  - **File:** `docs/guides/configuration.md`
  - **Expected:** documents the committed cutover derivation replacing the gitignored state file.
  - **R-IDs:** R5

### 10. Query-cache revalidation + atomic gap allocation (Wave 2 · R10, R25)

- [ ] 10.1 Symmetric-diff cache revalidation in discover (R10) (unit 1/2)
  - **File:** `scripts/planning_discover.py`
  - **Expected:** `revalidate_live_metadata` invalidates the cache on symmetric set-diff of live vs cached unit-id sets; `discover_units_issue` revalidates before returning cached projections.
  - **R-IDs:** R10
- [ ] 10.2 Symmetric-diff cache revalidation in discover (R10) (unit 2/2)
  - **File:** `scripts/planning_query_cache.py`
  - **Expected:** `revalidate_live_metadata` invalidates the cache on symmetric set-diff of live vs cached unit-id sets; `discover_units_issue` revalidates before returning cached projections.
  - **R-IDs:** R10
- [ ] 10.3 Atomic gap-number allocation (claim-by-create / retry-on-collision) (R25)
  - **File:** `scripts/planning_gap_capture.py`
  - **Expected:** `next_gap_number`/create invalidates the query cache before allocation and claims by create or retries on collision, so concurrent writers never persist duplicate gap ids or split `absorbs` edges.
  - **R-IDs:** R25
- [ ] 10.4 Query-cache freshness + multi-writer allocation fixtures (R10, R25) (unit 1/2)
  - **File:** `scripts/test/fixtures/planning-gap-alloc-multiwriter/harness.py`
  - **Expected:** new remote units by other writers are visible before TTL expiry; two concurrent allocate+create sequences yield two distinct gap ids with the cache invalidated before reading.
  - **R-IDs:** R25
- [ ] 10.5 Query-cache freshness + multi-writer allocation fixtures (R10, R25) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-query-cache/freshness.py`
  - **Expected:** new remote units by other writers are visible before TTL expiry; two concurrent allocate+create sequences yield two distinct gap ids with the cache invalidated before reading.
  - **R-IDs:** R10

### 11. Visibility axes + alias precedence + store-host privacy + privacy-ack (Wave 2 · R13, R14, R15, R29)

- [ ] 11.1 Three orthogonal visibility axes + tier-first rename (R13)
  - **File:** `scripts/planning_visibility.py`
  - **Expected:** `resolve_default_profile` splits into visibility (redaction) tier / `storeLocation` / store-host privacy with a tier-first rename and one-release back-compat; `probe_remote_visibility` is no longer the sole migration gate.
  - **R-IDs:** R13
- [ ] 11.2 Deterministic old→new alias precedence (R29)
  - **File:** `scripts/planning_visibility.py`
  - **Expected:** new keys win over deprecated aliases; a deprecated profile name emits a doctor deprecation warning; a mixed old/new config never weakens the redaction default.
  - **R-IDs:** R29
- [ ] 11.3 Store-host privacy per shipped provider + CI-only override (R14)
  - **File:** `scripts/planning_store.py`
  - **Expected:** `probe_store_host_privacy` is evaluated for every shipped provider with no placeholder always-false branches; `SW_STORE_HOST_PRIVACY` is honored only under an explicit CI-context probe.
  - **R-IDs:** R14
- [ ] 11.4 Doctor privacy-ack recording + key-naming reconciliation (R15) (unit 1/2)
  - **File:** `core/sw-reference/planning-privacy-notice.md`
  - **Expected:** doctor flags `privacyAck.required: true` with `recordedAt: null`, reconciles notice-doc `ackedAt` wording against the `recordedAt` key, and emits the exact remediation command per finding.
  - **R-IDs:** R15
- [ ] 11.5 Doctor privacy-ack recording + key-naming reconciliation (R15) (unit 2/2)
  - **File:** `scripts/planning-doctor.py`
  - **Expected:** doctor flags `privacyAck.required: true` with `recordedAt: null`, reconciles notice-doc `ackedAt` wording against the `recordedAt` key, and emits the exact remediation command per finding.
  - **R-IDs:** R15
- [ ] 11.6 Visibility axes + aliases fixtures (R13, R29) (unit 1/2)
  - **File:** `scripts/test/fixtures/planning-visibility-aliases/harness.py`
  - **Expected:** three axes modeled/named distinctly with one-release alias resolution; deprecated+new keys resolve to the new-key value with a deprecation warning; deprecated-only matches pre-rename behavior.
  - **R-IDs:** R29
- [ ] 11.7 Visibility axes + aliases fixtures (R13, R29) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-visibility-axes/harness.py`
  - **Expected:** three axes modeled/named distinctly with one-release alias resolution; deprecated+new keys resolve to the new-key value with a deprecation warning; deprecated-only matches pre-rename behavior.
  - **R-IDs:** R29
- [ ] 11.8 Docs: configuration guide visibility axes + privacy notice (R32) (unit 1/2)
  - **File:** `core/sw-reference/planning-privacy-notice.md`
  - **Expected:** configuration guide replaces the single visibility profile with three orthogonal axes + alias map; privacy notice documents `privacyAck.recordedAt`.
  - **R-IDs:** R15
- [ ] 11.9 Docs: configuration guide visibility axes + privacy notice (R32) (unit 2/2)
  - **File:** `docs/guides/configuration.md`
  - **Expected:** configuration guide replaces the single visibility profile with three orthogonal axes + alias map; privacy notice documents `privacyAck.recordedAt`.
  - **R-IDs:** R14

### 12. Memory backend local-only rename/document — 21a (Wave 2 · R21)

- [ ] 12.1 Rename + document the local-only planning-bodies cache (R21 / 21a)
  - **File:** `scripts/planning_store.py`
  - **Expected:** the memory backend's local-only `.cursor/sw-memory/planning-bodies/` behavior is renamed so its local-only, gitignored nature is explicit and no longer presents as a provider round-trip, removing the CI false-failure and misleading-durability surface.
  - **R-IDs:** R21
- [ ] 12.2 Docs: memory skill + planning-store memory provider (21a) (R32)
  - **File:** `core/skills/memory/SKILL.md`, `core/providers/planning-store/memory.md`
  - **Expected:** documents the local-only cache (21a) and references the later provider round-trip contract (21b).
  - **R-IDs:** R21

### 13. Chunk-manifest id rewrite + Jira chunking (Wave 3 · R8, R9)

- [ ] 13.1 Rewrite chunk manifest with real provider comment ids on put (R8) (unit 1/2)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** after posting overflow comments and `issue_get`, `put` rewrites the chunk manifest with real provider comment ids before persisting; `reassemble_body` consumes the rewritten ids so reassembly never selects stale comments.
  - **R-IDs:** R8
- [ ] 13.2 Rewrite chunk manifest with real provider comment ids on put (R8) (unit 2/2)
  - **File:** `scripts/planning_store.py`
  - **Expected:** after posting overflow comments and `issue_get`, `put` rewrites the chunk manifest with real provider comment ids before persisting; `reassemble_body` consumes the rewritten ids so reassembly never selects stale comments.
  - **R-IDs:** R8
- [ ] 13.3 Provider-aware Jira chunking in the standard write path (R9)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** `chunk_body_if_needed` applies Jira payload-size limits (port `chunk_body_for_jira_cloud`) so oversized Jira bodies chunk before the client rejects them.
  - **R-IDs:** R9
- [ ] 13.4 Chunk-reassembly + Jira-chunking fixtures (R8, R9) (unit 1/2)
  - **File:** `scripts/test/fixtures/planning-chunk-reassembly/harness.py`
  - **Expected:** repeated large updates reassemble correctly using rewritten provider comment ids (no stale comments); oversized Jira bodies chunk in the standard write path.
  - **R-IDs:** R9
- [ ] 13.5 Chunk-reassembly + Jira-chunking fixtures (R8, R9) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-jira-chunking/harness.py`
  - **Expected:** repeated large updates reassemble correctly using rewritten provider comment ids (no stale comments); oversized Jira bodies chunk in the standard write path.
  - **R-IDs:** R9

### 14. Put journal + concurrent chunked-put integrity (Wave 3 · R26, R27)

- [ ] 14.1 Partial-write journal + fail-closed manifest rewrite (R26)
  - **File:** `scripts/planning_store.py`
  - **Expected:** `put` records a partial-write journal (unit-id, step, provider ids) enabling idempotent resume; a failed manifest rewrite fails closed (prior etag or `sw:put-incomplete`), never leaving durable synthetic ids.
  - **R-IDs:** R26
- [ ] 14.2 Last-writer-wins body+comment consistency (R27)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** body + overflow-comment updates apply atomically (version token spanning the comment set, or delete-and-replace under the body etag) so reassembly never interleaves chunks from two writers.
  - **R-IDs:** R27
- [ ] 14.3 Doctor put-partial + cardinality-mismatch findings + fixtures (R26) (unit 1/2)
  - **File:** `scripts/planning-doctor.py`
  - **Expected:** doctor surfaces `put-partial` with remediation and flags manifest/comment cardinality mismatch; fixture: failure after `issue_create` leaves a resumable journal and retry converges to one issue.
  - **R-IDs:** R26
- [ ] 14.4 Doctor put-partial + cardinality-mismatch findings + fixtures (R26) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-put-journal/harness.py`
  - **Expected:** doctor surfaces `put-partial` with remediation and flags manifest/comment cardinality mismatch; fixture: failure after `issue_create` leaves a resumable journal and retry converges to one issue.
  - **R-IDs:** R26
- [ ] 14.5 Concurrent chunked-put integrity fixture (R27)
  - **File:** `scripts/test/fixtures/planning-concurrent-chunk/harness.py`
  - **Expected:** interleaved concurrent large puts reassemble to exactly one writer's body (no hybrid); doctor flags any cardinality mismatch.
  - **R-IDs:** R27

### 15. Provider-native labels + human-readable titles (Wave 4 · R11)

- [ ] 15.1 Serialize planning metadata as provider-native labels (write-side) (R11) (unit 1/2)
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** structural frontmatter keys (type/unit-id/status/topic/depends/absorbs/amends/visibility) promoted to provider-native labels; human-readable titles without `[planning] type:unit-id`; provider id treated as a storage pointer only (unit-id stays authoritative).
  - **R-IDs:** R11
- [ ] 15.2 Serialize planning metadata as provider-native labels (write-side) (R11) (unit 2/2)
  - **File:** `scripts/planning_store.py`
  - **Expected:** structural frontmatter keys (type/unit-id/status/topic/depends/absorbs/amends/visibility) promoted to provider-native labels; human-readable titles without `[planning] type:unit-id`; provider id treated as a storage pointer only (unit-id stays authoritative).
  - **R-IDs:** R11
- [ ] 15.3 Labels→unit read projection with body fallback + dual-read backfill (R11) (unit 1/2)
  - **File:** `scripts/planning_github_client.py`
  - **Expected:** read/discover paths project unit metadata from labels with body fallback; a one-release dual-read (labels + frontmatter) window and a backfill for existing issues; multi-value edges encoded within provider label-cardinality limits.
  - **R-IDs:** R11
- [ ] 15.4 Labels→unit read projection with body fallback + dual-read backfill (R11) (unit 2/2)
  - **File:** `scripts/planning_jira_client.py`
  - **Expected:** read/discover paths project unit metadata from labels with body fallback; a one-release dual-read (labels + frontmatter) window and a backfill for existing issues; multi-value edges encoded within provider label-cardinality limits.
  - **R-IDs:** R11
- [ ] 15.5 Native-labels fixture + issue-store provider docs (R32) (unit 1/2)
  - **File:** `core/providers/planning-store/issue-store.md`
  - **Expected:** metadata serialized as labels; titles human-readable; provider id canonical where supplied; docs describe labels carrying metadata with body holding prose + authoritative `sw-edges`.
  - **R-IDs:** R11
- [ ] 15.6 Native-labels fixture + issue-store provider docs (R32) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-native-labels/harness.py`
  - **Expected:** metadata serialized as labels; titles human-readable; provider id canonical where supplied; docs describe labels carrying metadata with body holding prose + authoritative `sw-edges`.
  - **R-IDs:** R11

### 16. Product source tags + schedule-hint reconciliation (Wave 4 · R12, R17)

- [ ] 16.1 Support and filter `sw:source:<owner>/<repo>` scoping (R12) (unit 1/2)
  - **File:** `scripts/planning_discover.py`
  - **Expected:** discovery/scheduler/gap-capture support `sw:source:<owner>/<repo>` scoping; default scope includes untagged legacy units with a `sw:source-missing` doctor warning rather than silently hiding them.
  - **R-IDs:** R12
- [ ] 16.2 Support and filter `sw:source:<owner>/<repo>` scoping (R12) (unit 2/2)
  - **File:** `scripts/planning_scheduler.py`
  - **Expected:** discovery/scheduler/gap-capture support `sw:source:<owner>/<repo>` scoping; default scope includes untagged legacy units with a `sw:source-missing` doctor warning rather than silently hiding them.
  - **R-IDs:** R12
- [ ] 16.3 Schedule-hint reconciliation surfaces `sw:schedule-stale` (R17)
  - **File:** `scripts/planning-graph.py`
  - **Expected:** reconcile validates each unit's `schedule:` hint (or `sw:gap-schedule:*` label) against its actual `absorbs` edges and surfaces `sw:schedule-stale` on mismatch.
  - **R-IDs:** R17
- [ ] 16.4 Source-tag + schedule-hint fixtures (R12, R17) (unit 1/2)
  - **File:** `scripts/test/fixtures/planning-schedule-hint/harness.py`
  - **Expected:** source-tag scoping filters discovery/scheduler/gap-capture; stale `schedule:` hints surface `sw:schedule-stale` against actual absorbs edges.
  - **R-IDs:** R17
- [ ] 16.5 Source-tag + schedule-hint fixtures (R12, R17) (unit 2/2)
  - **File:** `scripts/test/fixtures/planning-source-tag/harness.py`
  - **Expected:** source-tag scoping filters discovery/scheduler/gap-capture; stale `schedule:` hints surface `sw:schedule-stale` against actual absorbs edges.
  - **R-IDs:** R17

### 17. Terminal gap auto-capture + feature-named titles (Wave 5 · R19, R20)

- [ ] 17.1 Terminal auto-capture of unaddressed planning-store pain (R19) (unit 1/2)
  - **File:** `scripts/planning_gap_capture.py`
  - **Expected:** at termination, scan run-log + loop-health and auto-capture unaddressed pain as gap units with dedup against open gap titles; suppress on fail/abort verdicts; cap captures per run; human confirmation for substantial items via a substantial-vs-noise heuristic.
  - **R-IDs:** R19
- [ ] 17.2 Terminal auto-capture of unaddressed planning-store pain (R19) (unit 2/2)
  - **File:** `scripts/wave_terminal.py`
  - **Expected:** at termination, scan run-log + loop-health and auto-capture unaddressed pain as gap units with dedup against open gap titles; suppress on fail/abort verdicts; cap captures per run; human confirmation for substantial items via a substantial-vs-noise heuristic.
  - **R-IDs:** R19
- [ ] 17.3 Feature-named PR + release-please changelog titles (R20)
  - **File:** `scripts/wave_terminal.py`
  - **Expected:** `commitlint_safe_title` derives PR/changelog titles from the PRD title or task-list slug instead of the fixed `feat(prd-<n>): deliver wave` text.
  - **R-IDs:** R20
- [ ] 17.4 Terminal gap-capture + title fixtures (R19, R20) (unit 1/2)
  - **File:** `scripts/test/fixtures/deliver-terminal-gapcapture/harness.py`
  - **Expected:** terminal auto-captures deduped gap units with a confirmation gate; PR/changelog titles name the landed feature, not `deliver wave`.
  - **R-IDs:** R20
- [ ] 17.5 Terminal gap-capture + title fixtures (R19, R20) (unit 2/2)
  - **File:** `scripts/test/fixtures/terminal-title/harness.py`
  - **Expected:** terminal auto-captures deduped gap units with a confirmation gate; PR/changelog titles name the landed feature, not `deliver wave`.
  - **R-IDs:** R20

### 18. Memory backend provider round-trip — 21b (Wave 5 · R21)

- [ ] 18.1 True provider round-trip through the memory adapter with local cache (R21 / 21b)
  - **File:** `scripts/planning_store.py`
  - **Expected:** the memory backend planning-body path round-trips through the provider adapter with a local cache (21b), building on the 21a local-only rename.
  - **R-IDs:** R21
- [ ] 18.2 Memory round-trip fixture (R21 / 21b)
  - **File:** `scripts/test/fixtures/memory-roundtrip/harness.py`
  - **Expected:** planning bodies round-trip through the provider adapter (falling back to the R21a local cache when the provider is unavailable).
  - **R-IDs:** R21

### 19. Deliver-chain parity audit + published matrix (Wave 5 · R6)

- [ ] 19.1 Published command×artifact×backend parity matrix (R6)
  - **File:** `core/sw-reference/planning-deliver-parity-matrix.md`
  - **Expected:** the full `/sw-deliver` chain is audited for planning-store artifact emission parity, producing a published command×artifact×backend matrix linked from the deliver skill + configuration guide.
  - **R-IDs:** R6
- [ ] 19.2 Full-matrix CI parity fixture (R6)
  - **File:** `scripts/test/fixtures/planning-deliver-parity/full_matrix.py`
  - **Expected:** a CI fixture asserts that no file-store-only write path executes when the effective backend is issue-store authoritative; a full brainstorm→PRD→tasks→deliver cycle writes no tracked local planning artifact.
  - **R-IDs:** R6

## Relevant Files

- `scripts/planning_store.py` — issue-store backend put/freeze, kill-switch, store-host privacy, labels, journal (R7, R8, R11, R14, R26, R31, R21).
- `scripts/planning_canonical.py` — body composition, chunking, reassembly, last-writer-wins (R8, R9, R11, R27).
- `scripts/planning_migrate_issue_store.py` — shared `issue_store_separate_project` predicate + gap-backlog projection (R1).
- `scripts/gap_backlog.py`, `scripts/reconcile_lib.py` — gap resolution store close + label (R1, R4).
- `scripts/wave_spec_seed.py`, `scripts/planning_reconcile.py` — INDEX/derived-artifact write guards (R2, R3).
- `scripts/planning_query_cache.py`, `scripts/planning_discover.py` — cache revalidation + cutover call sites (R5, R10).
- `scripts/planning_gap_capture.py` — atomic gap allocation + terminal auto-capture (R25, R19).
- `scripts/planning_visibility.py` — three visibility axes + alias precedence (R13, R29).
- `scripts/planning_deliver_gate.py`, `scripts/planning_scheduler.py`, `scripts/planning-graph.py` — scheduler frontier + park + schedule hints (R16, R28, R12, R17).
- `scripts/wave_preflight.py`, `scripts/resolve-model-tier.py` — dispatch-preflight model resolution (R18).
- `scripts/wave_terminal.py` — terminal gap auto-capture + feature-named titles (R19, R20).
- `scripts/planning-doctor.py` — findings: `resolution-partial`, `put-partial`, cardinality-mismatch, `scheduler-exhausted`, `store-token-absent`/`probe-failed`, `wave-regression`, privacy-ack (R4, R14, R15, R26, R27, R28, R30, R31).
- `scripts/planning_cutover.py`, `scripts/planning_region_disposition.py` — committed cutover derivation (R5).
- `scripts/traceability-check.py`, `scripts/spec-union.py` — PRD 056 union load + no-restatement gate (R22).
- `scripts/test/fixtures/**` — per-requirement + per-wave parity, doc-impact, and integration fixtures (R6, R23, R24, R32 + all suites).
- Docs: `core/skills/**`, `core/providers/**`, `core/commands/sw-init.md`, `core/sw-reference/**`, `docs/guides/**`, `.sw/layout.md`, `CAPABILITIES.md`, `README.md` — Documentation Impact co-landing (R32).

## Notes

- **Guard predicate (D9):** R1–R4 guard on effective backend = issue-store AND `storeLocation.mode = separate-project` via the shared `issue_store_separate_project(root)` helper; `same-repo` retains local writes.
- **Contention families (see `skills/parallelism/SKILL.md`):** `scripts/planning_store.py` is shared by phases 3, 5, 11, 12, 13, 14, 15, 18 → serialized via the dependency chain 3→5→11→12→13→14→15 and 18 after 12/15. `scripts/planning-doctor.py` (phases 2, 5, 8, 11, 14) and `docs/guides/configuration.md` (phases 9, 11) contention is reflected in the dependency edges. Living INDEX/numbering and `GAP-BACKLOG.md` are issue-store authoritative under `separate-project` (no local tracked writes).
- **Cross-cutting invariants:** R22 (no 056 duplication), R23 (file-store parity), and R32 (docs co-landing) are enforced in every wave via the phase-1 scaffolding plus per-phase fixture/doc sub-tasks; R24 sequencing is asserted by the per-wave incremental parity fixture (1.4).
- **R6 wave-order deviation (D6):** the full parity audit lands in Wave 5 (phase 19) because its end-to-end matrix can only assert full parity after the Wave 2–4 guards land; per-wave incremental fixtures catch regressions earlier.
- **R21 split:** 21a (local-only rename/document, Wave 2 · phase 12) and 21b (provider round-trip, Wave 5 · phase 18) both trace to union R-ID R21.
- **Fixtures:** file-store parity fixtures always run in CI; issue-store integration fixtures skip-with-advisory when the store token is absent (R30).
- **Execute-tier granularity provenance:** `python3 scripts/tasks_generate.py apply-granularity` was run (refSplitCount 27, `check` verdict `pass`) and decomposed multi-file sub-tasks into single-file (or contention-grouped) refs; the frontmatter fences and `### N.` heading spacing it stripped were repaired to restore spec-rigor `extract_phases` compliance.

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 1 |
| 5 | 1, 3 |
| 6 | 1 |
| 7 | 6 |
| 8 | 6 |
| 9 | 1 |
| 10 | 6 |
| 11 | 5, 9 |
| 12 | 11 |
| 13 | 12 |
| 14 | 13 |
| 15 | 14 |
| 16 | 1 |
| 17 | 6, 8 |
| 18 | 12, 15 |
| 19 | 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 |

## Execute-tier granularity

> Frozen artifact (PRD 055 R17). Generated by `python3 scripts/tasks_generate.py apply-granularity` before `/sw-freeze` (refSplitCount 27; `check` verdict `pass`). Multi-file sub-tasks were decomposed into single-file refs; contention-grouped `core/**` doc pairs execute serially.

```json
{
  "version": 1,
  "generatedBy": "tasks_generate.py",
  "taskList": "docs/prds/057-planning-store-hardening/tasks-057-planning-store-hardening.md",
  "refSplitCount": 27,
  "note": "Every executable sub-task ref is within execute-tier thresholds (filesTouched<=3, distinctDirs<=2, traceabilityScenarios<=2); refs were decomposed per-file where separable, and contention-grouped doc pairs kept as serial single refs.",
  "splitPreflight": {
    "phaseCount": 19,
    "verdict": "pass",
    "oversizedRefs": []
  }
}
```

## Traceability

| R-ID | Task | Test scenario | ZOMBIES checklist |
|------|------|---------------|-------------------|
| R1 | 6.2 | `planning-file-store-parity` gap_capture_golden: store-only capture under issue-store separate-project, no GAP-BACKLOG mutation | Zero: no open gaps → sunset stub; One: single capture; Many: repeated captures; Interfaces: `--projection` flag; State: same-repo unchanged |
| R2 | 7.1 | spec-seed parity: INDEX write skipped under issue-store separate-project | Zero: no INDEX pre-exists; Boundaries: separate-project vs same-repo; Interfaces: effective-backend guard; State: file-store byte-identical |
| R3 | 7.2 | reconcile parity: no derived-artifact writes under issue-store separate-project | Zero: nothing to reconcile; Many: INDEX/archive/SUPERSEDED; Interfaces: store projection vs gitignored cache; State: same-repo retains |
| R4 | 8.1 | gap-resolution: issue close + resolution label idempotent; partial failure → `resolution-partial` | One: single gap close; Interfaces: idempotent re-run no-op; Exceptions: close-without-label partial; State: doctor reconciles mismatch |
| R5 | 9.1 | cutover-gate derived from committed config; no CI false failure | Zero: no state file; Interfaces: committed derivation; Exceptions: missing markers; State: gitignore auto-configured |
| R6 | 19.2 | `planning-deliver-parity` full_matrix: no file-store-only write under issue-store authoritative | Many: full brainstorm→PRD→tasks→deliver; Interfaces: command×artifact×backend matrix; State: end-to-end green |
| R7 | 3.1 | `planning-gitlab-demotion`: gitlab-issues absent from shipped set, selection fails closed | Zero: provider unimplemented; Interfaces: fail-closed message; Exceptions: selection refused; State: demoted to deferred |
| R8 | 13.1 | `planning-chunk-reassembly`: repeated large updates reassemble with rewritten comment ids, no stale | Many: repeated updates; Boundaries: overflow threshold; Interfaces: manifest rewrite; State: real ids replace synthetic |
| R9 | 13.3 | `planning-jira-chunking`: oversized Jira body chunks in standard write path before rejection | Boundaries: Jira payload-size limit; Many: multi-chunk body; Exceptions: over-limit pre-chunk; Interfaces: provider-aware chunker |
| R10 | 10.1 | `planning-query-cache` freshness: new remote unit visible before TTL via symmetric diff | Zero: empty cache; Many: multi-writer new units; Boundaries: pre-TTL; Interfaces: discover revalidates; State: symmetric set-diff invalidation |
| R11 | 15.1 | `planning-native-labels`: metadata as labels, human-readable titles, provider id as pointer | One: single unit; Many: multi-value edges within cardinality; Interfaces: labels→unit projection + body fallback; State: dual-read + backfill |
| R12 | 16.1 | `planning-source-tag`: `sw:source:<owner>/<repo>` scoping filters discovery/scheduler/gap-capture | Zero: untagged legacy default-included; Many: multiple sources; Interfaces: `sw:source-missing` warning; State: filterable scope |
| R13 | 11.1 | `planning-visibility-axes`: three orthogonal axes named/modeled distinctly | Boundaries: tier-first rename; Interfaces: one-release back-compat alias; State: axis separation; Exceptions: probe not sole gate |
| R14 | 11.3 | store-host privacy probed for every shipped provider; override CI-only | Zero: no placeholder always-false; Many: all shipped providers; Exceptions: unprobeable fails closed; State: `SW_STORE_HOST_PRIVACY` CI-only |
| R15 | 11.4 | `planning-doctor-privacy`: flags recordedAt:null, reconciles ackedAt/recordedAt, exact remediation | Zero: recordedAt null; Interfaces: exact remediation echo; Exceptions: required-but-unrecorded; State: key-name reconciliation |
| R16 | 2.1 | `planning-scheduler-frontier`: `next` skips unrunnable units with reasons, not frontier fail | Zero: no frozen task list; Many: multiple unrunnable; Interfaces: skip-with-reasons; State: file-path + issue-store paths both skip |
| R17 | 16.3 | `planning-schedule-hint`: stale `schedule:` surfaces `sw:schedule-stale` vs actual absorbs | One: single stale hint; Interfaces: `sw:gap-schedule:*` label; Exceptions: hint≠absorbs edges; State: reconcile signal |
| R18 | 4.1 | `dispatch-preflight` inherit+unmapped: resolves concrete model or remediation, no binding:no-model | Zero: unmapped agent; Interfaces: agent map→roles→remediation; Exceptions: no-model remediation; State: no forced inline authoring |
| R19 | 17.1 | `deliver-terminal-gapcapture`: dedup vs open titles, confirmation gate, suppress on fail | Zero: fail/abort suppresses; Many: capped captures; Boundaries: substantial-vs-noise heuristic; Interfaces: dedup by title |
| R20 | 17.3 | `terminal-title`: PR/changelog titles name landed feature, not `deliver wave` | One: single-feature title; Interfaces: PRD title/slug derivation; Boundaries: commitlint-safe; State: release-please title path |
| R21 | 12.1 | `memory-roundtrip`: 21a local-only renamed/documented; 21b provider round-trip with cache | Zero: provider unavailable → local cache; Interfaces: local-only not presented as round-trip; State: 21a rename then 21b round-trip |
| R22 | 1.1 | `spec-traceability-check`: no restated PRD 056 union text; loads 056 union from issue #218 | Zero: no restatement; Interfaces: store-loaded union; Exceptions: restated text fails; State: dependency invariant |
| R23 | 1.3 | `planning-file-store-parity`: golden outputs equivalent when backend ≠ issue-store | Many: gap capture/reconcile/spec-seed; Boundaries: byte-identical vs structural; Interfaces: per-command golden; State: pre/post guard equal |
| R24 | 1.4 | per-wave incremental parity: blockers earliest, R6 exempt to Wave 5 | Boundaries: earliest-wave blockers; Many: per-wave fixtures; Interfaces: wave assignment; State: wave-by-wave regression catch |
| R25 | 10.3 | `planning-gap-alloc-multiwriter`: two concurrent allocate+create yield distinct ids | Many: two concurrent writers; Boundaries: create-conflict; Interfaces: cache invalidated before read; Exceptions: retry-on-collision |
| R26 | 14.1 | `planning-put-journal`: failure after issue_create leaves resumable journal + `put-partial` | Exceptions: failure mid-put; Interfaces: idempotent resume; State: fail-closed manifest rewrite; Idempotency: retry converges no dup |
| R27 | 14.2 | `planning-concurrent-chunk`: interleaved puts reassemble to exactly one body, no hybrid | Many: two concurrent large puts; Boundaries: body etag; Interfaces: version token/delete-replace; State: cardinality mismatch flagged |
| R28 | 2.3 | `planning-parked-governance`: all-parked frontier → `scheduler-exhausted`; unauthorized park refused | Zero: empty post-filter frontier; Exceptions: unauthorized park; Interfaces: allowlist + reason; State: over-parked drift finding |
| R29 | 11.2 | `planning-visibility-aliases`: deprecated+new resolve to new-key with warning; deprecated-only pre-rename | Boundaries: both keys present; Interfaces: precedence table; Exceptions: deprecation warning; State: redaction default never weakened |
| R30 | 5.1 | `planning-ci-token-absent`: token unset → integration skip-with-advisory, file-store parity runs | Zero: token env unset; Interfaces: skip-with-advisory; Exceptions: `store-token-absent` not `probe-failed`; State: deterministic green |
| R31 | 5.3 | `planning-wave-rollback`: revert wave + kill-switch restores prior behavior, re-materializes | Interfaces: effective-backend kill-switch; Exceptions: `wave-regression` on drift; State: re-materialize from store; Idempotency: no data loss |
| R32 | 1.5 | `planning-057-doc-impact`: behavior change without paired doc update in same wave fails | Zero: no doc drift; Many: per-requirement doc paths; Interfaces: requirement→doc map; State: co-landing per wave |