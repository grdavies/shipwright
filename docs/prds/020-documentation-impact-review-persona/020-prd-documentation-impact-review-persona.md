---
date: 2026-06-26
topic: documentation-impact-review-persona
brainstorm: docs/brainstorms/2026-06-26-documentation-impact-review-persona-requirements.md
frozen: true
frozen_at: 2026-06-26
---

# PRD 020 — Documentation-impact review persona

## Overview

When a change is specced in this repo, the broad in-repo documentation surface — `README.md`, `docs/guides/*`,
command/skill docs under `core/commands/` + `core/skills/`, `AGENTS.md`, `INVARIANTS.md`, config/schema docs,
`.sw/layout.md`, and rule prose — can silently fall out of date. Coverage today is **partial**: living-doc
currency gates keep `INDEX.md` / `COMPLETION-LOG.md` / `GAP-BACKLOG.md` accurate (PRD 009); `docs-presence` /
`docs-currency` hooks and `docs-link-check.py` check presence/links; the `comment-accuracy` code-review agent
checks in-code comments. But **no review persona maps a proposed change to the documentation artifacts it
affects and recommends concrete documentation updates for inclusion in the spec.**

This PRD adds a reusable `sw-doc-review` persona — `sw-docs-currency-reviewer` — that, **at spec-time**, takes
the proposed spec and returns the specific in-repo documentation artifacts the change affects plus the required
updates, surfaced through the normal doc-review synthesis so accepted recommendations fold into the PRD/tasks
as documentation requirements. It is added to the **always-on core** so every non-Quick review considers
documentation impact. It closes GAP-BACKLOG row 40 and derives from the frozen brainstorm
`docs/brainstorms/2026-06-26-documentation-impact-review-persona-requirements.md` (R1–R9).

It is **complementary** to the living-doc currency gate (which governs only the three living indexes) and to
the `comment-accuracy` code reviewer (in-code comments) — this persona covers arbitrary documentation
artifacts at spec-time. A change-time / diff-based variant in `/sw-review` / ship is an explicit future
(Non-Goals), not v1.

## Goals

1. Every non-Quick doc review surfaces which documentation artifacts a proposed change affects and what updates
   they need — not generic advice, but specific artifact → update mappings.
2. Accepted documentation recommendations fold into the PRD/tasks as requirements via the existing synthesis,
   so documentation work is planned with the change rather than discovered after merge.
3. The persona reuses the existing doc-review machinery (agent file, registry, findings schema, tier routing)
   with no new review subsystem.

## Non-Goals

- A **change-time / diff-based** documentation reviewer in `/sw-review` or ship — explicit future; v1 is
  spec-time only.
- Auto-editing documentation or the parent doc — the persona recommends only; it never writes docs (mirrors
  the existing persona non-edit rule).
- A hard freeze/ship **block** on documentation findings — recommendations are gated_auto/manual via
  synthesis, not a blocking gate.
- Replacing or double-gating the living-doc currency gate (PRD 009) for `INDEX.md` / `COMPLETION-LOG.md` /
  `GAP-BACKLOG.md`.
- Changing the `comment-accuracy` code-review agent (in-code comments) or any code-review persona.

## Requirements

R1–R9 are carried forward from the frozen brainstorm (stable namespace; do not renumber). Requirement text
receives only clarifying edits.

### The persona

- **R1** A new persona `sw-docs-currency-reviewer` MUST be added (agent file `core/agents/sw-docs-currency-reviewer.md`),
  with the lens: "given the proposed spec, which in-repo documentation artifacts are affected, and what updates
  are required?" It MUST return JSON per `skills/doc-review/references/findings-schema.json`.
- **R4** The persona MUST evaluate a defined **doc-surface taxonomy** — `README.md`, `docs/guides/*`,
  command docs (`core/commands/`), skill docs (`core/skills/`), `AGENTS.md`, `INVARIANTS.md`, config/schema
  docs, `.sw/layout.md`, and rule prose (`core/rules/`) — and MUST map a spec change to **specific** affected
  artifacts (path + required update), never generic "update the docs" advice. When no documented surface is
  affected it MUST return an explicit "no affected artifacts" finding.

### Selection

- **R2** The persona MUST be added to the doc-review **always-on core** for non-Quick PRD-draft reviews
  (joining the existing five), and is therefore automatically part of the decision-record **full** panel.
- **R3** The persona MUST also run in the **PRD-amendment** review floor (currently coherence + scope-guardian)
  and the **decision-amendment** review floor, because amendments change documented behavior — exactly when
  docs drift. Quick tier still runs no panel.
- **R8** The doc-review **selection algorithm and activation record** MUST be updated to include the persona as
  always-on core; selection remains deterministic (no model judgment).

### Output contract

- **R5** Persona findings MUST carry recommended documentation-artifact updates that, on acceptance via the
  doc-review **synthesis** (`gated_auto` / `manual`), fold into the PRD requirements / tasks as documentation
  requirements. The persona MUST NOT silently auto-edit docs or the parent, and its findings MUST NOT be a hard
  freeze/ship block.
- **R6** The persona MUST be **complementary** to the living-doc currency gate: it MUST NOT re-gate or
  duplicate the `INDEX.md` / `COMPLETION-LOG.md` / `GAP-BACKLOG.md` currency the PRD 009 gate already enforces;
  its scope is arbitrary documentation artifacts at spec-time.

### Cross-cutting

- **R7** The persona tier MUST be `build` via `models.routing.agents` (both `.cursor/workflow.config.json` and
  the bundled `core/sw-reference/model-routing.defaults.json`), R9-compliant; the reviewer dispatch-check
  builder floor applies before spawn (PRD 017 R9 / `sw-subagent-dispatch`).
- **R9** All behavior authored in `core/` MUST propagate to `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all` (freshness gate passing), be covered by fixtures (see Testing Strategy), and
  be documented in `core/skills/doc-review/SKILL.md` (registry + selection + activation record) and the
  relevant guide.

## Technical Requirements

- **TR1 — Persona agent file.** Add `core/agents/sw-docs-currency-reviewer.md` (frontmatter `name`,
  `description`, `model: inherit`) with the R1/R4 lens + taxonomy and the findings-schema return contract
  (R1, R4).
- **TR2 — Registry + selection.** Update `core/skills/doc-review/SKILL.md`: add the persona to the always-on
  core list, the selection algorithm, the activation record, the PRD-amendment floor (U7), and the
  decision-amendment floor; decision-record full panel picks it up automatically (R2, R3, R8).
- **TR3 — Output/synthesis contract.** Document in the SKILL (and `references/synthesis.md` if needed) that
  docs-currency recommendations are spec-time doc requirements that fold into the PRD/tasks on acceptance —
  `gated_auto` / `manual`, never silent auto-edit, never a hard block (R5).
- **TR4 — Tier routing.** Add `sw-docs-currency-reviewer: build` to `models.routing.agents` in
  `.cursor/workflow.config.json` and `core/sw-reference/model-routing.defaults.json`; `/sw-init` seeding picks
  it up (R7).
- **TR5 — Living-doc complementarity.** Ensure no overlap/double-gating with the PRD 009 living-doc currency
  gate; the persona explicitly scopes out the three living indexes (R6).
- **TR6 — Emitter + docs + fixtures.** Regenerate `dist/`; update the SKILL + guide; add the Testing Strategy
  fixtures (R9).

## Security & Compliance

- **Read-only reviewer.** The persona reads the proposed spec + repo docs and returns findings JSON; it never
  edits the parent doc or repository documentation (existing persona non-edit invariant). No new write surface.
- **No new credential/data surface.** Documentation review introduces no auth, PII, or external-API exposure;
  it operates on in-repo text only.
- **Dispatch binding (R9 floor).** The persona is dispatched via the reviewer dispatch-check with a resolved
  concrete `build`-tier model (never `inherit` from the parent session), per PRD 017 R9 / `sw-subagent-dispatch`.
- **Synthesis gating preserved.** Recommendations route through the existing synthesis `gated_auto` / `manual`
  gates; nothing auto-applies, so a bad recommendation cannot silently mutate docs or the spec.

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (doc-review suites).

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `docs-currency-persona-present` | `sw-docs-currency-reviewer` agent file exists with the lens + findings-schema return | R1 |
| `docs-currency-always-on-core` | the persona is in the always-on core; fires on every non-Quick PRD review; activation record lists it | R2, R8 |
| `docs-currency-amendment-floor` | the persona runs in the PRD-amendment + decision-amendment floors; Quick runs no panel | R3 |
| `docs-currency-artifact-mapping` | findings map a spec change to specific artifacts from the taxonomy; "no affected artifacts" returned when none | R4 |
| `docs-currency-output-folds-to-spec` | accepted recommendations fold into PRD/tasks via synthesis (`gated_auto`/`manual`); no silent auto-edit; not a hard block | R5 |
| `docs-currency-no-living-doc-overlap` | the persona does not re-gate `INDEX.md`/`COMPLETION-LOG.md`/`GAP-BACKLOG.md` (no double-gating) | R6 |
| `docs-currency-tier-build` | `models.routing.agents` maps the persona to `build`; reviewer dispatch-check floor applies | R7 |
| `docs-currency-emitter-freshness` | `dist/` regenerated and fresh | R9 |
| `docs-currency-docs-presence` | doc-review SKILL + guide describe the persona, selection, and output contract | R9 |

## Rollout Plan

- **Single feature branch** `feat/documentation-impact-review-persona`, dependency-ordered: (1) persona agent
  file + taxonomy + findings contract (R1, R4; TR1); (2) registry + selection + activation record + amendment
  floors + output/synthesis contract (R2, R3, R5, R8; TR2, TR3); (3) tier routing + living-doc
  complementarity (R6, R7; TR4, TR5); (4) docs + dist + fixtures (R9; TR6).
- **Backward compatible.** Adding an always-on core persona increases each non-Quick panel by one persona;
  selection stays deterministic and Quick tier is unaffected. No existing persona changes.
- **Bootstrap caution.** Land with the selection + output-contract fixtures green before relying on its
  recommendations to seed doc tasks.
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | New standalone PRD (a reusable persona), not a per-PRD doc task | PRD 018 R18/R33 are one-off doc tasks for that PRD; this is a reusable reviewer added to the doc-review machinery, applicable to every future spec (scope-guardian + product lenses; the gap row's own distinction). |
| DL-2 | Spec-time persona only in v1; change-time/diff review deferred | Reuses the existing persona machinery (which reviews PRD drafts) and lands recommendations as plannable requirements; a diff-based change-time reviewer is a larger, separate surface in `/sw-review`/ship (operator selection; scope-guardian lens). |
| DL-3 | Always-on core (operator-selected) | Maximum coverage; documentation impact is relevant to nearly every change. The persona returns an explicit "no affected artifacts" finding when a PRD touches no documented surface, bounding the false-positive cost (operator selection). |
| DL-4 | Recommendations fold into the spec via synthesis; never auto-edit, never a hard block | Keeps the human/author in control of documentation requirements and avoids a brittle freeze blocker, while still planning doc work with the change (product + adversarial lenses). |
| DL-5 | Include in PRD-amendment + decision-amendment floors | Amendments change documented behavior and are a prime drift source; excluding them would leave the most common post-freeze change path uncovered (coherence + scope-guardian lenses). |
| DL-6 | Complementary to the living-doc currency gate; no double-gating | The PRD 009 gate owns the three living indexes; this persona owns arbitrary doc artifacts at spec-time — overlapping would double-gate and confuse findings ownership (coherence lens). |

## Open Questions

None. Where-it-runs (spec-time), output contract (folds into spec via synthesis), and selection (always-on
core) are operator-resolved (DL-2, DL-3, DL-4); amendment-floor inclusion is resolved in DL-5.
