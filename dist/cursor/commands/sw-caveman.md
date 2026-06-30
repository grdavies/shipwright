---
description: Override caveman communication intensity for the current chat until the next command dispatch. Does not load external skills or change artifact file fidelity.
alwaysApply: false
---

# `/sw-caveman`

Manual override for chat communication intensity. References bundled `core/communication/caveman-core.md` only.

## Args

`normal` | `lite` | `full` | `ultra` — set override for this chat until the next `sw-*` command dispatch.

No args: print the current resolved intensity (routing default, active command, or pending override).

## Scope

- Overrides `communication.routing` for orchestration chat only.
- Does **not** load `~/.agents/skills/caveman/SKILL.md` or wenyan variants.
- Does **not** compress artifact file content (brainstorm, PRD, tasks, commits, PR bodies).

## Guardrails

- Closed vocabulary: `normal` | `lite` | `full` | `ultra` only.
- Wenyan intensities are rejected.

**Communication intensity:** full (override command; does not inherit)

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-caveman`.
