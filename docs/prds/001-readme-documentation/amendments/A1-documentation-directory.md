---
date: 2026-06-24
amends: docs/prds/001-readme-documentation/001-prd-readme-documentation.md
frozen: true
frozen_at: 2026-06-24
supersedes: [R9, R10, R13, R14]
---

# Amendment A1: User docs live in `documentation/`, not `docs/`

## Overview

`docs/` is gitignored for Shipwright development artifacts (brainstorms, PRDs, decisions). User-facing
documentation moves to tracked `documentation/` at repo root. Supersedes R9, R10, R13, R14 from parent PRD.

## Goals

1. Separate plugin dev docs (`docs/`, ignored) from adopter-facing docs (`documentation/`, tracked).
2. Avoid `.gitignore` exceptions that blur artifact boundaries.

## Non-Goals

- Changing `.gitignore` rules for `docs/`.
- Adding `documentation/` to `.sw/layout.md` (pipeline contract only).
- `documentation/configuration.md` or `documentation/workflows.md` in v1.

## Requirements

- **R9** `documentation/commands.md`: orchestrator-focused table (~12 rows) with scope/non-goals; links to
  `core/commands/sw-*.md`.
- **R10** `documentation/getting-started.md`: three persona paths with concrete done states; migration note for
  duplicate plugins and `sw-` vs `ce-`.
- **R13** `.gitignore` unchanged — `docs/` stays ignored; `documentation/` tracked at repo root.
- **R14** README and `CONTRIBUTING.md` document `documentation/` as user-doc root (outside `.sw/layout.md`).
- **R17** README links to `documentation/getting-started.md` and `documentation/commands.md`.
- **R18** User docs never live under ignored `docs/`.

## Testing Strategy

| Scenario | Verification |
|----------|--------------|
| User docs tracked | `git check-ignore -v documentation/getting-started.md` returns not ignored |
| Dev docs ignored | `git check-ignore -v docs/prds/INDEX.md` returns ignored |
| README links | Manual: README → `documentation/*.md` resolve on GitHub |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| D7 | `documentation/` at repo root | Clean separation; no gitignore surgery |
| D8 | Outside `.sw/layout.md` | Layout governs sw- pipeline paths only |

## Context

Parent PRD placed guides under `docs/guides/` with gitignore exceptions. That conflates local dev artifacts
with user docs and requires maintaining exception rules.

## Rollout adjustment

1. Create `documentation/getting-started.md` and `documentation/commands.md`.
2. Rewrite README with `documentation/` links.
3. Add brief pointer in `CONTRIBUTING.md`.

## Open Questions

None.
