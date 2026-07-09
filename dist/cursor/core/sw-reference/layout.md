# Shipwright artifact layout

Single-source path contract for the documentation pipeline and downstream implementation workstream.
All `sw-` doc commands resolve paths from this document — do not re-decide locations in commands.

## Directory tree

```text
docs/
└── brainstorms/
    ├── YYYY-MM-DD-<topic>-requirements.md
    └── YYYY-MM-DD-<topic>-requirements.amendments/
        └── A<k>-<short>.md

docs/prds/
├── INDEX.md
├── COMPLETION-LOG.md
├── GAP-BACKLOG.md
└── <n>-<slug>/
    ├── <n>-prd-<slug>.md
    ├── tasks-<n>-<slug>.md
    └── amendments/
        └── A<k>-<short>.md

docs/decisions/
├── INDEX.md
├── SUPERSEDED.log          # append-only manifest (written on record-level supersede)
├── .memory-freeze-audit.log  # offline freeze audit breadcrumb (local; not authoritative)
├── <n>-<slug>.md
└── <n>-<slug>.amendments/
    └── A<k>-<short>.md

.cursor/
├── sw-deliver-plan.json    # deliver plan artifact (living, written by /sw-deliver plan)
├── sw-deliver-state.<slug>.json   # per-run scoped state — single canonical path at repo root (PRD 013 R6/R28)
├── sw-deliver-<slug>.lock         # per-run scoped orchestrator lock
├── sw-living-docs.lock            # repo-wide living-doc write serialization (PRD 013 R12)
├── sw-deliver-state.json          # legacy repo-wide state (migration breadcrumb after adopt)
├── sw-deliver.lock                # legacy repo-wide lock (superseded by scoped locks)
├── sw-deliver-runs/
│   ├── index.json                 # concurrent-run index (live scoped runs)
│   └── <phase-slug>/              # per-phase status (living)
│       ├── status.json
│       ├── ship-steps.json
│       ├── phase-step-plan.json
│       ├── execute-step-plan.json
│       ├── integrate-journal.json
│       ├── execute-supervised-confirmed.json
│       ├── gap-check.status.json
│       └── dispatch-decisions.json
```

### Deliver run-state ledger (PRD 059 R9–R11)

`taskLedger` on `.cursor/sw-deliver-state.<slug>.json` records per-subtask `done` state used by
`planning_store.py materialize --resync`. Pre-resync backups land beside the materialized destination as
`*.pre-resync.bak`. Planning query cache state: `.cursor/hooks/state/planning-query-cache.json`.


## Planning-unit model (PRD 031)

Canonical frontmatter schema: `core/sw-reference/planning-unit.schema.json` (validated by
`scripts/planning-unit-validate.py`). Status enums are type-conditioned via `scripts/planning_status_enum.py`
(stub values only — PRD 033 owns transition semantics).

### Unit folder layout

Every planning unit is a **folder** under the typed-unit tree (`docs/planning/` at cutover; see R5). Each
folder contains:

- A **canonical body file** with planning-unit frontmatter (`id`, `type`, `status`, `title`, `visibility`, edge
  arrays, optional `priority`/`tags`).
- **Optional ancillary tracked files** co-located in the same folder (e.g. a PRD unit's frozen task lists and
  `amendments/` subtree).

```text
docs/planning/
├── INDEX.md                         # single generated unified INDEX (R5)
└── <type>/<id>-<slug>/              # one folder per unit
    ├── <id>-<type>-<slug>.md        # canonical body (frontmatter + content)
    ├── tasks-<id>-<slug>.md         # optional (PRD units)
    └── amendments/                  # optional (PRD / decision units)
        └── A<k>-<short>.md
```

### Stable unit ids (R2)

- Unit `id` values are **stable**, **monotonic**, and **never reused** after assignment.
- All cross-references (`depends`, `blocks`, `supersedes`, `extends`, `absorbs`, INDEX rows) use the **unit id**
  — never a table row index, filesystem path alone, or positional reference.
- Gap units use the same id discipline (e.g. `gap-045-sample`) — they are not anonymous backlog rows.

### Unified INDEX schema (R5/R9/R24)

`docs/planning/INDEX.md` is the **single generated unified INDEX** produced from unit frontmatter by
`scripts/planning_index_gen.py`. It is never hand-maintained.

The INDEX carries three disjoint regions (HTML comment markers):

| Region | Owner | Purpose |
|--------|-------|---------|
| `structural` | INDEX generator | Rows from unit frontmatter (`id`, `type`, `title`, `status`, `visibility`, edges) |
| `derived` | reconciler (PRD 033) | Derived lifecycle status per unit — empty schema slot at cutover |
| `inFlight` | deliver writer (PRD 032) | Committed in-flight tuple per active unit (`runId`, `branch` or `branchToken`, `epoch`) — schema: `core/sw-reference/inflight-tuple.schema.json` |

**inFlight tuple (PRD 032):** markdown table rows in the INDEX `inFlight` region; no lifecycle status in the tuple
(033 derives `in-progress`). Cleartext `branch` is committed for non-private units until PRD 034 lands; the schema
reserves `branchToken` (hashed suffix) for private-unit redaction. The region is included in the PRD 034
emission-point registry handoff.

**Read-merge-write:** every writer parses the existing INDEX and preserves non-owned regions **byte-for-byte**.
Full-file regen that drops a sibling region is prohibited; `scripts/index-region-guard.py` enforces this on
pre-commit and in CI.

### Issue-store region disposition (PRD 043 R34)

### PRD 046 phase-1 region disposition (committed inFlight)

When `planning.store.backend` is `issue-store` and the cutover gate permits issue discovery:

| Region | Phase-1 authority | Writer | Notes |
| --- | --- | --- | --- |
| `structural` | file or issue (gated) | generator / issue-derived | `planning_discover.py` single source |
| `derived` | file (gated) | reconciler | issue-derived read-only when cutover open |
| `inFlight` | deliver run-state | deliver | sole writer; committed INDEX projection read-only |

Deliver writes the `inFlight` tuple to durable run-state and projects it read-only into the committed
INDEX `inFlight` region (`planning_region_disposition.py project`). The `inFlight` region is **never
mechanically edited** by reconciler or docs-merge — deliver writer only.

Dual-mode INDEX: file-store users remain inert; issue-store derives read-only views via `discover_units`
backend plug (`file` | `issue`). Generation token serializes concurrent INDEX regeneration (R88). The `inFlight` region is never mechanically edited by reconciler or docs-merge.


When `planning.store.backend` is `issue-store`, authoritative location per INDEX region is governed by
`core/providers/planning-store/issue-store.md`. Phase-1 interim (adoption gated):

| Region | Phase-1 authoritative | Post-adoption target |
| --- | --- | --- |
| `structural` | file-store (in-repo-public) | issue-derived rows |
| `derived` | file-store (reconciler) | issue-derived lifecycle |
| `inFlight` | deliver writer file tuple (PRD 032) | projected to issue store |

Until a region is issue-derived, the file-store remains authoritative — issue-store config alone does not
migrate regions.

**Zero stub files (R7):** when issue-store is the effective backend, doc commands must not commit
planning artifact bodies to the code repo; artifacts live as issues and materialize to git-ignored paths
at deliver time (Phase 3): `planning_store.py freeze` records `sw-freeze-record` hash; `planning_materialize.py provision` verifies hash before materializing frozen task lists to `.cursor/planning-materialized/`.

**Status precedence:** lifecycle consumers read `derived.status` when populated and fall back to structural
`status`; gap units (`type: gap`) always use structural status only.

### Private INDEX rows (R33 — PRD 034 handoff)

INDEX structural rows for `visibility: private` units carry **provisional** title metadata (`[provisional]` prefix)
until PRD 034 defines redaction/omission of private rows. Unit bodies for brainstorm/decision private units
remain gitignored under the interim `legacy-pre-034` profile (R18); only public metadata appears in INDEX.

### Migration cutover checklist (R27/R28)

Atomic release train (031 + 032 + 033) cutover gates:

1. Acquire migration lock; halt deliver/feedback append.
2. Run `planning_migrate.py write` then mandatory `--verify`.
3. Run `scripts/relief-acceptance-check.py` (derived INDEX status vs deliver state).
4. Flip `planningDir` to `docs/planning`; regenerate planning INDEX + legacy projections.
5. Run `scripts/planning_legacy_projection.py` to emit legacy `GAP-BACKLOG.md` + `INDEX.md` shims.
6. Run `scripts/copy-to-core.py` then `python3 -m sw generate --all` + emitter freshness fixtures (R25).

**Kill-criteria / falsification (R28):** if PRD 032/033 slip past the release threshold or the reconciler
misses the accuracy floor on the relief fixture corpus, fall back to shim + legacy layout; R10 supersession
edges recorded in `.cursor/planning-migration-supersession-map.json` are **reversible** via `--rollback`.

### Gaps as first-class units (R3)

Gap artifacts are planning units with `type: gap` (folder + frontmatter) on file-backend, or native `sw:gap`
provider issues under **issue-store** (PRD 045 R21). They render as rows in the **single generated unified INDEX** — not a separate gap-only index. Legacy
`docs/prds/GAP-BACKLOG.md` is a **write-through projection** from gap issues when issue-store is active (PRD
045 R72) or a compatibility projection until consumers migrate (R27).

### Issue-store separate-project write guards (PRD 057 R1–R3)

Under issue-store `separate-project` (`planning.store.storeLocation.mode`), the code repo is no longer the
authoritative surface for derived/generated planning artifacts — the shared predicate
`issue_store_separate_project(root)` (`scripts/planning_migrate_issue_store.py`, delegating to
`planning_artifact_handle.issue_store_separate_project_effective`) gates every write below to skip the tracked
local file and project to the authoritative store (or a gitignored cache) instead. `same-repo` deployments are
unaffected — local writes are retained exactly as before this guard existed.

| Artifact | `same-repo` / non-issue-store | issue-store `separate-project` |
|----------|-------------------------------|----------------------------------|
| `docs/prds/GAP-BACKLOG.md` | local write-through projection (R1) | write-through to the issue store only; local write skipped (sunset stub once no open gaps remain) |
| `docs/prds/INDEX.md` (spec-seed) | `wave_spec_seed.ensure_redacted_index` writes it (R2) | skipped — deliver run-entry materialize + the issue store supply task content |
| `docs/prds/INDEX.md` / `INDEX-archive.md` / `SUPERSEDED.md` / legacy projection (reconcile) | `planning_reconcile.reconcile_core` writes all four (R3) | none written; derived map projects to the store via `planning_index_issue.project_derived_map` (PRD 056 R8), additionally cached at the gitignored `.cursor/hooks/state/planning-index-derived.json` when the cutover `derived` region authority is issue |

The two-track mechanical allowlist (see `core/rules/sw-git-conventions.mdc` **Two-track doc edits**) is
clarified accordingly: under issue-store authority the mechanical write projects to the store rather than a
tracked local file.

### Scheduler park state (PRD 057 R16, R28)

The scheduler frontier skips units that cannot run and can **park** units out of scheduling:

- **`sw:parked` label** — under issue-store, a unit carrying this provider-native label is dropped from the
  frontier so legacy migrated units no longer stall `next` (R16, D4).
- **`.cursor/planning-parked.json`** — a local, backend-neutral, git-ignored park registry
  (`unit-id → {reason, actor, at}`) written only on an explicit `planning-graph.py park`/`unpark`. When
  empty, the file-store scheduling path is unchanged (R23). Parking is authorized only for actors in
  `planning.scheduler.parkAllowlist` and requires a reason (fail-closed).
- An empty post-filter frontier yields an explicit `scheduler-exhausted` scheduler halt and an
  `over-parked-frontier` `planning-doctor.py` drift finding — never a silent empty result.

## Naming conventions

| Artifact | Path pattern | Written by | Frozen |
|----------|--------------|------------|--------|
| Brainstorm requirements | `docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md` | `/sw-brainstorm` | `/sw-freeze` |
| Brainstorm amendment | `docs/brainstorms/...-requirements.amendments/A<k>-<short>.md` | manual / future | `/sw-freeze` |
| PRD | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` | `/sw-prd` | `/sw-freeze` |
| Task list | `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` | `/sw-tasks` | `/sw-freeze` |
| PRD amendment | `docs/prds/<n>-<slug>/amendments/A<k>-<short>.md` | `/sw-amend` | `/sw-freeze` |
| Decision record | `docs/decisions/<n>-<slug>.md` | `/sw-prd --type decision` | `/sw-freeze` |
| Decision amendment | `docs/decisions/<n>-<slug>.amendments/A<k>-<short>.md` | `/sw-amend` | `/sw-freeze` |
| Living index | `docs/prds/INDEX.md` | `/sw-freeze`, `/sw-tasks` | never |
| Decision index | `docs/decisions/INDEX.md` | `/sw-freeze` | never |
| Completion log | `docs/prds/COMPLETION-LOG.md` | implementation workstream | never |
| Gap backlog | `docs/prds/GAP-BACKLOG.md` | issue-derived write-through projection (issue-store) or legacy reconciler | never |

### PRD numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `docs/prds/` for the highest existing `<n>` and incrementing.
- Collision policy: same feature re-run → new `<n>` + distinct slug; never overwrite without explicit confirmation.

### Decision record numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `docs/decisions/` for the highest existing `<n>` and incrementing — **separate counter from `docs/prds/`**.
- Collision policy: same topic re-run → new `<n>` + distinct slug; never overwrite without explicit confirmation.

### Slug (`<slug>`)

- Lowercase kebab-case derived from the feature topic (e.g. `doc-pipeline`, `user-auth`).
- Must be filesystem-safe; no spaces.

### Amendment naming (`A<k>-<short>`)

- `<k>` is a monotonic integer within the parent (`A1`, `A2`, …).
- `<short>` is a brief kebab-case descriptor (e.g. `A1-fail-closed-enforcement-point`).

## Frontmatter contracts

### Brainstorm / PRD / task list (pre-freeze)

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>
brainstorm: docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md   # Full-tier PRD only (R52)
prd: docs/prds/<n>-<slug>/<n>-prd-<slug>.md                      # brainstorm forward ref (R53); list when multiple
---
```

- **`brainstorm:`** (canonical) — repo-relative path to the source brainstorm. Required on every **Full-tier** PRD
  at draft time (`/sw-prd` writes it; `/sw-freeze` + `scripts/doc-link-check.py` verify it). Legacy alias:
  `source_brainstorm:` (accepted by the gate only; new PRDs MUST use `brainstorm:`).
- **`prd:`** — repo-relative path (or YAML list) from a **writable** brainstorm back to derived PRD(s). Written
  when the PRD is created or frozen (`/sw-prd` / `/sw-freeze`); skipped when the brainstorm is already frozen
  (PRD `brainstorm:` remains authoritative).

### Frozen artifact

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>          # PRD/task only
frozen: true
frozen_at: YYYY-MM-DD
---
```

### Amendment

```yaml
---
date: YYYY-MM-DD
amends: <parent-path>
frozen: true
frozen_at: YYYY-MM-DD
supersedes: [R<n>, ...]       # optional
retracts: [R<n>, ...]         # optional
---
```

Amendment body is **delta-only** — parent file is never edited.

## Command read/write map

| Command | Reads | Writes |
|---------|-------|--------|
| `/sw-triage` | user input, file list | tier decision (no files) |
| `/sw-brainstorm` | user dialogue | `docs/brainstorms/...-requirements.md` |
| `/sw-prd` | brainstorm (Full) or triaged request (Standard) | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` |
| `/sw-prd --type decision` | optional brainstorm; up-front cross-cutting decision | `docs/decisions/<n>-<slug>.md` |
| `/sw-doc-review` | PRD or decision-record draft | in-place edits (pre-freeze only) |
| `/sw-freeze` | target artifact | `frozen: true` frontmatter; `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` entry |
| `/sw-amend` | frozen parent PRD | `docs/prds/<n>-<slug>/amendments/A<k>-<short>.md` |
| `/sw-tasks` | frozen PRD + union | `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md`, `INDEX.md` |
| `/sw-doc` | tier from triage | delegates to above |

### Deliver state canonicalization (R28)

The live deliver run-state file exists **once** at the repo-root scoped path
(`.cursor/sw-deliver-state.<slug>.json`). Orchestrator and phase worktrees read and write through
`wave_state.scoped_paths()` / `resolve_state_path()` at the git toplevel — never a second authoritative
copy under `.sw-worktrees/**/.cursor/`. `wave_compound.py record-premerge` and
`cleanup_lib.resolve_deliver_state()` use the same resolver.

## Operator worktree contract (PRD 049 R1)

Single authority for which checkout owns implementation versus conductor runtime during `/sw-deliver`.

| Checkout | Path / branch | Role |
| --- | --- | --- |
| Primary | Repo root (usually `defaultBaseBranch` after orchestrator provision) | Operator shell; **must not** accumulate tracked implementation commits during a deliver run |
| Orchestrator | `.sw-worktrees/<slug>-orchestrator` → `<type>/<slug>` | Conductor loop cwd; merge queue, living-doc reconcile, terminal retro/ship |
| Phase | `.sw-worktrees/<slug>-phase-*` → `<type>/<slug>-phase-<phase-slug>` | `/sw-ship` / `/sw-execute` implementation; isolated phase branch |
| Conductor runtime | Repo-root `.cursor/` (gitignored) | Canonical deliver state, locks, run logs — **not** feature implementation |

```text
repo-root/                          primary checkout (defaultBaseBranch)
├── .cursor/                        conductor runtime (canonical; gitignored)
│   ├── sw-deliver-state.<slug>.json
│   ├── sw-deliver-runs/<phase>/status.json   ← mirrored from phase worktree
│   └── …
└── .sw-worktrees/
    ├── <slug>-orchestrator/        conductor-loop cwd (<type>/<slug>)
    └── <slug>-phase-<phase>/       ship/execute cwd (phase branch)
```

**Invariants:**

- Repo-root `.cursor/` updates during deliver are **expected** — agents must not treat them as
  implementation artifacts to commit.
- `status.json` copy direction is **phase worktree → repo root** (mirror for collection/merge only).
  Never a general root→worktree state sync.
- Ship and execute run in the **phase worktree**; the conductor loop runs from the **orchestrator
  worktree** (mandatory provisioning — not repo root as an alternate cwd).

## Living vs frozen layers

- **Frozen:** brainstorms, PRDs, task lists, amendments — immutable after `/sw-freeze`; change only via new amendments.
- **Living:** `INDEX.md`, `COMPLETION-LOG.md` — updated as work progresses; never frozen.
- **Gap backlog:** `GAP-BACKLOG.md` — under issue-store, issue-derived write-through projection only (PRD 045 R72); file-backend legacy projection until cutover; never hand-appendable; not frozen.
- **Generated install trees:** `dist/cursor/` and `dist/claude-code/` — committed outputs of `python3 -m sw generate`; edit `core/` then regenerate (freshness gate in `scripts/test/run_emitter_fixtures.py`). Not hand-edited except via emitter changes.


## Build-chain source of truth (PRD 038)

Machine-readable map: `core/sw-reference/build-chain-sot.json` (lint: `scripts/build-chain-sot-lint.py`).

| Tree | Role | Edit where |
| --- | --- | --- |
| `scripts/` | Harness SoT — runtime entrypoints (`wave.py`, gates, tests) | Repo root only |
| `core/scripts/` | Mirrored harness (excludes `test/`, `check-frozen.py`) | Via `copy-to-core` from `scripts/` |
| `commands/`, `skills/`, `rules/`, `agents/`, `providers/` | Emittable content SoT | Repo root → `copy-to-core` → `core/` |
| `.sw/` | Operator-edited sw-reference inputs (subset) | Repo root `.sw/` |
| `core/sw-reference/` | `.sw/` sync + `coreAuthoredAllowlist` artifacts | `.sw/` or allowlisted core paths |
| `dist/cursor/`, `dist/claude-code/` | Emitter output only | `python3 -m sw generate --all` after `core/` changes |
| `scripts/test/fixtures/parity/cursor-golden.manifest` | Committed golden parity | `scripts/snapshot-tree.py` after dist changes |

**Not in repo scope:** `~/.cursor/plugins/local/shipwright/` (plugin install path). `copy-to-core` reads
repo trees only — never the install path.

**Unified sync:** after editing `scripts/` or emittable roots, run:

```bash
python3 scripts/build-chain-sync.py
```

Runs `python3 -m sw generate --all` → golden re-snapshot when `dist/` changes → `copy-to-core.py`.
`copy-to-core --force` is **fixture/CI-only** (set `SW_BUILD_CHAIN_FORCE=1` or run under CI); operator
workflows must remediate via `.sw/` instead. Last-synced provenance lives at `.sw/build-chain-last-synced.json`.

## Capability manifest + selector (PRD 021)

Authoring lives under `core/`; the emitter propagates manifest artifacts into both dist trees.

| Artifact | Role |
| --- | --- |
| `core/sw-reference/capability-manifest.schema.json` | JSON Schema for per-capability `capability` frontmatter |
| `core/sw-reference/capability-manifest.md` | Frontmatter, precedence, trust-boundary contract |
| `core/sw-reference/capability-index.json` | Emitter-generated aggregate (committed; freshness-gated) |
| `core/sw-reference/signal-context.schema.json` | Versioned selector inputs |
| `scripts/capability-select.py` | Deterministic selector primitive |
| `scripts/capability-manifest-lint.py` | Author-time precedence/conflict/anti-spoof lint |
| `scripts/doc-review-select.py` / `scripts/code-review-select.py` | Selection-family wrappers |

**Freshness:** `scripts/test/run_emitter_fixtures.py` fails when `capability-index.json` or dist trees drift
from current frontmatter. Regenerate after manifest edits: `python3 -m sw generate --all`.

**Pre-selection:** `wave_preflight` / selector entrypoints fail closed when the runtime index does not
reproduce from current sources.

## Config keys

`workflow.config.json`:

- `planningDir`: `"docs/planning"` — canonical planning-unit tree (post-cutover; pre-cutover may remain
  `docs/prds` until migration `--verify` passes).
- `prdsDir`: `"docs/prds"` — legacy PRD directory alias (defaults to `docs/prds` until `planningDir` cutover).
- `tasksDir`: `"docs/prds"` — frozen task-list alias (defaults to `prdsDir` until cutover).
- `decisionsDir`: `"docs/decisions"` — decision-record root (flat files + sibling `.amendments/` dirs).
- `delegation.mode`: `bind-only` | `heuristic` | `default` — selects delegate-by-default gate behavior
  (PRD 017; default `bind-only` until Phase-2 live acceptance, else `default`).
- `communication.routing` — `commands`, `skills`, and `agents` maps for caveman intensity; seeded from
  `core/sw-reference/communication-routing.defaults.json` via `/sw-setup`.
- `models.routing` — command/skill/agent model tier maps; resolve at dispatch via `resolve-model-tier.py`.

### Dispatch preflight artifacts (PRD 017 + A2 R38/R39)

Per-delegated-Task binding is recorded immediately before spawn:

```bash
python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <agent-id> --command <sw-*> [--skill <name>]
python3 scripts/dispatch-check.py --agent <id> --command <sw-*> --parent-model <concrete-id> [--dispatch-id <id>]
```

**Keyed store (R38):** one JSON record per dispatch under
`.cursor/hooks/state/task-dispatch-preflight/<dispatch-id>.json` (legacy single-file
`task-dispatch-preflight.json` read fallback when exactly one unconsumed record exists). Each record carries
the full binding payload, `expiresAt` (TTL), and `consumedAt` after the hook consumes **only** the matching
`dispatchId`. Parallel persona panels require **N unique ids** — consuming record `A` leaves record `B` valid.

Model tier uses R39b precedence via `resolve-model-tier.py` / `dispatch-check.py` (explicit agent routing →
`--command` → `--agent`). The `preToolUse` hook (`core/hooks/before_task_dispatch.py`) denies bound `Task`
spawns lacking a fresh, matching record. Operator-facing deliver resume: `/sw-deliver run <frozen-task-list-path>`
— not raw `bash deliver-loop`.

### Pre-work memory search (PRD 019)

Work-performing commands (`/sw-execute`, `/sw-debug`, `/sw-prd`, `/sw-brainstorm`, `/sw-amend`,
`/sw-review`, `/sw-stabilize`) MUST run a scoped `memory-preflight` search before the first substantive
mutation. Record the breadcrumb mechanically:

```bash
python3 scripts/wave.py memory prework record --surface sw-execute --scope "<paths>" [--hit-count N]
```

Artifacts:

| Path | Role |
| --- | --- |
| `.cursor/hooks/state/memory-prework-search.json` | Redacted per-surface search record (or `memory:offline` / `memory:none`) |
| `.cursor/sw-deliver-runs/run.<slug>.log` | Per-deliver-run append-only audit breadcrumb (PRD 050 R4) |
| `.cursor/doc-review-runs/<dispatch-id>.json` | Per-dispatch token-estimate telemetry for `/sw-doc-review` persona panels (PRD 058 R28) |

The `preToolUse` hook (`core/hooks/before_task_dispatch.py`) denies the first file-mutating tool call
when no fresh record exists. Delegated work sub-agents inherit the obligation per
`rules/sw-subagent-dispatch.mdc` (perform-or-be-handed-redacted-result). Provider outage degrades open
via probe-gated `memory:offline` — never blocks work.

## Kernel classification, guidelines, and two-tier plan persistence (PRD 022)

| Artifact | Path / field | Writer | Role |
| --- | --- | --- | --- |
| Kernel classification | `core/sw-reference/kernel-classification.{json,md}` | docs/emitter | read-only at runtime |
| Guidelines | `core/sw-reference/guidelines.{schema.json,md,json}` | docs/emitter | read-only at runtime |
| Phase step plan | `.cursor/sw-deliver-runs/<phase-slug>/phase-step-plan.json` | phase executor (`ship_phase_steps.py` / `plan_persist.py`) | per-phase run dir |
| Wave batching plan | `waveBatchingPlan` on `.cursor/sw-deliver-state.<slug>.json` | conductor only (`plan_persist.py`; `SW_CALLER_ROLE=conductor`) | shared run-state |
| Two-tier lifecycle | `twoTierLifecycle` on shared run-state | conductor | `wave-validated` → `phase-plan-pending` → `phase-plan-validated` |
| Plan validation | `python3 scripts/wave.py plan validate` → `scripts/wave_plan_validate.py` | mechanical gate | proposals only |

**Wave authority (single source of truth):** the conductor deliver loop reads `waveBatchingPlan` from shared
run-state when present (`wave_deliver_loop.effective_wave_plan`); otherwise it falls back to the frozen
`.cursor/sw-deliver-plan.json` waves. Phase execution reads `phase-step-plan.json` in the phase run dir as the
sole step authority (`ship_phase_steps.authoritative_chain`); canonical `SHIP_CHAIN` is the fallback only.

**Single-writer guard:** `save_deliver_state` and `plan_persist.guarded-state-save` refuse writes when
`SW_CALLER_ROLE=phase` (exit 20). Phase-scoped artifacts (`ship-steps.json`, `phase-step-plan.json`,
`status.json`) are written only under the phase slug's run dir.

**Invariants home:** `core/sw-reference/kernel-classification.md` — cross-link; do not duplicate the kernel
enumeration elsewhere.
### Three-tier plan lifecycle (PRD 053 — wave / phase / execute)

| Tier | Artifact | Proposer | Validate | Resume owner |
| --- | --- | --- | --- | --- |
| Wave | `waveBatchingPlan` on shared run-state | Conductor at wave entry | `wave.py plan validate --tier wave` | Conductor |
| Phase | `phase-step-plan.json` | Phase executor at phase entry | `wave.py plan validate --tier phase` | Phase executor (`ship_phase_steps.py`) |
| Execute | `execute-step-plan.json` | Phase executor before fan-out | `wave.py plan validate --tier execute` | Phase executor (`execute_plan.py`) |

Phase entry lifecycle (ordered): `phase-step-plan` validate → `execute-step-plan` validate (when
`execute.enabled`) → execute fan-out → per-ref integrate → resume phase chain at `sw-verify`.

| Artifact | Path | Writer | Role |
| --- | --- | --- | --- |
| Execute step plan | `.cursor/sw-deliver-runs/<phase-slug>/execute-step-plan.json` | `execute_plan.py` / `wave_plan_validate.py` | Closed-world DAG of sub-task refs, batches, edges |
| Integrate journal | `.cursor/sw-deliver-runs/<phase-slug>/integrate-journal.json` | `execute_integrate.py` | Append-only per-ref merge audit (separate from conductor `mergeQueue` / `mergeJournal`) |
| Per-ref execute status | `.cursor/sw-execute-runs/<sanitized-ref>/status.json` | `execute_task_status.py` | TDD + refactor rollup per sub-task ref |
| Supervised plan confirm | `.cursor/sw-deliver-runs/<phase-slug>/execute-supervised-confirmed.json` | `execute_ship.py` | One halt marker per phase under `deliver.autonomy.mode: supervised` |

**Sub-branch naming:** `feat/<slug>-phase-<phase-slug>--task-<ref>` (sanitized ref; `countsTowardCeiling: false`).
Provisioned by `execute_plan.py provision-sub-branch`; torn down after successful integrate.

**Integrate vs merge-queue boundary:** `execute_integrate.py` (phase-executor scoped, single-flight per phase
worktree) merges sub-branch tips into the phase branch. Conductor `wave_merge.py` phase→target merge is
unchanged — execute integrate never enqueues on the conductor merge queue.

**`benefitMetric.decomposed.stepPlanAdaptivity` execute fields** (numeric only):

| Field | Type | Notes |
| --- | --- | --- |
| `refsParallelized` | int | Batches with width > 1 |
| `runtimeExpansions` | int | Synthetic child refs from runtime expansion |
| `skippedRefs` | int | Terminal `skipped` refs |
| `parallelBatchWidth` | int | Max batch width in execute plan |
| `refCount` | int | Total refs in execute plan |

## Deliver pilot run records (PRD 023)

| Artifact | Path / field | Writer | Role |
| --- | --- | --- | --- |
| Per-phase dispatch decisions | `.cursor/sw-deliver-runs/<phase-slug>/dispatch-decisions.json` | phase executor | intra-phase fan-out audit (R17) |
| Intra-phase fan-out snapshot | `intraPhaseFanOut` on phase status / `phases.<id>` | phase executor | latest partition + worker count + cap state (R15–R17) |
| Per-phase benefit metric | `benefitMetric` on phase status / shared run-state `phases.<id>` | phase executor at terminal | R31 capture (numeric/enumerated only) |
| Run-level benefit rollup | `benefitMetric` on `.cursor/sw-deliver-state.<slug>.json` | conductor at terminal | paired-run aggregation input |
| Benefit report | `python3 scripts/wave.py plan benefit-report --pairs <path>` → `scripts/wave_plan_benefit.py` | operator / soak protocol | R31 decision rule (fail-closed to `canonical`) |

### `benefitMetric` object (R31 — numeric/enumerated only)

Recorded on per-phase status and optionally rolled up on shared deliver run-state. No transcripts, file
contents, secrets, or free-text blobs.

```json
{
  "planPolicy": "canonical",
  "kernelVerdict": {
    "terminalPhaseStatuses": ["green-merged"],
    "gateOutcome": "green",
    "mergeReadyCount": 1
  },
  "canonicalStepSet": ["sw-tmp-init", "sw-execute", "..."],
  "executedStepSet": ["sw-tmp-init", "sw-execute", "..."],
  "stepsSkippedWithoutRework": 0,
  "stabilizeReentries": [{"step": "sw-verify", "attributed": true}],
  "escapedDefectSignal": "none",
  "phaseWallClockMs": 120000,
  "decomposed": {
    "stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0},
    "waveSchedule": {"wallClockMs": 0},
    "intraPhase": {"wallClockMs": 0}
  }
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `planPolicy` | `canonical` \| `proposed` | policy under measurement |
| `kernelVerdict` | object | equivalence tuple for stratum grouping |
| `canonicalStepSet` | string[] | baseline chain for the phase |
| `executedStepSet` | string[] | steps actually advanced |
| `stepsSkippedWithoutRework` | int | canonical − executed minus attributed stabilize re-entries |
| `stabilizeReentries` | `{step, attributed: bool}[]` | attributed re-entry zeroes credit for that skipped step |
| `escapedDefectSignal` | enum | `none`, `terminal_pr_ci_red`, `post_merge_stabilize`, `post_merge_revert` |
| `phaseWallClockMs` | int | phase wall-clock; secondary guard vs paired canonical |
| `decomposed` | object | category breakdown (`stepPlanAdaptivity`, `waveSchedule`, `intraPhase`) |

**Decision rule:** `wave.py plan benefit-report` compares paired `canonical` vs `proposed` metrics at
identical `kernelVerdict`. Primary signal: `stepsSkippedWithoutRework` net-of-rework must be strictly
positive per pair; wall-clock must not regress beyond ε at equal verdict; minimum N pairs per stratum.
Insufficient N or non-positive benefit **fails closed** to `canonical`.
### `dispatch-decisions.json` (R17)

Append-only per-phase audit log written by `scripts/intra_phase_dispatch.py`.

```json
{
  "version": 1,
  "decisions": [{
    "timestamp": "2026-06-27T08:00:00Z",
    "signals": {"fileCount": 4, "derivedTags": ["docs"], "conductorMode": "inline", "phaseType": "ship"},
    "declaredPartition": [{"files": ["docs/guides/configuration.md"], "workerId": "w1"}],
    "chosenParallelism": {"workers": 1, "serialized": false},
    "degradeReason": null
  }]
}
```

### `intraPhaseFanOut` snapshot (R15–R17)

Latest validated fan-out state on phase status (not a substitute for the append-only decision log):

```json
{
  "activeWorkers": 1,
  "globalCap": 4,
  "parallelBudget": 2,
  "partitionSummary": ["docs/guides/configuration.md"]
}
```

### Phase terminal `status.json` (PRD 036 R13–R17)

Written only by `scripts/ship-phase-status.py` (or driver `canonical-reemit`). Key fields:

| Field | Role |
| --- | --- |
| `verdict` | `merge-ready-green` or `blocked` |
| `head` | Full 40-char phase branch tip SHA |
| `gate` | Diagnostic gate snapshot (not authorization) |
| `provenanceMarker` | SHA256 over canonical fields (excludes `writtenAt`) |
| `shipSteps` | Optional embedded step snapshot |
| `writtenAt` | UTC emission timestamp |

Per-head ship leases live under `.cursor/sw-deliver-locks/<hash>-<phase>.lock` (PRD 036 R2).

Recovery command: `/sw-ship --phase-mode --from <terminal-step>`; auto re-emit counter on deliver state:
`statusReemitAttempts`.

## Episodic orchestrator scratch (PRD 024 TR6 / R37)

Debug and feedback orchestrators use **ephemeral, per-invocation** namespaced scratch — not deliver-style
durable run state. Artifacts are abandoned on terminal halt; there is no crash-resume checkpoint and no
writes to deliver-scoped paths.

| Path | Role |
| --- | --- |
| `.cursor/sw-debug-runs/<runId>/run-meta.json` | Episodic debug run metadata (`crashResume: false`) |
| `.cursor/sw-debug-runs/<runId>/signal_context.json` | Entry snapshot before `plan validate` (TR3) |
| `.cursor/sw-debug-runs/<runId>/episodic-run-summary.json` | R21 surfacing (chosen plan, capability set, rejections) |
| `.cursor/sw-feedback-runs/<runId>/` | Same layout for `/sw-feedback` |
| `.cursor/sw-doc-runs/<runId>/signal_context.json` | Doc entry snapshot (durable handoff remains docs-worktree scoped) |

Mechanical primitives:

```bash
python3 scripts/orchestrator_signal_context.py . capture --orchestrator-type debug --run-id <id> --input '{"signal_type":"error"}'
python3 scripts/orchestrator_run.py . provision --orchestrator-type debug --run-id <id>
python3 scripts/orchestrator_run.py . teardown --orchestrator-type debug --run-id <id>
```

Cross-orchestrator isolation: episodic runs refuse writes under `.cursor/sw-deliver-state*`,
`.cursor/sw-deliver-runs/`, and other deliver-scoped paths (`scripts/orchestrator_run.py assert-write`).

## Per-task execute status (PRD 039 R2)

Per-task TDD + refactor rollup lives under `.cursor/sw-execute-runs/<sanitized-task-ref>/status.json`
(written by `scripts/execute_task_status.py`). Schema reference:
`core/skills/execute-discipline/references/refactor-status-schema.json`.

```json
{
  "taskRef": "2.1",
  "refactor": {
    "ran": true,
    "skipped": false,
    "skipReason": "",
    "signalRef": "/tmp/sw-quality.signal.json",
    "verdict": "clean",
    "metricDelta": { "coupling": "unavailable", "cohesion": "unavailable", "complexity": 0.0, "churn": 0 }
  }
}
```

| Field | Role |
| --- | --- |
| `refactor.ran` | Step executed (structural edit optional when signal is `none`/`clean`) |
| `refactor.skipped` | Operational skip — requires non-empty `skipReason` |
| `refactor.signalRef` | Path to quality harness signal consumed by the step |
| `refactor.verdict` | `clean`, `advise`, `poor`, `regressed`, `skipped`, or `none` |
| `refactor.metricDelta` | Delta vs pre-refactor harness snapshot; anti-gaming bar when hints non-empty |

Gate: `python3 scripts/refactor-gate.py --status <path> [--signal <signal-path>]`.


## Sizing & Split Suggestions (PRD 040)

Draft-only advisory block rendered by `python3 scripts/phase_sizing.py advisory <task-list>` into unfrozen
task lists. The block uses the heading `## Sizing & Split Suggestions`, carries structural sizing/split
guidance and a cost estimate, and **must be stripped before freeze** (`python3 scripts/phase_sizing.py
strip-advisory --inplace <path>`). Frozen artifacts reject the block via `phase_sizing.py check-frozen`,
`scripts/spec-rigor-check.py`, and `scripts/check_frozen_scan.py`.

| Artifact | Role |
| --- | --- |
| `core/sw-reference/phase-sizing.schema.json` | JSON Schema for deterministic sizing scorer output |
| `scripts/phase_sizing.py` | Scorer, split suggestion, advisory render/strip commands |

## Python entrypoint model (R32)

Harness scripts live under `scripts/*.py` and execute via `python3 scripts/<name>.py`.
The build chain is `python3 scripts/copy-to-core.py` → `python3 -m sw generate --all` with golden parity under `scripts/test/fixtures/parity/`.

## Self-improving loop stores (PRD 041)

| Store | Path | Writer | Semantics |
| --- | --- | --- | --- |
| Meta inbox draft | `.cursor/sw-meta-inbox/{signalId}.json` | `scripts/sw_state_write.py` (`sw_state_write_lib`) | Redacted draft; schema `core/sw-reference/meta-inbox-draft.schema.json`; per-checkout projection |
| Failure signatures | `${GIT_DIR}/shipwright-failure-signatures.json` | `scripts/sw_state_write.py` | Shared-git-dir authority; append-only upsert via `failure_signature_record_lib`; schema `core/sw-reference/failure-signature.schema.json` |
| Loop health | `${GIT_DIR}/shipwright-loop-health.json` | `scripts/sw_state_write.py` | Shared-git-dir authority; diagnostic-only (`gating: false`); schema `core/sw-reference/loop-health.schema.json` |
| Root-cause records | `${GIT_DIR}/shipwright-root-cause-records.json` | `scripts/sw_state_write.py` | Shared-git-dir authority; escalation via `failure_signature_escalate_lib`; schema `core/sw-reference/root-cause-record.schema.json` |
| Anomaly pattern catalog | `core/sw-reference/anomaly-patterns.json` | repo-curated (read-only at runtime) | Recognition/annotation only; consumed by `rca-core` + read-only `/sw-debug` |

All writes pass through `memory_redact.redact` and schema validation; direct `write_json` to these paths is forbidden.
`index-merge` on `failure-signatures` merges linked worktree stores into the shared-git-dir authority.



## Primary-checkout guard convention (PRD 050 D6)

Scripts that mutate git state against the shared primary checkout MUST:

1. Resolve working root from `Path.cwd()` (never `__file__`-derived paths).
2. Call `scripts/primary_checkout_guard.py` `guard()` / `enforce_guard()` with `(resolved_root, artifact_branch)` before any checkout/commit.
3. Acquire `primary-checkout.lock` under `.cursor/sw-deliver-runs/` before mutating primary checkout HEAD.

## Issue-store migration journal (PRD 044 Phase 1)

Bidirectional file ⇄ issue migration records durable per-artifact state under hook ephemeral state:

| Path | Writer | Semantics |
| --- | --- | --- |
| `.cursor/hooks/state/issue-store-migration-journal.json` | `scripts/planning_migrate_issue_store.py` (`run_store_migration`) | Per-artifact state machine `pending` → `created` → `verified` → `source-removed`; idempotency key `source_path:content_hash`; verify-then-delete ordering |
| `.cursor/hooks/state/context-compress-cache/` | `scripts/context_compress.py` | Gitignored CCR cache keyed by full SHA-256 of redacted content; orchestrator-only `retrieve()` (PRD 058 R20–R22) |

Dry-run (no `--apply`) must not create or update this file. Command surface: `/sw-migrate` /
`scripts/planning_migrate.py` `store-files-to-issues` | `store-issues-to-files`.

## Hook-state vs deliver durable state (PRD 050 A1 R31)

| State class | Canonical root |
| --- | --- |
| Deliver durable state (`.cursor/sw-deliver-state.<slug>.json`, locks, merge queue) | Repo root (primary checkout) |
| Hook ephemeral state (`.cursor/hooks/state/*`) | R20-resolved active root (worktree when aligned) |
