---
date: 2026-06-26
topic: documentation-impact-review-persona
prd: docs/prds/020-documentation-impact-review-persona/020-prd-documentation-impact-review-persona.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 020 Documentation-impact review persona

Generated from the frozen PRD spec union (R1–R9). Phases are dependency-ordered per the Rollout Plan:
persona file → registry/selection/output → tier + complementarity → docs/dist/fixtures.

## Tasks

### 1. Persona agent file + taxonomy — S

- [ ] 1.1 Add the `sw-docs-currency-reviewer` persona agent file
  - **File:** `core/agents/sw-docs-currency-reviewer.md`
  - **Expected:** frontmatter (`name`, `description`, `model: inherit`); lens "given the proposed spec, which in-repo documentation artifacts are affected and what updates are required?"; evaluates the doc-surface taxonomy (README, `docs/guides/*`, `core/commands/`, `core/skills/`, `AGENTS.md`, `INVARIANTS.md`, config/schema docs, `.sw/layout.md`, `core/rules/`); maps a spec change to specific artifacts (path + required update); returns "no affected artifacts" when none; returns JSON per `skills/doc-review/references/findings-schema.json`
  - **R-IDs:** R1, R4

### 2. Registry, selection, and output contract — M

- [ ] 2.1 Add the persona to the registry, always-on core, and activation record
  - **File:** `core/skills/doc-review/SKILL.md`
  - **Expected:** persona added to the always-on core (non-Quick PRD-draft selection) and the selection algorithm + activation record; automatically part of the decision-record full panel; selection stays deterministic; Quick runs no panel
  - **R-IDs:** R2, R8
- [ ] 2.2 Add the persona to the PRD-amendment + decision-amendment review floors
  - **File:** `core/skills/doc-review/SKILL.md` (Amendment review U7 + Decision amendment review)
  - **Expected:** the persona runs in the PRD-amendment floor (alongside coherence + scope-guardian) and the decision-amendment floor; Quick unaffected
  - **R-IDs:** R3
- [ ] 2.3 Output/synthesis contract for doc recommendations
  - **File:** `core/skills/doc-review/SKILL.md`, `core/skills/doc-review/references/synthesis.md`
  - **Expected:** docs-currency findings carry recommended doc-artifact updates that fold into PRD requirements/tasks on acceptance via synthesis (`gated_auto`/`manual`); never silent auto-edit of docs/parent; never a hard freeze/ship block
  - **R-IDs:** R5

### 3. Tier routing + living-doc complementarity — S

- [ ] 3.1 Route the persona tier to `build`
  - **File:** `.cursor/workflow.config.json`, `core/sw-reference/model-routing.defaults.json`
  - **Expected:** `models.routing.agents.sw-docs-currency-reviewer: build` in both; `/sw-init` seeding picks it up; reviewer dispatch-check builder floor applies before spawn (PRD 017 R9)
  - **R-IDs:** R7
- [ ] 3.2 Ensure no living-doc currency-gate overlap
  - **File:** `core/skills/doc-review/SKILL.md` (scope note)
  - **Expected:** the persona explicitly scopes out `INDEX.md`/`COMPLETION-LOG.md`/`GAP-BACKLOG.md` (owned by the PRD 009 living-doc gate); no double-gating
  - **R-IDs:** R6

### 4. Docs + dist + fixtures — M

- [ ] 4.1 Regenerate `dist/` and pass the freshness gate
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `scripts/test/run-emitter-fixtures.sh` passes; `dist/` parity with `core/` (new agent file + SKILL changes propagated)
  - **R-IDs:** R9
- [ ] 4.2 Author the fixture suite
  - **File:** `scripts/test/run-doc-fixtures.sh` / doc-review selection suite (new scenarios)
  - **Expected:** all Testing-Strategy fixtures present and green (persona present, always-on core, amendment floors, artifact mapping, output folds to spec, no living-doc overlap, tier build)
  - **R-IDs:** R9
- [ ] 4.3 Update documentation
  - **File:** `core/skills/doc-review/SKILL.md` (registry/selection/activation/output), relevant guide
  - **Expected:** the persona, its selection (always-on + amendment floors), taxonomy, and output contract documented
  - **R-IDs:** R9

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | `docs-currency-persona-present` |
| R2 | 2.1 | `docs-currency-always-on-core` |
| R3 | 2.2 | `docs-currency-amendment-floor` |
| R4 | 1.1 | `docs-currency-artifact-mapping` |
| R5 | 2.3 | `docs-currency-output-folds-to-spec` |
| R6 | 3.2 | `docs-currency-no-living-doc-overlap` |
| R7 | 3.1 | `docs-currency-tier-build` |
| R8 | 2.1 | `docs-currency-always-on-core` (activation record) |
| R9 | 4.1, 4.2, 4.3 | `docs-currency-emitter-freshness`; `docs-currency-docs-presence` |

## Relevant Files

- `core/agents/sw-docs-currency-reviewer.md` — new persona (lens + taxonomy + findings contract)
- `core/skills/doc-review/SKILL.md` — registry, always-on core, amendment floors, activation record, output contract
- `core/skills/doc-review/references/synthesis.md` — doc-recommendation fold-into-spec handling
- `.cursor/workflow.config.json`, `core/sw-reference/model-routing.defaults.json` — `models.routing.agents` tier
- `scripts/test/run-doc-fixtures.sh` — selection + output-contract fixtures

## Notes

- Always-on core (R2) adds one persona to every non-Quick panel; the "no affected artifacts" finding (R4)
  bounds false-positive cost when a PRD touches no documented surface.
- Spec-time only in v1; a change-time/diff reviewer in `/sw-review`/ship is an explicit Non-Goal (future).
