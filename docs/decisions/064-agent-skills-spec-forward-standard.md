# 064 — Agent Skills spec as forward design standard

**Status:** accepted  
**Date:** 2026-07-11  
**PRD:** 064 (R16)  
**Workstream:** B — progressive disclosure and standards conformance

## Context

Shipwright skills are authored as `SKILL.md` files with YAML frontmatter, consumed by Cursor and
Claude Code adapters under `dist/`. Prior conventions mixed plugin-specific `capability:` blocks,
oversized monolithic skill bodies, and inconsistent `name`/`description` contracts. PRD 064 phases 1–3
align identity, progressive disclosure, and validation gates; this decision records the **forward**
authoring standard for all new and materially revised skills.

The [Agent Skills open specification](https://agentskills.io/specification) defines portable skill
metadata, progressive disclosure via `references/`, and description shape suitable for tool routing.

## Decision

1. **Forward standard:** New skills and substantive rewrites MUST conform to the Agent Skills spec
   closed top-level field set (`name`, `description`, optional `license`, `allowed-tools`,
   `metadata`, `compatibility`).
2. **Progressive disclosure:** SKILL.md body MUST stay within the 500-line budget; depth-1
   `references/*.md` hold run-mode matrices, recovery procedures, and worked examples. Reference
   files MUST NOT link to further nested reference tiers.
3. **Description contract:** `description` MUST state what the skill does and include an explicit
   "Use when..." trigger with matchable keywords; non-goals where ambiguity is likely; ≤1024 chars.
4. **Name identity:** `name` MUST equal the unprefixed kebab-case directory name (R13); dist
   adapters mirror core identity without `sw-` prefixes on skill `name`.
5. **Capability relocation:** Shipwright-specific capability metadata lives under
   `metadata.shipwright-capability` with a one-release dual-read window (R14).
6. **Enforcement:** `scripts/skills-spec-guard.py` (phase 3) is the mechanical gate; until wired,
   authors follow this ADR and progressive-disclosure refactors (phases 1–2) as the normative
   template.

## Consequences

- **Positive:** Tool routing improves; skills shrink to focused entrypoints; dist parity and guard
  fixtures have a single external spec to cite.
- **Negative:** Large legacy skills require refactors (deliver, conductor completed in phase 2);
  description rewrites are labor-intensive (phase 3).
- **Neutral:** Existing skills remain valid during dual-read; superseded top-level `capability:`
  blocks are tolerated until the guard reaches zero findings.

## Compliance

| Surface | Requirement |
| --- | --- |
| `core/skills/**/SKILL.md` | Spec field set + budgets |
| `dist/cursor/skills/`, `dist/claude-code/skills/` | Mirrored identity and references |
| `scripts/skills-spec-guard.py` | Authoritative mechanical check (phase 3) |
| `scripts/check-gate.py` | Guard registered when phase 3 lands |

## References

- PRD 064 — agentic quality patterns and standards conformance
- Agent Skills specification — https://agentskills.io/specification
- Phase 2 task 2.3 — record forward standard ADR
