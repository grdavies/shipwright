# Model tiering (R8 / R9 / R30)

Three layers — policy, dispatch, enforcement. See plan 006 KTD5.

## Layer 1 — Policy (`workflow.config.json`)

Semantic tiers map to **concrete platform model IDs** per project:

```json
"models": {
  "tiers": {
    "cheap": "composer-2-fast",
    "build": "composer-2",
    "deep": "gpt-5.5"
  },
  "aliases": {
    "fast": "cheap"
  },
  "roles": {
    "builder": "build",
    "reviewer": "build"
  }
}
```

- **`cheap` / `build` / `deep`** — policy vocabulary only; not valid in agent `model:` frontmatter.
- **Tier values** — Cursor/Claude dispatch IDs ([Cursor subagents](https://cursor.com/docs/subagents#model-configuration)).
- **`roles`** — builder vs reviewer floor; `roles.reviewer` tier must be ≥ `roles.builder`.

## Layer 2 — Dispatch (`agents/*.md`)

| Agent kind | Recommended `model:` |
|------------|----------------------|
| `pf-*-reviewer` | `inherit` — matches parent capability (CE pattern) |
| Specialist (must always run hot) | Concrete platform ID from `models.tiers` |

Do **not** put `cheap`/`build`/`deep` or vendor aliases like `sonnet` in shipped reviewer agents.

## Layer 3 — Enforcement

| Check | What |
|-------|------|
| `scripts/model-tier-check.sh` | Config `roles.reviewer` ≥ `roles.builder`; concrete agent models resolve via aliases to tier ≥ builder; `inherit` passes static check |
| `/pf-doc-review`, `pf-subagent-dispatch` | **Runtime R9:** parent model tier ≥ builder when dispatching `inherit` reviewers |

`inherit` reviewers cannot be fully R9-verified in CI — orchestrator must not run doc-review on a sub-`build` parent.

## Validate

```bash
bash scripts/model-tier-check.sh --config .pf/workflow.config.example.json
```
