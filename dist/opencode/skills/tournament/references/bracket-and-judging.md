# Bracket and judging (PRD 064 R5)

## Deterministic bracket

The driver (`scripts/tournament.py bracket` / `advance`) owns bracket ordering:

1. Seed attempts in plan order (`attempt-1`, `attempt-2`, …).
2. Pair sequentially: (1,2), (3,4), …; odd attempt receives a bye.
3. Winners advance to the next round using the same pairing rule.
4. Champion is the sole survivor.

## Rubric (default)

| Dimension | Question |
| --- | --- |
| `fit-to-requirements` | How well does the option satisfy stated requirements? |
| `feasibility` | Can we ship this with known constraints? |
| `risk` | What failure modes remain? |
| `clarity` | Is the proposal actionable and unambiguous? |

Judges score A and B per dimension (0–5), pick `winnerId`, and emit `rationale`.

## Persistence

```bash
python3 scripts/tournament.py persist \
  --plan "$RUN_DIR/tournament-plan.json" \
  --bracket "$RUN_DIR/tournament-bracket.json" \
  --winner-id attempt-2 \
  --rationale "Lower risk with equal fit" \
  --attempts "$RUN_DIR/tournament-attempts.json" \
  --out "$RUN_DIR/tournament-result.json"
```
