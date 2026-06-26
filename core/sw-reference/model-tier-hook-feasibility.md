# Model-tier Task hook — feasibility spike (PRD 012 phase 4 / DL-2)

**Date:** 2026-06-25  
**Verdict:** **Deferred — do not register in `hooks.json`**

## Goal

Optional belt-and-suspenders (R5): a `preToolUse` hook that injects a resolved concrete
`model` onto Task calls targeting `sw-*-reviewer` personas and native-panel specialists.

## Spike method

1. **Cursor hook contract review** ([Hooks docs](https://cursor.com/docs/hooks)):
   - `preToolUse` output may include `updated_input` to rewrite tool arguments.
   - `subagentStart` output is **`permission` + `user_message` only** — no `updated_input`, no model field.

2. **Task-tool mutation reports:** Community and upstream trackers report that `preToolUse`
   `updated_input` is **silently ignored** for the Task / Agent tool (model and prompt overrides
   do not reach the spawned subagent). See
   [Cursor forum: preToolUse updated_input ignored for Task](https://forum.cursor.com/t/pretooluse-hook-updated-input-is-silently-ignored-for-the-task-tool/151985).

3. **Logic prototype:** `core/hooks/before_task_dispatch.py` implements resolver integration and
   returns the correct `updated_input.model` when fed synthetic `preToolUse` stdin. Fixture:
   `scripts/test/fixtures/task-dispatch-hook-feasibility.sh`.

## Conclusion

| Mechanism | Can inject Task `model`? | Ship? |
| --- | --- | --- |
| `reviewer-dispatch-check.sh` + dispatcher procedure (phase 2–3) | Yes (caller stamps `model:`) | **Yes — enforcement floor** |
| `preToolUse` + `updated_input` on Task | Documented; **not applied by platform** for Task | **No** |
| `subagentStart` | **No** model field in output schema | **No** |

**Phase 4 closes as deferred:** R3 preflight remains the sole mechanical floor. The hook module
is retained for fixtures and future Cursor support; it is **not** registered in
`platforms/cursor/emitter.py` `hooks.json` until platform applies `updated_input` for Task.

## Re-open criteria

Register `before-task-dispatch` in plugin hooks when **both** are true:

1. Cursor applies `preToolUse` `updated_input.model` (or equivalent) on Task spawns — verified manually.
2. `task-dispatch-hook-injection` fixture passes against a live hook registration smoke test.
