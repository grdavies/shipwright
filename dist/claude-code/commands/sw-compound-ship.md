---
description: Post-merge compounding orchestrator (retro → compound → optional memory-sync → status). Fires after human merge; never merges or auto-promotes rules.
alwaysApply: false
---

# `/sw-compound-ship`

Post-merge orchestrator. Runs the compounding chain after the human merge gate. Delegates to atomic
`sw-` commands; does not reimplement their procedures.

## Preconditions

- PR merged by a human — this command does **not** merge.
- Invoke from the worktree that shipped the phase (or after updating local `main` from remote).

## Chain

```
sw-retro → sw-compound → [sw-memory-sync] → sw-status reconcile → sw-status append-log
```

- `sw-memory-sync` runs by default; omit with `--skip-memory-sync`.
- Atomic commands remain independently runnable.

## Subsumed atomic commands

`/sw-retro`, `/sw-compound`, `/sw-memory-sync`, `/sw-status`

## Flags

- `--from <step>` — resume mid-chain (`retro`, `compound`, `memory-sync`, `status`).
- `--skip-memory-sync` — skip transcript distillation.
- `--dry-run` — print the chain; no mutations.

## State (per-worktree)

Via `scripts/shipwright-state.sh`: record `lastCommand: sw-compound-ship` and the completed sub-step when
resuming with `--from`.

## Procedure

1. Confirm post-merge context (merged PR or explicit user acknowledgment).
2. **`/sw-retro`** — `Load skills/retro/SKILL.md`; produce learning candidates (report-only).
3. **`/sw-compound`** — `Load skills/compound/SKILL.md`; route writes through `memory-preflight` +
   `scripts/memory-redact.sh`.
4. **`/sw-memory-sync`** — unless `--skip-memory-sync`; distill new agent-transcript deltas.
5. **`/sw-status`** — `bash scripts/reconcile-status.sh reconcile`, then `append-log` for the shipped
   phase. Include GAP-BACKLOG summary (read-only).
6. Report: memories written/updated, INDEX/COMPLETION-LOG paths, and handoff to the next phase.

## Stop conditions

- User halts at retro or compound approval gates.
- Memory provider unreachable (fail-closed per R44).
- `reconcile-status.sh` errors on frozen PRD guard.

## Guardrails

- **Never merge** or force-push — runs after merge, not instead of it.
- **Delegates** — do not bypass atomic command guardrails.
- **Never auto-promote rule-class memories** (R42) — rule writes require user confirmation +
  `/sw-memory-audit` allowlist.
- Redact before any memory persist (`scripts/memory-redact.sh`).
- Frozen PRDs never modified by status reconcile.

## Handoff

Stack the next phase: update parent branch, `/sw-start` for the next slice (see workflow sequencing).
