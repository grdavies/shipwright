---
description: Create a sibling amendment for a frozen PRD with continued R-IDs and supersede/retract directives. Does not edit the parent file.
alwaysApply: false
---

# `/pf-amend`

Post-freeze correction path. Parent PRD stays byte-stable.

## Scope

- Input: frozen parent PRD path + delta description.
- Output: `prds/<n>-<slug>/amendments/A<k>-<short>.md`.
- Does **not** modify the parent file.

## Procedure

1. Read frozen parent; extract highest R-ID and existing amendments.
2. Assign next amendment number `A<k>` in `amendments/`.
3. Draft delta-only body with R-IDs continuing parent namespace.
4. Optional frontmatter directives:
   - `supersedes: [R<n>, ...]` — new continued R-ID replaces parent requirement.
   - `retracts: [R<n>, ...]` — parent requirement dropped (record rationale in body).
5. Run `/pf-doc-review` — coherence + scope-guardian verify targets exist, aren't retracted, rationale present.
6. Freeze amendment via `/pf-freeze`.
7. Update `prds/INDEX.md` amendment links.

## Guardrails

- Parent file is never written.
- Undeclared contradiction with parent → failure mode; declared supersede/retract → sanctioned.
- Amendment review scales to tier; coherence + scope-guardian always run against parent.

## Exemplar

`docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.amendments/A1-fail-closed-enforcement-point.md`
