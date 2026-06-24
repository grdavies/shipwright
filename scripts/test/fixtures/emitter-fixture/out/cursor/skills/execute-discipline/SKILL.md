---
name: execute-discipline
description: Per-task TDD gate, two-stage subagent review, and executable-plan self-review for /pf-execute. Consumes U6 traceability.
---

# Execute discipline (IM5 + IM6)

Bounded implementation loop inside `/pf-execute`. One **task ref** at a time (e.g. `1.2`); each task runs
plan self-review → TDD red → implement → TDD green → two-stage review before the next task.

## Per-task loop

```
plan-self-review → TDD red → implement → TDD green → tdd-gate → stage-1 review → stage-2 review → next task
```

1. **Plan self-review** — `bash scripts/plan-self-review.sh --tasks <file> [--task-ref <ref>]`
   Validates executable steps (`**File:**`, `**Expected:**`) and scans for placeholders.
2. **Resolve traceability** — from `## Traceability` (U6), load `testScenario` + `rid` for this task ref.
3. **TDD red** — run the traced test command; record failure in `/tmp/pf-tdd.status.json` (`red.observed: true`,
   `red.exitCode != 0`). If no test scenario exists, record `skipped: true` with reason — gate returns `skipped`.
4. **Implement** — minimal change for the task; do not weaken assertions to force green.
5. **TDD green** — re-run the same test; record pass (`green.observed: true`, `green.exitCode: 0`).
6. **TDD gate** — `bash scripts/tdd-gate.sh --status /tmp/pf-tdd.status.json` must return `pass` or `skipped`.
7. **Two-stage review** (fresh subagent per task when delegated — see `rules/pf-subagent-dispatch.mdc`):
   - **Stage 1 — spec-compliance:** diff satisfies task + union R-IDs; no out-of-scope edits.
   - **Stage 2 — code-quality:** naming, structure, obvious bugs; no scope expansion.
8. Halt on stage failure; fix or escalate (R29). Leave work uncommitted for `/pf-verify`.

## TDD status shape

Emit `/tmp/pf-tdd.status.json` before calling the gate:

```json
{
  "rid": "R1",
  "taskRef": "1.1",
  "testScenario": "traceability complete fixture R1",
  "red": { "observed": true, "exitCode": 1 },
  "green": { "observed": true, "exitCode": 0 },
  "testWeakened": false,
  "skipped": false,
  "skipReason": ""
}
```

### Verdict contract (`scripts/tdd-gate.sh`)

| Verdict | Meaning | Exit |
| --- | --- | --- |
| `pass` | Red failure observed before green pass; test not weakened | `0` |
| `skipped` | No test scenario or explicit skip with reason | `10` |
| `fail` | Green without red, red was already passing, or test weakened | `20` |

Complements `skills/verification-gate` — TDD gate is **per-task pre-verify**; verification-gate runs at ship.

## Executable plan shape (task sub-items)

After `/pf-tasks` Go expansion, each implementable sub-task includes:

```markdown
- [ ] 1.1 Add tdd-gate script (R1)
  - **File:** `scripts/tdd-gate.sh`
  - **Expected:** JSON verdict; exit 0 on pass, 20 on fail
  - **R-IDs:** R1
```

Parent phase items may stay checklist-only; **sub-tasks** under active phase carry `File` + `Expected`.

## Self-review checks (`plan-self-review.sh`)

| Check | Severity |
| --- | --- |
| Sub-task missing `**File:**` or path backtick | error |
| Sub-task missing `**Expected:**` | error |
| `TBD`, `TODO`, `...`, `placeholder` in executable block | error |
| Very short Expected (&lt; 8 chars) | warn |

## Guardrails

- Do not rewrite tests to match broken behavior (pairs with U4 dev-time gate).
- Two-stage review is **between tasks**, not batched at phase end.
- Subagent dispatch for implement + review follows R37 + `pf-subagent-dispatch.mdc`.
- No commit/push/PR from this skill — `/pf-execute` boundary unchanged.
