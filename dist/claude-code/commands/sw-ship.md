---
description: Gated orchestrator over the phase loop — advances on green, halts at human merge gate. Never merges.
alwaysApply: false
---

# `/sw-ship`

Orchestrates the atomic phase loop inside the worktree. Delegates to each command's procedure; never merges.

## Chain

```
sw-tmp init → sw-execute → sw-verify → verification-gate → sw-review → sw-simplify → gap-check → sw-commit → sw-pr → sw-watch-ci → sw-stabilize → sw-ready [PAUSE] → sw-tmp clean
```

- **sw-tmp** — at chain start: `bash scripts/sw-tmp.sh clean` then `bash scripts/sw-tmp.sh init` (records
  `runDir` in phase-state). At chain end: `bash scripts/sw-tmp.sh clean`. No `trap … EXIT` (markdown-orchestrated
  chain).
- **verification-gate** — `Load skills/verification-gate/SKILL.md`; run `scripts/verify-evidence.sh` on
  structured status files under the resolved run dir. Policy by `inconclusiveClass`:
  - **Halt** on `not-verified` or `missing-required`.
  - **`no-baseline` / `unattributed`** — log loudly and **continue** into `sw-commit` (which owns the logged
    decision prompt). Does not override `check-gate.sh`.
- **sw-simplify** — behavior-preserving deslop after review; re-runs verify + `simplify-gate.sh`. **Halt** on
  `regressed`; **log and continue** on `inconclusive`. Skipped by `--fast` / `--skip-simplify`.
- `sw-review` in configured mode; `review.noDefer` honored.
- `gap-check` default-on (`skills/gap-check`); `--fast` skips.
- `sw-stabilize` uses `stabilize-loop` when present.
- Terminal pause at merge gate — "ready to merge — your call".

## Flags

- `--fast` — skip gap-check and sw-simplify.
- `--skip-simplify` — skip sw-simplify only (gap-check still runs unless `--fast`).
- `--signal-id <id>` — after merge-ready pause, offer `/sw-feedback-close` for this backlog signal.
- `--from <step>` — resume mid-chain.
- `--dry-run` — print plan; no mutations.

## State (per-worktree)

Via `scripts/phase-state.sh`: `shipStartedAt`, `lastCommand`, `phaseStatus`, `iteration`, `runDir`.

Resume: `--from` › `lastCommand` (next step) › chain start.

**Stale-green re-verify:** if `lastCommand` is `sw-ready` / `phaseStatus: green`, re-run `check-gate.sh` live
before reporting done. If no longer green → `phaseStatus: blocked`, re-enter at `sw-stabilize`.

## CI segment

After `sw-pr`: bounded wait per `checks.watch` (`maxWaitMinutes`, `pollSeconds`). `yellow` is not terminal —
poll until green, red, or budget exhausted. After `sw-stabilize` push, re-arm CodeRabbit barrier on new head.

Gate (authoritative):

```bash
GATE="${CLAUDE_PLUGIN_ROOT:-$PWD}/scripts/check-gate.sh"
if OUT=$(bash "$GATE"); then GATE_EC=0; else GATE_EC=$?; fi
echo "$OUT" | jq .
```

Persist terminal green only on live `GATE_EC == 0`. Then `/sw-ready` and stop.

**Feedback closure (optional):** when `--signal-id <id>` is set and human has confirmed closure, run
`/sw-feedback-close` after live green — requires verify status (and gate JSON when PR exists).

## Stop conditions

- Step failure or stabilize hard stop.
- **verification-gate** returns `not-verified` (fresh attributable failure).
- **verification-gate** returns `inconclusive` with `inconclusiveClass: missing-required`.
- **sw-simplify** / `simplify-gate.sh` returns `regressed` (post-cleanup verify failure).
- **Local review gate** — when `review.local.gate.haltOn` includes validated P0/P1 and
  `/tmp/sw-local-review-gate-result.json` reports `verdict: halt`, stop for human triage (surface-only
  default logs and continues). Never overrides `check-gate.sh`.
- User ambiguity (branch/scope/config).
- CI budget exhausted while `yellow`.
- Merge gate reached on live green.

## Guardrails

- Never merge or force-push.
- Advance only on green; never skip steps.
- Delegate — do not bypass command guardrails.
- All **merge-gate** truth from `check-gate.sh` — verification-gate is pre-CI local evidence only.
- `inconclusive` with `no-baseline` / `unattributed` logs and continues; `missing-required` halts the ship chain.
