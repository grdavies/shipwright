# Model tiering (R8 / R9 / R30)

Three layers — policy, dispatch, enforcement. PRD 008 adds **four semantic tiers** and per-command/skill
routing defaults.

## Layer 1 — Policy (`workflow.config.json`)

Semantic tiers map to **concrete platform model IDs** per project. `/sw-setup` seeds the block from the
detected platform catalog plus `core/sw-reference/model-routing.defaults.json`.

```json
"models": {
  "tiers": {
    "cheap": "composer-2.5-fast",
    "build": "composer-2.5",
    "mid": "gpt-5.5-medium",
    "deep": "claude-opus-4-8-thinking-high"
  },
  "aliases": { "fast": "cheap" },
  "roles": { "builder": "build", "reviewer": "build" },
  "routing": {
    "commands": { "sw-prd": "deep", "sw-doc": "inherit" },
    "skills": { "prd": "deep" },
    "agents": { "sw-coherence-reviewer": "build", "correctness": "deep" }
  }
}
```

### Four tiers

| Tier | Typical use |
| --- | --- |
| `cheap` | Mechanical ops — triage, verify, commit, status |
| `build` | Implementation, debug, review orchestration (`models.roles.builder`) |
| `mid` | Medium reasoning — gaps, simplify, memory-sync, non-high-stakes panel specialists |
| `deep` | Doc authoring, high-stakes review, adversarial/security personas |

- **`cheap` / `build` / `mid` / `deep`** — policy vocabulary only; not valid in agent `model:` frontmatter.
- **`inherit`** — routing sentinel only (orchestrators `sw-doc`, `sw-ship`, `sw-deliver`, `sw-compound-ship`);
  resolve delegated children via `resolve-model-tier.sh --delegate`.
- **Tier values** — Cursor/Claude dispatch IDs ([Cursor subagents](https://cursor.com/docs/subagents#model-configuration)).
- **`roles`** — builder vs reviewer floor; `roles.reviewer` tier must be ≥ `roles.builder`.

### Platform catalogs (`scripts/seed-model-config.sh`)

| Tier | Cursor | Claude Code |
| --- | --- | --- |
| `cheap` | `composer-2.5-fast` | `claude-4.5-haiku-thinking` |
| `build` | `composer-2.5` | `claude-4.6-sonnet-medium-thinking` |
| `mid` | `gpt-5.5-medium` | `claude-4.6-sonnet-medium-thinking` |
| `deep` | `claude-opus-4-8-thinking-high` | `claude-opus-4-8-thinking-high` |

**Claude mid collapse:** on `claude-code`, `mid` and `build` share the same Sonnet ID — semantic `mid` still
exists in routing for cross-platform parity; only the concrete ID collapses.

### Routing resolution

```bash
bash scripts/resolve-model-tier.sh --command sw-prd
bash scripts/resolve-model-tier.sh --skill prd
bash scripts/resolve-model-tier.sh --command sw-doc --delegate sw-prd
bash scripts/resolve-model-tier.sh --tier deep
bash scripts/resolve-model-tier.sh --agent sw-coherence-reviewer
```

Config `models.routing` (including `models.routing.agents` for per-reviewer/native-panel tiers) overrides
bundled defaults; missing keys fall back to `core/sw-reference/model-routing.defaults.json`.

## Layer 2 — Dispatch (`commands/`, `skills/`, `agents/`)

| Surface | Tier documentation |
| --- | --- |
| `core/commands/sw-*.md` | `**Model tier:**` line + resolver hint |
| `core/skills/*/SKILL.md` | tier + subagent dispatch tier when Task tool used |
| `agents/sw-*-reviewer` | `model: inherit` — matches parent capability (CE pattern) |
| Specialist agents | Concrete platform ID from `models.tiers` when hot path required |

Do **not** put `cheap`/`build`/`mid`/`deep` or vendor aliases like `sonnet` in shipped reviewer agents.

## Layer 3 — Enforcement

| Check | What |
| --- | --- |
| `scripts/model-tier-check.sh` | Four-tier order; `roles.reviewer` ≥ `roles.builder`; concrete agent models ≥ builder; `inherit` passes static check |
| `scripts/model-routing-check.sh` | Defaults cover all shipped commands/skills; valid tier keys; R27 parity with communication defaults when present |
| `scripts/resolve-model-tier.sh` | Runtime tier → concrete ID; `inherit` → `modelId: null` exit 0 |
| `scripts/resolve-intensity.sh` | Runtime intensity resolution with command → skill → agent → default precedence |
| `/sw-doc-review`, `sw-subagent-dispatch` | **Runtime R9:** parent model tier ≥ builder when dispatching `inherit` reviewers |
| `scripts/dispatch-check.sh` | Fail-closed binding check (`binding:no-model`, `binding:no-intensity`, `harness:capacity`) before Task spawn |

### Task hook (R5 — registered, forward-compatible)

A `preToolUse` hook (`core/hooks/before_task_dispatch.py`) resolves `updated_input.model`
via `resolve-model-tier.sh --agent` and is **registered in both platform `hooks.json` files**
(Cursor `preToolUse`, Claude Code `PreToolUse`). Platform effectiveness is unverified:
Cursor does not currently apply `updated_input` for Task; Claude Code behavior is untested.
The hook fails open on unexpected runtime errors and logs mutation attempts to stderr. Mechanical dispatch
preflight + `dispatch-check.sh` remain the enforcement floor regardless of hook effectiveness. See
`core/sw-reference/model-tier-hook-feasibility.md` for full rationale.

`inherit` reviewers cannot be fully R9-verified in CI — orchestrator must not run doc-review on a sub-`build` parent.

## Validate

```bash
bash scripts/model-tier-check.sh --config .sw/workflow.config.example.json
bash scripts/model-routing-check.sh
bash scripts/test/fixtures/model-tier-routing.sh
bash scripts/test/run-model-binding-fixtures.sh
```
