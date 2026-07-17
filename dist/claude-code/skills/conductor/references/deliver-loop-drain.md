## Deliver-loop mechanical drain + timing (PRD 062 R7, R9, R19)

`wave_deliver_loop.py` reads `deliver.loop.drainMechanical` (default **`true`**):

| `drainMechanical` | Behavior |
| --- | --- |
| `true` (default) | `deliver-loop` executes mechanical actions in-process until `awaitAgent`, `awaitInFlight`, or a legitimate halt — reduces driver re-invocation churn |
| `false` | One mechanical step per `deliver-loop` invocation (legacy one-step posture) |

**Termination / halt surfaces:**

- **`--max-steps` budget** (default 12 per invocation) — when still mechanical after the budget,
  `conductor:drain-step-budget-exceeded` halts fail-closed (not an unqualified pass).
- **No-progress circuit breaker** — identical `nextAction` + state signature 3× → `conductor:no-progress`.
- **Identical mechanical signature N×** without state advance → stall halt (not pass).

**`elapsedMs` (R9):** `driver-transition` log events and `execute-mechanical` results include wall-clock
`elapsedMs` (optional subprocess timings). Values are numeric only — no secret-bearing argv in logs. Gate
semantics unchanged; timing is diagnostic/operator-observable only.
