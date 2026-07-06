---
prd: docs/planning/prd/056-prd-issue-store-deliver-progress-native-links/056-prd-issue-store-deliver-progress-native-links.md
visibility: public
frozen: true
frozen_at: 2026-07-06
rescan: A3-deliver-run-entry-materialize
---

# Tasks — PRD 056 Issue-store deliver progress and native provider links

## Relevant Files

- `scripts/planning_github_client.py` — GitHub native link REST
- `scripts/planning_gitlab_client.py` — GitLab link REST
- `scripts/planning_jira_client.py` — Jira issue links
- `scripts/issues_lib.py` — IssuesClient link forwarding
- `scripts/planning_canonical.py` — edge → native resolver
- `scripts/planning_migrate_issue_store.py` — migration native projection
- `scripts/planning_gap_capture.py` — gap native links
- `scripts/planning_hierarchy.py` — epic/sub-issue apply
- `scripts/planning_progress.py` — new progress sync module
- `scripts/wave_deliver_loop.py` — phase provision hook
- `scripts/wave_merge.py` — post-merge progress sync
- `scripts/wave_living_docs.py` — issue-store INDEX projection
- `scripts/phase_acceptance_gate.py` — checkbox → issue sync
- `core/sw-reference/suite-registry.json` — fixture registration
- `scripts/wave_deliver.py` — run-entry task list resolution
- `scripts/planning_deliver_gate.py` — scheduler taskList resolution
- `scripts/planning_path_redirect.py` — materialized path redirect

## Notes

- Absorbs **gap-038** via amendment **A3** — Phase 0 MUST complete before Phase 1 (deliver run-entry bootstrap).
- Closes gap-033, gap-037, gap-002, gap-003 (via amendments A1–A2). Phase 1–2 MUST complete before Phase 3+ (native links block hierarchy).
- File-store repos: guard all mutations behind `resolve_effective_backend`.

## Tasks

### 0. Run-entry materialize (small) — Amendment A3

- [x] 0.1 Run-entry materialize before plan/preflight
  - **File:** `scripts/planning_materialize.py`, `scripts/wave_deliver.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** issue-store effective and logical `body-path` absent → materialize + `verify-frozen-hash` before `plan`/`preflight`; no operator bootstrap
  - **R-IDs:** R17, R19

- [x] 0.2 `resolve_task_list_path` materialized fallback
  - **File:** `scripts/wave_deliver.py`, `scripts/wave_spec_seed.py`, `scripts/planning_path_redirect.py`
  - **Expected:** reads `.cursor/planning-materialized/<body-path>` when logical path missing; file-store unchanged
  - **R-IDs:** R18

- [x] 0.3 Scheduler returns runnable `taskList` for issue-only units
  - **File:** `scripts/planning_deliver_gate.py`, `scripts/planning_scheduler.py`
  - **Expected:** `/sw-deliver next` and `task_list_for_unit` work without code-repo stub files
  - **R-IDs:** R20

- [x] 0.4 Add `planning-deliver-run-entry-fixtures` harness
  - **File:** `scripts/unit_tests/planning/harness_planning_deliver_run_entry.py`, `core/sw-reference/suite-registry.json`
  - **Expected:** no local task file; `preflight`/`plan` pass after run-entry materialize only
  - **R-IDs:** R10, R17, R18, R19, R20

### 1. GitHub native links adapter (small)

- [ ] **1.1** Implement native link create/sync in `planning_github_client.py`
  - **File:** `scripts/planning_github_client.py`, `scripts/issues_lib.py`
  - **Expected:** `create`/`update` accept `native_links`; `get` returns persisted links; no `del native_links`
  - **R-IDs:** R1, R2

- [ ] **1.2** Extend `probe-issues-token` for link/sub-issue scope
  - **File:** `scripts/planning_store.py`
  - **Expected:** probe JSON includes `nativeLinksCapable: true|false`
  - **R-IDs:** R3, R10

- [ ] **1.3** Add `planning-native-links-fixtures` harness (GitHub fixture tree)
  - **File:** `scripts/unit_tests/planning/harness_planning_native_links.py`, `core/sw-reference/suite-registry.json`
  - **Expected:** round-trip create → get → reconcile_edges pass
  - **R-IDs:** R10

### 2. GitLab and Jira native links (medium)

- [ ] **2.1** GitLab client native link implementation
  - **File:** `scripts/planning_gitlab_client.py`
  - **Expected:** same contract as GitHub; degradation notice on missing capability
  - **R-IDs:** R1, R2, R3

- [ ] **2.2** Jira client issue-link implementation
  - **File:** `scripts/planning_jira_client.py`
  - **Expected:** `linkDefaults` config; createmeta-driven link type; notice on failure
  - **R-IDs:** R1, R2, R3

- [ ] **2.3** `native_links_from_edges` resolver in planning_canonical
  - **File:** `scripts/planning_canonical.py`
  - **Expected:** resolves unit ids → issue ids via issue unit index
  - **R-IDs:** R4

### 3. Emit native links on planning writes (medium)

- [ ] **3.1** Migration create passes native projections
  - **File:** `scripts/planning_migrate_issue_store.py`
  - **Expected:** files-to-issues verify includes native link parity
  - **R-IDs:** R4

- [ ] **3.2** Gap capture + hierarchy create emit native links
  - **File:** `scripts/planning_gap_capture.py`, `scripts/planning_hierarchy.py`
  - **Expected:** sub-issue-of and depends edges create provider links
  - **R-IDs:** R4

### 4. Deliver provision hierarchy wiring (medium)

- [ ] **4.1** Add `planning_progress.py` scaffold + hierarchyMap state shape
  - **File:** `scripts/planning_progress.py`, `scripts/wave_state.py`
  - **Expected:** durable `hierarchyMap` on deliver state; load/save helpers
  - **R-IDs:** R5, R7

- [ ] **4.2** Invoke hierarchy apply from phase provision
  - **File:** `scripts/wave_deliver_loop.py` (or `wave.py phase provision`)
  - **Expected:** issue-store effective → non-dry-run hierarchy; checkbox fallback notice only
  - **R-IDs:** R5, R9

- [ ] **4.3** Fixture: provision calls hierarchy when issue-store configured
  - **File:** `scripts/unit_tests/planning/harness_planning_deliver_progress.py`
  - **Expected:** stub client records epic + sub-issue creates
  - **R-IDs:** R10

### 5. Phase-green progress sync (medium)

- [ ] **5.1** `sync_phase_done` updates sub-issue labels/state
  - **File:** `scripts/planning_progress.py`, `scripts/wave_merge.py`
  - **Expected:** after merge-ready-green, `sw:phase:<id>:done` label applied
  - **R-IDs:** R6, R7

- [ ] **5.2** Checkbox toggle propagation from phase acceptance / execute status
  - **File:** `scripts/phase_acceptance_gate.py`, `scripts/execute_task_status.py`
  - **Expected:** toggles sync when hierarchyMap present
  - **R-IDs:** R7

- [ ] **5.3** Deliver progress fixtures (simulated phase green)
  - **File:** `scripts/unit_tests/planning/harness_planning_deliver_progress.py`
  - **Expected:** phase 1 green → sub-issue label delta asserted
  - **R-IDs:** R10

### 6. Living-docs issue projection (small)

- [ ] **6.1** Issue-store projection in living-docs reconcile
  - **File:** `scripts/wave_living_docs.py`, `scripts/planning_index_issue.py` (new or extend planning_index_gen)
  - **Expected:** when cutover derived=issue, INDEX status written via `planning_store.put`
  - **R-IDs:** R8, R9

- [ ] **6.2** Extend planning-cutover fixtures for reconcile projection
  - **File:** `scripts/unit_tests/git/harness_planning_cutover.py`
  - **Expected:** derived=issue → put called; file-store unchanged when file authority
  - **R-IDs:** R8, R10

### 7. Doc-currency and gap closure (small)

- [ ] **7.1** Update workflows.md + issue-store provider docs for native links + deliver sync
  - **File:** `docs/guides/workflows.md`, `core/providers/planning-store/issue-store.md`
  - **Expected:** documents hook points and degradation notices
  - **R-IDs:** R1–R8

- [ ] **7.2** Mark gap-033 and gap-037 resolved via reconcile after merge
  - **File:** `docs/prds/GAP-BACKLOG.md` projection / issue-store gap units
  - **Expected:** gap status `resolved` with absorbs PRD 056 reference
  - **R-IDs:** R10


### 8. Issue-store doc pipeline authoring (medium) — Amendment A1

- [ ] **8.1** Route `/sw-brainstorm`, `/sw-prd`, `/sw-tasks` through `planning_store.put`
  - **File:** `core/skills/brainstorm/SKILL.md`, `core/skills/prd/SKILL.md`, `core/skills/tasks/SKILL.md`, `core/commands/sw-doc.md`
  - **Expected:** issue-store effective → put only; no local `docs/brainstorms` or `docs/prds` writes
  - **R-IDs:** R11, R12

- [ ] **8.2** Extend spec-rigor + doc_link for issue-store handles
  - **File:** `scripts/spec-rigor-check.py`, `scripts/doc_link.py`
  - **Expected:** gates pass on virtual body-path + unit id without git file
  - **R-IDs:** R13

- [ ] **8.3** Fixture: sw-doc dry-run creates issues not files
  - **File:** `scripts/unit_tests/planning/harness_planning_doc_issue_store.py`
  - **Expected:** separate-project config → zero code-repo doc diff
  - **R-IDs:** R11, R13

### 9. Separate-project docs bypass (small) — Amendment A2

- [ ] **9.1** Guard `docs_worktree.py` and `/sw-doc` for separate-project
  - **File:** `scripts/docs_worktree.py`, `core/commands/sw-doc.md`
  - **Expected:** provision skipped; handoff lists issue refs only
  - **R-IDs:** R14

- [ ] **9.2** Doctor detects local planning file writes under separate-project
  - **File:** `scripts/planning_store.py` (doctor subcommand)
  - **Expected:** exit 20 when tracked planning bodies appear in code repo
  - **R-IDs:** R15

- [ ] **9.3** Spec-seed bypass for separate-project (phase-provision materialize only)
  - **File:** `scripts/wave_spec_seed.py`, `scripts/planning_materialize.py`
  - **Expected:** `spec-seed` skips code-repo doc copy; phase-provision materialize unchanged; run-entry covered by Phase 0
  - **R-IDs:** R16

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 0 | none |
| 1 | 0 |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 3 |
| 5 | 4 |
| 6 | 4 |
| 7 | 5, 6 |
| 8 | 7 |
| 9 | 8 |
## Traceability

| R-ID | Task ref | Test scenario | ZOMBIES |
|------|----------|---------------|---------|
| R1 | 1.1, 2.1, 2.2 | GitHub create preserves native_links param | Z: no links; O: one sub-issue; M: multiple edge types; B: invalid target id; I: update adds link; E: reconcile_edges; S: adapter disabled |
| R2 | 1.1 | get returns native_links matching body native array | Z: empty native; O: single link; M: many links; B: broken target; I: read after update; E: round-trip; S: degraded mode |
| R3 | 1.2, 2.1 | probe returns capable false → notice once, deliver continues | Z: capable; O: one 403; M: repeated calls deduped notice; B: total API failure; I: partial links; E: body authoritative; S: skip links |
| R4 | 3.1, 3.2 | migrate create emits native for depends edge | Z: no edges; O: one depends; M: graph of edges; B: unresolved target; I: gap capture link; E: verify pass; S: file-store skip |
| R5 | 4.2 | phase provision invokes hierarchy apply | Z: file-store; O: one phase list; M: multi-phase; B: missing token; I: re-provision idempotent; E: hierarchyMap set; S: checkbox fallback |
| R6 | 5.1 | merge-ready-green applies phase done label | Z: no map; O: phase 1 done; M: all phases; B: missing sub-issue; I: re-merge noop; E: label present; S: file-store |
| R7 | 5.2 | checkbox toggle syncs to sub-issue body | Z: unchecked; O: one toggle; M: all refs; B: no hierarchyMap; I: ledger+issue align; E: acceptance gate; S: file only |
| R8 | 6.1 | living-docs projects INDEX status to issue | Z: file authority; O: complete status; M: gap resolve batch; B: cutover ambiguous; I: reconcile idempotent; E: issue label; S: dry-run |
| R9 | 4.2, 6.1 | file-store path has no new put calls | Z: default config; O: single command; M: full deliver stub; B: misconfigured backend; I: toggle issue-store; E: no file delta; S: regression |
| R10 | 0.4, 1.3, 5.3, 6.2 | fixture suites registered in suite-registry | Z: skip network; O: one fixture; M: full matrix; B: missing registry; I: CI shard; E: green harness; S: dry-run only |
| R11 | 8.1 | sw-doc creates issue not file | Z: file-store; O: brainstorm put; M: prd+tasks+freeze; B: missing token; I: re-run idempotent; E: issue index; S: same-repo git |
| R12 | 8.1 | skills cite unit ids | Z: n/a file-store; O: one handoff; M: full chain; B: path leak; I: doc review; E: grep clean; S: inherit |
| R13 | 8.2 | spec-rigor on virtual path | Z: missing unit; O: pass; M: full tier; B: dangling ref; I: amend; E: freeze; S: dry-run |
| R14 | 9.1 | docs_worktree skipped | Z: same-repo runs; O: separate-project skip; M: handoff refs; B: provision called; I: resume; E: no docs branch; S: file-store |
| R15 | 9.2 | doctor catches local write | Z: clean; O: one stray file; M: brainstorm+prd; B: gitignored only; I: after delete; E: pass; S: warn-only forbidden |
| R16 | 0.1, 0.2, 9.3 | run-entry + phase-provision materialize | Z: no deliver; O: materialize once; M: full run; B: spec-seed path; I: re-materialize; E: verify hash; S: file-store |
| R17 | 0.1 | `/sw-deliver run` with logical path only → plan succeeds | Z: file-store; O: logical path; M: full run; B: missing token; I: re-run idempotent; E: preflight pass; S: manual materialize |
| R18 | 0.2 | file-store repo unchanged | Z: default config; O: one command; M: deliver stub; B: issue-store toggle; I: materialized read; E: no file delta; S: regression |
| R19 | 0.1 | tampered issue body halts at verify-frozen-hash | Z: valid hash; O: one byte drift; M: re-fetch; B: missing record; I: after fix; E: tamper-detected; S: skip verify |
| R20 | 0.3 | `/sw-deliver next` returns runnable taskList | Z: file discover; O: issue-only unit; M: eligible queue; B: index-incomplete; I: force-refresh; E: taskList path; S: stub file |