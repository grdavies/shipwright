---
date: 2026-06-27
topic: planning-feedback-lifecycle
prd: docs/prds/035-planning-autonomy-and-orchestration/035-prd-planning-autonomy-and-orchestration.md
frozen: true
frozen_at: 2026-06-29
absorbs_amendments:
  - amendments/A1-deliver-conductor-completion.md
  - amendments/A2-gap-lifecycle-and-doc-format.md
---

# Tasks — PRD 035 Planning Autonomy, Backlog Pull-In & Two-Track Orchestration

Generated from the frozen PRD spec union **R1–R24** plus amendments **A1 R25–R50** and **A2 R51–R58** (Requirements + Technical Requirements + Security &
Compliance; no amendments). This is the capstone of the Planning & Feedback Lifecycle and **composes** PRD
031 (unit model + path helper), 032 (mutation-safety guards + `inFlight` signal), 033 (lifecycle/reconciler/
scheduler + INDEX `derived`/`inFlight` regions), and 034 (visibility resolver) — those are external `depends:`
prerequisites, not intra-PRD phases. Six dependency-ordered phases mirror the rollout: the related-units
scanner + pull-in proposal flow (Phase 1) and the two-track edit driver (Phase 3) are independent infra that
can land in parallel; the autonomy posture + bounded `full-conductor` (Phase 2) builds on the scanner's
proposals; the finalized command surface (Phase 4) wires all three; emitter/dist parity (Phase 5) and the
doc-impact acceptance + no-regression gates (Phase 6) close out. Every phase ships behind passing fixtures
registered in `core/sw-reference/pr-test-plan.manifest.json` and is independently mergeable.

## Tasks

### 1. Related-units scanner + pull-in proposal flow — L

- [ ] 1.1 Related-units scanner module + confirm-list emission (R17)
  - **File:** `scripts/planning-related.sh`, `scripts/planning_related.py`
  - **Expected:** scanner reads the PRD 031/033 graph and produces ranked, threshold-gated absorption/amendment
    proposals consumed by `/sw-prd` and `/sw-tasks`; routes every candidate through the visibility resolver
    (R4) and emits a **confirm-list, never an auto-absorb**. Fixture `scanner-confirm-list-not-autoabsorb`
    asserts proposal output contains no applied edges.
  - **R-IDs:** R17
- [ ] 1.2 Deterministic-first similarity + opt-in semantic + minimum-recall (R5)
  - **File:** `scripts/planning_related.py`
  - **Expected:** similarity ships deterministic-first (shared file paths + tags + id/lineage edges); semantic
    matching is opt-in behind a config flag and only widens the proposal set (never auto-absorbs); proposals
    are rank-thresholded and repeat proposals for already-flagged stale candidates are suppressed. Fixtures:
    `related-deterministic-rank-threshold`, `related-repeat-suppression`, `semantic-optin-flag-gated`, and the
    minimum-recall acceptance fixture `min-recall-gap-043-044-046` asserting those absorption cases appear in
    proposals on the migrated corpus.
  - **R-IDs:** R5
- [ ] 1.3 Visibility-resolver routing for proposals (private metadata-only) (R4)
  - **File:** `scripts/planning_related.py`, `core/skills/visibility/references/emission-points.md`
  - **Expected:** pull-in proposals route through the PRD 034 resolver; private-unit candidates contribute
    metadata only (id/title/status/edges, honoring opaque-title) and never body text, even under opt-in
    semantic matching; the confirm-list is registered in the 034 emission-point registry. Fixture
    `private-metadata-only-proposal` proves a private gap's non-opaque title may appear in a proposal but its
    body never does.
  - **R-IDs:** R4
- [ ] 1.4 Frozen-safe pull-in routing (R7)
  - **File:** `scripts/planning_related.py`, `scripts/planning-related.sh`
  - **Expected:** a pull-in/absorption confirm against a frozen or `planned` (frozen) unit does not mutate the
    frozen unit — it is routed to an amendment track or a new superseding unit; adding an `absorbs:` edge that
    would change frozen scope requires explicit `--accept-frozen-impact` (logged); freeze immutability (031
    R17) has no pull-in exception. Fixture `frozen-pull-in-routes-amendment` asserts no frozen mutation absent
    the flag.
  - **R-IDs:** R7
- [ ] 1.5 `/sw-prd` creation pull-in proposal + stale flagging + human confirm (R1)
  - **File:** `core/commands/sw-prd.md`
  - **Expected:** at PRD/unit creation the graph is auto-scanned for related gap/units; absorption candidates
    are proposed; the scan flags stale candidates already resolved/absorbed by a shipped unit; the human
    confirms which to absorb (gated authoring). Fixture `prd-pull-in-proposal-confirm` exercises propose to
    stale-flag to confirm.
  - **R-IDs:** R1
- [ ] 1.6 `/sw-tasks` generation re-scan amendment proposal + confirm (R2)
  - **File:** `core/commands/sw-tasks.md`
  - **Expected:** at task generation the backlog is re-scanned for newly-related items and PRD amendments are
    proposed; the human confirms. Fixture `tasks-rescan-amendment-proposal`.
  - **R-IDs:** R2
- [ ] 1.7 Autonomous absorption-edge maintenance, choices human-gated (R3)
  - **File:** `core/commands/sw-prd.md`, `core/commands/sw-tasks.md`
  - **Expected:** edge/status maintenance for absorption is autonomous (materialized by the PRD 033
    reconciler); only the pull-in and amendment **choices** are human-gated. Fixture
    `absorption-edge-autonomous-choices-gated` asserts the reconciler applies edges only after a confirmed
    choice.
  - **R-IDs:** R3
- [ ] 1.8 Proposal payload redaction (R22)
  - **File:** `scripts/planning_related.py`, `core/scripts/memory-redact.sh`
  - **Expected:** pull-in/amendment proposals route external/context payloads through `memory-redact.sh` and
    embed them only in fenced untrusted blocks; the proposal step never forwards raw transcripts or provider
    memory payloads; private-unit bodies/opaque titles are filtered by the visibility resolver (R4). Fixture
    `proposal-payload-redaction`.
  - **R-IDs:** R22

### 2. Autonomy posture + bounded full-conductor — L

- [ ] 2.1 `planning.autonomy` config key owned here (R19)
  - **File:** `core/sw-reference/config.schema.json`, `core/sw-reference/workflow.config.example.json`, `.sw/workflow.config.example.json`
  - **Expected:** the `planning.autonomy` enum key (`maintenance-only` default | `full-conductor`) is owned
    here (PRD 033 reads it and stubs the default in the train); the bounded full-conductor path adopts the
    conductor skill's legitimate-halt model and records the confidence threshold, per-session mutation budget,
    undo window, and the gap/absorption-only + non-private absorption scope; cross-ref to 033 soft-enforce.
    Fixture `planning-autonomy-config-enum` validates the enum + closed-world rejection.
  - **R-IDs:** R19
- [ ] 2.2 Maintenance-only default — autonomous bookkeeping, gated content (R6)
  - **File:** `scripts/planning_autonomy.py`, `core/skills/conductor/SKILL.md`
  - **Expected:** mechanical/living maintenance graph bookkeeping runs autonomously with no prompts;
    content-authoring decisions (pull-in, amendments, priority changes, cancel/supersede) are auto-proposed but
    human-confirmed by default. Fixture `maintenance-only-default-no-prompts`.
  - **R-IDs:** R6
- [ ] 2.3 Bounded `full-conductor` driver (R8)
  - **File:** `scripts/planning_autonomy.py`, `core/skills/conductor/SKILL.md`
  - **Expected:** the `full-conductor` opt-in elevates **gap/absorption-class** content decisions to in-loop
    auto-decision governed by the conductor's legitimate-halt model; off by default; never weakens the
    merge-to-`main` gate; **never auto-absorbs `private`/`memory` units**; subject to a per-session
    autonomous-mutation budget + loop hard-stop inherited from the conductor skill (halt + human resume after N
    mutations); absorption still requires an explicit edge-confidence threshold and a reversible undo window
    before the PRD 033 reconciler materializes the flip. Fixture `full-conductor-bounded-budget-halt` asserts
    gap-only elevation, private-unit refusal, budget halt, and undo.
  - **R-IDs:** R8
- [ ] 2.4 Enqueue-handoff-only / no nested dispatch (R9)
  - **File:** `scripts/planning_autonomy.py`, `core/rules/sw-naming.mdc`
  - **Expected:** the `full-conductor` driver only **enqueues handoff commands**; it may not invoke
    `/sw-deliver`, `/sw-doc`, or any orchestrator from within its loop (sw-naming/sw-conductor boundary), and
    there is an explicit halt between a reconcile batch and any downstream dispatch. Fixture
    `enqueue-handoff-no-nested-dispatch`.
  - **R-IDs:** R9
- [ ] 2.5 Durable logging of autonomy/override actions + budget cap (R23)
  - **File:** `scripts/planning_autonomy.py`
  - **Expected:** `full-conductor` opt-in, any `--override`, `--accept-frozen-impact`, and direct-to-trunk are
    explicit, logged to durable state (who/when/why), and never the default; branch protection is never
    bypassed; the per-session mutation budget caps autonomous graph churn. Fixture
    `autonomy-actions-logged-durable`.
  - **R-IDs:** R23

### 3. Two-track edit driver — L

- [ ] 3.1 Two-track edit driver module (R18)
  - **File:** `scripts/docs-edit-route.sh`, `scripts/two_track_lib.py`
  - **Expected:** the driver classifies an edit as mechanical (batched auto-merge PR / direct-to-trunk where
    permitted) vs substantive (auto-driven docs worktree + PR) using the R11 allowlist; it reuses the existing
    `docs_worktree.sh`/`docs_pr.sh` machinery and adds the net-new `docs-merge.sh`, the host-API
    branch-protection probe (R13), and the both-region content-hash abort (R14). Fixture
    `two-track-driver-classify-route` mirrors the merge-queue fixtures.
  - **R-IDs:** R18
- [ ] 3.2 Mechanical allowlist classifier (R11)
  - **File:** `scripts/two_track_lib.py`
  - **Expected:** the mechanical allowlist is limited to **reconciler-generated artifacts** — the INDEX
    active/archive **`derived` region only**, the SUPERSEDED manifest, and the generated gap index; the
    `inFlight` region is **never** mechanically edited (it is the PRD 032 deliver writer's sole region); **any
    path under `docs/planning/<unit-id>/` — body or frontmatter — is substantive**. Fixtures:
    `mechanical-allowlist-derived-only`, `inflight-never-mechanical`, `planning-path-forced-substantive`, and
    the misclassification regression `frontmatter-edit-substantive-regression`.
  - **R-IDs:** R11
- [ ] 3.3 Mechanical batched docs-only PR + CI-gated auto-merge (R10)
  - **File:** `scripts/docs-merge.sh`
  - **Expected:** mechanical/living maintenance edits are batched and committed via a docs-only PR with
    CI-gated auto-merge (or direct-to-trunk where the repo permits), without a per-edit PR. Fixture
    `mechanical-batched-auto-merge`.
  - **R-IDs:** R10
- [ ] 3.4 Substantive auto-driven docs worktree + PR (R12)
  - **File:** `scripts/docs-edit-route.sh`, `scripts/docs_worktree.sh`, `scripts/docs_pr.sh`
  - **Expected:** substantive authoring retains the docs-branch to docs-PR gate but is fully auto-driven
    (auto-provisioned worktree, auto-opened PR) so it is a single command rather than manual git. Fixture
    `substantive-auto-driven-pr`.
  - **R-IDs:** R12
- [ ] 3.5 Host-API branch-protection probe + fail-closed PR path (R13)
  - **File:** `scripts/host_lib.py`, `scripts/docs-merge.sh`
  - **Expected:** protection is detected via the host API (not assumed); when detection is ambiguous or `gh`
    auth is missing, the driver defaults to the PR path and never attempts a direct push; `allowDirectTrunk:
    true` requires a **live protection probe succeeding within a configured TTL** and is **never combined with
    auto-merge in public-repo templates**; under any detected protection it fails closed to the PR path.
    Fixture `branch-protection-defaults-pr-path`.
  - **R-IDs:** R13
- [ ] 3.6 Both-region content-hash serialization + auto-merge abort (R14)
  - **File:** `scripts/docs-merge.sh`, `scripts/two_track_lib.py`
  - **Expected:** the batched PR embeds a **monotonic content-hash covering both INDEX regions (`derived` +
    `inFlight`)** taken at open; the auto-merge is aborted if either region's hash advanced since — so a stale
    maintenance PR can never revert reconciler updates or clobber in-flight markers. Fixture
    `both-region-content-hash-abort`.
  - **R-IDs:** R14
- [ ] 3.7 Pre-merge mechanical safety + secret-scan (R24)
  - **File:** `scripts/docs-merge.sh`
  - **Expected:** two-track auto-merge applies only to mechanical maintenance on the docs path (R11 allowlist)
    and never to substantive specs, the `inFlight` region, or the protected trunk merge gate; a pre-merge
    fixture fails the mechanical PR if any unit-body marker or `docs/planning/<unit-id>/` path appears in its
    diff, and runs the same secret-scan as pre-push. Fixture `mechanical-premerge-secret-scan`.
  - **R-IDs:** R24

### 4. Planning command surface finalization — S

- [x] 4.1 Wire reconciler entry, scheduler entry, and posture config (R15)
  - **File:** `core/commands/sw-doc.md`, `scripts/planning-graph.sh`
  - **Expected:** the planning command surface is finalized (D6) and wired — the mechanical reconciler entry
    (`scripts/planning-graph.sh reconcile`, invoked by living-status and `/sw-doc`), the graph-driven scheduler
    entry (`/sw-deliver next`, PRD 033), and the `planning.autonomy` posture config key; commands resolve paths
    via the PRD 031 helper; no new top-level command (extends `/sw-doc`, not a `/sw-plan`). Fixture
    `command-surface-wired`.
  - **R-IDs:** R15

### 5. Emitter + dist parity — S

- [x] 5.1 `copy-to-core` parity + emitter freshness for new scripts/config (R20)
  - **File:** `scripts/copy-to-core.sh`, `dist/cursor/scripts/`, `dist/claude-code/scripts/`
  - **Expected:** autonomy/pull-in/two-track artifacts land in `core/` and propagate to both dist trees;
    `copy-to-core` parity and emitter-freshness fixtures cover the new scripts and config keys. Fixtures:
    `copy-to-core-parity-035`, `emitter-freshness-035`.
  - **R-IDs:** R20

### 6. Doc-impact acceptance + no-regression — M

- [ ] 6.1 Doc-impact acceptance updates (R21)
  - **File:** `core/commands/sw-prd.md`, `core/commands/sw-tasks.md`, `core/commands/sw-doc.md`,
    `core/commands/sw-feedback.md`, `core/skills/feedback/references/route-record.md`, `core/rules/sw-naming.mdc`,
    `core/skills/git-workflow/SKILL.md`, `core/rules/sw-git-conventions.mdc`, `core/skills/conductor/SKILL.md`,
    `core/sw-reference/config.schema.json`, `core/sw-reference/workflow.config.example.json`,
    `.sw/workflow.config.example.json`, `docs/guides/configuration.md`, `docs/guides/workflows.md`,
    `docs/guides/commands.md`
  - **Expected:** as acceptance criteria, this PRD updates the docs it changes: `sw-prd.md`/`sw-tasks.md`
    (pull-in proposal confirm-list); `sw-doc.md` (reconciler hook, two-track edits, posture);
    `sw-feedback.md` + `route-record.md` + `sw-naming.mdc` (route gap-capture to gap units, not GAP-BACKLOG);
    `git-workflow/SKILL.md` + `sw-git-conventions.mdc` (two-track policy); `conductor/SKILL.md` (bounded
    full-conductor legitimate-halt + mutation-budget + no-nested-dispatch clauses); `config.schema.json` + both
    `workflow.config.example.json` copies + `configuration.md` (the `planning.autonomy` enum key with cross-ref
    to 033 soft-enforce); and the 033-coordinated `workflows.md`/`commands.md` 035-owned sections (two-track
    edit driver, mechanical allowlist, posture, full-conductor — the lifecycle/reconciler sections are
    033-owned). Fixture `doc-currency-035`.
  - **R-IDs:** R21
- [ ] 6.2 No-regression on delivery-feeding documentation gates (R16)
  - **File:** `scripts/spec-rigor-check.sh`, `scripts/traceability-check.sh`
  - **Expected:** no regression to the documentation that feeds the delivery loop — frozen immutability,
    traceability, and spec-rigor gates are preserved; foundational frozen workflow invariants are retained.
    Fixture `no-regression-035`.
  - **R-IDs:** R16


### 7. Deliver conductor completion (amendment A1) — L

- [x] 7.1 Build-chain ship verify + parity in verify.test (R25–R26)
  - **File:** `core/commands/sw-ship.md`, `.cursor/workflow.config.json`, `scripts/build-chain-sync.sh`
  - **Expected:** phase/terminal ship fails when build-chain paths drift; `verify.test` includes parity fixtures.
    Fixtures: `ship-without-build-chain-sync-fails`, `verify-test-includes-parity`.
  - **R-IDs:** R25, R26
- [x] 7.2 Post-merge environmental verify + deterministic regen (R27–R29)
  - **File:** `scripts/wave_merge.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** build-chain-only post-merge failures classify environmental; parallel-wave regen before verify.
    Fixtures: `post-merge-build-chain-environmental`, `merge-queue-deterministic-regen`, `parallel-wave-regen-before-verify`.
  - **R-IDs:** R27, R28, R29
- [x] 7.3 Remediation routing + batch queue hygiene (R30–R34)
  - **File:** `scripts/wave_deliver_loop.py`, `scripts/wave_failure.py`
  - **Expected:** `verify:failed` routes remediate; no-progress does not pre-empt; batch head reconcile after stabilize.
    Fixtures: `verify-failed-routes-remediate`, `no-progress-before-first-remediate`, `current-wave-overflow-terminal`, `whole-batch-merge-wait`, `batch-integration-head-reconcile`.
  - **R-IDs:** R30, R31, R32, R33, R34
- [x] 7.4 Conductor continuity + terminal path (R35–R43)
  - **File:** `core/skills/conductor/SKILL.md`, `scripts/wave_terminal.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** no illegitimate halts; terminal autonomy honors `deliver.terminal.autonomy: auto`.
    Fixtures: `post-remediation-no-status-pause`, `dispatch-ship-completes-in-turn`, `await-agent-same-turn-continue`, `terminal-eligibility-teardown-green-parity`, `terminal-retro-before-pr-auto`, `terminal-ship-autonomous-watch`, `single-flight-phase-ship`, `terminal-status-provenance-reemit`, `terminal-pr-prepare-commitlint`.
  - **R-IDs:** R35, R36, R37, R38, R39, R40, R41, R42, R43
- [x] 7.5 Worktree lifecycle + operator resume (R44–R47)
  - **File:** `scripts/wave_merge.py`, `scripts/wave_failure.py`, `scripts/wave_lifecycle.py`
  - **Expected:** eager teardown; parallel ceiling wouldFree; `/sw-deliver run` resume strings.
    Fixtures: `eager-phase-teardown-after-merge`, `parallel-ceiling-would-free`, `status-collect-background-worktree`, `deliver-resume-command-is-sw`.
  - **R-IDs:** R44, R45, R46, R47
- [x] 7.6 Docs durability + deferrals (R48–R50)
  - **File:** `scripts/wave_spec_seed.py`, `scripts/planning_legacy_projection.py`, `core/commands/sw-deliver.md`
  - **Expected:** post-freeze durability; projection refuse; cleanup autonomy hook when configured.
    Fixtures: `post-freeze-docs-durability`, `projection-refuse-hand-maintained`, `re-freeze-contract-amendment`, `cleanup-autonomy-auto-post-merge`.
  - **R-IDs:** R48, R49, R50

### 8. Gap lifecycle + doc format (amendment A2) — M

- [x] 8.1 Mechanical gap resolve + freeze absorbs flip (R51–R52)
  - **File:** `scripts/living-status-gap-resolve.sh`, `core/commands/sw-freeze.md`
  - **Expected:** PRD ship flips gap rows; freeze writes schedule from `absorbs:` frontmatter.
    Fixtures: `gap-resolve-on-prd-ship`, `freeze-absorbs-flips-gap-schedule`.
  - **R-IDs:** R51, R52
- [x] 8.2 Gap backlog integrity guard (R53–R54)
  - **File:** `scripts/gap-backlog.sh`, `scripts/docs-currency-gate.sh`, `core/skills/living-status/SKILL.md`
  - **Expected:** index/table binary status consistency CI guard.
    Fixtures: `gap-backlog-index-integrity`, `gap-backlog-ci-guard`.
  - **R-IDs:** R53, R54
- [x] 8.3 Shared doc-format tokenizer (R55–R58)
  - **File:** `scripts/doc_format_tokenizer.py`, `scripts/spec-rigor-check.sh`, `scripts/traceability-check.sh`
  - **Expected:** normalize-before-rigor; shared regex; minimum-recall passes; feedback routing prefers gap units.
    Fixtures: `doc-format-normalize-before-rigor`, `spec-rigor-traceability-regex-parity`, `min-recall-gap-043-044-046`.
  - **R-IDs:** R55, R56, R57, R58

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | none |
| 4 | 1, 2, 3 |
| 5 | 1, 2, 3, 4 |
| 6 | 4, 5 |
| 7 | 1, 2, 3, 4, 5, 6 |
| 8 | 1, 7 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.5 | prd-pull-in-proposal-confirm |
| R2 | 1.6 | tasks-rescan-amendment-proposal |
| R3 | 1.7 | absorption-edge-autonomous-choices-gated |
| R4 | 1.3 | private-metadata-only-proposal |
| R5 | 1.2 | min-recall-gap-043-044-046 |
| R6 | 2.2 | maintenance-only-default-no-prompts |
| R7 | 1.4 | frozen-pull-in-routes-amendment |
| R8 | 2.3 | full-conductor-bounded-budget-halt |
| R9 | 2.4 | enqueue-handoff-no-nested-dispatch |
| R10 | 3.3 | mechanical-batched-auto-merge |
| R11 | 3.2 | mechanical-allowlist-derived-only |
| R12 | 3.4 | substantive-auto-driven-pr |
| R13 | 3.5 | branch-protection-defaults-pr-path |
| R14 | 3.6 | both-region-content-hash-abort |
| R15 | 4.1 | command-surface-wired |
| R16 | 6.2 | no-regression-035 |
| R17 | 1.1 | scanner-confirm-list-not-autoabsorb |
| R18 | 3.1 | two-track-driver-classify-route |
| R19 | 2.1 | planning-autonomy-config-enum |
| R20 | 5.1 | copy-to-core-parity-035 |
| R21 | 6.1 | doc-currency-035 |
| R22 | 1.8 | proposal-payload-redaction |
| R23 | 2.5 | autonomy-actions-logged-durable |
| R24 | 3.7 | mechanical-premerge-secret-scan |
| R25 | 7.1 | ship-without-build-chain-sync-fails |
| R26 | 7.1 | verify-test-includes-parity |
| R27 | 7.2 | post-merge-build-chain-environmental |
| R28 | 7.2 | merge-queue-deterministic-regen |
| R29 | 7.2 | parallel-wave-regen-before-verify |
| R30 | 7.3 | verify-failed-routes-remediate |
| R31 | 7.3 | no-progress-before-first-remediate |
| R32 | 7.3 | current-wave-overflow-terminal |
| R33 | 7.3 | whole-batch-merge-wait |
| R34 | 7.3 | batch-integration-head-reconcile |
| R35 | 7.4 | post-remediation-no-status-pause |
| R36 | 7.4 | dispatch-ship-completes-in-turn |
| R37 | 7.4 | await-agent-same-turn-continue |
| R38 | 7.4 | terminal-eligibility-teardown-green-parity |
| R39 | 7.4 | terminal-retro-before-pr-auto |
| R40 | 7.4 | terminal-ship-autonomous-watch |
| R41 | 7.4 | single-flight-phase-ship |
| R42 | 7.4 | terminal-status-provenance-reemit |
| R43 | 7.4 | terminal-pr-prepare-commitlint |
| R44 | 7.5 | eager-phase-teardown-after-merge |
| R45 | 7.5 | parallel-ceiling-would-free |
| R46 | 7.5 | status-collect-background-worktree |
| R47 | 7.5 | deliver-resume-command-is-sw |
| R48 | 7.6 | post-freeze-docs-durability |
| R49 | 7.6 | (deferral doc — no fixture) |
| R50 | 7.6 | cleanup-autonomy-auto-post-merge |
| R51 | 8.1 | gap-resolve-on-prd-ship |
| R52 | 8.1 | freeze-absorbs-flips-gap-schedule |
| R53 | 8.2 | gap-backlog-index-integrity |
| R54 | 8.2 | gap-backlog-ci-guard |
| R55 | 8.3 | doc-format-normalize-before-rigor |
| R56 | 8.3 | spec-rigor-traceability-regex-parity |
| R57 | 8.3 | min-recall-gap-043-044-046 |
| R58 | 8.3 | (feedback routing — doc + fixture) |


## Notes

- External `depends:` (not intra-PRD phases): PRD 031 (unit schema + path helper + INDEX generator seam), 032
  (`inFlight` region + mutation-safety guards), 033 (lifecycle/reconciler `scripts/planning-graph.sh`,
  scheduler `/sw-deliver next`, INDEX `derived`/`inFlight` regions, SUPERSEDED manifest, gap index), and 034
  (visibility resolver + emission-point registry). Phase 3 replaces the PRD 033 R17 interim no-auto-PR
  behavior.
- Net-new surfaces: `scripts/planning-related.sh` + `scripts/planning_related.py` (scanner),
  `scripts/planning_autonomy.py` (bounded full-conductor driver), `scripts/docs-edit-route.sh` +
  `scripts/two_track_lib.py` (two-track classifier/driver), and `scripts/docs-merge.sh` (merge + checks-wait,
  since `docs_pr.sh` stops at PR open). All new fixtures register in
  `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.
- The `full-conductor` driver only enqueues handoffs and never nests orchestrator dispatch (R9); branch
  protection is never bypassed and auto-merge never touches the protected trunk gate (R13/R24).
