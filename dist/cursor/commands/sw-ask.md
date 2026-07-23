---
description: Route a free-form question to the best-fit existing persona for a read-only consult. Does not draft, review, freeze, dispatch a pipeline command, or mutate any file, config, or planning-store artifact.
alwaysApply: false
---

# `/sw-ask`

A read-only consult. Pick the existing persona whose declared domain best matches the question, answer in
that persona's voice, and stop — no pipeline side effects, ever.

## Scope

- Input: a free-form question (`/sw-ask <question>`), optionally `--persona <id>` to force a specific persona.
- Output: the chosen persona's id + one-line rationale for the pick, followed by its answer.
- Does **not** write, edit, freeze, dispatch `/sw-doc-review`, `/sw-brainstorm`, or any other command; does
  not persist the exchange to memory or the planning store.

## Persona catalog

`/sw-ask` selects from the existing `core/agents/sw-*-reviewer.md` persona catalog (the same eight personas
`/sw-doc-review` dispatches) plus any personas crystallized via `/sw-become` under `core/personas/`. It never
invents a new persona inline — that is `/sw-become`'s job.

| Persona | Best-fit domain |
| --- | --- |
| `sw-coherence-reviewer` | Internal consistency, contradictions, terminology drift |
| `sw-feasibility-reviewer` | Will this actually work — dependency, migration, integration risk |
| `sw-scope-guardian-reviewer` | Is this in scope, unjustified complexity, boundary creep |
| `sw-product-reviewer` | Premise, strategic consequence, what-to-build-and-why |
| `sw-adversarial-reviewer` | Failure scenarios, edge cases, abuse paths |
| `sw-docs-currency-reviewer` | Which docs need to change, adopter-doc impact |
| `sw-security-reviewer` | Auth, data handling, API exposure, trust boundaries |
| `sw-design-reviewer` | UI/UX flow, interaction design, accessibility |
| Any `core/personas/<slug>.md` crystallized via `/sw-become` | Whatever domain that persona was crystallized for |

## Procedure

1. Read the question. If `--persona <id>` is given and that persona exists, use it — skip selection.
2. **Select** — match the question's dominant domain against the catalog table above (and any
   `core/personas/` entries); on a tie or no clear match, default to `sw-product-reviewer` (broadest
   generalist framing) and say so explicitly rather than silently guessing.
3. **Consult** — answer as that persona, grounded in its declared stance from its agent file. This is a
   conversational read-only answer, not a `findings-schema.json` report — no autofix classes, no
   applied/gated/manual routing.
4. **No side effects** — never write a file, call `planning_store.put`, call `memory-preflight` write mode,
   or dispatch another `sw-` command as part of answering.
5. Report the persona chosen + one-line rationale, then the answer.

**Communication intensity:** normal

**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-ask`. The consulted
persona's own voice does not change its dispatch model tier; `/sw-ask` answers inline rather than spawning a
Task, so no separate persona-tier resolution is required for the common case. When the question is complex
enough to warrant a dedicated sub-agent consult, dispatch the persona as a `readonly: true` Task and resolve
its tier via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --agent <persona-id>` first.

## Guardrails

- Read-only, always — no mutation of planning store, git, workflow config, or memory.
- Never a substitute for `/sw-doc-review` (structured multi-persona panel with synthesis) or `/sw-brainstorm`
  (requirements authoring) — those remain the only paths that produce pipeline artifacts.
- Never silently invents a persona not in the catalog — unmatched domains fall back to the generalist
  default with an explicit note, or the operator is pointed at `/sw-become`.
