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
```

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
| Gap backlog | `docs/prds/GAP-BACKLOG.md` | `/sw-feedback` (Phase 2) | never |

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
  at draft time (`/sw-prd` writes it; `/sw-freeze` + `scripts/doc-link-check.sh` verify it). Legacy alias:
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

## Living vs frozen layers

- **Frozen:** brainstorms, PRDs, task lists, amendments — immutable after `/sw-freeze`; change only via new amendments.
- **Living:** `INDEX.md`, `COMPLETION-LOG.md` — updated as work progresses; never frozen.
- **Gap backlog:** `GAP-BACKLOG.md` — committed, append-only, hand-appendable; not frozen, not git-derived.
- **Generated install trees:** `dist/cursor/` and `dist/claude-code/` — committed outputs of `python3 -m sw generate`; edit `core/` then regenerate (freshness gate in `scripts/test/run-emitter-fixtures.sh`). Not hand-edited except via emitter changes.

## Capability manifest + selector (PRD 021)

Authoring lives under `core/`; the emitter propagates manifest artifacts into both dist trees.

| Artifact | Role |
| --- | --- |
| `core/sw-reference/capability-manifest.schema.json` | JSON Schema for per-capability `capability` frontmatter |
| `core/sw-reference/capability-manifest.md` | Frontmatter, precedence, trust-boundary contract |
| `core/sw-reference/capability-index.json` | Emitter-generated aggregate (committed; freshness-gated) |
| `core/sw-reference/signal-context.schema.json` | Versioned selector inputs |
| `scripts/capability-select.sh` | Deterministic selector primitive |
| `scripts/capability-manifest-lint.sh` | Author-time precedence/conflict/anti-spoof lint |
| `scripts/doc-review-select.sh` / `scripts/code-review-select.sh` | Selection-family wrappers |

**Freshness:** `scripts/test/run-emitter-fixtures.sh` fails when `capability-index.json` or dist trees drift
from current frontmatter. Regenerate after manifest edits: `python3 -m sw generate --all`.

**Pre-selection:** `wave_preflight` / selector entrypoints fail closed when the runtime index does not
reproduce from current sources.

## Config keys

`workflow.config.json`:

- `prdsDir`: `"docs/prds"` — PRD root (per-PRD subdirs live beneath).
- `tasksDir`: `"docs/prds"` — task lists co-locate with their PRD (`docs/prds/<n>-<slug>/tasks-...`).
- `decisionsDir`: `"docs/decisions"` — decision-record root (flat files + sibling `.amendments/` dirs).
- `delegation.mode`: `bind-only` | `heuristic` | `default` — selects delegate-by-default gate behavior
  (PRD 017; default `bind-only` until Phase-2 live acceptance, else `default`).
- `communication.routing` — `commands`, `skills`, and `agents` maps for caveman intensity; seeded from
  `core/sw-reference/communication-routing.defaults.json` via `/sw-setup`.
- `models.routing` — command/skill/agent model tier maps; resolve at dispatch via `resolve-model-tier.sh`.

### Dispatch preflight artifacts (PRD 017)

Per-delegated-Task binding is recorded immediately before spawn:

```bash
bash scripts/wave.sh dispatch preflight --dispatch-id <id> --agent <agent-id> --command <sw-*> [--skill <name>]
bash scripts/dispatch-check.sh --agent <id> --command <sw-*> --parent-model <concrete-id> [--dispatch-id <id>]
```

Preflight nonce + resolved model/intensity live in the per-worktree shipwright state (`scripts/shipwright-state.sh`).
The `preToolUse` hook (`core/hooks/before_task_dispatch.py`) denies bound `Task` spawns lacking a fresh record.
Operator-facing deliver resume: `/sw-deliver run <frozen-task-list-path>` — not raw `bash deliver-loop`.

### Pre-work memory search (PRD 019)

Work-performing commands (`/sw-execute`, `/sw-debug`, `/sw-prd`, `/sw-brainstorm`, `/sw-amend`,
`/sw-review`, `/sw-stabilize`) MUST run a scoped `memory-preflight` search before the first substantive
mutation. Record the breadcrumb mechanically:

```bash
bash scripts/wave.sh memory prework record --surface sw-execute --scope "<paths>" [--hit-count N]
```

Artifacts:

| Path | Role |
| --- | --- |
| `.cursor/hooks/state/memory-prework-search.json` | Redacted per-surface search record (or `memory:offline` / `memory:none`) |
| `.cursor/sw-deliver-runs/run.log` | Append-only audit breadcrumb |

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
| Plan validation | `bash scripts/wave.sh plan validate` → `scripts/wave_plan_validate.py` | mechanical gate | proposals only |

**Wave authority (single source of truth):** the conductor deliver loop reads `waveBatchingPlan` from shared
run-state when present (`wave_deliver_loop.effective_wave_plan`); otherwise it falls back to the frozen
`.cursor/sw-deliver-plan.json` waves. Phase execution reads `phase-step-plan.json` in the phase run dir as the
sole step authority (`ship_phase_steps.authoritative_chain`); canonical `SHIP_CHAIN` is the fallback only.

**Single-writer guard:** `save_deliver_state` and `plan_persist.guarded-state-save` refuse writes when
`SW_CALLER_ROLE=phase` (exit 20). Phase-scoped artifacts (`ship-steps.json`, `phase-step-plan.json`,
`status.json`) are written only under the phase slug's run dir.

**Invariants home:** `core/sw-reference/kernel-classification.md` — cross-link; do not duplicate the kernel
enumeration elsewhere.

## Deliver pilot run records (PRD 023)

| Artifact | Path / field | Writer | Role |
| --- | --- | --- | --- |
| Per-phase dispatch decisions | `.cursor/sw-deliver-runs/<phase-slug>/dispatch-decisions.json` | phase executor | intra-phase fan-out audit (R17) |
| Intra-phase fan-out snapshot | `intraPhaseFanOut` on phase status / `phases.<id>` | phase executor | latest partition + worker count + cap state (R15–R17) |
| Per-phase benefit metric | `benefitMetric` on phase status / shared run-state `phases.<id>` | phase executor at terminal | R31 capture (numeric/enumerated only) |
| Run-level benefit rollup | `benefitMetric` on `.cursor/sw-deliver-state.<slug>.json` | conductor at terminal | paired-run aggregation input |
| Benefit report | `bash scripts/wave.sh plan benefit-report --pairs <path>` → `scripts/wave_plan_benefit.py` | operator / soak protocol | R31 decision rule (fail-closed to `canonical`) |

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

**Decision rule:** `wave.sh plan benefit-report` compares paired `canonical` vs `proposed` metrics at
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


