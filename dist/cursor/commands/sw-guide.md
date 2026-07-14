---
description: Read-only diagnostic that explains sw- workflow behavior and checks current repo config/state/planning-backend reachability, citing relevant guides. Never mutates config, git, or the planning store.
alwaysApply: false
---

# `/sw-guide`

The read-only "why is this happening / how does this work" surface. Explains workflow behavior, diagnoses
the current repo's config/state/planning-backend health, and points at the right guide — without touching
anything.

## Scope

- Input: a question about workflow behavior (`/sw-guide why did deliver halt?`), or bare `/sw-guide` for a
  general health diagnostic.
- Output: an explanation grounded in the actual `core/commands/`, `core/skills/`, and `docs/guides/` content
  plus live, read-only diagnostic probes of this repo's config/state/backend.
- Does **not** write, fix, configure, or dispatch anything — `/sw-init` (config), `/sw-status` (living
  status), and `/sw-debug` (RCA) own mutation-adjacent or authoritative-report paths respectively; `/sw-guide`
  is pure explanation + read-only diagnosis.

## Procedure

### 1. Diagnose (read-only probes only)

Run only inspection/probe commands — never anything that writes:

```bash
python3 scripts/sw-configure.py drift-check                      # config vs schema drift
python3 scripts/verify-unconfigured.py                            # placeholder verify.* detection
python3 scripts/planning-doctor.py                                 # planning-store backend reachability
python3 scripts/shipwright-state.py read                           # current worktree state
python3 scripts/host-doctor.py                                     # git host/forge reachability
```

Summarize findings in plain language — do not just paste raw JSON.

### 2. Explain

For a behavior question, ground the answer in the actual command/skill contract rather than general
knowledge:

1. Identify the command(s)/skill(s) the question is about.
2. Read the relevant `core/commands/sw-*.md` and/or `core/skills/*/SKILL.md` for the authoritative procedure
   and guardrails.
3. Answer citing the specific mechanism (e.g. "deliver halted because `deliver.autonomy.maxIterations` was
   hit — see `core/commands/sw-deliver.md` **Hard stops**"), not a generic restatement.
4. Cite the matching `docs/guides/*.md` reference (configuration, workflows, decision-tree, glossary) so the
   operator has a durable pointer, not just a one-off chat answer.

### 3. Report

- Diagnostic summary (config drift, verify status, planning-backend reachability, current state) when run
  bare or as context for a behavior question.
- For a specific question: the grounded explanation + guide citation.
- Never a fix or a config change — if a fix is warranted, name the command that owns it (`/sw-init` for
  config, `/sw-debug` for RCA, `/sw-status` for living-status reconcile) rather than performing it.

**Communication intensity:** normal

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-guide`.

## Guardrails

- Read-only, always — no writes to config, git, memory, or the planning store, and no dispatch of another
  `sw-` command on the operator's behalf.
- Grounded answers only — cite the actual command/skill/guide text, never invent behavior that is not in the
  loaded procedure.
- When diagnosis surfaces an actionable fix, name the owning command instead of performing the fix.
