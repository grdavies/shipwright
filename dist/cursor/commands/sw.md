---
description: Read per-worktree Shipwright state and the planning store, then propose the single next action with confirmation. Does not itself implement, ship, merge, or replace the orchestrator each proposed action dispatches to.
alwaysApply: false
---

# `/sw`

The bare, state-aware entry point. `/sw` with no arguments is **not a static menu** — it reads durable state,
computes the one action that actually advances the repo right now, and asks you to confirm before dispatching
it. Every other `sw-` command remains independently invokable; `/sw` is a convenience router on top, never a
replacement.

## Scope

- Input: none (bare `/sw`), or a free-form hint (`/sw continue`, `/sw what's next`).
- Output: one proposed next action + resume/confirm prompt; on confirm, in-turn dispatch to the named
  command.
- Does **not** implement, ship, merge, freeze, or bypass the merge gate of any command it routes to — it is a
  router, not an orchestrator body.

## Procedure

### 1. Read durable state (read-only)

```bash
python3 scripts/shipwright-state.py read
python3 scripts/wave_living_docs.py . phase-status-live
python3 scripts/planning-graph.py status --unit-id <unit-id>   # when a candidate unit is already known from state
```

Also check for an unconfigured repo (`.cursor/workflow.config.json` absent and no
`.cursor/sw-memory.provider` marker) before anything else — see **Routing table** row 0.

### 2. Resolve the single next action

Evaluate in this fixed precedence order (first match wins — never present more than one candidate):

| Priority | Durable signal | Next action |
| --- | --- | --- |
| 0 | No config and no zero-config marker present | `/sw-init` — first-run setup |
| 1 | A live deliver run (`wave_living_docs.py phase-status-live`) is `running` or `blocked` for the current worktree | `/sw-deliver run` resume (state already holds `source_task_list` / `--unit-id`) |
| 2 | `shipwright.json` `phaseStatus` is `running`/`blocked` and no deliver run owns it (manual ship path) | `/sw-ship` resume on the current phase branch |
| 3 | A frozen task list exists for the active unit with no deliver run started | `/sw-deliver run <frozen-task-list>` |
| 4 | A drafted-but-unfrozen PRD or decision record exists for the active unit | Continue the doc chain: `/sw-doc-review` (if not yet reviewed) or `/sw-freeze` (if reviewed) |
| 5 | A drafted brainstorm exists with no PRD yet | `/sw-prd` |
| 6 | Nothing in flight, planning-store `next` yields an eligible unit | `/sw-triage` on that unit (classify before ceremony) |
| 7 | Nothing in flight, no eligible unit | Report idle state; suggest `/sw-triage` on a new idea or `/sw-status` for a full picture |

Config drift (`sw-configure.py drift-check`) and verify-unconfigured (`scripts/verify-unconfigured.py`)
surface as **notices alongside** the resolved action — never as a competing action of their own.

### 3. Confirm, then dispatch in-turn

1. Print the resolved action, the durable evidence that produced it (one line — branch/run id/unit id), and
   the exact command it will run.
2. Wait for explicit confirm (`yes` / `proceed`) or a redirect (operator names a different command instead).
3. On confirm, dispatch the named command in the same turn — `/sw` does not re-implement that command's
   procedure; it hands off entirely.
4. On decline or redirect, run the operator's chosen command instead (or stop cleanly if they decline
   everything).

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw`.

## Guardrails

- Read-only until the confirm step — no mutation before the operator confirms the proposed action.
- Never proposes more than one action at a time; ties break by the fixed precedence table, not by guessing.
- Never bypasses the merge gate, freeze gate, or any halt the dispatched command would itself enforce.
- Ambiguity between two equally valid resolutions (e.g. two live deliver runs across worktrees) reports both
  and asks which worktree — never silently picks one.
