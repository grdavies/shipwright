---
date: 2026-06-22
topic: tiered-ceremony-triage
frozen: true
frozen_at: 2026-06-23
---
# Tiered ceremony with up-front triage

## Context

Not every change needs brainstorm → PRD → full panel. Risk triggers (auth, payments, migrations, public API) must force adequate ceremony without blocking small fixes.

## Decision

- **D1** `/pf-triage` classifies Quick (straight to implementation), Standard (short PRD + tasks), or Full (brainstorm → PRD → panel → freeze)
- **D2** Risk triggers force at least Standard tier — classifier reliability is load-bearing
- **D3** Quick tier skips doc-review panel entirely; non-Quick runs review per doc-type rules

## Rationale

Keeps "quicker" honest while preserving deep ceremony for high-blast-radius work. Same-inputs-same-tier is deterministic.

## Alternatives

- Single ceremony level — rejected (blocks small fixes)
- Model-judged tier — rejected (not auditable)

## Consequences

`/pf-doc` orchestrator is tier-gated. Implementation workstream receives Quick handoff without doc pipeline (plan 003).
