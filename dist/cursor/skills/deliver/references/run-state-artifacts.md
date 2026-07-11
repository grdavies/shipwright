# Run State Artifacts

### Provision-time materialization (PRD 034 R7/R8/R20)

Private and memory planning-unit bodies may live outside the tracked tree (`planning.store` backends). During
phase provision — after worktree add and before preflight/spec-seed reads — `wave_lifecycle.py` invokes
`scripts/planning_materialize.py` to copy required spec bodies into the ignored prefix
`.cursor/planning-materialized/`. A post-materialize `secret-scan file` runs; paths register in deliver
run-state for orphan sweep; teardown deletes the tree. Pre-commit, pre-push, and CI diff scans reject any
staged path under the prefix (`scripts/materialized-prefix-scan.py`) — the **commit-boundary barrier** holds
even under `git add -f`. Store backend + revision are pinned at provision; mid-run `planning.store` config
changes halt with remediation. CI/host never materializes.

Fixture suite: `python3 scripts/test/run_planning_materialize_fixtures.py` (registered as
`planning-materialize-fixtures` in the PR test-plan manifest).
### Unit-id derivation (gap-051 / PRD 058 R1–R2)

Frozen task lists participate in **two distinct unit-id derivations** — do not conflate them:

| Function | Module | Input | Derived id | Consumer |
| --- | --- | --- | --- | --- |
| `unit_id_from_task_list` | `scripts/planning_deliver_gate.py` | Task-list **parent directory** under `docs/prds/<n>-<slug>/` | `<n>-prd-<slug>` (legacy `prd-<slug>` dirs unchanged) | Planning-graph dependency gate / scheduler |
| `unit_id_from_task_list_rel` | `scripts/planning_materialize.py` | Task-list **filename stem** | `tasks-<n>-<slug>` | Issue-store materialize / run-entry pin |

Example path `docs/prds/058-dispatch-loop-hardening/tasks-058-dispatch-loop-hardening.md`:
- graph unit id → `058-prd-dispatch-loop-hardening`
- materialize/store unit id → `tasks-058-dispatch-loop-hardening`

`dependency_gate` / `run_start_revalidate` fail closed when the derived graph unit is missing and the path is
outside the canonical `docs/prds/<n>-<slug>/` layout; pre-freeze canonical task lists are allowlisted (R5).

See also `core/commands/sw-deliver.md` **Unit-id derivation**.

**Per-branch scoping (PRD 013 R6–R11):** `<slug>` derives from the target feature branch
(`feat/<slug>` → `sw-deliver-state.<slug>.json`). Orthogonal branches run concurrently with
independent state/lock files; `assert_run_identity` and lock refusal apply **within** a scope only.
Legacy repo-wide state is adopted to the scoped path on first read (breadcrumb left at the legacy path).

**Single canonical write path (R28):** all readers and writers (`wave_state.py`, `wave_compound.py`
`record-premerge`, `cleanup_lib.resolve_deliver_state`) resolve the scoped path at the git toplevel —
never a duplicate copy under an orchestrator worktree `.cursor/`.

**Freeze-time commit (PRD 013 R1–R5):** `/sw-freeze` invokes `check-frozen.py freeze-commit` → shared
`wave_spec_seed.py` helper (same as `/sw-doc` afterTasks). Commits docs-only onto `<type>/<slug>`;
never `main`; verdict-independent (commit failure warns; stamp still completes).

### Run-state schema (scoped `.cursor/sw-deliver-state.<slug>.json`)

Initialized from the phase-mode plan via `scripts/wave.py state init --plan .cursor/sw-deliver-plan.json`:

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
written by `scripts/wave.py deliver-loop` on every transition. A fresh agent resumes from this state alone.

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
scripts/wave.py deliver-loop --dry-run
scripts/wave.py state init --plan .cursor/sw-deliver-plan.json
scripts/wave.py state phase --id 1 --status in-flight
scripts/wave.py state phase --slug rename-deliver --status green-merged
scripts/wave.py state get
scripts/wave.py state terminal --verdict complete
```

Per-phase `/sw-ship` outcomes live in `sw-deliver-runs/<phase>/status.json` (`merge-ready-green` |
`blocked`); `scripts/ship-phase-status.py` syncs `blocked` into run-state when present.

### Orchestrator lock + merge journal (R51)

```bash
scripts/wave.py lock acquire --target feat/<slug> --nonblock   # exit 20 if held
scripts/wave.py lock release
scripts/wave.py journal begin --phase <phase-slug> [--head <sha>]
scripts/wave.py journal complete --phase <phase-slug>
```

- **Lock:** atomic create on `.cursor/sw-deliver-<slug>.lock`; a lock for branch A does not block
  branch B; a second live run on the **same** branch refuses (`exit 20`) until `lock release`.
- **Merge journal:** open entry before phase → `<type>/<slug>` merge; cleared after push + state commit.
  Resume detects interrupted merge via `journal status`.

### Progress log (R54)

Append-only JSON lines at `.cursor/sw-deliver-runs/run.log` on run init, phase transitions, lock
acquire/release, merge journal events, and terminal halt.

```bash
scripts/wave.py log tail --lines 20
```

Each line: `{ "event": "phase-transition", "phaseId": "1", "from": "pending", "to": "in-flight", "at": "..." }`.

