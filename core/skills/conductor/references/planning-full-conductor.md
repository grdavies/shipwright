## Bounded planning full-conductor (PRD 035 R8–R9, R23)

`planning.autonomy` defaults to `maintenance-only`: mechanical/living graph bookkeeping runs autonomously
with **no prompts**; content-authoring decisions (pull-in, amendments, priority changes, cancel/supersede)
are auto-**proposed** and human-confirmed. The opt-in `full-conductor` posture elevates only
**gap/absorption-class** decisions to in-loop auto-decision via `scripts/planning_autonomy.py`.

| Constraint | Enforcement |
| --- | --- |
| Scope | Gap/absorption class only — never private/memory units |
| Confidence | `planning.fullConductor.confidenceThreshold` before auto-decide |
| Undo | `planning.fullConductor.undoWindowSeconds` before reconciler materializes |
| Mutation budget | `planning.fullConductor.mutationBudget` per session → legitimate halt `planning-mutation-budget` |
| No nested dispatch | Driver **enqueues handoffs only** — never `/sw-deliver`, `/sw-doc`, or any orchestrator from its loop |
| Reconcile boundary | Explicit halt between reconcile batch completion and downstream dispatch |
| Merge gate | Never weakens merge-to-`main`; branch protection never bypassed |
| Durable audit | Opt-in, `--override`, `--accept-frozen-impact`, direct-to-trunk logged (who/when/why) |

Entrypoints:

```bash
python3 scripts/planning_autonomy.py . posture
python3 scripts/planning_autonomy.py . evaluate --decision-type gap-absorb --visibility public
python3 scripts/planning_autonomy.py . step --proposals-file proposals.json
python3 scripts/planning_autonomy.py . enqueue-handoff --command "/sw-tasks confirm …"
python3 scripts/planning_autonomy.py . check-dispatch --command "/sw-deliver run …"
```

Resume after `planning-mutation-budget` halt: operator acknowledges and re-runs with explicit confirm or
lower scope — same legitimate-halt model as deliver conductor budgets.

Workflow pushes use `scripts/git-push.py` only (secret-scan pre-push; phase sub-agents never raw `git push`).
