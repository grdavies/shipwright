---
date: 2026-06-25
amends: docs/prds/009-autonomous-orchestration-conductor/009-prd-autonomous-orchestration-conductor.md
frozen: true
frozen_at: 2026-06-25
---

# Amendment A2: README + user-guide refresh for 009 command/workflow/usage changes

## Overview

PRD 009 and amendment A1 introduce user-visible changes — the autonomous conductor loop and its
legitimate-halt set, the `deliver.autonomy` and run-level-budget config, mechanical living-doc currency, and
the brainstorm↔PRD frontmatter fields. Parent R36 (per TR17) covers the **command/skill descriptions** at
the command surface plus the relevant `docs/guides/*` snippets for autonomy behavior, but it does not name
`README.md` and does not require comprehensive adopter-guide coverage of the new config knobs, gates,
living-doc behavior, or frontmatter fields. This amendment requires those user-facing surfaces to be updated for every
command/workflow/usage change introduced by 009 and its amendments, with a presence check and
removal of stale legacy references. It continues the parent R-ID namespace with **R56–R57** and changes no
parent requirement.

## Context

The plugin's value to adopters depends on the top-level docs matching actual behavior. Parent R36 / TR17
scope documentation to command/skill descriptions and "relevant `docs/guides/*`" for autonomy/parallelism;
they do not name `README.md` and do not require comprehensive coverage of the new config knobs, gates,
living-doc behavior, or frontmatter fields. This amendment adds the end-user-documentation requirement as a
distinct surface from R36 (which remains the command-description requirement): R36 governs the command
surface, R56 governs `README.md` + the narrative guides. The `docs/guides/` set is
`getting-started.md`, `workflows.md`, `configuration.md`, and `commands.md`.

## Goals

1. **Accurate adopter docs** — `README.md` and `docs/guides/*` reflect the conductor autonomy/parallelism
   model, the legitimate-halt set, the new config knobs, living-doc currency, and the brainstorm↔PRD
   frontmatter fields.
2. **Caught, not assumed** — a presence/accuracy check verifies the key new surfaces are documented and that
   stale legacy command references are gone, rather than relying on reviewer memory.

## Non-Goals

- Superseding parent R36 — R36 (command/skill descriptions) stands; R56 adds the README + narrative-guide
  surface.
- Rewriting unrelated guide content beyond what the 009 / A1 / A2 changes require.
- Documentation for orchestrators other than `/sw-deliver` beyond the enumerated adoption path (parent
  R33/R35 own that; their *implementation* is out of parent scope).

## Requirements

- **R56** `README.md` and the `docs/guides/*` set (`getting-started.md`, `workflows.md`, `configuration.md`,
  `commands.md`) MUST be updated to reflect every command, workflow, and usage change introduced by PRD 009
  and its amendments — the conductor autonomy/parallelism behavior and legitimate-halt set, the
  `deliver.autonomy` knob and run-level budget (with defaults), mechanical living-doc currency
  (INDEX/COMPLETION-LOG/GAP-BACKLOG) behavior, and the brainstorm↔PRD frontmatter fields — so adopters
  reading the top-level documentation see accurate usage. This complements parent R36 (command/skill
  descriptions); it does not supersede it.
- **R57** A docs presence check MUST assert that the key new surfaces are documented in
  `README.md`/`docs/guides/*` (the `deliver.autonomy` config and its default, the legitimate-halt set,
  living-doc currency, and the brainstorm↔PRD frontmatter fields) and that stale legacy command references
  predating the `sw-` rename (e.g. `/pf-*` / `pf-`) are removed from those user-facing docs; it MUST be
  wired into the documentation/test gate.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `user-docs-009-coverage` | `README.md` + each `docs/guides/*` file names the new autonomy/config/living-doc/frontmatter surfaces | R56, R57 |
| `user-docs-no-legacy-refs` | no `/pf-*` / `pf-` legacy command references remain in `README.md` or `docs/guides/*` | R57 |

Emitter propagation does not apply — `README.md` and `docs/guides/*` are repo-level adopter docs, not
`core/`-emitted artifacts.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-A2-1 | R56 adds README + narrative guides as a distinct documentation surface from parent R36, not a supersede | R36 governs command/skill descriptions; the adopter-facing README and guides are a separate surface the parent never named. Additive avoids disturbing R36's existing task/fixture mapping. |
| DL-A2-2 | A presence check (R57) backs the doc update mechanically, including stale-reference removal | Parent R36 is verified by review, which lets drift persist (e.g. the legacy `pf-` reference still in repo); a mechanical check is consistent with A1's fail-closed doc gates. |

## Open Questions

None.
