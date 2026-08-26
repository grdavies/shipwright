---
description: Read per-worktree Shipwright state and the planning store, then propose the single next action with confirmation. Does not itself implement, ship, merge, or replace the orchestrator each proposed action dispatches to.
alwaysApply: false
---

# `/sw`

The bare, state-aware entry point. `/sw` with no arguments is **not a static menu** — it reads durable state,
computes the one action that actually advances the repo right now, and asks you to confirm before dispatching
it. Every other `sw-` command remains independently invokable; `/sw` is a convenience router on top, never a
replacement or mega-front-door.

Programmatic routing lives in `scripts/sw_router.py` — the command doc and module share one bounded contract.

## Scope

- Input: none (bare `/sw`), or a free-form hint (`/sw continue`, `/sw what's next`).
- Output: one proposed next action + resume/confirm prompt; on confirm, in-turn dispatch to the named
  command.
- Does **not** implement, ship, merge, freeze, or bypass the merge gate of any command it routes to — it is a
  router, not an orchestrator body. Does **not** invent new top-level `sw-*` commands (R29, R30).

## Bounded destinations (R25, R29, R30, R39)

`/sw` routes only to these five destination families — never beyond them:

| Destination | Typical command | When |
| --- | --- | --- |
| **capture** | `/sw-note` | Rough idea or notebook item not yet worth planning-store ceremony |
| **explore** | `/sw-explore` | Destination-first structured exploration before PRD/doc work |
| **doc** | `/sw-doc`, `/sw-doc-review`, `/sw-freeze`, `/sw-prd` | Documentation chain continuation |
| **deliver** | `/sw-deliver run <frozen-task-list>` | Frozen task list ready for implementation waves |
| **resume** | `/sw-deliver run`, `/sw-ship`, `/sw-explore resume` | In-flight deliver, ship, or exploration session |

No additional top-level command surface is introduced by the router — closed allowlist enforced in
`scripts/sw_router.py`.

## Procedure

### 1. Read durable state (read-only)

```bash
python3 scripts/shipwright-state.py read
python3 scripts/wave_living_docs.py . phase-status-live
python3 scripts/planning-graph.py status --unit-id <unit-id>   # when a candidate unit is already known from state
python3 scripts/sw_router.py propose '<signals-json>'          # bounded route proposal from signals
```

Also check for an unconfigured repo (`.cursor/workflow.config.json` absent and no
`.cursor/sw-memory.provider` marker) before anything else — see **Routing table** row 0.

Build the signal bundle from durable reads (deliver run, phase ship, exploration map/readiness, notebook
counts, planning `next`, operator hint) and call `sw_router.py propose` for the canonical resolution.

### 2. Resolve the single next action

Evaluate in this fixed precedence order (first match wins — never present more than one candidate):

| Priority | Durable signal | Destination | Next action |
| --- | --- | --- | --- |
| 0 | No config and no zero-config marker present | resume | `/sw-init` — first-run setup |
| 1 | A live deliver run (`wave_living_docs.py phase-status-live`) is `running` or `blocked` for the current worktree | resume | `/sw-deliver run` resume (state already holds `source_task_list` / `--unit-id`) |
| 2 | `shipwright.json` `phaseStatus` is `running`/`blocked` and no deliver run owns it (manual ship path) | resume | `/sw-ship` resume on the current phase branch |
| 3 | A frozen task list exists for the active unit with no deliver run started | deliver | `/sw-deliver run <frozen-task-list>` |
| 4 | Exploration map open and **not** ready for doc handoff | explore | `/sw-explore resume <map-id>` or `/sw-explore` |
| 5 | Exploration readiness sufficient (`readyForDocHandoff`) | doc | `/sw-doc --from-explore <map-id>` (loop guard applies) |
| 6 | Open notebook ideas or operator capture hint | capture | `/sw-note` |
| 7 | A drafted-but-unfrozen PRD or decision record exists for the active unit | doc | `/sw-doc-review` (if not yet reviewed) or `/sw-freeze` (if reviewed) |
| 8 | A drafted brainstorm exists with no PRD yet | doc | `/sw-prd` |
| 9 | Nothing in flight, planning-store `next` yields an eligible unit | doc | `/sw-triage --unit-id <id>` (classify before ceremony) |
| 10 | Nothing in flight, no eligible unit | capture | Report idle via `/sw-status`; suggest `/sw-note` or `/sw-triage` |

Config drift (`sw-configure.py drift-check`) and verify-unconfigured (`scripts/verify-unconfigured.py`)
surface as **notices alongside** the resolved action — never as a competing action of their own.

### Route reasons (R25)

Every proposal includes a **route reason** from `sw_router.py`:

- `code` — stable machine identifier (e.g. `live-deliver-run`, `exploration-ready`)
- `message` — one-line operator explanation
- `evidence` — durable signal excerpt (run id, map id, task-list path)

Print the reason with the proposal before asking for confirm.

### Persistence effects (R25, R39)

Before confirm, declare **persistence effects** for the destination — what would be written on proceed:

| Destination | Declared writes (on confirm only) |
| --- | --- |
| capture | Append to `.cursor/sw-notebook/notebook.jsonl` |
| explore | Conditional `ExplorationMap` persist under `.cursor/sw-explore/maps/` (trigger-gated only) |
| doc | Substantive planning docs via docs worktree route |
| deliver | Deliver run state + phase worktree provisioning |
| resume | Advance existing deliver/ship/explore session state |

Read-only until confirm — no mutation before operator approval.

### Cancel and override (R25)

- **Cancel** — operator declines; `sw_router.py apply_cancel` returns `cancelled` with empty persistence
  effects; stop cleanly.
- **Override** — operator names a different bounded destination; `sw_router.py apply_override` validates the
  destination is in the closed set and re-declares persistence effects before dispatch.

### Explore↔doc loop guard (R50)

`sw_router.py` tracks recent `explore`/`doc` transitions. Repeated alternation beyond the configured ceiling
refuses the next explore or doc proposal with `explore-doc-loop-guard` — operator must break the cycle
explicitly (e.g. confirm deliver or capture) rather than bounce indefinitely.

### 3. Confirm, then dispatch in-turn

1. Print the resolved action, the route reason (code + evidence), declared persistence effects, and the exact
   command it will run.
2. Wait for explicit confirm (`yes` / `proceed`) or a redirect (operator names a different bounded
   destination instead).
3. On confirm, dispatch the named command in the same turn — `/sw` does not re-implement that command's
   procedure; it hands off entirely.
4. On decline or redirect, run `apply_cancel` / `apply_override` then the operator's chosen command (or stop
   cleanly if they decline everything).

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw`.

## Guardrails

- Read-only until the confirm step — no mutation before the operator confirms the proposed action.
- Never proposes more than one action at a time; ties break by the fixed precedence table, not by guessing.
- Never bypasses the merge gate, freeze gate, or any halt the dispatched command would itself enforce.
- Ambiguity between two equally valid resolutions (e.g. two live deliver runs across worktrees) reports both
  and asks which worktree — never silently picks one.
- Closed command surface — `sw_router.py` refuses invented top-level `sw-*` commands not on the allowlist.
