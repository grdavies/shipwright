---
description: Orchestrate the doc pipeline (triage-gated brainstorm → PRD → panel → freeze → tasks). Does not run implementation or skip human judgment gates.
alwaysApply: false
---

# `/pf-doc`

Documentation orchestrator. Delegates to atomic `pf-` doc commands; does not reimplement them.

## Chain (tier-gated)

```
/pf-triage → [Full: /pf-brainstorm] → /pf-prd → /pf-doc-review → /pf-freeze → /pf-tasks
```

| Tier | Stages run |
|------|------------|
| Full | brainstorm → PRD → panel (7 personas) → freeze → tasks |
| Standard | PRD → panel (reduced) → freeze → tasks |
| Quick | **not entered** — route to implementation workstream |

## Subsumed atomic commands

`/pf-triage`, `/pf-brainstorm`, `/pf-prd`, `/pf-doc-review`, `/pf-freeze`, `/pf-tasks`

Each remains independently runnable.

## Procedure

1. Run `/pf-triage` (or accept pre-classified tier).
2. If Quick → report handoff to implementation; stop.
3. If Full → `/pf-brainstorm`; halt on blocker.
4. `/pf-prd` per tier rules.
5. `/pf-doc-review` per tier scaling.
6. Halt on `manual` or `gated_auto` trade-offs — do not auto-decide.
7. `/pf-freeze` on PRD (and brainstorm if applicable).
8. `/pf-tasks` with Go gate.
9. Report artifact paths and handoff to implementation.

## Flags

- `--from <stage>` — resume from a specific atomic stage.
- `--tier <quick|standard|full>` — skip triage when tier already known.

## Guardrails

- Halts at human-judgment gates (Go, manual trade-offs).
- Does not merge, ship, or run CI gate.
- Pattern: v1 `/ship` delegates-to-atomics model.
