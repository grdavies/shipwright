---
name: sw-deliver
description: Dependency-ordered deliver waves with dependent-branch stacking and integration branch lifecycle.
---

# Deliver orchestration

Layer above `/sw-ship` for **phase-mode** (frozen task-list phases stacking onto `<type>/<slug>`) and
**multi-feature mode** (independent features promoting via `integration/<stamp>`). Reuses `scripts/worktree.sh`
and `skills/parallelism/` wholesale.

**Conductor:** load `skills/conductor/SKILL.md` for the shared autonomous loop (self-continuation,
legitimate halts, parallel dispatch, resumption). `/sw-deliver` is the pilot consumer; enforce
`rules/sw-conductor.mdc`. Do not re-author loop logic in this skill (R1, R3).


**Model tier:** build — resolve via `bash scripts/resolve-model-tier.sh --skill deliver`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Deliver plan representation

Path: `.cursor/sw-deliver-plan.json` (machine-readable; see `.sw/layout.md`).

```json
{
  "verdict": "pass",
  "mode": "phase",
  "source_task_list": "docs/prds/<n>-<slug>/tasks-<n>-<slug>.md",
  "prd_number": "004",
  "target": {"type": "feat", "slug": "<slug>", "branch": "feat/<slug>"},
  "items": [{"id": "1", "slug": "<phase-slug>", "title": "...", "branch": "feat/<slug>-phase-<phase-slug>"}],
  "edges": [{"from": "1", "to": "2"}],
  "waves": [["1"], ["2", "3"]],
  "contention": {"serialized": ["doc-numbering"], "notes": "..."},
  "notices": []
}
```

Multi-feature mode uses `"mode": "multi-feature"` with conforming type-prefixed branches (e.g. `feat/<id>`); `pf/<id>` is prohibited (R24).

- **waves:** ordered batches; no intra-wave dependencies.
- **contention:** shared-migration refusal + living INDEX/numbering counters force serialization;
  `injectedEdges` records contention-forced edges merged into `edges` / `waves`.

### v1 deferrals (PRD 013 R13–R16)

- **Cross-feature waves (R13):** `plan --task-list <frozen> --items a,b --combine [--edges b:1]` mixes
  phase-mode units with multi-feature items; waves honor the combined edge set (`mode: combined`).
- **File-set edge inference (R14):** when `## Phase Dependencies` is absent, overlapping `**File:**`
  paths infer edges before sequential fallback; an explicit dependency table always wins.
- **Live phase status (R15):** `/sw-status` `derive --json` embeds `livePhaseStatus` for in-flight runs;
  `wave_living_docs.py phase-status-live` renders per-phase status, attempt, and blocker mid-run.
- **Contention → `/sw-tasks` (R16):** plan-time serialization notices persist to run-state
  `contentionFeedback`; surface suggestions (never auto-rewrite frozen tasks) via
  `scripts/wave_deliver.py <root> tasks-suggest [--target <type>/<slug>]`.

## Run-state artifacts

| Artifact | Path |
|----------|------|
| Plan | `.cursor/sw-deliver-plan.json` |
| Run state (scoped) | `.cursor/sw-deliver-state.<slug>.json` — canonical at **repo root** only (R28) |
| Orchestrator lock (scoped) | `.cursor/sw-deliver-<slug>.lock` |
| Concurrent-run index | `.cursor/sw-deliver-runs/index.json` |
| Living-doc serialization | `.cursor/sw-living-docs.lock` |
| Per-phase `/sw-ship` status | `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Dispatch decisions | `.cursor/sw-deliver-runs/<phase-slug>/dispatch-decisions.json` |
| Phase step plan | `.cursor/sw-deliver-runs/<phase-slug>/phase-step-plan.json` |
| Append-only progress log | `.cursor/sw-deliver-runs/run.log` |
| Legacy (migration only) | `.cursor/sw-deliver-state.json`, `.cursor/sw-deliver.lock` |

**Two-tier plan persistence (PRD 022):** validated wave-batching plans live on shared run-state
(`waveBatchingPlan`, conductor-only); validated phase step plans live under the phase run dir
(`phase-step-plan.json`, executor-owned). `orchestration.planPolicy` defaults to `canonical`; recorded mode
is honored on resume. Proposals validate via `bash scripts/wave.sh plan validate` before persist — see
`skills/conductor/SKILL.md` **Two-tier plan lifecycle**.

**Proposed-path (PRD 023):** live `proposed` on `/sw-deliver` requires the TR0 dependency gate
(`scripts/pilot_dependency_gate.py` / `scripts/test/pilot-022-prerequisite-check.sh`) plus pilot opt-in guards
(see `core/commands/sw-deliver.md` **Pilot opt-in**). When enabled, `wave_deliver_loop.py` invokes wave/phase
`plan validate` with `--record-rejection` at each proposal site; rejections fall back to canonical waves/chain
without kernel changes. Default `canonical` is byte-identical to pre-023 behavior.

**Benefit metric + reporting (R31):** per-phase and run-level `benefitMetric` objects (numeric/enumerated only)
are captured at terminal phase status and rolled up on shared run-state. Operator soak comparisons use
`bash scripts/wave.sh plan benefit-report --pairs <path>` → `scripts/wave_plan_benefit.py`. Schema and
decision rule: `.sw/layout.md` **Deliver pilot run records**.

**Intra-phase fan-out snapshot:** `intraPhaseFanOut` on phase status / `phases.<id>` records the latest
validated partition, active worker count, and cap state; append-only audit lives in per-phase
`dispatch-decisions.json` (see `skills/parallelism/SKILL.md`).

Living artifacts under `.cursor/` are **never committed** (`/sw-commit` excludes them).

### Provision-time materialization (PRD 034 R7/R8/R20)

Private and memory planning-unit bodies may live outside the tracked tree (`planning.store` backends). During
phase provision — after worktree add and before preflight/spec-seed reads — `wave_lifecycle.py` invokes
`scripts/planning_materialize.py` to copy required spec bodies into the ignored prefix
`.cursor/planning-materialized/`. A post-materialize `secret-scan file` runs; paths register in deliver
run-state for orphan sweep; teardown deletes the tree. Pre-commit, pre-push, and CI diff scans reject any
staged path under the prefix (`scripts/materialized-prefix-scan.sh`) — the **commit-boundary barrier** holds
even under `git add -f`. Store backend + revision are pinned at provision; mid-run `planning.store` config
changes halt with remediation. CI/host never materializes.

Fixture suite: `bash scripts/test/run-planning-materialize-fixtures.sh` (registered as
`planning-materialize-fixtures` in the PR test-plan manifest).

**Per-branch scoping (PRD 013 R6–R11):** `<slug>` derives from the target feature branch
(`feat/<slug>` → `sw-deliver-state.<slug>.json`). Orthogonal branches run concurrently with
independent state/lock files; `assert_run_identity` and lock refusal apply **within** a scope only.
Legacy repo-wide state is adopted to the scoped path on first read (breadcrumb left at the legacy path).

**Single canonical write path (R28):** all readers and writers (`wave_state.py`, `wave_compound.py`
`record-premerge`, `cleanup_lib.resolve_deliver_state`) resolve the scoped path at the git toplevel —
never a duplicate copy under an orchestrator worktree `.cursor/`.

**Freeze-time commit (PRD 013 R1–R5):** `/sw-freeze` invokes `check-frozen.sh freeze-commit` → shared
`wave_spec_seed.py` helper (same as `/sw-doc` afterTasks). Commits docs-only onto `<type>/<slug>`;
never `main`; verdict-independent (commit failure warns; stamp still completes).

### Run-state schema (scoped `.cursor/sw-deliver-state.<slug>.json`)

Initialized from the phase-mode plan via `scripts/wave.sh state init --plan .cursor/sw-deliver-plan.json`:

```json
{
  "verdict": "running",
  "target": {"type": "feat", "slug": "<slug>", "branch": "feat/<slug>"},
  "source_task_list": "docs/prds/<n>-<slug>/tasks-<n>-<slug>.md",
  "prd_number": "004",
  "phases": {
    "1": {
      "id": "1",
      "slug": "<phase-slug>",
      "title": "...",
      "branch": "feat/<slug>-phase-<phase-slug>",
      "status": "pending",
      "updatedAt": "2026-06-25T00:00:00Z"
    }
  },
  "mergeJournal": null,
  "completedMerges": [],
  "currentWave": 1,
  "nextAction": "lock-acquire",
  "remediationAttempts": {},
  "driverHeartbeatAt": "2026-06-25T00:00:00Z",
  "runStartedAt": "2026-06-25T00:00:00Z",
  "driverIterationCount": 0,
  "noProgressStreak": 0,
  "planRejectionLog": [],
  "updatedAt": "2026-06-25T00:00:00Z"
}
```

**Driver cursor (R1/R2):** `currentWave`, `nextAction`, `remediationAttempts`, and `driverHeartbeatAt` are
written by `scripts/wave.sh deliver-loop` on every transition. A fresh agent resumes from this state alone.

**Phase status vocabulary:** `pending` | `in-flight` | `green-merged` | `teardown-pending` |
`teardown-complete` | `blocked` | `rejected`.

**Operator resume (R29):**

```text
/sw-deliver run docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
```

The bash `deliver-loop` driver is for conductor in-turn mechanical re-invocation — not the user-facing
resume command.

**Helpers (internal driver):**

```bash
scripts/wave.sh deliver-loop --dry-run
scripts/wave.sh state init --plan .cursor/sw-deliver-plan.json
scripts/wave.sh state phase --id 1 --status in-flight
scripts/wave.sh state phase --slug rename-deliver --status green-merged
scripts/wave.sh state get
scripts/wave.sh state terminal --verdict complete
```

Per-phase `/sw-ship` outcomes live in `sw-deliver-runs/<phase>/status.json` (`merge-ready-green` |
`blocked`); `scripts/ship-phase-status.sh` syncs `blocked` into run-state when present.

### Orchestrator lock + merge journal (R51)

```bash
scripts/wave.sh lock acquire --target feat/<slug> --nonblock   # exit 20 if held
scripts/wave.sh lock release
scripts/wave.sh journal begin --phase <phase-slug> [--head <sha>]
scripts/wave.sh journal complete --phase <phase-slug>
```

- **Lock:** atomic create on `.cursor/sw-deliver-<slug>.lock`; a lock for branch A does not block
  branch B; a second live run on the **same** branch refuses (`exit 20`) until `lock release`.
- **Merge journal:** open entry before phase → `<type>/<slug>` merge; cleared after push + state commit.
  Resume detects interrupted merge via `journal status`.

### Progress log (R54)

Append-only JSON lines at `.cursor/sw-deliver-runs/run.log` on run init, phase transitions, lock
acquire/release, merge journal events, and terminal halt.

```bash
scripts/wave.sh log tail --lines 20
```

Each line: `{ "event": "phase-transition", "phaseId": "1", "from": "pending", "to": "in-flight", "at": "..." }`.

## Parallel scheduler (R14/R44)

After `plan`, compute ceiling-bounded dispatch batches:

```bash
scripts/wave.sh schedule --plan .cursor/sw-deliver-plan.json
# optional override: --ceiling 2
```

- Reads `worktree.parallelCeiling` from `.cursor/workflow.config.json` (default **4**).
- Each **wave** may require multiple **batches** when `len(wave) > parallelCeiling`.
- Batches are greedy left-to-right chunks; the scheduler **never unwinds** a running phase to
  admit a queued one.
- **Ceiling accounting (R44):** only wave-level `/sw-ship` phase worktrees count toward the ceiling.
  Internal sub-agent dispatch *within* a phase's `/sw-ship` (`rules/sw-subagent-dispatch.mdc`) does
  **not** consume slots. The orchestrator merge queue progresses without holding a phase slot.

Schedule JSON shape:

```json
{
  "parallelCeiling": 4,
  "schedule": [
    {
      "wave": 2,
      "phases": ["2", "3", "4", "5"],
      "batches": [
        {"parallel": ["2", "3", "4", "5"], "slotCount": 4, "remainderQueued": false}
      ],
      "countsTowardCeiling": true
    }
  ]
}
```

When a wave exceeds the ceiling, `batches` splits into sequential chunks (e.g. ceiling 2 with
phases `["2","3","4"]` → `[["2","3"],["4"]]`).

## Conductor parallel dispatch (R14–R16, R22)

When a wave has N independent ready phases, the driver emits **`dispatch-batch`** — one action marking all N
`in-flight` atomically. The conductor spawns N background `Task` sub-agents (up to `parallelCeiling`):

1. Driver `provision-phase` (mechanical) until worktrees exist for the batch.
2. Driver returns `dispatch-batch` → conductor spawns N background Tasks (`run_in_background: true`).
3. Wait for durable `status.json` per **Parallel-wave completion wait** in `skills/conductor/SKILL.md`.
4. Driver `collect-all-ready` enqueues simultaneous greens in phase-id order → `merge run-next`
   (conductor only). **Whole-batch gate (R10):** the driver never `merge-enqueue`s a lone ready member while
   sibling in-flight phases lack validated terminal status; integration HEAD is pinned at collect-all-ready.
5. **Deterministic merge conflicts (R12):** conflicts confined to `core/sw-reference/deterministic-regen-paths.json`
   auto-resolve via regenerate-and-restage in the orchestrator worktree; semantic paths halt.

On `status collect` with `blocked`, `blast-radius apply` blocks transitive dependents only (R24):

```bash
scripts/wave.sh status collect --phase-slug <phase-slug>
scripts/wave.sh blast-radius apply --phase-slug <upstream-slug>
```

## Branch topology (R35/R53)

| Role | Branch | Worktree path |
|------|--------|---------------|
| Feature base | `<type>/<slug>` | `.sw-worktrees/<slug>-orchestrator` (infrastructure) |
| Phase unit | `<type>/<slug>-phase-<phase-slug>` | `.sw-worktrees/<slug>-phase-<phase-slug>` |

Phase branches come from the deliver plan `items[].branch`. The orchestrator worktree checks out
`<type>/<slug>` (detached at the target tip when that branch is already checked out elsewhere) and does
**not** consume a `parallelCeiling` slot (`countsTowardCeiling: false` in per-worktree state).

```bash
scripts/wave.sh assert-entry
scripts/wave.sh orchestrator provision --plan .cursor/sw-deliver-plan.json
scripts/wave.sh orchestrator status
scripts/wave.sh phase provision --phase-id 1 --plan .cursor/sw-deliver-plan.json
scripts/wave.sh forward-merge --worktree .sw-worktrees/<slug>-phase-<phase> --base feat/<slug>
scripts/wave.sh phase-teardown --name <slug>-phase-<phase>
```

**Forward-merge (R20/R40):** after a sibling merges into `<type>/<slug>`, integrate the new tip into a
dependent phase branch via **merge** (never rebase a published phase branch). Conflicts surface as
`blocked` with `cause: forward-merge:conflict`.

**Teardown (R21):** only `git worktree remove` + `prune` — never `rm` the directory.

## Stacking

Dependents provision with:

```bash
scripts/worktree.sh provision <name> --base <dependency-branch> --branch <type>/<name>
```

`<type>` must be drawn from `release-please-config.json` `changelog-sections[].type` (e.g. `feat`, `fix`,
`chore`). `pf/<name>` is prohibited; the branch-name guard (`scripts/branch-name-guard.sh`) refuses
non-conforming names at creation time (R22–R25).

Merge pre-flight from `skills/parallelism/` runs before stacking. No item touches `main` mid-wave.

## Integration branch

After green leaves:

1. Create `integration/<stamp>` from `main`.
2. Merge green leaf branches.
3. Run whole-suite check (`check-gate.sh` on integration PR head).
4. Human gate authorizes `promote` in dependency order.

## Promotion (pre-merge validated)

For each leaf in dependency order:

1. Build disposable candidate ref: `main` + already-promoted + this leaf.
2. Push candidate branch + open short-lived PR.
3. Run `check-gate.sh` on PR head — green only then fast-forward to `main`.
4. Red candidate halts promotion before `main` is touched.

## Attributability

| Integration red type | Action |
|---------------------|--------|
| Reproduces in one leaf | Route to that leaf's stabilize loop |
| Every leaf/pair green in isolation | Delta-debug minimal subset + human escalation |

## High-contention surfaces

Living `docs/prds/INDEX.md`, `docs/decisions/INDEX.md`, and doc-numbering counters are shared mutable state — serialize doc-creation across a wave or late-bind numbering at integration.

## Phase `/sw-ship` dispatch (R48/R18)

Each phase runs the full `/sw-ship` chain inside an isolated worktree. The orchestrator MUST dispatch with the
non-interactive contract:

```bash
export SW_PHASE_MODE=1
export SW_PHASE_SLUG=<phase-slug>
export SW_RUN_DIR=.cursor/sw-deliver-runs/<phase-slug>
# invoke /sw-ship --phase-mode in the phase worktree
```

On completion, read `$SW_RUN_DIR/status.json` (or `.cursor/sw-deliver-runs/<phase>/status.json`):

| `verdict` | Orchestrator action |
| --- | --- |
| `merge-ready-green` | Enqueue serialized merge into `<type>/<slug>` (R19); never merge to `main` here |
| `blocked` | Record `blocked` in run-state; apply blast-radius (R25/R26); surface `cause` |

Terminal pause is suppressed; `/sw-deliver` must not wait on human input for per-phase outcomes.

## Conductor in-turn loop (R2, R6, R7, R13)

`/sw-deliver` consumes `skills/conductor/SKILL.md` for the autonomous loop. Summary:

1. Run `bash scripts/wave.sh deliver-loop` from the orchestrator worktree.
2. While `verdict: running` and no legitimate halt:
   - `awaitAgent: false` → re-invoke `deliver-loop` immediately (same turn).
   - `awaitAgent: true` → execute `next.action` (`dispatch-ship`, `remediate`, `retrospective`, or
     `terminal-ship`), then re-invoke `deliver-loop`.
3. Never end the turn asking the user to "continue deliver" when progress is still possible (R13).

**Retrospective handoff (R9):** when `next.action` is `retrospective`, run **`/sw-retrospective --pre-merge`**
on the orchestrator worktree only — do not inline retro/compound/memory/status. Respect `compound.autonomy`
via `bash scripts/wave.sh retrospective autonomy`. Then re-invoke `deliver-loop` for `terminal-ship`.

**Self-wake (R8/R9):** terminal-PR CI uses `notify_on_output` on `^DELIVER_WAKE_<run-id>`; tear down all
watchers on terminal halt. **Parallel-wave wait (R44):** poll or self-wake on durable `status.json` set.
**Headless fallback (R46):** bounded poll to `checks.watch.maxWaitMinutes`, then one consolidated halt.

**Hard stop (R38):** `deliver.autonomy.maxIterations` + 3× no-progress on `(nextAction, stateSignature)` —
see `rules/sw-subagent-dispatch.mdc`.

## Sub-agent dispatch spike (R63)

**Spike conclusion (2026-06):** Cursor's parent agent can launch **background** subagents via the Task tool
(`run_in_background: true`), but **nested** dispatch (a subagent launching its own subagents) is not a reliable
platform contract — depth and tool availability vary by runtime.

**Default / fallback:** per-phase `/sw-execute` uses **inline two-stage review** from
`rules/sw-subagent-dispatch.mdc` (spec-compliance → code-quality) when:

- nested background dispatch is unavailable or untested for the active runtime, or
- the phase touches ≤3 files with sequential edits (inline is already preferred).

When background dispatch **is** available at the orchestrator level, `/sw-deliver` may dispatch phase
`/sw-ship` as a background Task; the orchestrator still collects outcomes from the durable
`sw-deliver-runs/<phase>/status.json` path — never from ephemeral `sw-tmp` run dirs alone.

## Serialized merge queue (R17/R19/R50/R52)

After `merge-ready-green` status is collected, phases enter a **single-flight** merge queue. Only one
phase → `<type>/<slug>` merge runs at a time; journal + lock prevent double-merge.

```bash
# 1. Collect durable /sw-ship outcome (R38) — never read sw-tmp run dirs
scripts/wave.sh status collect --phase-slug <phase-slug>

# 2. Enqueue when status is merge-ready-green
scripts/wave.sh merge enqueue --phase-slug <phase-slug>

# 3. Review barrier + live gate before merge (R17/R52) — exit 10 while yellow/pending review
scripts/wave.sh merge gate-check --pr <n>

# 4. Process next queued phase (true merge commit, --no-ff)
scripts/wave.sh merge run-next --orchestrator-worktree .sw-worktrees/<slug>-orchestrator

# Resume predicate (R50): phase tip is ancestor of target tip after merge
scripts/wave.sh merge ancestry-check --phase-branch feat/<slug>-phase-<phase> --target feat/<slug>
```

- **Merge method:** true `git merge --no-ff` only (no squash/rebase) so ancestry reconciliation holds.
- **Review barrier:** `merge gate-check` / `merge run-next` refuse until `check-gate.sh` is **green** and
  `coderabbitLanded` is not `false` (pending async review is non-green for auto-merge).
- **Journal:** `merge run-next` opens `mergeJournal` before merge and clears on success (coordinates with
  `wave.sh journal` helpers).
- **No-PR path:** when a phase has no open PR, `merge run-next` uses local-evidence from durable
  `status.json` (merge-ready-green + head SHA binding) plus post-merge incremental verify; remote
  `check-gate.sh` authority applies at the terminal PR only.
- **Push chokepoint:** workflow pushes use `scripts/git-push.sh` → `scripts/secret-scan.sh` before
  `git push` (including `sw-pr` and stabilize re-pushes).

## Terminal report (R24/R55/R57)

When all phases are `green-merged`:

```bash
scripts/wave.sh report terminal
```

Emits per-phase PR links (`mergedPhases`), Conventional Commit types from `release-please-config.json`,
and the whole-feature gate line: `ready to merge — your call` for `<type>/<slug> → main`.

## Release bookkeeping (R58–R60)

After each green phase merge into `<type>/<slug>`, the orchestrator (single locked merge step only) updates
`CHANGELOG.md` and `version.txt` in the orchestrator worktree:

```bash
scripts/wave.sh bookkeeping record --phase-slug <slug> --message "..." --type feat \
  --merge-commit <sha> --commit
scripts/wave.sh bookkeeping revert --phase-slug <slug> --commit   # after git revert of phase merge
scripts/wave.sh bookkeeping projected --types feat,fix
```

- Appends to `## [Unreleased]` under the release-please-mapped section (`feat`→Features, `fix`→Bug Fixes, …).
- Entries carry `<!-- sw-deliver:<phase-slug> -->` markers for revert/unstack (R45/R59).
- `version.txt` = projected next semver (breaking→major, `feat`→minor, `fix`/`perf`→patch aggregate).
- Bookkeeping edits commit as `chore: deliver bookkeeping for phase <slug>` (not listed in changelog).
- `merge run-next` invokes `bookkeeping record --commit` automatically after a green merge.

`CHANGELOG.md` / `version.txt` are contention-serialized (R11) — never edited inside parallel phase worktrees.

## Living-doc currency (R47–R51)

After each green phase merge, `merge run-next` also invokes `living-docs reconcile --commit` on the
orchestrator worktree — updating `docs/prds/INDEX.md` status from durable run state (`not-started` |
`in-progress` | `complete`), resolving absorbed `GAP-BACKLOG` rows when the PRD completes, and committing
the three ledger files onto `<type>/<slug>`.

Before the terminal PR gate, `terminal pr prepare` appends an idempotent `COMPLETION-LOG` row
(`living-docs append-terminal --commit`) and runs `docs-currency` — a hard-block on drift in the current
run's INDEX row, completion-log entry, and absorbed gaps (R50; parity with task-currency R15).

```bash
scripts/wave.sh living-docs reconcile --commit
scripts/wave.sh living-docs append-terminal --commit
scripts/wave.sh docs-currency
bash scripts/reconcile-status.sh set-index-status --prd <NNN> --status in-progress
bash scripts/reconcile-status.sh append-log-idempotent --prd <NNN> --phase all --pr <N> --sha <sha>
bash scripts/reconcile-status.sh gap-resolve --absorbing-prd <NNN> --pr <N>
```

See `skills/living-status/SKILL.md` for the canonical INDEX status enum and reconcile primitives.

## Incremental verify + failure routing (R25–R27, R39, R45–R46)

After each phase merge into `<type>/<slug>`, `merge run-next` runs configured `verify.*` on the orchestrator
worktree head (R39). Flaky failures get one re-run before blocking (R27).

```bash
scripts/wave.sh verify run --orchestrator-worktree .sw-worktrees/<slug>-orchestrator
scripts/wave.sh verify run-after-merge --phase-slug <slug>   # revert on fail (R45)
scripts/wave.sh blast-radius apply --phase-slug <slug>       # block transitive dependents (R25)
scripts/wave.sh report blockers                              # consolidated halt report (R26)
scripts/wave.sh stabilize route --phase-slug <slug>          # → /sw-stabilize recommendation (R27)
scripts/wave.sh revert phase --phase-slug <slug>             # git revert + bookkeeping + blast-radius
scripts/wave.sh terminal deny --scope whole-feature|per-phase [--phase-slug <slug>]
```

- **Blast radius:** only transitive dependents of a `blocked` phase are blocked; independent siblings continue
  and may still auto-merge greens (R25).
- **Verify red:** routes to `/sw-stabilize` on `<type>/<slug>`, reverts the offending merge (R45), marks phase
  `blocked`, re-blocks dependents; does not open/advance the terminal PR.
- **Terminal deny (R46):** records `terminalRejected` in run-state; resume must not re-present the rejected PR.
- **`status collect` on `blocked`:** automatically applies blast-radius to dependents.

## Terminal PR gate and resume (R22–R24, R29–R30, R43, R56)

When all phases are `green-merged` and none `blocked`:

```bash
scripts/wave.sh resume reconcile                    # remote <type>/<slug> tip is ground truth (R29/R50)
scripts/wave.sh terminal pr prepare                 # open/update single <type>/<slug> → main PR (R22)
scripts/wave.sh terminal pr gate                    # check-gate.sh on terminal PR head (R23/R24)
scripts/wave.sh terminal pr status
scripts/wave.sh report terminal                     # /sw-ready form when gate green
scripts/wave.sh ack check|complete|status           # optional cadence (deliver.phaseAckCadence, R56)
```

- **No `integration/<stamp>`** in phase-mode — one terminal PR only (R22).
- **Rejected terminal** (`terminal deny`): resume must not re-present the same PR (R46).
- **INDEX `inFlight` region (PRD 032):** deliver run-start writes a committed tuple (`runId`, `branch` or
  `branchToken`, `epoch`) under the living-doc single-writer lock after `lock-acquire` / before
  `orchestrator-provision`; cleared at run completion via `inflight-signal-clear`. Lifecycle `in-progress` is
  **not** stored in the tuple — PRD 033 derives it. Durable run-id lease in scoped deliver state is authoritative
  (R2). Set `SW_INDEX_REGION_WRITER=deliver` on INDEX commits touching `inFlight`.
- **Run-state** binds `source_task_list` + `prd_number`; wave run never `in-progress` INDEX status mutation (PRD 033 derives lifecycle).
- **`deliver.phaseAckCadence: K`** (default `0`): pause for human `ack complete` after every K phase merges (R56).

### Terminal autonomy — amendment A1 (PRD 013 R20–R27)

Config: `deliver.terminal.autonomy` (`supervised` | `auto`, default `supervised`); `cleanup.autonomy`
(`confirm` | `auto`, default `confirm`).

```bash
scripts/wave.sh terminal autonomy                      # read knob + mode
scripts/wave.sh terminal retro run [--dry-run]         # retrospective before PR (R20/R21)
scripts/wave.sh terminal ship run [--dry-run]          # PR → push → gate watch (R22/R23)
python3 scripts/cleanup_lib.py <root> --autonomous     # zero-interaction cleanup when safe (R25/R26)
```

- **`auto`:** retrospective + terminal ship run hands-off; merge to `main` stays human-gated (R23).
- **`supervised`:** preserves today's halts (`exit 11` supervised-checkpoint).
- Cleanup `auto` applies only the dry-run `wouldRemove` set when merge is deterministic, no in-flight
  scoped run, and not current/default branch; `indeterminate` → human gate.

## Base-branch preflight and spec visibility (R49, R61, R62)

Before phase dispatch, phase-mode `preflight` / `plan` runs **base-branch preflight** (R49):

```bash
scripts/wave.sh preflight --task-list docs/prds/<n>-<slug>/tasks-....md
scripts/wave.sh preflight-base --target feat/<slug>   # atomic check
```

- Verifies `.github/workflows` `pull_request` triggers cover `<type>/**` bases (not main-only).
- When `review.provider` is configured, requires repo review config so phase PRs can land reviews (R52).
- Fails closed with remediation hints — never silent `checkCount==0` timeout-blocked degradation.

**Spec in worktrees (R61):** `docs/prds/` is git-tracked (`docs/*` ignored, `!docs/prds/**` un-ignored).
Frozen task lists and PRDs must resolve inside the active worktree (prefer repo-relative paths;
absolute paths under the worktree root are allowed) — never paths into another checkout.

**Post-run learnings (R62):**

```bash
scripts/wave.sh memory learnings distill
scripts/wave.sh memory learnings prepare --out .cursor/sw-deliver-learnings.md
# then memory-preflight write (category: learning) with redacted payload only
```

Distills contention, blast-radius, revert, and blocked-phase patterns from plan + run log — never raw
transcripts or sub-agent logs. Always pipe through `scripts/memory-redact.sh` before persist.

## Concurrency invariants (PRD 036 — acceptance)

Operator-facing guarantees enforced by CI fixtures (`run-dual-ship-fixtures.sh`,
`run-regression-remediation-fixtures.sh`, `run-parallel-merge-safety-fixtures.sh`,
`run-status-integrity-fixtures.sh`):

1. **Single-flight ship (R1–R5):** one in-turn `/sw-ship --phase-mode` per phase head; per-head lease +
   PR idempotency; conductor never backgrounds ship on the same head.
2. **Regression remediation (R6–R8):** `verify:failed` routes to bounded `/sw-stabilize`; remediation
   attempts change the durable state signature; exhaustion halts with a consolidated report.
3. **Whole-batch merge (R9–R12):** no early single-phase merge while siblings lack validated terminal
   status; deterministic phase-id merge order; bounded auto-regen for deterministic-conflict paths only.
4. **Status provenance (R13–R17):** `ship-phase-status.sh` emits an offline-regenerable provenance marker;
   forged or stale `merge-ready-green` is rejected; recovery reuses `/sw-ship --phase-mode --from <step>`
   — never hand-edit `status.json`.

Trust boundaries unchanged (R22): human merge to `main`, secret-scan push chokepoint, scoped deliver
locks, and frozen-doc CI gates.
