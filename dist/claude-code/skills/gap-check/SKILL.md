---
name: sw-gap-check
description: Compare phase plan (spec union + task checklist) against git diff; bounded closers for in-scope gaps. Default-on in /sw-ship.
---

# gap-check

Catches planned vs actual before commit.


**Model tier:** mid — resolve via `python3 scripts/resolve-model-tier.py --skill gap-check`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Inputs

- **Plan:** task checklist for `phaseSlug` in `tasksDir` + spec union (`scripts/spec-union.py <prd>`).
- **Backlog:** open rows from `python3 scripts/feedback-backlog.py list --open-only` (`skills/feedback-closure/SKILL.md`) — map against diff when PR-linked.
- **Native panel advisory (R75):** when present, read `$runDir/sw-local-review-run-report.json` (resolved via
  `python3 scripts/sw-tmp.py resolve` or `shipwright-state` `runDir`) and consume `scope_fidelity_advisory` **advisory
  only** — defer / stub / omission hints from phase-1 `scope-fidelity`. This input MUST NOT alter gap-check's
  binding verdict; gap-check remains the sole requirements-completeness authority (R12/R50).
- **Actual:** diff against per-worktree `parentBranch`:

```bash
PARENT=$(python3 scripts/shipwright-state.py read | Python json -r .parentBranch)
git diff --stat "$PARENT"...HEAD
git diff "$PARENT"...HEAD
```

## Procedure

1. Load config + plan + diff + open backlog items.
2. Read-only subagent maps each checklist item → `done` | `partial` | `missing` + unplanned hunks.
3. Gap report table.
4. In-scope gaps → bounded closer subagents (one gap each); re-verify.
5. Ambiguous/out-of-scope → escalate (toward feedback workstream `005`); never absorb silently.
6. Re-map once; escalate residuals.


## Deliver binding (PRD 055 R13, R25)

On the **deliver merge path** (`merge-enqueue` / `merge_ready_in_flight_phases`), gap-check is **mechanical**
via `scripts/gap-check-gate.py`:

- Emits/consumes `.cursor/sw-deliver-runs/{phaseSlug}/gap-check.status.json` with binding `pass|halt`.
- `ship-phase-status.py` refuses `merge-ready-green` when the durable verdict is `halt`.
- **`--fast` is prohibited** for deliver merge decisions (`--deliver-merge --fast` fails closed with
  `deliver-gap-check-no-fast-skip`). Standalone `/sw-ship` may still use `--fast` per ship skill contract.

## Modes

- **Default (`/sw-ship`):** after execute; `--fast` skips.
- **Standalone (`/sw-gaps`):** same; `--report-only` never mutates.

## Guardrails

- Mapping before closers.
- Closers bounded — no scope expansion.
- Spec union is the requirement source, not bare parent PRD.
