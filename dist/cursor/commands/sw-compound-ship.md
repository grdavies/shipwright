---
description: Compounding orchestrator (retro → compound → optional memory-sync → status). Pre-merge in-loop via --pre-merge; post-merge standalone. Never merges or auto-promotes rules.
alwaysApply: false
---

# `/sw-compound-ship`

Orchestrates the compounding chain. Delegates to atomic `sw-` commands; does not reimplement their
procedures.

## Modes

| Mode | When | Preconditions |
| --- | --- | --- |
| **Pre-merge (in-loop)** | `/sw-deliver` after all phases green, before human merge gate | Feature branch merge-ready; invoke with `--pre-merge` |
| **Post-merge (standalone)** | After human merge to `main` | PR merged by a human — this command does **not** merge |

Driver env (pre-merge): `bash scripts/wave.sh compound-ship premerge-env`

## Chain

```
sw-retro → sw-compound → [sw-memory-sync] → sw-status reconcile → sw-status append-log
```

- `sw-memory-sync` runs by default; omit with `--skip-memory-sync`.
- Atomic commands remain independently runnable.

## Subsumed atomic commands

`/sw-retro`, `/sw-compound`, `/sw-memory-sync`, `/sw-status`

## Flags

- `--pre-merge` — in-loop mode (R17–R20): commit file outputs on the feature branch; record
  `completed-pending-merge` via `bash scripts/wave.sh compound-ship record-premerge --prd <n> --phase <name>`.
- `--from <step>` — resume mid-chain (`retro`, `compound`, `memory-sync`, `status`).
- `--skip-memory-sync` — skip transcript distillation.
- `--dry-run` — print the chain; no mutations.

## State (per-worktree)

Via `scripts/shipwright-state.sh`: record `lastCommand: sw-compound-ship` and the completed sub-step when
resuming with `--from`.

Run state (pre-merge): `.cursor/sw-deliver-state.json` gains `compoundShip.premergeDone` and
`completion.status: completed-pending-merge` after `record-premerge` (R53).

## Procedure

### Pre-merge (`--pre-merge`)

1. Confirm feature branch is merge-ready (all phases `green-merged` on `<type>/<slug>`).
2. **`/sw-retro`** — learning candidates (report-only).
3. **`/sw-compound`** — route writes through `memory-preflight` + `scripts/memory-redact.sh`.
4. **`/sw-memory-sync`** — unless `--skip-memory-sync`; provider unreachable → **fail-closed** (R19).
5. **`/sw-status`** — `bash scripts/reconcile-status.sh reconcile --require-merge` (INDEX `complete` only
   after merge detection, R53); `append-log` for COMPLETION-LOG (R20).
6. **Commit file outputs only** on the feature branch: COMPLETION-LOG, INDEX, CHANGELOG/version,
   learnings notes (R18). **Never commit** memory/provider artifacts (R19).
7. `bash scripts/wave.sh compound-ship record-premerge --prd <n> --phase <name> [--notes "..."]`
8. Hand off to terminal merge gate (`/sw-deliver` → `terminal-ship`).

### Post-merge (default)

1. Confirm post-merge context (merged PR or explicit user acknowledgment).
2. Run the same chain; `reconcile` without `--require-merge` may mark INDEX `complete` when appropriate.
3. Report memories written/updated and handoff to next phase.

## Stop conditions

- User halts at retro or compound approval gates.
- Memory provider unreachable (fail-closed per R19/R44).
- `reconcile-status.sh` errors on frozen PRD guard.

**Communication intensity:** full

**Model tier:** inherit — resolve delegated atomics via `bash scripts/resolve-model-tier.sh --command <child-slug>`; do not dispatch on bare `--command sw-compound-ship`.

## Guardrails

- **Never merge** or force-push.
- **Delegates** — do not bypass atomic command guardrails.
- **Never auto-promote rule-class memories** (R21/R42) — rule writes require user confirmation +
  `/sw-memory-audit` allowlist; pre-merge `record-premerge` stamps `ruleClassPromotion: human-gated`.
- Redact before any memory persist (`scripts/memory-redact.sh`).
- Frozen PRDs never modified by status reconcile (except permitted checkbox progress on task files).
- Pre-merge completion is **`completed-pending-merge`** until merge detection — a declined human merge must
  not report `complete` or `merged` (R53).

## Handoff

- **Pre-merge:** `/sw-deliver` terminal PR prepare/gate; human merges; loop suggests `/sw-cleanup` when
  merge detected (R31).
- **Post-merge:** stack next phase via workflow sequencing.
