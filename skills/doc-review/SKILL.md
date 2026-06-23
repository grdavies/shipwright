---
name: pf-doc-review
description: Review PRD drafts with parallel persona sub-agents and a synthesizer that auto-applies safe fixes. Tier-scaled panel; Quick tier skips review.
---

# Document review (`/pf-doc-review`)

Multi-persona PRD review. Pattern borrowed from compound-engineering `ce-doc-review` (slim vendored adaptation).

## Tier scaling

| Tier | Personas |
|------|----------|
| Full | All seven: coherence, feasibility, product, scope-guardian, security, design, adversarial |
| Standard | coherence + scope-guardian (floor) + content-triggered extras |
| Quick | None — do not invoke |

## Always-on (when panel runs)

- `pf-coherence-reviewer`
- `pf-scope-guardian-reviewer`

## Content-triggered (Standard+)

- **product** — challengeable premise or strategic weight
- **security** — auth, payments, PII, external APIs
- **design** — UI/UX, flows, accessibility
- **feasibility** — always on for Full; on Standard when plan-shaped content present
- **adversarial** — high-stakes domain, new abstractions, scope extension

## Dispatch

1. Read full PRD (no section splitting) — each persona is a parallel sub-agent (R28/R31).
2. Each agent returns JSON per `references/findings-schema.json`.
3. Synthesizer follows `references/synthesis.md`.
4. Apply `safe_auto` silently; gate `gated_auto` and `manual`.

## Amendment review (U7)

When reviewing `amendments/A<k>-*.md` drafts:

- **coherence** + **scope-guardian** always run against the frozen parent (read-only).
- Verify every `supersedes`/`retracts` target exists in the parent effective spec.
- Reject targets already retracted; require rationale for each retract.
- Flag undeclared contradictions with parent requirements; declared directives are the sanctioned path.
- Never edit the parent file — fixes apply only to the amendment draft.

## Handoff

→ `/pf-freeze` when no blocking manual trade-offs remain.
