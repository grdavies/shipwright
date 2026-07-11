---
name: execute-discipline
description: Per-task TDD gate, two-stage subagent review, and executable-plan self-review for /sw-execute. Use when implementing frozen task phases with R-ID traceability. Does not ship or merge.
---
# Execute discipline (IM5 + IM6)

Bounded implementation loop inside `/sw-execute`. One **task ref** at a time (e.g. `1.2`); each task runs
plan self-review → TDD red → implement → TDD green → two-stage review before the next task.


**Model tier:** build — resolve via `python3 scripts/resolve-model-tier.py --skill execute-discipline`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).


## Ref-scoped dispatch (PRD 053)

When `/sw-execute` is dispatched with a single `--task-ref`, run the per-task loop for **that ref only**.
Persist status via `execute_task_status.py`. Sibling refs are scheduled by the phase executor execute plan.

## Per-task loop

```
plan-self-review → TDD red → implement → TDD green → tdd-gate → refactor → stage-1 review → stage-2 review → next task
```

1. **Plan self-review** — `python3 scripts/plan-self-review.py --tasks <file> [--task-ref <ref>]`
   Validates executable steps (`**File:**`, `**Expected:**`) and scans for placeholders.
2. **Resolve traceability** — from `## Traceability` (U6), load `testScenario` + `rid` + `zombiesChecklist` for this task ref.
   - `python3 scripts/zombies_gate.py --tasks <file> --task-ref <ref>` (or `--record` JSON) — halt on exit `20` when scenario is bound but checklist is empty.
   - `python3 scripts/traceability_bind.py bind --root . --out .shipwright/traceability-baseline.json --task-ref <ref> --rid <rid>` — freeze pre-red test baseline (R9).
3. **TDD red** — run the traced test command; record failure in `/tmp/sw-tdd.status.json` (`red.observed: true`,
   `red.exitCode != 0`). If no test scenario exists, record `skipped: true` with reason — gate returns `skipped`.
4. **Implement** — minimal change for the task; do not weaken assertions to force green.
5. **TDD green** — re-run the same test; record pass (`green.observed: true`, `green.exitCode: 0`).
   - Optional advisory: `python3 scripts/verify_mutation.py` when `verifyMutation.enabled` is true (never default-blocking).
   - `python3 scripts/test_tamper_check.py --baseline .shipwright/traceability-baseline.json --status /tmp/sw-tdd.status.json` after green — authoritative over `testWeakened` (exit `20` on R9a flags).
   - Advisory: `python3 scripts/over_mock_scan.py --root .` — surface flags to stage-1 review.
6. **TDD gate** — `python3 scripts/tdd-gate.py --status /tmp/sw-tdd.status.json [--require-skip-reason]` must return `pass` or `skipped` (phase mode defaults `--require-skip-reason` on). — `python3 scripts/tdd-gate.py --status /tmp/sw-tdd.status.json` must return `pass` or `skipped`.
7. **Refactor** (PRD 039 R1/R7) — always run and record:
   - Snapshot quality signal: `python3 scripts/quality_provider.py > /tmp/sw-quality.signal.json`
   - When signal is `none`, record `verdict: none` / `signal: none` without structural edits.
   - When `advise`/`poor`, attempt behavior-preserving structural refactor; re-run verify; compare with `python3 scripts/simplify-gate.py` (baseline vs post).
   - `regressed` → revert refactor edits only; record `skipped` with reason unless human override.
   - Persist via `python3 scripts/execute_task_status.py --task-ref <ref> --write '<json>'` including `refactor: { ran, skipped, skipReason, signalRef, verdict, metricDelta }`.
   - Gate: `python3 scripts/refactor-gate.py --status <path> [--signal /tmp/sw-quality.signal.json]` — halt on `20`.
9. **Two-stage review** (fresh subagent per task when delegated — see `rules/sw-subagent-dispatch.mdc`):
   - **Stage 1 — spec-compliance:** diff satisfies task + union R-IDs; no out-of-scope edits.
   - **Stage 2 — code-quality:** naming, structure, obvious bugs; no scope expansion.
10. Halt on stage failure; fix or escalate (R29). Leave work uncommitted for `/sw-verify`.

## TDD status shape

Emit `/tmp/sw-tdd.status.json` before calling the gate:

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

### Verdict contract (`scripts/tdd-gate.py`)

| Verdict | Meaning | Exit |
| --- | --- | --- |
| `pass` | Red failure observed before green pass; test not weakened | `0` |
| `skipped` | No test scenario or explicit skip with reason | `10` |
| `fail` | Green without red, red was already passing, or test weakened | `20` |

Complements `skills/verification-gate` — TDD gate is **per-task pre-verify**; verification-gate runs at ship.

## Executable plan shape (task sub-items)

After `/sw-tasks` Go expansion, each implementable sub-task includes:

```markdown
- [ ] 1.1 Add tdd-gate script (R1)
  - **File:** `scripts/tdd-gate.py`
  - **Expected:** JSON verdict; exit 0 on pass, 20 on fail
  - **R-IDs:** R1
```

Parent phase items may stay checklist-only; **sub-tasks** under active phase carry `File` + `Expected`.

## Self-review checks (`plan-self-review.py`)

| Check | Severity |
| --- | --- |
| Sub-task missing `**File:**` or path backtick | error |
| Sub-task missing `**Expected:**` | error |
| `TBD`, `TODO`, `...`, `placeholder` in executable block | error |
| Very short Expected (&lt; 8 chars) | warn |

## Guardrails

- Do not rewrite tests to match broken behavior (pairs with U4 dev-time gate).
- Two-stage review is **between tasks**, not batched at phase end.
- Subagent dispatch for implement + review follows R37 + `sw-subagent-dispatch.mdc`.
- No commit/push/PR from this skill — `/sw-execute` boundary unchanged.


## Refactor-vs-simplify boundary (R7)

**Refactor** (this skill) is per-task, after green, before stage-1 review — structural quality driven by the
harness signal. **`/sw-simplify`** (in `/sw-ship`) is post-review deslop on the phase delta — gated by
`simplify-gate.py`. Neither inlines the other.
