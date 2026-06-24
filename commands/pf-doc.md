---
description: Orchestrate the doc pipeline (triage-gated brainstorm → PRD → panel → freeze → tasks). Does not run implementation or skip human judgment gates.
alwaysApply: false
---

# `/pf-doc`

Documentation orchestrator. Delegates to atomic `pf-` doc commands; does not reimplement them.

## Chain (tier-gated)

```
/pf-triage → [Full: /pf-brainstorm] → /pf-prd → /pf-doc-review → spec-rigor → /pf-freeze → /pf-tasks → spec-rigor + traceability → /pf-freeze
```

| Tier | Stages run |
|------|------------|
| Full | brainstorm → PRD → panel (signal-driven) → freeze → tasks |
| Standard | PRD → panel (signal-driven) → freeze → tasks |
| Quick | **not entered** — route to implementation workstream |

## Subsumed atomic commands

`/pf-triage`, `/pf-brainstorm`, `/pf-prd`, `/pf-doc-review`, `/pf-freeze`, `/pf-tasks`

Each remains independently runnable.

## Procedure

1. Run `/pf-triage` (or accept pre-classified tier).
2. If Quick → report handoff to implementation; stop.
3. If Full → `/pf-brainstorm`; halt on blocker.
4. `/pf-prd` per tier rules.
5. `/pf-doc-review` — tier gates whether panel runs (Quick skips); non-Quick uses signal-driven persona selection per `skills/doc-review/SKILL.md`.
6. Halt on `manual` or `gated_auto` trade-offs — do not auto-decide.
7. Run spec-rigor PRD gates (`skills/spec-rigor/SKILL.md`); halt on `fail`.
8. `/pf-freeze` on PRD (and brainstorm if applicable).
9. `/pf-tasks` with Go gate; traceability + analyze gates before task freeze.
10. Report artifact paths and handoff to implementation.

## Flags

- `--from <stage>` — resume from a specific atomic stage.
- `--tier <quick|standard|full>` — skip triage when tier already known.

## Guardrails

- Halts at human-judgment gates (Go, manual trade-offs).
- Does not merge, ship, or run CI gate.
- Pattern: v1 `/ship` delegates-to-atomics model.
