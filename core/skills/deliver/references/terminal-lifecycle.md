# Terminal Lifecycle

## Serialized merge queue (R17/R19/R50/R52)

After `merge-ready-green` status is collected, phases enter a **single-flight** merge queue. Only one
phase → `<type>/<slug>` merge runs at a time; journal + lock prevent double-merge.

```bash
# 1. Collect durable /sw-ship outcome (R38) — never read sw-tmp run dirs
scripts/wave.py status collect --phase-slug <phase-slug>

# 2. Enqueue when status is merge-ready-green
scripts/wave.py merge enqueue --phase-slug <phase-slug>

# 3. Review barrier + live gate before merge (R17/R52) — exit 10 while yellow/pending review
scripts/wave.py merge gate-check --pr <n>

# 4. Process next queued phase (true merge commit, --no-ff)
scripts/wave.py merge run-next --orchestrator-worktree .sw-worktrees/<slug>-orchestrator

# Resume predicate (R50): phase tip is ancestor of target tip after merge
scripts/wave.py merge ancestry-check --phase-branch feat/<slug>-phase-<phase> --target feat/<slug>
```

- **Merge method:** true `git merge --no-ff` only (no squash/rebase) so ancestry reconciliation holds.
- **Review barrier:** `merge gate-check` / `merge run-next` refuse until `check-gate.py` is **green** and
  `coderabbitLanded` is not `false` (pending async review is non-green for auto-merge).
- **Journal:** `merge run-next` opens `mergeJournal` before merge and clears on success (coordinates with
  `wave.py journal` helpers).
- **No-PR path:** when a phase has no open PR, `merge run-next` uses local-evidence from durable
  `status.json` (merge-ready-green + head SHA binding) plus post-merge incremental verify; remote
  `check-gate.py` authority applies at the terminal PR only.
- **Push chokepoint:** workflow pushes use `scripts/git-push.py` → `scripts/secret-scan.py` before
  `git push` (including `sw-pr` and stabilize re-pushes).

## Terminal report (R24/R55/R57)

When all phases are `green-merged`:

```bash
scripts/wave.py report terminal
```

Emits per-phase PR links (`mergedPhases`), Conventional Commit types from `release-please-config.json`,
and the whole-feature gate line: `ready to merge — your call` for `<type>/<slug> → main`.

## Release bookkeeping (R58–R60)

After each green phase merge into `<type>/<slug>`, the orchestrator (single locked merge step only) updates
`CHANGELOG.md` and `version.txt` in the orchestrator worktree:

```bash
scripts/wave.py bookkeeping record --phase-slug <slug> --message "..." --type feat \
  --merge-commit <sha> --commit
scripts/wave.py bookkeeping revert --phase-slug <slug> --commit   # after git revert of phase merge
scripts/wave.py bookkeeping projected --types feat,fix
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
`in-progress` | `complete`) and committing the ledger files onto `<type>/<slug>`.

**Absorbed-gap resolution on `complete` (PRD 048 R1):** when `reconcile-status.py set-index-status --status complete`
writes a PRD row, `reconcile_lib.set_index_status()` runs `gap_backlog.resolve_for_prd()` in-process immediately
after the INDEX write — flipping matching `scheduled`/`open` GAP-BACKLOG rows to `resolved` idempotently. This
post-write hook is the primary flip path; it is **distinct** from PRD 046 A2's out-of-scope `finalize-completion`
→ `living-docs reconcile --commit` call site (derived-status region vs. structural `set-index-status` write).
`living-docs reconcile` may still run on `finalize-completion` as a redundant safety net but does not replace the
in-process hook. On flip failure after a successful INDEX write, `set-index-status` returns `verdict: partial`
(exit 21) for operator retry — see `skills/living-status/SKILL.md`.

Before the terminal PR gate, `terminal pr prepare` appends an idempotent `COMPLETION-LOG` row
(`living-docs append-terminal --commit`) and runs `docs-currency` — a hard-block on drift in the current
run's INDEX row, completion-log entry, and absorbed gaps (`open` and `scheduled` rows for the absorbing PRD;
R50/R3; parity with task-currency R15).

```bash
scripts/wave.py living-docs reconcile --commit
scripts/wave.py living-docs append-terminal --commit
scripts/wave.py docs-currency
python3 scripts/reconcile-status.py set-index-status --prd <NNN> --status in-progress
python3 scripts/reconcile-status.py set-index-status --prd <NNN> --status complete   # auto-flips absorbed gaps
python3 scripts/reconcile-status.py append-log-idempotent --prd <NNN> --phase all --pr <N> --sha <sha>
python3 scripts/living-status-gap-resolve.py --absorbing-prd <NNN> [--scope-note <text>]  # manual retry only
```

See `skills/living-status/SKILL.md` for the canonical INDEX status enum and reconcile primitives.

**Deliver-chain parity matrix (PRD 057 R6):** the published command×artifact×backend audit for
planning-store emission parity lives at `core/sw-reference/planning-deliver-parity-matrix.md`.
Under issue-store `separate-project`, pollution/currency guards skip tracked local derived writes
(`GAP-BACKLOG.md`, `INDEX.md`, `INDEX-archive.md`, `SUPERSEDED.md`); the matrix names each guarded
command surface and the CI fixture (`scripts/test/fixtures/planning-deliver-parity/full_matrix.py`)
that asserts no file-store-only write path runs when the effective backend is issue-store authoritative.

## Incremental verify + failure routing (R25–R27, R39, R45–R46)

After each phase merge into `<type>/<slug>`, `merge run-next` runs configured `verify.*` on the orchestrator
worktree head (R39). Flaky failures get one re-run before blocking (R27).

```bash
scripts/wave.py verify run --orchestrator-worktree .sw-worktrees/<slug>-orchestrator
scripts/wave.py verify run-after-merge --phase-slug <slug>   # revert on fail (R45)
scripts/wave.py blast-radius apply --phase-slug <slug>       # block transitive dependents (R25)
scripts/wave.py report blockers                              # consolidated halt report (R26)
scripts/wave.py stabilize route --phase-slug <slug>          # → /sw-stabilize recommendation (R27)
scripts/wave.py revert phase --phase-slug <slug>             # git revert + bookkeeping + blast-radius
scripts/wave.py terminal deny --scope whole-feature|per-phase [--phase-slug <slug>]
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
scripts/wave.py resume reconcile                    # remote <type>/<slug> tip is ground truth (R29/R50)
scripts/wave.py terminal pr prepare                 # open/update single <type>/<slug> → main PR (R22)
scripts/wave.py terminal pr gate                    # check-gate.py on terminal PR head (R23/R24)
scripts/wave.py terminal pr status
scripts/wave.py report terminal                     # /sw-ready form when gate green
scripts/wave.py ack check|complete|status           # optional cadence (deliver.phaseAckCadence, R56)
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
scripts/wave.py terminal autonomy                      # read knob + mode
scripts/wave.py terminal retro run [--dry-run]         # retrospective before PR (R20/R21)
scripts/wave.py terminal ship run [--dry-run]          # PR → push → gate watch (R22/R23)
python3 scripts/cleanup_lib.py <root> --autonomous     # zero-interaction cleanup when safe (R25/R26)
```

- **`auto`:** retrospective + terminal ship run hands-off; merge to `main` stays human-gated (R23).
- **`supervised`:** preserves today's halts (`exit 11` supervised-checkpoint).
- Cleanup `auto` applies only the dry-run `wouldRemove` set when merge is deterministic, no in-flight
  scoped run, and not current/default branch; `indeterminate` → human gate.

## Base-branch preflight and spec visibility (R49, R61, R62)

Before phase dispatch, phase-mode `preflight` / `plan` runs **base-branch preflight** (R49):

```bash
scripts/wave.py preflight --task-list docs/prds/<n>-<slug>/tasks-....md
scripts/wave.py preflight-base --target feat/<slug>   # atomic check
```

- Verifies `.github/workflows` `pull_request` triggers cover `<type>/**` bases (not main-only).
- When `review.provider` is configured, requires repo review config so phase PRs can land reviews (R52).
- Fails closed with remediation hints — never silent `checkCount==0` timeout-blocked degradation.

**Spec in worktrees (R61):** `docs/prds/` is git-tracked (`docs/*` ignored, `!docs/prds/**` un-ignored).
Frozen task lists and PRDs must resolve inside the active worktree (prefer repo-relative paths;
absolute paths under the worktree root are allowed) — never paths into another checkout.

**Post-run learnings (R62):**

```bash
scripts/wave.py memory learnings distill
scripts/wave.py memory learnings prepare --out .cursor/sw-deliver-learnings.md
# then memory-preflight write (category: learning) with redacted payload only
```

Distills contention, blast-radius, revert, and blocked-phase patterns from plan + run log — never raw
transcripts or sub-agent logs. Always pipe through `scripts/memory-redact.py` before persist.
