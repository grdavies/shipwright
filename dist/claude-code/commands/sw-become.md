---
description: Research and crystallize a new consult persona into one fixed local destination with confirm-before-write. Does not overwrite an existing persona, does not run the doc-review panel, and does not copy proprietary text or assets.
alwaysApply: false
---

# `/sw-become`

Turn a rough persona idea ("a performance-obsessed pragmatist", "someone who's shipped three failed
migrations") into a durable, consultable persona that `/sw-ask` can route questions to later.

## Scope

- Input: a persona idea, domain, or stance description.
- Output: one new file under `core/personas/<slug>.md` (on confirm) + a `models.routing.agents.<slug>` entry
  in `.cursor/workflow.config.json`.
- Does **not** overwrite an existing persona file, run `/sw-doc-review`, or embed proprietary text/assets
  (competitor craft patterns are inspiration only — R38).

## Fixed local destination

Every crystallized persona lands at **exactly one** path: `core/personas/<slug>.md`. This is a distinct
catalog from `core/agents/sw-*-reviewer.md` (the fixed eight doc-review personas wired into the capability
manifest) — `/sw-become` never edits or extends that catalog.

## Fixed schema

```yaml
---
name: <slug>
description: <one sentence domain + one sentence what it will not weigh in on>
domain: <short domain label, e.g. "performance", "migration-risk">
stance: <one or two sentences — the persona's core conviction>
createdAt: YYYY-MM-DD
source: sw-become
---

<persona body: voice, framing questions it asks, guardrails on what it will not opine on>
```

## Procedure

1. **Research** — read `core/agents/*.md` and `core/personas/*.md` for near-duplicate domains; read relevant
   `docs/decisions/` and `docs/guides/` for repo context the persona should be grounded in. Flag (do not
   silently proceed on) a near-duplicate domain — offer to route to `/sw-ask --persona <existing>` instead.
2. **Crystallize** — draft the fixed-schema file above. Keep the stance sharp and specific — a persona that
   agrees with everything is not useful. Never copy proprietary competitor text/assets verbatim; inspiration
   only (R38).
3. **Confirm-before-write** — show the full draft to the operator. Accept `write` or `cancel` only; no
   partial/implicit write. `cancel` creates nothing.
4. **No-overwrite guard** — if `core/personas/<slug>.md` already exists, refuse the write. Offer: pick a
   different slug, or route to manually editing the existing persona (never silently overwrite).
5. **Model-tier binding** — on confirmed write, also add
   `models.routing.agents.<slug>: "<tier>"` to `.cursor/workflow.config.json` (default `build`; ask if the
   operator wants `cheap`/`mid`/`deep` instead). This makes the persona's dispatch tier resolvable via
   `python3 scripts/resolve-model-tier.py --agent <slug>` the same way doc-review personas resolve — never
   left as a bare unresolvable `inherit`.
6. **Report** — persona path, model tier bound, and the exact `/sw-ask --persona <slug> "<question>"` command
   to consult it.

**Communication intensity:** normal

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-become`.

## Guardrails

- Confirm-before-write is mandatory — never write on the first draft without an explicit `write`.
- Never overwrites an existing `core/personas/<slug>.md` — collision always routes to a rename or an explicit
  "edit the existing persona instead" note.
- Never embeds secrets, credentials, or proprietary competitor text/assets in a persona file.
- Model-tier binding is part of the same confirmed write — a persona is never left without a resolvable tier.
