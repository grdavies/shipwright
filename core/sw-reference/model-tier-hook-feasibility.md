# Model-tier Task hook — feasibility spike (PRD 012 phase 4 / DL-2)

**Date:** 2026-06-25 (spike) / 2026-06-26 (revised decision)  
**Verdict:** **Registered — forward-compatible (Option C)**

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

## Platform assessment

| Mechanism | Cursor | Claude Code |
| --- | --- | --- |
| `preToolUse` `updated_input` on Task | Documented; **not applied by platform** (DL-2 spike confirmed) | **Unverified** — no Claude Code environment available |
| `dispatch-check.py` preflight (phase 2–3) | ✅ enforcement floor | ✅ enforcement floor |

## Decision — Option C (2026-06-26)

Register the hook in both platforms now. Rationale:

- The hook logic is already written, tested, and isolated in `core/hooks/before_task_dispatch.py`.
- Phase 2 `dispatch-check.py` is the real enforcement floor — hook effectiveness is
  additive defense-in-depth only. A no-op hook does not degrade correctness.
- Forward compatibility: when Cursor applies `updated_input` for Task, coverage is automatic
  with zero further changes. Same for Claude Code if/when verified.
- The hook fails open on all unexpected errors (top-level exception catch) and logs mutation
  attempts to stderr for observability.
- Re-opening a deferred GAP-BACKLOG item later would require additional spike work and a new
  PR cycle. Registering now eliminates that cost.

## Registration

| Platform | Hook event | Entry point | Mutation status |
| --- | --- | --- | --- |
| Cursor | `preToolUse` | `${CURSOR_PLUGIN_ROOT}/hooks/before-task-dispatch.py` | `updated_input` emitted; not applied by platform (DL-2) |
| Claude Code | `PreToolUse` | `${CLAUDE_PLUGIN_ROOT}/hooks/claude-hook.py` (dispatch) | `updated_input` emitted; platform behavior unverified |

## Observability

When the hook resolves a bound agent, it logs to stderr:

```
sw-model-binding: preToolUse mutation attempted model=<id> agent=<id>
```

This confirms the hook is firing and what it attempted. Whether the mutation was honored can
only be verified by observing the downstream model in use by the spawned agent.

## Re-evaluate criteria

Downgrade to deferral only if the hook causes measurable dispatch latency regression or
introduces a failure mode that breaks Task spawning. Otherwise keep registered as the platform
matures toward full `updated_input` support.
