# Shipwright commands

Shipwright exposes `sw-` commands in Cursor and Claude Code. **Orchestrators** chain phases;
**atomics** do one bounded step. For full procedure text, open the linked command file under
`core/commands/`.

## Helper scripts (bootstrap argv)

Command procedures that shell out to Shipwright helpers use the **bootstrap CLI** so they work in consumer
repos without repo-local façade files:

```bash
python3 scripts/sw_bootstrap.py <helper.py> [-- ARGS...]
python3 scripts/sw_bootstrap.py --print <helper.py>   # resolved absolute path only
```

Examples:

```bash
python3 scripts/sw_bootstrap.py memory-redact.py dispatch
python3 scripts/sw_bootstrap.py git-push.py -- -u origin HEAD
python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-watch-ci
```

Shipwright harness development still invokes `python3 scripts/<helper>.py` directly from the repo-root
`scripts/` tree. Consumer operators copy bootstrap argv from this guide and from
[configuration — Scripts resolution](configuration.md#scripts-resolution-consumer-repos).

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
- **Orchestrator auto-adopt:** on resume, reuse `.sw-worktrees/<slug>-orchestrator` when branch/slug match and the tree is clean; otherwise provision halts with a typed cause. Resume with `/sw-deliver run` — consumable state skips nested preflight.
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

### Graph execution runtime

After cutover, **WorkflowGraph** (`scripts/graph/`) is the **sole production execution runtime** for
`/sw-deliver`, `/sw-doc`, `/sw-debug`, and `/sw-feedback`. Phase/wave plans and episodic orchestrator
intents compile onto the same IR; operator UX stays on existing `sw-` commands — **no**
`/sw-graph-*` slash commands.

| Operator need | Where | Notes |
| --- | --- | --- |
| Plan summary / critical path | `/sw-deliver` `--explain-plan` | Read-only; refuses `--write` / `--persist` |
| Live node progress | `/sw-status` (`graph-progress`) | States: completed, cached/skipped, failed, retrying, running, dependency-blocked, pool-queued, awaiting-human-gate |
| Per-node blockers | `/sw-status` (`explain <nodeId>`) | Actionable-first hierarchy + canonical `nextAction` |
| Planning unit lifecycle | `planning-graph.py status --unit-id <id>` | Planning graph only — not WorkflowGraph execution |
| Cutover stage | `scripts/graph/cutover.py` | `dogfood` → `limited-scope` → `full-ownership`; never drops the human merge gate |
| Serial-equivalent lane | `resourceLimits.maxConcurrency: 1` | Tested mitigation; cache remains independently disableable |

Mechanical entrypoints (same surfaces `/sw-status` delegates to):

```bash
python3 scripts/wave_deliver.py <repo> explain-plan [--task-list <path>|--plan <path>|--graph-json <path>] [--compact] [--text]
python3 scripts/status_integrity.py graph-progress --run-id <runId> [--format json|text] [--compact]
python3 scripts/status_integrity.py explain <nodeId> --run-id <runId> [--format json|text] [--compact]
python3 scripts/planning-graph.py status --unit-id <unit-id>   # planning graph — not execution
```

Receipts, in-flight intents, and status/explain index by the generic graph `runId` (mapped from the
deliver/orchestrator `runId`). Domain vocabulary:
[`graph-domain-terminology.md`](graph-domain-terminology.md). Command detail:
[`sw-deliver.md`](../../core/commands/sw-deliver.md), [`sw-status.md`](../../core/commands/sw-status.md).

**Conductor vs GraphScheduler:** `/sw-deliver` conductor fan-out (parallel phases, merge queue)
is not the `GraphScheduler` owning loop. Graph node admission, `ExecutionBackend` envelopes, cache consult, and
timing attribution live under `scripts/graph/` — operator UX stays on existing commands (no `/sw-graph-*`).


### Workflow optimizer policy

The graph **optimizer** proposes alternate WorkflowGraph layouts under
`orchestration.planPolicy: proposed`. It never invents a parallel operator surface — outcomes surface
only on existing **`/sw-deliver`** and **`/sw-status`** commands (no `/sw-graph-*` slash commands).

| Policy layer | Rule |
| --- | --- |
| **Immutable kernel fields** | Merge gate, credential broker, write-isolation lease, mechanical verification, and host slot accounting stay byte-identical to canonical; unclassified kernel-compiler fields force canonical fallback |
| **Optimizable envelope** | Concurrency, batching, and discretionary node ordering within the proposal budget and cutover stage |
| **Required-capability invariant** | Proposals that delete or weaken required-capability nodes, or raise host demand above ceiling, are rejected **before** shadow |
| **Shadow evaluation** | Read-only scoring of candidate vs canonical from kernel metrics — no mutating dispatch, no credential broker, no write-scoped worktree |
| **Promotion / demotion** | `proposed` → `canonical` requires sample floor, strata, bounded prediction error, named authorizer, and digest-bound confirmation on `/sw-deliver`; defined regressions demote back to `canonical` |
| **In-run kill switch** | Operator kill switch takes effect within the active run and forces `canonical` until cleared |

**Where outcomes appear (graph status and explain surfaces):**

| Need | Surface | Content |
| --- | --- | --- |
| Plan comparison (read-only) | `/sw-deliver --explain-plan` | Node count, parallelism, critical path — no shadow mutation |
| Shadow comparison | `/sw-deliver` (when `proposed` is active) | Predicted latency, cost, parallelism, node count, resource demand, verification coverage; proposal-supplied metric fields are ignored |
| Live progress | `/sw-status` (`graph-progress`) | Receipt-backed node states for the active `runId` |
| Stable reason codes + next action | `/sw-status` (`explain <nodeId>`) | Every optimizer and convergence outcome emits `reasonCode`, `verdict`, responsible node/artifact, explanation, and canonical `nextAction` (convergence codes prefixed `graph.convergence.*`) |
| Digest-bound promotion confirm | `/sw-deliver` | Human confirmation binds the expanded template digest on an existing operator command |

Mechanical shadow and observability entrypoints (same surfaces `/sw-status` delegates to):

```bash
python3 scripts/status_integrity.py graph-progress --run-id <runId>
python3 scripts/status_integrity.py explain <nodeId> --run-id <runId>
```

Configuration for promotion evidence, demotion, kill switch, and registry-sourced capability docs:
[`configuration.md` — Workflow optimizer and capability registry](configuration.md#workflow-optimizer-and-capability-registry).
Composition, convergence, and domain terms:
[`workflows.md`](workflows.md#typed-fragment-composition-and-adaptive-convergence),
[`graph-domain-terminology.md`](graph-domain-terminology.md).

### Deliver operator surface
<!-- currency: refreshed 2026-09-03T19:55:07Z — terminal prepare vs wave_terminal (phase-before-orch teardown) -->

Mechanical list / resume / finalize commands report run identity, target branch, stage, lock holder,
and `requiresAdoption` **before** any mutation. Operators invoke them via `wave_deliver.py` (or
`python3 scripts/wave.py` when routed).

| Command | Reports (read-only) | Mutates when |
| --- | --- | --- |
| `list` | Every known run: `runId`, `targetBranch`, `unit`, `stage`, `terminalStatus`, `lock`, `requiresAdoption`, `statePath`, `taskList` | Never |
| `resume-locate` | Resolved `runId` + full `run` envelope; on ambiguity/zero runs emits enumerated `runs` + `halt` | Never — use `/sw-deliver run` to continue |
| `finalize` | Terminal merge verification outcome, `terminalReceipt`, released resources | After verified default-branch merge only |

```bash
# Enumerate all deliver runs (run-scoped + legacy slug-scoped awaiting adoption)
python3 scripts/wave_deliver.py . list

# Resolve resume cardinality (0 → halt resume:none; >1 nonterminal → halt resume:ambiguous)
python3 scripts/wave_deliver.py . resume-locate
python3 scripts/wave_deliver.py . resume-locate --run-id deliver-<uuid>

# Finalize after human merge to main (distinct from cleanup / planning-unit closure)
python3 scripts/wave.py finalize --run-id <runId>
```

**Resume cardinality:** with no `--run-id`, exactly one nonterminal run must exist. Legacy
slug-scoped state appears as `legacy-<slug>` with `requiresAdoption: true` until `wave_run_adopt.py`
migrates it into `.cursor/sw-deliver-runs/<runId>/`.

**Legacy adoption recovery:** when global plan/state was reset but slug-scoped files remain, adoption
replays a single global-plan read and writes run-scoped `plan.json` + `state.json`. Failed adoption
surfaces in `list` output — never silent fallback to repository-global plan paths.

**Finalize vs cleanup:** `finalize` (`run-finalize`) verifies the merge commit, writes the terminal receipt,
marks the run `immutable`, and releases target-lock resources. It does **not** close planning units, absorb
gaps, or delete worktrees — those are separate hygiene steps after merge detection.

**Phase-before-orch teardown:** `release_run_resources` (shared by deliver-loop and terminal closeout)
removes phase worktrees before the orchestrator worktree, keeps primary cwd when pruning orch, and
tolerates husk/parked trees — never tear down orch while phase worktrees still depend on the run.

**Run-state mirror + finalize checkpoint:** before terminal-ship / finalize, slug-scoped deliver state is
mirrored into `.cursor/sw-deliver-runs/<runId>/` when run-scoped state is missing (`ensure_run_scoped_state_mirrored`).
Finalize is write-ahead resumable via `finalize-checkpoint.json` (`release` → `projection` → `receipt` →
`immutable`). After squash-merge deletes the feature branch, host PR merge evidence still verifies; partial
finalize returns typed `finalize:partial` / `finalize:checkpoint-incomplete` with
`resumeCommand` (`python3 scripts/wave.py finalize --run-id <runId>`) — never silent success.

**Orch cwd adopt + exclusive run lease:** managed orchestrator worktrees auto-adopt a validated recorded
path (execution-time identity rebind); invalid/missing paths fail closed with typed cause + `resumeCommand`.
Mutating run-scoped state requires an exclusive durable `runId` lease under `.cursor/sw-deliver-run-locks/`
(generation fencing; stale reclaim bumps generation). See `core/commands/sw-deliver.md` absorb map and
[workflows — Deliver driver resilience](workflows.md#deliver-driver-resilience-decision-acknowledgements).

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
| Retro painful gap capture | `/sw-retro` → `planning_gap_capture.py retro-capture` (draft); `retro-confirm` / `retro-materialize` per item |

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

### Credential operations

Host, planning-store, and memory adapters resolve secrets through the credential broker — not from committed
config bodies. Operator commands:

| Operation | Command |
| --- | --- |
| Full repository diagnosis (surfaces + reference listing) | `python3 scripts/credentials-doctor.py --root .` |
| Remediation for a failure code | `python3 scripts/credentials-doctor.py remediate --scope local\|ci --code <code> --root .` |
| Guided credential migration | `python3 scripts/sw-configure.py credential plan` / `apply --confirm` |
| Legacy `tokenEnv` → `credentialRef` migration | `python3 scripts/sw-configure.py credential migrate --confirm` |
| CI env-backend declaration | `python3 scripts/sw-configure.py credential declare-ci --confirm` |
| Add selector entry | `python3 scripts/sw-configure.py credential selector-add …` (see [configuration](configuration.md#machine-local-selector-file)) |

**Doctor reference listing:** the top-level JSON report includes a `references` array — one object per
selector entry with `ref`, `backend`, `scopes` (`allowedRepos`, `allowedProjectIds`, `allowedEndpoints`),
`principal`, and `lastSuccessfulResolution`. Findings name `credentialRef` only — never secret values.

**Planning backend disable** (durable per-repo override — forces effective backend to `in-repo-public`):

```bash
python3 scripts/planning_backend_control.py disable --set-by <who> --reason "<why>" [--expires-at <ISO8601>]
python3 scripts/planning_backend_control.py enable
python3 scripts/planning_backend_control.py list
```

Record path: `$GIT_COMMON_DIR/shipwright/planning-backend-disable.json` (mode `0600`, user-owned, no
symlinks). `planning-doctor.py` surfaces an active disable as `backend-disable-record`. Mid-deliver backend
control changes fail closed — finish or abort the run first.

**Credential rotation (repository-safe):** rotate backend material without editing the code repo:

1. Leave committed `credentialRef` values and selector `ref` keys unchanged.
2. Replace secret material at the backend only:
   - **`environment`:** rotate the declared env var in your profile or CI secret store.
   - **`keystore`:** update the native Keychain / Credential Manager item for service
     `shipwright.credential/<ref>` (macOS/Windows workstations only).
   - **`github_cli`:** re-authenticate with GitHub CLI (`gh auth login`) under the isolated config dir.
   - **`git_credential`:** update the credential helper store for the scoped hostname.
3. Re-run `python3 scripts/credentials-doctor.py --root .` and confirm `lastSuccessfulResolution` updates
   for the rotated ref.
4. Optional audit: append a `rotation` event to the machine-local provenance journal (string metadata only —
   no secrets). See `.sw/layout.md` **Credential machine-local records**.

Never widen selector scope (`allowedRepos`, `allowedProjectIds`, `allowedEndpoints`) without pairing
approval.


## Entry points

| Command | When to use | Does not |
|---------|-------------|----------|
| [`/sw`](../../core/commands/sw.md) | Bare state-aware entry — reads worktree/planning state and proposes the one next action, with confirm | Implement, ship, or merge on its own; it hands off to the command it proposes |
| [`/sw-triage`](../../core/commands/sw-triage.md) | Classify Quick / Standard / Full before doc or impl | Draft docs or implement |
| [`/sw-init`](../../core/commands/sw-init.md) | First run in a target repo — guided scan → confirm → unresolved-only interview, providers, `doc.afterTasks`, memory store, doctor | Scaffold CI or migrate memories |
| [`/sw-worktree`](../../core/commands/sw-worktree.md) | Isolate work in a per-item worktree (required before impl on bare `main`) | Run phase loop or merge |
| [`/sw-start`](../../core/commands/sw-start.md) | Open a phase branch inside the active worktree; worktree guard runs before writes | Push or open PR |

## Consult and capture

Lightweight surfaces that sit alongside the pipeline without joining it — none of these freeze artifacts,
implement, or merge.

| Command | Role | Does not |
|---------|------|----------|
| [`/sw-ask`](../../core/commands/sw-ask.md) | Route a free-form question to the best-fit existing persona for a read-only answer | Write, review, freeze, or dispatch another command |
| [`/sw-become`](../../core/commands/sw-become.md) | Research and crystallize a new persona for later `/sw-ask` consults, confirm-before-write | Overwrite an existing persona; run the doc-review panel |
| [`/sw-note`](../../core/commands/sw-note.md) | One-line idea/task/note capture outside the planning store, with confirm-first graduation to a gap or brainstorm | Write to the planning store directly, or replace feedback gap-capture |
| [`/sw-guide`](../../core/commands/sw-guide.md) | Read-only explanation of workflow behavior plus config/state/planning-backend diagnosis | Mutate config, git, or the planning store |

### `/sw-note` — local notebook capture

Low-ceremony scratch that lives under `.cursor/sw-notebook/notebook.jsonl` — deliberately **outside**
`docs/planning/`, the issue-store, and `GAP-BACKLOG.md`, so jotting never touches freeze or currency
machinery.

| Shape | Meaning | Lifecycle |
| --- | --- | --- |
| `idea` | Rough idea not yet worth a brainstorm | Open until graduated or dismissed |
| `task` | Small actionable reminder | `open` → `done` via `/sw-note done <id>` |
| `note` | Plain fact/observation worth remembering | Open indefinitely; no done state |

**Input:** `/sw-note <text>` (auto-classified), or explicit `/sw-note task|idea|note <text>` with optional
`#tag` tokens. Text passes through `python3 scripts/sw_bootstrap.py memory-redact.py` before append. The notebook directory
is operator-local scratch — never committed; first write adds `.cursor/sw-notebook/` to `.gitignore` when
needed.

**Graduate (confirm-first):** `/sw-note graduate <id> --to gap|brainstorm` shows the item and target;
requires explicit `proceed` before any planning-store write. On confirm:

- `--to gap` → `python3 scripts/sw_bootstrap.py planning_gap_capture.py -- <repo> capture --signal-id notebook:<id> --title "<text>"`
- `--to brainstorm` → hand off to `/sw-brainstorm` with the note text as seed (brainstorm doc owned by `/sw-brainstorm`)

Bidirectional provenance: notebook item records `graduatedTo` / `graduatedAt`; target artifact carries a
back-pointer (`notebookRef` in gap body or brainstorm Key Decisions). Graduated and done items are retained —
never deleted.

**Session index (opt-in):** `notebook.sessionIndex: true` injects a distilled, redacted index of **open**
items at session start; redaction failure skips injection entirely (never injects raw text). See
[configuration — Notebook session index](configuration.md#notebook-session-index).

## Deprecated command aliases (closed rename table)

These renames are the only ones in scope; each deprecated name delegates to its replacement with identical
behavior for one release before removal.

| Deprecated | Use instead | Alias window |
|------------|-------------|--------------|
| `/sw-setup` | `/sw-init` | One release |
| `/sw-compound` | `/sw-retrospective` | One release |
| `/sw-compound-ship` | `/sw-retrospective` | One release |

See [decision tree](decision-tree.md) for retirement timing and routing.

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
| [`/sw-watch-ci`](../../core/commands/sw-watch-ci.md) | Poll PR checks via `check-gate.py`; **halt** (not poll) on unavailable Checks capability |
| [`/sw-stabilize`](../../core/commands/sw-stabilize.md) | Clear CI + review blockers |
| [`/sw-ready`](../../core/commands/sw-ready.md) | Terminal readiness report; echoes `review: off` or `review: not configured` from gate JSON |

**Unavailable Checks capability (`host-auth-required`):** when `check-gate.py` reports `blocked` with `reasonCode: host-auth-required`, the host token cannot read CI check status. This is a **remediation halt** — emit guidance from `core/providers/host/remediation-checks.md` and stop. Do not poll CI, attempt stabilization, or treat the state as retryable yellow/pending.

**Gap-check write (required):** before `merge-ready-green`, the ship chain must persist a binding
`gap-check.status.json` via `python3 scripts/gap-check-gate.py write pass --phase-slug <slug>`.
`/sw-ship` phase-mode and `ship-phase-status.py` refuse `merge-ready-green` when gap-check is
missing or `halt`. Phase-mode may **auto-repair** `gap-check-missing` when authoritative
evaluation exists for the exact phase HEAD — forged passes without `evaluationProvenance` are refused.
Status writes route through `status_integrity.write_status_atomic` (provenance stamped, forgery
fail-closed). See `core/commands/sw-ship.md` **Phase-ship hygiene floors**.

**Closeout hardening:** deliver resume, adopt, and post-merge closure surfaces are documented in
`core/commands/sw-deliver.md` **Closeout hardening** (hygiene auto-repair, prefer-run-scoped adopt,
numeric absorb exactly-one). Absorb acceptance map: `core/sw-reference/layout.md` **Closeout surfaces**.

**Worktree invariant:** never write implementation files on bare `main` — use a worktree + phase
branch.

## Planning refusal ledger (operator CLI)

Refused substantive writes are recorded operator-locally under `.cursor/sw-refusal-ledger` (or
`planning.refusalLedger.path`). Inspect and purge via the refusal ledger CLI — **reconciling a refused write
after inspection is a human decision**; export surfaces operator-runnable record commands only and does not
replay refused writes.

```bash
python3 scripts/sw_bootstrap.py planning_refusal_ledger_cli.py -- list
python3 scripts/sw_bootstrap.py planning_refusal_ledger_cli.py -- show <entryId>
python3 scripts/sw_bootstrap.py planning_refusal_ledger_cli.py -- export [--out path]
python3 scripts/sw_bootstrap.py planning_refusal_ledger_cli.py -- purge --entry-id <id>   # or --all (journaled)
```

`/sw-cleanup` dry-run may enumerate `refusal-ledger-entry` purge candidates; confirm applies the same purge
semantics. Default ledger layout: `core/sw-reference/layout.md` (Planning backend and authority).

Refusal-ledger writes also feed the projection **outbox** (`planning_projection_ledger.py`) so
pending projection destinations drain on subsequent authority mutations rather than relying on a single
in-process attempt.

## Memory and compounding

| Command | Role |
|---------|------|
| [`/sw-memory-sync`](../../core/commands/sw-memory-sync.md) | Distill transcript deltas to durable memory |
| [`/sw-memory-audit`](../../core/commands/sw-memory-audit.md) | Read-only memory hygiene audit |
| [`/sw-compound`](../../core/commands/sw-compound.md) | Distill retro into memories |
| [`/sw-retro`](../../core/commands/sw-retro.md) | Post-ship retrospective (report-only) |
| [`/sw-retrospective`](../../core/commands/sw-retrospective.md) | Consolidated retro → compound → memory-sync chain |

### Retro gap capture — per-item digest-bound confirm

When `retrospective.gapCapture.enabled` is true, painful retro items may enter a supervised gap inbox.
**Human confirmation is per item**, bound to the redacted draft content digest — a batch UI may list
multiple drafts, but each **materialize** call requires its own matching `--digest` ack for that
`signalId`. Confirm and materialize are separate steps; unattended dispatch refuses silent mint.

```bash
python3 scripts/sw_bootstrap.py planning_gap_capture.py -- retro-capture --retro-json .cursor/sw-retro-output.json
python3 scripts/sw_bootstrap.py planning_gap_capture.py -- retro-confirm --signal-id <signalId> --digest <digest>
python3 scripts/sw_bootstrap.py planning_gap_capture.py -- retro-materialize --signal-id <signalId> --digest <digest>
```

Digest mismatch halts with `retro-gap-digest-mismatch`; materialize without prior confirm halts with
`retro-gap-ack-required`. See [`/sw-retrospective`](../../core/commands/sw-retrospective.md) and
[`configuration.md`](configuration.md#retrospective-gap-capture).

## Quick reference — commands you invoke directly

| Command | One-line use case |
|---------|-------------------|
| `/sw` | Not sure what's next? Read state and propose it |
| `/sw-init` | First run or doctor in a target repo |
| `/sw-triage` | How much ceremony does this work need? |
| `/sw-doc` | Full documentation pipeline |
| `/sw-deliver run` | **Primary** — implement frozen tasks to one terminal merge gate |
| `/sw-ship` | Manual single-phase verify → PR → CI loop (Quick tier / debug) |
| `/sw-debug` | Diagnose production or CI failure |
| `/sw-feedback` | Intake and route external signals |
| `/sw-worktree` | Isolate work in a git worktree (manual path) |
| `/sw-start` | Start a phase branch (manual path) |
| `/sw-execute` | Implement one task slice (manual path) |
| `/sw-status` | Reconcile PRD status; live WorkflowGraph progress + node explain |
| `/sw-memory-sync` | Distill session into durable memory |
| `/sw-memory-audit` | Audit memory hygiene (read-only) |
| `/sw-note` | Capture idea/task/note outside the planning store; graduate to gap or brainstorm on confirm |
| `/sw-compound` | Turn retro into memories |
| `/sw-retro` | Post-ship retrospective report |

> 40+ commands exist today. This table lists orchestrators and common atomics only. Grep
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

