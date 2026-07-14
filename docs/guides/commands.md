# Shipwright commands

Shipwright exposes `sw-` commands in Cursor and Claude Code. **Orchestrators** chain phases;
**atomics** do one bounded step. For full procedure text, open the linked command file under
`core/commands/`.

## Orchestrators

| Command | Scope | Does not |
|---------|-------|----------|
| [`/sw-doc`](../../core/commands/sw-doc.md) | Doc pipeline: triage → brainstorm (Full) → PRD → review → freeze → **single-pass** `/sw-tasks`; then `doc.afterTasks` (`stop` \| `confirm` \| `auto`) | Implement, merge, or skip human gates |
| [`/sw-deliver`](../../core/commands/sw-deliver.md) | **Primary** implementation orchestrator — frozen task-list phase-mode or multi-feature wave | Bypass `/sw-ship`, auto-merge to `main`, or re-author frozen tasks |
| [`/sw-ship`](../../core/commands/sw-ship.md) | **Manual** single-phase loop: execute → verify → review → commit → PR → CI → stabilize → ready; also runs **inside** each `/sw-deliver` phase | Merge (halts at merge gate) |
| [`/sw-debug`](../../core/commands/sw-debug.md) | Production/dev RCA and route by fix size | Implement, commit, or merge |
| [`/sw-feedback`](../../core/commands/sw-feedback.md) | Normalize inbound signals and route to debug, gaps, or brainstorm | Analyze, author, or dispatch without confirmation |
| [`/sw-compound-ship`](../../core/commands/sw-compound-ship.md) | Pre-merge (in-loop) or post-merge: retro → compound → optional memory-sync | Merge or auto-promote rules |
| [`/sw-cleanup`](../../core/commands/sw-cleanup.md) | Dry-run default cleanup of merged branches, stale worktrees, completed run-state | Delete without confirm or drop in-flight runs |

### `/sw-deliver` — phase-mode and multi-feature

**Phase-mode (default after `/sw-doc`):**

```text
/sw-deliver run docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
```

- **Mode auto-detect:** `--task-list` → phase-mode; `--items`/`--edges` → multi-feature; both → halt.
- **Single terminal merge gate:** per-phase PRs auto-merge into `<type>/<slug>` on green; one
 human-gated `<type>/<slug> → main` PR at the end.
- **Resumption:** re-run `run` after interrupt; durable `deliver-loop` cursor in
 `.cursor/sw-deliver-state.<slug>.json` at repo root; `plan --from <phase>` when resuming mid-wave.
- **Pre-merge compounding:** full `/sw-compound-ship --pre-merge` before the terminal human merge gate;
 completion stays `completed-pending-merge` until merge is detected.
- **Dry-run:** `scripts/wave.py plan --task-list <path> --dry-run` — plan JSON only, no artifact write.

**Autonomy:** default `deliver.autonomy.mode: autonomous` — conductor in-turn loop to terminal
gate. **Legitimate halt** (`legitimate.halt`) only (see [`configuration.md`](configuration.md)). Parallel phases when the
plan allows; outcomes from durable `status.json` only.

**Living-doc currency:** INDEX / COMPLETION-LOG / gap-index reconcile in-loop (legacy GAP-BACKLOG projection read-only); `docs-currency` blocks
terminal merge on drift.

**Frontmatter:** Full-tier PRDs require `brainstorm:`; `/sw-freeze` verifies linkage.

**Multi-feature mode:** `plan`/`run` with `--items` and `--edges`; integration surface at
`integration/<stamp>`; promotion via `promote` (human-gated).

See [`core/commands/sw-deliver.md`](../../core/commands/sw-deliver.md) and
[`core/skills/deliver/SKILL.md`](../../core/skills/deliver/SKILL.md).

**Plan validation:** mechanical gate for agent-proposed phase/wave plans — not hand-authored in
chat. Default `orchestration.planPolicy: canonical` preserves today's behavior; `proposed` is opt-in on
the `/sw-deliver` pilot (TR0 gate, per-run acknowledgement, non-`main` target).

```bash
python3 scripts/wave.py plan benefit-report --pairs scripts/test/fixtures/benefit-metric/positive-pairs.json
```

```bash
python3 scripts/wave.py plan validate --tier phase --phase-type ship --proposal <path|json>
python3 scripts/wave.py plan validate --tier wave --proposal <path|json> --plan .cursor/sw-deliver-plan.json
```

Call-site map: [`call-site-map.md`](../../scripts/test/fixtures/planning-post-migration/022-kernel-classification-and-plan-validation/call-site-map.md).

**Push safety:** workflow pushes route through `scripts/git-push.py` → `scripts/secret-scan.py`
before `git push` (including `sw-pr` and stabilize re-pushes).

### Planning surface

Extends `/sw-doc` — no `/sw-plan` command.

| Surface | Command / script |
| --- | --- |
| Pull-in at PRD creation | `/sw-prd` → `planning-related.py scan --mode creation` + confirm-list |
| Backlog re-scan at tasks | `/sw-tasks` → `planning-related.py scan --mode tasks-rescan` |
| Mechanical reconciler | `python3 scripts/planning-graph.py reconcile` |
| Scheduler | `/sw-deliver next` |
| Autonomy posture | `planning.autonomy` (`maintenance-only` default \| `full-conductor`) |
| Two-track doc edits | `scripts/docs-edit-route.py` → mechanical `docs-merge.py` or substantive docs worktree + PR |
| Gap capture from feedback | `/sw-feedback` → `planning_gap_capture.py` (not legacy `GAP-BACKLOG.md`) |

See [`core/commands/sw-doc.md`](../../core/commands/sw-doc.md) **Planning command surface** and
[`core/skills/conductor/SKILL.md`](../../core/skills/conductor/SKILL.md) **Bounded planning full-conductor**.



### Issue-store migration

| Command | Role |
| --- | --- |
| [`/sw-migrate`](../../core/commands/sw-migrate.md) | Bidirectional files ⇄ issues migration; dry-run default |
| `store-doctor` | Detect/repair half-migrated journal states |
| `store-scan-quiesce` | Inspect deliver/reconcile blockers before migrating |

Quiesce deliver and reconciler before `--apply`. During transition `GAP-BACKLOG.md` is a read-only
projection — use `planning_gap_capture.py` for new gaps (see [`feedback` skill](../../core/skills/feedback/SKILL.md)).


### Issue-store probes

| Probe | Command |
| --- | --- |
| Effective backend + Bitbucket guidance | `python3 scripts/planning_store.py resolve-backend` |
| Bitbucket routing when `issuesProvider` unset | `python3 scripts/planning_store.py bitbucket-issue-store-guidance` |
| Jira init (auth, privacy, createmeta, labels) | `python3 scripts/planning_store.py probe-jira-init` |
| Issues token scope | `python3 scripts/planning_store.py probe-issues-token` |

Jira Cloud is the default Jira flavor; DC/Server expands on validated demand. Bitbucket code repos default
to a **separate** GitHub/GitLab planning project — Jira is opt-in. See
[`configuration.md`](configuration.md#issue-store-opt-in) and
[`workflows.md`](workflows.md#issue-store-on-bitbucket-hosts).


## Entry points

| Command | When to use | Does not |
|---------|-------------|----------|
| [`/sw-triage`](../../core/commands/sw-triage.md) | Classify Quick / Standard / Full before doc or impl | Draft docs or implement |
| [`/sw-setup`](../../core/commands/sw-setup.md) | First run in a target repo — providers, `doc.afterTasks`, memory store, doctor | Scaffold CI or migrate memories |
| [`/sw-worktree`](../../core/commands/sw-worktree.md) | Isolate work in a per-item worktree (required before impl on bare `main`) | Run phase loop or merge |
| [`/sw-start`](../../core/commands/sw-start.md) | Open a phase branch inside the active worktree; worktree guard runs before writes | Push or open PR |

## Doc pipeline atomics

| Command | Role |
|---------|------|
| [`/sw-brainstorm`](../../core/commands/sw-brainstorm.md) | Requirements exploration (Full tier) |
| [`/sw-prd`](../../core/commands/sw-prd.md) | PRD or decision-record draft |
| [`/sw-doc-review`](../../core/commands/sw-doc-review.md) | Persona panel on spec drafts |
| [`/sw-freeze`](../../core/commands/sw-freeze.md) | Irreversible artifact freeze |
| [`/sw-tasks`](../../core/commands/sw-tasks.md) | Complete frozen task list in **one pass** (no Go gate); standalone run stops without implementation prompt |
| [`/sw-amend`](../../core/commands/sw-amend.md) | Post-freeze PRD amendment |

`doc.afterTasks` is the sole human checkpoint between PRD freeze and implementation when using
`/sw-doc`.

## Ship loop atomics

These compose the **single-phase** ship loop. In normal use, invoke **`/sw-deliver run`** instead
it dispatches this chain per phase automatically. Use the atomics directly for Quick-tier hotfixes,
debugging one phase, or when you deliberately skip the orchestrator.

| Command | Role |
|---------|------|
| [`/sw-execute`](../../core/commands/sw-execute.md) | One phase-sized implementation slice; worktree guard before writes |
| [`/sw-verify`](../../core/commands/sw-verify.md) | Scoped local verification |
| [`/sw-review`](../../core/commands/sw-review.md) | Local then provider code review (`review.provider`; default **`none`**) |
| [`/sw-commit`](../../core/commands/sw-commit.md) | Commit after verify + review |
| [`/sw-pr`](../../core/commands/sw-pr.md) | Push and open/update PR |
| [`/sw-watch-ci`](../../core/commands/sw-watch-ci.md) | Poll PR checks via `check-gate.py` |
| [`/sw-stabilize`](../../core/commands/sw-stabilize.md) | Clear CI + review blockers |
| [`/sw-ready`](../../core/commands/sw-ready.md) | Terminal readiness report; echoes `review: off` or `review: not configured` from gate JSON |

**Worktree invariant:** never write implementation files on bare `main` — use a worktree + phase
branch.

## Memory and compounding

| Command | Role |
|---------|------|
| [`/sw-memory-sync`](../../core/commands/sw-memory-sync.md) | Distill transcript deltas to durable memory |
| [`/sw-memory-audit`](../../core/commands/sw-memory-audit.md) | Read-only memory hygiene audit |
| [`/sw-compound`](../../core/commands/sw-compound.md) | Distill retro into memories |
| [`/sw-retro`](../../core/commands/sw-retro.md) | Post-ship retrospective (report-only) |

## Quick reference — commands you invoke directly

| Command | One-line use case |
|---------|-------------------|
| `/sw-setup` | First run or doctor in a target repo |
| `/sw-triage` | How much ceremony does this work need? |
| `/sw-doc` | Full documentation pipeline |
| `/sw-deliver run` | **Primary** — implement frozen tasks to one terminal merge gate |
| `/sw-ship` | Manual single-phase verify → PR → CI loop (Quick tier / debug) |
| `/sw-debug` | Diagnose production or CI failure |
| `/sw-feedback` | Intake and route external signals |
| `/sw-worktree` | Isolate work in a git worktree (manual path) |
| `/sw-start` | Start a phase branch (manual path) |
| `/sw-execute` | Implement one task slice (manual path) |
| `/sw-status` | Reconcile PRD status from git facts |
| `/sw-memory-sync` | Distill session into durable memory |
| `/sw-memory-audit` | Audit memory hygiene (read-only) |
| `/sw-compound` | Turn retro into memories |
| `/sw-retro` | Post-ship retrospective report |

> 34 commands exist today. This table lists orchestrators and common atomics only. Grep
> `core/commands/sw-*.md` for the complete set.

See [Getting started](getting-started.md) for boundary modes and worktree rules.

**Review opt-out:** the canonical way to disable external review is `review.provider: "none"` (schema default). CodeRabbit is opt-in only.

### orchestrator plan-policy (fan-out)

| Command | Adoption | Notes |
| --- | --- | --- |
| `/sw-deliver` | `full` pilot | Durable run-state; `deliver-loop` driver |
| `/sw-debug` | `full` episodic | Proposed entry + surfacing under `.cursor/sw-debug-runs/` |
| `/sw-doc` | **`consistency-only` default** | Canonical path + doc-review halts; proposed pack deferred unless probe shows latitude |
| `/sw-feedback` | `full` episodic | Untrusted-signal halts; `.cursor/sw-feedback-runs/` scratch |

Fixtures: `python3 scripts/test/run_fanout_fixtures.py`; A2 binding: `python3 scripts/test/run_dispatch_foundation_fixtures.py`.

## Deliver autonomy

`/sw-deliver` phase-mode uses **heartbeat-gated** resume: stale `driverHeartbeatAt` is required to
re-adopt unless self-wake. Parallel waves wait for whole-batch terminal status before merge .
Phase PR CI uses bounded poll/self-wake — not terminal-only watch.

Operator halts include `tasks-currency-divergence`, `gap-check-missing`, `batch-integration-head-moved`,
and living-docs **deferral** (`livingDocDeferral` + `resumeCommand`) when the repo-wide lock is held.

