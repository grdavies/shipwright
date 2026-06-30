---
description: Consolidated post-delivery retrospective (retro → compound write → memory-sync → status). Supports --pre-merge/--post-merge phase dispatch; does not merge or auto-promote rules.
alwaysApply: false
---

# `/sw-retrospective`

Single user-facing entry for post-delivery compounding. Delegates to atomic `sw-` commands and the internal
compound write step; does not reimplement their procedures.

## Modes

| Mode | When | Preconditions |
| --- | --- | --- |
| **Pre-merge (in-loop)** | `/sw-deliver` after all phases green, before human merge gate | Feature branch merge-ready; invoke with `--pre-merge` |
| **Post-merge (standalone)** | After human merge to `main` | PR merged by a human — this command does **not** merge |

**Auto-detect (no flag):** resolve phase from deliver run-state + merge status:

```bash
bash scripts/wave.sh retrospective detect-phase
```

Returns `pre-merge` when the target feature branch is merge-ready but not yet on `main`; `post-merge` when
merge is detected or no deliver context applies.

Driver env (pre-merge): `bash scripts/wave.sh retrospective premerge-env`

## Chain

```
sw-retro → compound-write (internal) → [sw-memory-sync] → sw-status reconcile → sw-status append-log
```

- The **compound write** step loads `skills/compound/SKILL.md` inline — not `/sw-compound` (internal-only, R3).
- `sw-memory-sync` runs by default; omit with `--skip-memory-sync`.
- Atomic `/sw-retro`, `/sw-memory-sync`, and `/sw-status` remain independently runnable.

## Subsumed steps

Internal: compound write (`skills/compound/SKILL.md`). Atomic: `/sw-retro`, `/sw-memory-sync`, `/sw-status`.

## Flags

- `--pre-merge` — in-loop mode (R6): commit file outputs on the feature branch; record
  `completed-pending-merge` via `bash scripts/wave.sh retrospective record-premerge --prd <n> --phase <name>`.
- `--post-merge` — standalone reconcile after merge detection.
- `--from <step>` — resume mid-chain (`retro`, `compound`, `memory-sync`, `status`).
- `--skip-memory-sync` — skip transcript distillation.
- `--dry-run` — print the chain; no mutations.

## Autonomy (`compound.autonomy`)

Read mode: `bash scripts/wave.sh retrospective autonomy` (config key `compound.autonomy`, default `supervised`).

| Mode | Behavior |
| --- | --- |
| **`supervised`** (default) | Preserve today's gates: retro/compound approval prompts; pre-merge waits for human merge acknowledgment before INDEX → `complete`. |
| **`auto`** | Run the pre-merge chain hands-off when the terminal PR is green; commit learnings/status on the feature branch; treat merge as external; post-merge reconcile on merge detection without re-prompting. |

**Safety gates (all modes, R7/R8):** memory writes remain fail-closed via `memory-preflight` + redaction; rule-class
promotion stays human-gated (`/sw-memory-audit` allowlist). Autonomy never bypasses these.

**Completion semantics (R6/R11):** pre-merge always records `completed-pending-merge`; INDEX → `complete` only on
real merge detection (`reconcile --require-merge` pre-merge; merge detection post-merge) — even under `auto`.

## State (per-worktree)

Via `scripts/shipwright-state.py`: record `lastCommand: sw-retrospective` and the completed sub-step when
resuming with `--from`.

Run state (pre-merge): `.cursor/sw-deliver-state.json` gains `compoundShip.premergeDone` and
`completion.status: completed-pending-merge` after `record-premerge` (R6).

## Procedure

### Phase resolution

1. If `--pre-merge` → pre-merge mode.
2. If `--post-merge` → post-merge mode.
3. Else run `bash scripts/wave.sh retrospective detect-phase` and use the returned `phase`.

### Pre-merge (`--pre-merge` or auto-detected)

1. Confirm feature branch is merge-ready (all phases `green-merged` on `<type>/<slug>`).
2. **`/sw-retro`** — learning candidates (report-only).
3. **Compound write** — load `skills/compound/SKILL.md`; route writes through `memory-preflight` +
   `scripts/memory-redact.py` (internal step — not `/sw-compound`).
4. **`/sw-memory-sync`** — unless `--skip-memory-sync`; provider unreachable → **fail-closed** (R7).
5. **`/sw-status`** — `python3 scripts/reconcile-status.py reconcile --require-merge` (INDEX `complete` only
   after merge detection, R11); `append-log` for COMPLETION-LOG.
6. **Commit file outputs only** on the feature branch: COMPLETION-LOG, INDEX, CHANGELOG/version,
   learnings notes. **Never commit** memory/provider artifacts (R7).
7. `bash scripts/wave.sh retrospective record-premerge --prd <n> --phase <name> [--notes "..."]`
8. Hand off to terminal merge gate (`/sw-deliver` → `terminal-ship`).

### Post-merge (`--post-merge` or auto-detected)

1. Confirm post-merge context (merged PR or explicit user acknowledgment).
2. Run the same chain; `reconcile` without `--require-merge` may mark INDEX `complete` when appropriate.
3. Report memories written/updated and handoff to next phase.

## Stop conditions

- User halts at retro or compound approval gates when `compound.autonomy: supervised` (default).
- Under `compound.autonomy: auto`, skip approval / "did you merge?" prompts only — not memory or rule-class gates.
- Memory provider unreachable (fail-closed per R7).
- `reconcile-status.py` errors on frozen PRD guard.

**Communication intensity:** full

**Model tier:** inherit — resolve delegated atomics via `python3 scripts/resolve-model-tier.py --command <child-slug>`; do not dispatch on bare `--command sw-retrospective`.

## Guardrails

- **Never merge** or force-push.
- **Delegates** — do not bypass atomic command guardrails.
- **Never auto-promote rule-class memories** (R8) — rule writes require user confirmation +
  `/sw-memory-audit` allowlist; pre-merge `record-premerge` stamps `ruleClassPromotion: human-gated`.
- Redact before any memory persist (`scripts/memory-redact.py`).
- Frozen PRDs never modified by status reconcile (except permitted checkbox progress on task files).
- Pre-merge completion is **`completed-pending-merge`** until merge detection — a declined human merge must
  not report `complete` or `merged` (R11).

## Handoff

- **Pre-merge:** `/sw-deliver` terminal PR prepare/gate; human merges; loop suggests `/sw-cleanup` when
  merge detected.
- **Post-merge:** stack next phase via workflow sequencing.

## Post-merge INDEX safety (A1)

Post-merge compounding uses `completion finalize-if-merged` only. On failure, resume with the printed `resumeCommand` — do **not** fall back to bare `reconcile-status.py reconcile` on `main`. Single-unit bookkeeping belongs on a docs branch.
