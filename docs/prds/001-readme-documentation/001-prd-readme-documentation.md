---
date: 2026-06-24
topic: readme-documentation
frozen: true
frozen_at: 2026-06-24
---

# PRD 001: README and user documentation

## Overview

Shipwright needs user-facing documentation that matches the current plugin surface (v1.1.0, 34+ `sw-` commands,
four orchestrators, tier-gated doc pipeline). The README will become an onboarding hub; two guide files under
`docs/guides/` carry persona paths and command taxonomy. This is markdown-only v1 — no static site generator.

**Brainstorm input:** `docs/brainstorms/2026-06-24-readme-documentation-requirements.md`

## Goals

1. Reduce time-to-first-value for new adopters (install plugin → configure target repo → run first orchestrator).
2. Communicate outcome-led value (traceable specs, gated ship loop, compounding memory) and trust boundaries.
3. Map workstreams and tier routing so users pick the right orchestrator without reading all command files.
4. Establish a maintainable docs layout that does not duplicate `core/commands/` or `config.schema.json`.

## Non-Goals

- Docs site generator, auto-generated command tables, video demos, marketplace copy, SKILL rewrites (v1).
- Exhaustive per-command reference (~34 rows) or workflow playbooks with inlined orchestrator chains.
- `docs/guides/configuration.md` and `docs/guides/workflows.md` in v1.
- CI link-check automation in v1.
- Expanding `CONTRIBUTING.md` beyond plugin-author scope.

## Requirements

- **R1** README hero: tagline, three outcome bullets, trust line (human gates, never auto-merge).
- **R2** README two-repo mental model callout: global plugin install vs per-target-repo `/sw-setup`.
- **R3** README three-step plugin install quick start with copy-paste commands and reload instruction.
- **R4** README target-repo first-run section covering `/sw-setup` and zero-config in-repo memory path.
- **R5** README prerequisites checklist (git, `gh`, optional CodeRabbit / Recallium / Sentry) before install steps.
- **R6** README "when to use what" routing table: `/sw-doc`, `/sw-ship`, `/sw-feedback`, `/sw-debug`,
  `/sw-compound-ship`.
- **R7** README tier table (Quick / Standard / Full) with doc-chain entry and Quick bypass to implementation.
- **R8** README single mermaid workstream diagram (four nodes) with Quick-tier doc-path bypass annotated.
- **R9** `docs/guides/commands.md`: orchestrator-focused table (~12 rows) with scope/non-goals; links to
  `core/commands/sw-*.md`.
- **R10** `docs/guides/getting-started.md`: three persona paths (new feature, quick fix, production incident) with
  concrete done states; migration note for duplicate plugins and `sw-` vs `ce-`.
- **R11** All README and guide links use repository-relative paths valid on GitHub and in clones.
- **R12** README footer separates user guides from `CONTRIBUTING.md` (plugin development).
- **R13** `.gitignore` updated to version `docs/guides/`, `docs/brainstorms/`, `docs/prds/`, `docs/decisions/`.
- **R14** `.sw/layout.md` and `core/sw-reference/layout.md` document `docs/guides/` as living user docs (never
  frozen, not written by `sw-` doc commands).
- **R15** README length capped at ~150 lines; developer "Components" portability table demoted (link to
  CONTRIBUTING or collapsible section).
- **R16** Doc initiative success: new user can identify next command within 60 seconds of landing on README;
  manual link verification passes for README + both guides.

## Technical Requirements

- Authoring sources: `README.md`, `docs/guides/getting-started.md`, `docs/guides/commands.md`,
  `.gitignore`, `.sw/layout.md`, `core/sw-reference/layout.md`.
- Command table content must be sourced from existing `core/commands/*.md` `description:` frontmatter — manual
  curation v1, no generator script.
- Mermaid diagram must stay high-level; do not duplicate full chains from `sw-ship.md` or `sw-doc.md`.
- Claude Code install remains one README paragraph (parity note only).
- Do not bundle guides into `dist/cursor/` install tree v1.

## Security & Compliance

- User docs must not instruct committing secrets, API keys, or raw session transcripts.
- Provider credentials remain environment-sourced; docs reference config keys only.
- Migration guidance must warn about removing duplicate plugin directories to avoid command shadowing.

## Testing Strategy

| Scenario | Verification |
|----------|--------------|
| README hero present | Manual: tagline + 3 outcomes + trust line visible above fold |
| Install quick start | Manual: 3 copy-paste steps + reload |
| Two-repo model | Manual: distinct plugin install vs `/sw-setup` sections |
| Link hygiene | Manual: click all relative links on GitHub preview |
| Command table cap | Manual: `commands.md` row count ≤ 15 |
| Gitignore fix | `git check-ignore -v docs/guides/getting-started.md` returns not ignored |
| Layout contract | Manual: `docs/guides/` entry in `.sw/layout.md` |
| README length | `wc -l README.md` ≤ 150 |

## Rollout Plan

1. Fix `.gitignore` and layout contract (R13, R14) — unblocks tracked guides.
2. Draft `docs/guides/getting-started.md` and `docs/guides/commands.md`.
3. Rewrite README sections per R1–R8, R12, R15; preserve accurate install/config facts.
4. Manual link and length verification.
5. Single PR; no dist/ regeneration required (user docs outside `core/`).

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | Markdown-only v1, no doc site | Matches install model; 34 commands fit tables |
| D2 | Two guides only | Scope guardian: avoid four-file mini-site |
| D3 | ~12-row command table | Sustainable manual curation; links to core/commands for depth |
| D4 | Gitignore exceptions for docs/ | Feasibility P0: guides must be versioned |
| D5 | Demote Components table | User README should not lead with portability milestones |
| D6 | Defer CI link checker | v1 manual verification sufficient |

## Open Questions

None — resolved during doc-review synthesis. Implementation may keep `docs/plans/` gitignored if desired.
