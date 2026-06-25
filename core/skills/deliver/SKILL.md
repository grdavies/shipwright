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

## Run-state artifacts

| Artifact | Path |
|----------|------|
| Plan | `.cursor/sw-deliver-plan.json` |
| Run state | `.cursor/sw-deliver-state.json` |
| Orchestrator lock | `.cursor/sw-deliver.lock` |
| Per-phase `/sw-ship` status | `.cursor/sw-deliver-runs/<phase-slug>/status.json` |
| Append-only progress log | `.cursor/sw-deliver-runs/run.log` |

Living artifacts under `.cursor/` are **never committed** (`/sw-commit` excludes them).

### Run-state schema (`.cursor/sw-deliver-state.json`)

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
  "updatedAt": "2026-06-25T00:00:00Z"
}
```

**Driver cursor (R1/R2):** `currentWave`, `nextAction`, `remediationAttempts`, and `driverHeartbeatAt` are
written by `scripts/wave.sh deliver-loop` on every transition. A fresh agent resumes from this state alone.

**Phase status vocabulary:** `pending` | `in-flight` | `green-merged` | `blocked` | `rejected`.

**Helpers:**

```bash
scripts/wave.sh deliver-loop --task-list docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
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

- **Lock:** atomic create on `.cursor/sw-deliver.lock` keyed by `<type>/<slug>` metadata; second
  invocation refuses (`exit 20`) until `lock release`.
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
   - `awaitAgent: true` → execute `next.action` (`dispatch-ship`, `remediate`, `compound-ship`, or
     `terminal-ship`), then re-invoke `deliver-loop`.
3. Never end the turn asking the user to "continue deliver" when progress is still possible (R13).

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
- **INDEX.md** uses only `not-started` / `complete` — never `in-progress` (R43). Run-state binds
  `source_task_list` + `prd_number`; wave run does not freeze INDEX to in-progress.
- **`deliver.phaseAckCadence: K`** (default `0`): pause for human `ack complete` after every K phase merges (R56).

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
