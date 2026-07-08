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
  resolve delegated children via `resolve-model-tier.py --delegate`.
- **Tier values** — Cursor/Claude dispatch IDs ([Cursor subagents](https://cursor.com/docs/subagents#model-configuration)).
- **`roles`** — builder vs reviewer floor; `roles.reviewer` tier must be ≥ `roles.builder`.

### Platform catalogs (`scripts/seed-model-config.py`)

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
python3 scripts/resolve-model-tier.py --command sw-prd
python3 scripts/resolve-model-tier.py --skill prd
python3 scripts/resolve-model-tier.py --command sw-doc --delegate sw-prd
python3 scripts/resolve-model-tier.py --tier deep
python3 scripts/resolve-model-tier.py --agent sw-coherence-reviewer
```

Config `models.routing` (including `models.routing.agents` for per-reviewer/native-panel tiers) overrides
bundled defaults; missing keys fall back to `core/sw-reference/model-routing.defaults.json`.

### Inherit-orchestrator agent fallback (R18)

`wave_preflight.py cmd_dispatch` (`scripts/wave_preflight.py dispatch preflight`) resolves the concrete
model for a sub-agent dispatched under an `inherit` orchestrator command (e.g. `sw-doc`, `sw-ship`). When the
agent has **no** `models.routing.agents` entry, `resolve-model-tier.py` no longer dead-ends on a bare
`inherit`/`modelId: null` pass-through (which `cmd_dispatch` used to reject with the generic
`binding:no-model` cause). Instead it walks a fixed fallback order before giving up:

1. **Agent map** — `models.routing.agents[<agent>]`, when present, wins outright.
2. **`models.roles` fallback** — `models.roles.builder` resolves the dispatch when the agent is unmapped.
3. **Actionable remediation** — when neither resolves (no agent-map entry and no `models.roles.builder`),
   the resolver fails with a distinct `no-model:remediation` cause (never `binding:no-model`) naming the
   exact config fix (add `models.routing.agents.<agent>` or set `models.roles.builder`).

This order applies only when a concrete `--agent` accompanies an `inherit` command; pure top-level
orchestrator dispatch (`resolve-model-tier.py --command sw-ship`, no `--agent`) keeps the intentional
`{"tier": "inherit", "modelId": null}` pass-through unchanged — callers resolve the child command
themselves via `--delegate`. Because the fallback always yields either a concrete model or a clear
remediation, `cmd_dispatch` never forces the caller into inline (non-delegated) authoring merely because an
agent id was absent from the routing map (PRD 057 R18, gap-047).

## Layer 2 — Dispatch (`commands/`, `skills/`, `agents/`)

**Capability selection is orthogonal** — manifest-driven eligibility (`scripts/capability-select.py`,
`core/sw-reference/capability-manifest.md`) chooses *which* skills/personas/providers are in scope for a
`signal_context`. Model tier resolution (`resolve-model-tier.py`, `dispatch-check.py`) chooses *which concrete
model* dispatches a selected agent. Do not conflate the two. **`orchestration.planPolicy` is also orthogonal**
— it governs agent-proposed step/wave plans, not model tier or capability selection.

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
| `scripts/model-tier-check.py` | Four-tier order; `roles.reviewer` ≥ `roles.builder`; concrete agent models ≥ builder; `inherit` passes static check |
| `scripts/model-routing-check.py` | Defaults cover all shipped commands/skills; valid tier keys; R27 parity with communication defaults when present |
| `scripts/resolve-model-tier.py` | Runtime tier → concrete ID; `inherit` → `modelId: null` exit 0 |
| `scripts/resolve-intensity.py` | Runtime intensity resolution with command → skill → agent → default precedence |
| `/sw-doc-review`, `sw-subagent-dispatch` | **Runtime R9:** parent model tier ≥ builder when dispatching `inherit` reviewers |
| `scripts/dispatch-check.py` | Fail-closed binding check (`binding:no-model`, `binding:no-intensity`, `binding:*-directive*`, `harness:capacity`) before Task spawn; `--prompt` validates the embedded directive |
| `scripts/dispatch_intensity_check.py` | Canonical `format_intensity_directive()` builder + structural anchor validator (R7/R8) shared by hook, CLI, and embedder call sites |
| `before_task_dispatch.py` | Fail-closed prompt-literal intensity enforcement (R9–R11); registered and live |

### Task hook — model mutation still deferred; intensity enforcement live (R5/R14)

A `preToolUse` hook (`core/hooks/before_task_dispatch.py`) still emits `updated_input.model` from
`resolve-model-tier.py --agent`, but **Cursor does not apply `updated_input` for the Task tool** (DL-2).
**Intensity enforcement is live** via prompt-literal structural validation: embedder call sites prepend
`format_intensity_directive()` to `tool_input.prompt`; the hook and `dispatch-check.py --prompt` share
`dispatch_intensity_check.py` so pre-flight and post-hoc checks cannot diverge. Spike record:
`core/sw-reference/model-tier-hook-feasibility.md`.

`inherit` reviewers cannot be fully R9-verified in CI — orchestrator must not run doc-review on a sub-`build` parent.

## Validate

```bash
python3 scripts/model-tier-check.py --config .sw/workflow.config.example.json
python3 scripts/model-routing-check.py
python3 scripts/test/fixtures/model-tier-routing.py
python3 scripts/test/run_model_binding_fixtures.py
```
