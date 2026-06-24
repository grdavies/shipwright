---
date: 2026-06-23
topic: conditional-review-personas
frozen: true
frozen_at: 2026-06-23
---
# Conditional review-persona selection

## Context

Doc-review previously scaled persona count by triage tier (Full = all seven). Code review already conditions on diff content. The over-loading concern applies to Full-tier doc review loading security/design on changes with no auth/UI surface.

## Decision

- **D1** Tier decides whether review runs, not which personas run — Quick skips; non-Quick uses signal-driven selection
- **D2** Doc-review always-on core is five personas: coherence, feasibility, scope-guardian, product, adversarial
- **D3** Only security and design are signal-gated specialists with deterministic keyword/structural triggers
- **D4** Every activation is logged with matched signals; `--personas` / `--all` overrides are recorded

## Rationale

Preserves phase-flow's auditable same-inputs-same-panel identity while adopting CE's always-on-core + conditional-specialist shape. Semantic personas resist clean gating so they stay always-on.

## Alternatives

- Keep Full = all seven — rejected (over-loads irrelevant personas)
- Judgment-based selection like CE — rejected (breaks deterministic audit trail)

## Consequences

`skills/doc-review/SKILL.md` rewritten for signal-driven selection. Decision-record drafts (cross-cutting) still use Full panel per plan 006 U2.
