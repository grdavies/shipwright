---
description: Gated orchestrator over the phase loop — advances on green, halts at human merge gate. Never merges.
alwaysApply: false
---

# `/pf-ship`

Orchestrates the atomic phase loop inside the worktree. Delegates to each command's procedure; never merges.

## Chain

```
pf-execute → pf-verify → verification-gate → pf-review → pf-simplify → gap-check → pf-commit → pf-pr → pf-watch-ci → pf-stabilize → pf-ready [PAUSE]
```

- **verification-gate** — `Load skills/verification-gate/SKILL.md`; run `scripts/verify-evidence.sh` on
  structured status files. **Halt** on `not-verified`; **log and continue** on `inconclusive` (no mid-chain
  pause). Does not override `check-gate.sh`.
- **pf-simplify** — behavior-preserving deslop after review; re-runs verify + `simplify-gate.sh`. **Halt** on
  `regressed`; **log and continue** on `inconclusive`. Skipped by `--fast` / `--skip-simplify`.
- `pf-review` in configured mode; `review.noDefer` honored.
- `gap-check` default-on (`skills/gap-check`); `--fast` skips.
- `pf-stabilize` uses `stabilize-loop` when present.
- Terminal pause at merge gate — "ready to merge — your call".

## Flags

- `--fast` — skip gap-check and pf-simplify.
- `--skip-simplify` — skip pf-simplify only (gap-check still runs unless `--fast`).
- `--signal-id <id>` — after merge-ready pause, offer `/pf-feedback-close` for this backlog signal.
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

**Feedback closure (optional):** when `--signal-id <id>` is set and human has confirmed closure, run
`/pf-feedback-close` after live green — requires `/tmp/pf-verify.status.json` (and gate JSON when PR exists).

## Stop conditions

- Step failure or stabilize hard stop.
- **verification-gate** returns `not-verified` (fresh attributable failure).
- **pf-simplify** / `simplify-gate.sh` returns `regressed` (post-cleanup verify failure).
- User ambiguity (branch/scope/config).
- CI budget exhausted while `yellow`.
- Merge gate reached on live green.

## Guardrails

- Never merge or force-push.
- Advance only on green; never skip steps.
- Delegate — do not bypass command guardrails.
- All **merge-gate** truth from `check-gate.sh` — verification-gate is pre-CI local evidence only.
- `inconclusive` from verification-gate never halts the ship chain (log only).
