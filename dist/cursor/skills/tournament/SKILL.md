---
name: tournament
description: Run a bounded N-attempt tournament with deterministic bracketing and pairwise judges. Use when brainstorm divergence selection needs an isolated winner among competing options. Does not auto-apply decisions or bypass human synthesis.
---
# Tournament primitive

Bounded option selection via isolated attempts, a driver-held deterministic bracket, and pairwise judge agents scoring an explicit rubric (PRD 064 R5).


**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill tournament`.

## Config (`tournament`)

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Master switch — off keeps manual divergence selection |
| `n` | `3` | Max isolated attempts (2–8) |
| `cost_ceiling` | `0` | Advisory cost cap; `0` = unset |

```bash
python3 scripts/tournament.py config --root .
```

## Procedure

1. **Gate** — `should-run` requires `enabled: true` and ≥2 viable divergence candidates.
2. **Plan attempts** — `plan` emits `attempt-1..N` with clean-context briefs.
3. **Attempt fan-out** — one fresh `sw-tournament-attempt` Task per attempt (`readonly: true`). Attempts never share context.
4. **Bracket** — `bracket` builds deterministic pairwise rounds (driver-owned).
5. **Judge fan-out** — one `sw-tournament-judge` Task per pairing (`readonly: true`) scoring the rubric in `references/bracket-and-judging.md`.
6. **Advance** — `evaluate-match` + `advance` until a champion exists.
7. **Persist** — `persist` writes winner + rationale JSON under the run dir.

Dispatch recipes: `rules/sw-subagent-dispatch.mdc` **Tournament dispatch**. Status schema: `references/tournament-schema.json`.

## Guardrails

- First call site is brainstorm divergence selection only (R6).
- Driver owns bracket ordering — agents judge pairings only.
- Never merge attempts or judge transcripts across contexts.
- Does not skip the human synthesis checkpoint — it informs it.
