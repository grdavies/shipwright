---
description: Gated orchestrator over the phase loop — advances on green, halts at human merge gate. Never merges.
alwaysApply: false
---

# `/pf-ship`

Orchestrates the atomic phase loop inside the worktree. Delegates to each command's procedure; never merges.

## Chain

```
pf-execute → pf-verify → pf-review → gap-check → pf-commit → pf-pr → pf-watch-ci → pf-stabilize → pf-ready [PAUSE]
```

- `pf-review` in configured mode; `review.noDefer` honored.
- `gap-check` default-on (`skills/gap-check`); `--fast` skips.
- `pf-stabilize` uses `stabilize-loop` when present.
- Terminal pause at merge gate — "ready to merge — your call".

## Flags

- `--fast` — skip gap-check.
- `--from <step>` — resume mid-chain.
- `--dry-run` — print plan; no mutations.

## State (per-worktree)

Via `scripts/phase-state.sh`: `shipStartedAt`, `lastCommand`, `phaseStatus`, `iteration`.

Resume: `--from` › `lastCommand` (next step) › chain start.

**Stale-green re-verify:** if `lastCommand` is `pf-ready` / `phaseStatus: green`, re-run `check-gate.sh` live
before reporting done. If no longer green → `phaseStatus: blocked`, re-enter at `pf-stabilize`.

## CI segment

After `pf-pr`: bounded wait per `checks.watch` (`maxWaitMinutes`, `pollSeconds`). `yellow` is not terminal —
poll until green, red, or budget exhausted. After `pf-stabilize` push, re-arm CodeRabbit barrier on new head.

Gate (authoritative):

```bash
GATE="${CURSOR_PLUGIN_ROOT:-$PWD}/scripts/check-gate.sh"
if OUT=$(bash "$GATE"); then GATE_EC=0; else GATE_EC=$?; fi
echo "$OUT" | jq .
```

Persist terminal green only on live `GATE_EC == 0`. Then `/pf-ready` and stop.

## Stop conditions

- Step failure or stabilize hard stop.
- User ambiguity (branch/scope/config).
- CI budget exhausted while `yellow`.
- Merge gate reached on live green.

## Guardrails

- Never merge or force-push.
- Advance only on green; never skip steps.
- Delegate — do not bypass command guardrails.
- All gate truth from `check-gate.sh`.
