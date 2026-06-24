---
date: 2026-06-22
topic: persona-panel-full-tier
frozen: true
frozen_at: 2026-06-23
---
# Persona panel — original Full-tier selection (founding KD-R7)

## Context

Pre-implementation PRD review used parallel persona sub-agents with a synthesizer applying safe fixes. At Full tier, all seven personas ran regardless of change content.

## Decision

- **D1** Parallel persona sub-agents critique PRD drafts; synthesizer applies safe_auto fixes and surfaces gated/manual trade-offs
- **D2** Full tier loaded all seven personas (coherence, feasibility, scope-guardian, product, adversarial, security, design) regardless of content signals
- **D3** Standard tier used reduced panel with content-triggered extras; Quick tier skipped review

## Rationale

Original founding decision before signal-driven revision. Preserved as frozen record for traceability; superseded for ongoing doc-review selection.

## Alternatives

- No persona panel — rejected (misses pre-build critique)
- Single reviewer — rejected (insufficient blast-radius coverage)

## Consequences

Superseded by `decisions/001-conditional-review-personas.md` via record-level amendment A1. Decision-record drafts still use Full panel per plan 006 U2.
