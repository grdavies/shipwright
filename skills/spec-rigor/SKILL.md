---
name: spec-rigor
description: Pre-freeze spec quality gates (clarify, checklist, analyze) and R-ID→task→test traceability. Tier-gated; blocks freeze on hard failures.
---

# Spec-rigor gates (IM4)

Pre-freeze quality and traceability discipline for the doc workstream. Complements `skills/doc-review` (persona
panel) — structural gates run **after** panel synthesis and **before** `/pf-freeze`.

## Tier policy

| Tier | Pre-PRD-freeze | Pre-task-freeze |
| --- | --- | --- |
| **Full** | clarify + checklist | analyze + traceability |
| **Standard** | checklist only | analyze + traceability |
| **Quick** | — (doc chain not entered) | — |

**Clarify** is Full-only because `/pf-brainstorm` + `/pf-prd` dialogue already reduces ambiguity on Standard.
**Analyze** and **traceability** always run before task-list freeze — every tier that reaches tasks needs
spec↔task consistency and R-ID→test coverage.

## Passes

### Clarify (ambiguity — Full, pre-PRD-freeze)

Resolve or explicitly defer every open question before freeze:

- Scan `## Open Questions` — no unresolved bullets (`- [ ]`, `TBD`, `???`, `TODO`).
- Scan requirement bodies for ambiguity markers (`TBD`, `TODO`, `FIXME`, `???`, `to be determined`).
- Surface blocking questions to the user; do not freeze until cleared or moved to Decision Log with rationale.

### Checklist (requirement quality — pre-PRD-freeze)

Deterministic PRD checks via `scripts/spec-rigor-check.sh --artifact prd`:

- At least one stable R-ID in Requirements.
- No duplicate R-IDs.
- No ambiguity markers in requirement text.
- Required PRD sections present (Overview, Goals, Non-Goals, Requirements, Testing Strategy).

### Analyze (spec↔task consistency — pre-task-freeze)

Via `scripts/spec-rigor-check.sh --artifact tasks`:

- Task file references every effective R-ID from `scripts/spec-union.sh` (union, not parent-only).
- Parent tasks are dependency-ordered; no orphan R-IDs in union without a task reference.
- `## Traceability` table present and parseable.

### Traceability (R-ID → task → test — pre-task-freeze)

Via `scripts/traceability-check.sh`:

- Each effective R-ID maps to a **task ref** (e.g. `1.2`, `2`) and a **named test scenario** (fixture name,
  test file path, or explicit scenario label — not "add tests later").
- Uncovered R-IDs block task-list freeze (`verdict: gaps`, exit `20`).
- Output is stable JSON for fixtures and downstream U7 TDD gate consumption.

## Canonical scripts

```bash
# Pre-PRD-freeze (pass --tier full|standard)
bash scripts/spec-rigor-check.sh --artifact prd --path docs/prds/.../prd.md --tier full

# Pre-task-freeze
bash scripts/spec-rigor-check.sh --artifact tasks --path docs/prds/.../tasks.md --prd docs/prds/.../prd.md
bash scripts/traceability-check.sh --prd docs/prds/.../prd.md --tasks docs/prds/.../tasks.md
```

### Verdict contract

| Verdict | Meaning | Exit |
| --- | --- | --- |
| `pass` | All applicable gates satisfied | `0` |
| `warn` | Advisory findings only (e.g. short requirement text) | `10` |
| `fail` | Hard blocker — do not freeze | `20` |

`warn` allows freeze to proceed with logged findings. `fail` halts until fixed.

## Task-list traceability shape

Every frozen task list includes:

```markdown
## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.2 | run-gate-fixtures.sh frozen guard |
| R2 | 2.1 | spec-union supersede fixture |
```

Task items cite R-IDs inline: `- [ ] 1.2 Implement gate (R1)`.

## Integration points

| Command | When |
| --- | --- |
| `/pf-freeze` | PRD → spec-rigor PRD gates; task list → analyze + traceability |
| `/pf-tasks` | Generate traceability table during expansion; run checks before freeze |
| `/pf-doc` | Chain includes spec-rigor before each freeze step |

## Guardrails

- Gates are **additive** — they do not replace doc-review or freeze CI (`check-frozen.sh`).
- No auto-fix of PRD/task content — surface findings; human or synthesizer fixes.
- Redact any persisted gate summary through `bash scripts/memory-redact.sh` (R41).
