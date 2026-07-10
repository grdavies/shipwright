# Planning deliver parity matrix (PRD 057 R6)

Published audit of the brainstorm → PRD → tasks → `/sw-deliver` chain for **planning-store
artifact emission parity**. Each row names a command surface, the artifact it may emit, and the
behavior under the three effective-backend shapes Shipwright supports.

**Guard predicate (D9):** pollution/currency guards (R1–R4) activate only when the effective backend
is `issue-store` **and** `planning.store.storeLocation.mode` is `separate-project`, via the shared
`issue_store_separate_project_effective(root)` helper (`scripts/planning_artifact_handle.py`). When
the predicate is false, output MUST remain equivalent to pre-057 file-store behavior (R23).

| Command / entrypoint | Artifact | file-store (default) | issue-store `same-repo` | issue-store `separate-project` | Requirement |
| --- | --- | --- | --- | --- | --- |
| `/sw-brainstorm`, `/sw-prd`, `/sw-freeze`, `/sw-tasks` (`docs_worktree provision`) | `docs/planning/<topic>/` worktree | provisions local docs worktree | provisions local docs worktree | **skip** — `separate-project-issue-store` handoff; authoring via `planning_store.put` handles | R3 |
| `planning_gap_capture` → `refresh_gap_backlog_projection` | `docs/prds/GAP-BACKLOG.md` | writes/updates projection row | writes/updates projection row | **skip** — write-through to store only; `--projection` retains legacy row | R1 |
| `wave_spec_seed.ensure_redacted_index` | `docs/prds/INDEX.md` | writes INDEX structural region | writes INDEX structural region | **skip** — store is authoritative | R2 |
| `wave_spec_seed` (spec-seed onto `<type>/<slug>`) | `docs/prds/INDEX.md` + feature branch | unchanged local INDEX write | unchanged local INDEX write | **skip** INDEX write; seeds implementation branch only | R2 |
| `planning_reconcile.reconcile_core` | `docs/prds/INDEX.md`, `INDEX-archive.md`, `SUPERSEDED.md`, `GAP-BACKLOG.md` projection | writes all tracked derived artifacts | writes all tracked derived artifacts | **skip** local derived writes; `storeProjection` to issue store | R3 |
| `gap_backlog.resolve_for_prd` | gap frontmatter / `GAP-BACKLOG.md` row | local status flip | local status flip | **store close + `sw:gap-resolved` label** (idempotent) | R4 |
| `reconcile_lib.set_index_status` | INDEX PRD row + absorbed gap resolution | local INDEX + local gap flip | local INDEX + local gap flip | INDEX/store path; forwards `resolution-partial` from R4 | R4 |
| `living-docs reconcile` / `append-terminal` | INDEX derived region, `COMPLETION-LOG.md` | local git commits on orchestrator branch | local git commits | deliver INDEX status commits on orchestrator branch; no tracked planning-body pollution | R3 |
| `planning_store.put` / `get` / `freeze` | unit bodies, labels, chunk manifest | file under `docs/prds/` / `docs/brainstorms/` | issue in code repo | issue in separate planning project | R8–R11 |
| `planning-doctor` (`doctor_separate_project_local_writes`) | — (detection only) | skipped | skipped | **fail** if tracked planning-body files remain in code repo | R6 |
| `/sw-deliver` `merge run-next` → `living-docs reconcile` | INDEX `derived` region status | local reconcile | local reconcile | backend-conditioned; see `skills/living-status/SKILL.md` | R3 |
| `/sw-deliver` terminal (`wave_terminal`) | gap auto-capture, PR titles | local gap file when file-store | store write-through when issue-store | store write-through; no local `GAP-BACKLOG` under separate-project | R19, R20 |

## CI fixtures

| Fixture | Proves | Path |
| --- | --- | --- |
| `planning-file-store-parity` | Per-command golden outputs equivalent when backend ≠ issue-store (R23) | `scripts/test/fixtures/planning-file-store-parity/harness.py` |
| `planning-deliver-parity` `wave_incremental` | Per-wave incremental guards + R24 sequencing (blockers earliest; R6 in Wave 5) | `scripts/test/fixtures/planning-deliver-parity/wave_incremental.py` |
| `planning-deliver-parity` `full_matrix` | End-to-end: no tracked local planning artifact under issue-store `separate-project` authoritative backend (R6) | `scripts/test/fixtures/planning-deliver-parity/full_matrix.py` |

## Operator surfaces

- Deliver orchestrator: `core/skills/deliver/SKILL.md` (living-doc currency + terminal gate).
- Configuration: `docs/guides/configuration.md` (issue-store axes and `storeLocation.mode`).

## Operator projection matrix (PRD 061 R10–R15)

Portable semantic graph projections for product-owner browse surfaces. Pattern-only
rows document integration contracts for adapters not yet shipped.

| Backend | PRD / brainstorm / gap / tasks | Phases | Progress | Edges | Release grouping | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `github-issues` | Issues + Projects v2 fields | Parent + Project fields; native sub-issues opt-in | Parent labels/checkboxes + Projects | `sw-edges` / native links / Project relations | Milestone and/or Project fields | **Live** — R11/R11a |
| `jira` | Issue types + links + labels | Sub-task when verbs ship; else checkbox via facade | Facade progress + labels/status | Store graph → issue links | fixVersion/sprint or labels | Target matrix row (R12) |
| `gitlab-issues` | Issues + labels (spec) | Sub-issue (spec) | Labels/status | Store graph → links (spec) | Iteration / labels | Target fail-closed (R13) |
| `in-repo-public` | File bodies under `docs/planning/` | `### N.` checkboxes | Checkbox + derived INDEX | Frontmatter + `sw-edges` | `sw:release:*` labels | File-native projection |
| `none` | Same as `in-repo-public` fallback | Checkbox bodies | Checkbox + derived INDEX | Frontmatter + `sw-edges` | `sw:release:*` labels | issuesProvider none |
| `linear` (pattern) | Project / Document / Issue | Milestones + sub-issues | Native status | IssueRelation | Cycle / Milestone | Prerequisite PRD 061 (R14) |
| `notion` (pattern) | Database per artifact type | Relation children | Status property | dual_property relations | Date/select properties | Prerequisite PRD 061 (R15) |

Conformance fixtures: `scripts/unit_tests/planning/harness_planning_061_github_projects.py`.

