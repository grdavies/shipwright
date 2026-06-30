---
date: 2026-06-25
topic: model-tier-setup-defaults
source_brainstorm: docs/brainstorms/2026-06-24-model-tier-setup-defaults-requirements.md
frozen: true
frozen_at: 2026-06-25
---

# PRD 008 — Model tier setup defaults and routing registry

## Overview

Shipwright's model tier policy (`models.tiers`, `models.roles`, `models.aliases`, and optional
`models.routing` in `workflow.config.json`) is defined in schema and example config but is **not**
seeded by `/sw-setup`, under-documented in the configuration guide, and absent from most live configs —
including this repo's `.cursor/workflow.config.json`. Runtime dispatch references tiers procedurally in
commands and rules but has no resolver script and no authoritative command→tier routing table.

This PRD wires **platform-aware four-tier defaults** into `/sw-setup` (Option A: detect active platform,
write a single `models` block) and adds a **config-driven routing registry** (`models.routing`) seeded
from `core/sw-reference/model-routing.defaults.json`. It extends the tier vocabulary from three to four
tiers (`cheap` / `build` / `mid` / `deep`) so Cursor defaults can express Composer 2.5 (most work),
GPT-5.5 (medium effort), and Opus 4.8 (high-level doc writing) without conflating medium and deep.
Claude Code receives a separate all-Anthropic default catalog.

**Input:** [docs/brainstorms/2026-06-24-model-tier-setup-defaults-requirements.md](../../brainstorms/2026-06-24-model-tier-setup-defaults-requirements.md) (Full tier).

## Goals

1. **Operational tier policy** — fresh `/sw-setup` scaffold writes a valid four-tier `models` block for the
   detected platform; doctor mode offers repair when absent.
2. **Authoritative routing** — every shipped `sw-*` command and reasoning skill has a default tier assignment
   in `model-routing.defaults.json`, seeded into `models.routing` by setup.
3. **Runtime resolution** — `scripts/resolve-model-tier.py` turns semantic tier names and routing lookups
   into concrete dispatch IDs for orchestrators and fixtures.
4. **Documentation alignment** — `models-tiering.md`, configuration guide, README setup, and example config
   reflect four tiers, both platform catalogs, and routing resolution.
5. **Dogfood** — Shipwright's own `.cursor/workflow.config.json` gains a Cursor catalog `models` block.
6. **Frontmatter floor preserved** — semantic tier names never appear in agent `model:` frontmatter;
   orchestrators with `inherit` defer to child command routing (KD8).
7. **Unblock PRD 005** — four-tier seed + `mid` tier enables PRD 005 R27 native panel mid/deep dispatch.

## Non-Goals

- `models.platforms.*` dual-map in one config (Option B).
- Per-command `model:` YAML frontmatter on command files (routing stays in config).
- `models.routing.agents` map — agent tiers remain procedural per KD7 and `sw-subagent-dispatch.mdc`.
- Automatic runtime enforcement of parent model tier (R9 floor remains procedural).
- Hook-based injection of model into Task tool calls.
- PRD 005 native panel implementation (this PRD only seeds tiers the panel will consume).
- Changing `workflow.config.json` path for Claude Code.
- User-interactive model picker in setup (defaults only; manual edit after setup).
- Mandatory runtime invocation of `resolve-model-tier.py` from hooks or command runners (R19/R20 are
  procedural guidance for agents).

## Scope Boundaries

**In scope:**

- `/sw-setup` scaffold + doctor for `models` seeding and repair.
- Four-tier policy, platform default catalogs (Cursor + Claude Code).
- `model-tier-check.py` tier-order update; `resolve-model-tier.py` helper.
- `models.routing` schema, default registry (`model-routing.defaults.json`), and setup seeding.
- Full command + skill tier inventory (KD5, KD6); agent rules (KD7) via `sw-subagent-dispatch.mdc`.
- Model tier lines in all command and reasoning skill procedures.
- Example config, models-tiering doc, configuration guide, setup command, README setup mention.
- Fixture coverage; shipwright repo config dogfood.
- Emitter change limited to copying `model-routing.defaults.json` to `dist/` (no broader emitter refactors).

**Out of scope:** see Non-Goals above and brainstorm deferred items (Option B, hooks, PRD 005 panel).

## Requirements

Requirements R1–R26 carry forward from the frozen brainstorm with stable R-IDs.

### Setup & platform defaults

- **R1** `/sw-setup` scaffold mode MUST write a complete `models` block (tiers, aliases, roles) when
  creating a new `workflow.config.json`, using the detected platform's default catalog per KD3 in the
  brainstorm.
- **R2** `/sw-setup` doctor mode MUST detect a missing `models` block and offer to add platform defaults
  without overwriting unrelated config keys.
- **R2b** Doctor mode MUST offer **realign `models.tiers` to detected platform** only on explicit user
  confirm (lists diffs); MUST NOT auto-overwrite user-edited `models.tiers` on doctor entry. R14 platform
  overwrite applies to scaffold re-run or confirmed realign only.
- **R3** `/sw-setup` MUST detect platform as `cursor` or `claude-code` via a documented signal (e.g.
  `CURSOR_AGENT`, Claude Code env marker, or explicit user choice when ambiguous).
- **R14** Setup report output MUST summarize the written tier map (tier → model ID) and note that re-run on
  another platform overwrites `models.tiers`.
- **R15** `models` block MUST remain optional in schema — repos without tiering continue to pass
  `model-tier-check.py` with `"tiering not configured"` — but setup MUST always seed it on fresh scaffold.

### Four-tier policy & validation

- **R4** The canonical tier order MUST be `cheap` < `build` < `mid` < `deep`; `scripts/model-tier-check.py`
  MUST validate `roles.reviewer` tier rank ≥ `roles.builder` tier rank using this four-tier order.
- **R5** `.sw/workflow.config.example.json` and `core/sw-reference/workflow.config.example.json` MUST reflect
  the Cursor four-tier catalog from KD3 in the brainstorm.
- **R6** `.sw/models-tiering.md` and `core/sw-reference/models-tiering.md` MUST document four tiers, both
  platform default catalogs, `models.routing` resolution (KD4–KD7), and the R9 runtime contract unchanged.
- **R13** Shipwright's own `.cursor/workflow.config.json` MUST gain a `models` block matching the Cursor
  catalog (dogfood alignment).

### Routing registry & resolver

- **R16** `.sw/config.schema.json` MUST admit optional `models.routing` with `commands` and `skills` maps
  (string → semantic tier name). Routing values MUST be `cheap` | `build` | `mid` | `deep` | `inherit`
  (`inherit` is a routing-only sentinel, not a `models.tiers` key). Replace any erroneous
  communication-intensity enum on `models.routing` with semantic tier values.
- **R17** `/sw-setup` MUST seed the complete default `models.routing` maps per KD5 and KD6 in the brainstorm
  for the detected platform (tier names only; IDs come from `models.tiers`).
- **R18** `scripts/resolve-model-tier.py` MUST support `--tier <name>`, `--command <slug>`, `--skill <name>`,
  and `--delegate <child-slug>` (for `inherit` orchestrators) lookups into `models.routing`. When routing
  resolves to `inherit`, emit `{ "tier": "inherit", "modelId": null, "source": "routing" }` with exit `0` —
  callers MUST resolve delegated children, not dispatch on orchestrator lookup alone. Missing keys for shipped
  atomic commands MUST fail closed (exit `20`); fallback defaults apply only to standalone skill invocation.
- **R21** `core/sw-reference/model-routing.defaults.json` MUST be the single authored source for default
  command + skill routing maps; setup copies from this file; example config embeds the same defaults inline
  for readability.
- **R22** `scripts/model-tier-check.py` (or a sibling `model-routing-check.py`) MUST validate every key in
  `model-routing.defaults.json` resolves to a tier present in `models.tiers` (or `inherit`) and that every
  shipped `sw-*` command and reasoning skill from KD5/KD6 has a defaults entry.
- **R25** `models.routing` entries MUST be overridable in `workflow.config.json` without editing plugin files;
  doctor mode offers restore-from-defaults for routing only when all referenced tiers exist in live
  `models.tiers`; otherwise offer combined four-tier upgrade + routing seed.
- **R27** `model-routing.defaults.json` command keys MUST match `communication-routing.defaults.json` keys
  exactly when both files exist (PRD 006 R14 parity); fixture failure on drift.
- **R26** When an orchestrator with routing tier `inherit` delegates to an atomic command, resolution MUST use
  the child command's `models.routing.commands` entry exclusively (KD8) — the orchestrator's active model MUST
  NOT downgrade the child (e.g. `/sw-doc` → `/sw-prd` always resolves `deep`).

### Command, skill & agent surfaces

- **R9** `core/rules/sw-subagent-dispatch.mdc` MUST reference `models.tiers.mid` for medium-effort delegation,
  `models.tiers.deep` for high-stakes dispatch, and `models.routing` for command/skill resolution.
- **R10** Doc-pipeline commands (`sw-brainstorm.md`, `sw-prd.md`, `sw-tasks.md`, `sw-amend.md`) MUST reference
  routing tier `deep` and instruct orchestrators to resolve via `scripts/resolve-model-tier.py --command <slug>`.
- **R19** Every `core/commands/sw-*.md` file MUST include a **Model tier** line in procedure (or scope) stating
  its routing tier and how to resolve it (`inherit`, or `resolve-model-tier.py --command <slug>`).
- **R20** Every `core/skills/*/SKILL.md` that drives agent reasoning MUST document its routing tier and
  subagent dispatch tier (when Task tool is used).
- **R24** Orchestrator commands (`sw-doc`, `sw-ship`, `sw-deliver`, `sw-compound-ship`) MUST NOT override the
  user's active model; they delegate to atomics that each resolve their own routing entry.

### Documentation & setup command

- **R7** `docs/guides/configuration.md` MUST add a **Models** setup step and document `models.tiers`,
  `models.aliases`, `models.roles`, and `models.routing` keys. `README.md` setup steps MUST mention model
  tier defaults seeded by `/sw-setup`.
- **R8** `core/commands/sw-setup.md` MUST add a setup step for model tier defaults (between guardrails and
  environment doctor, or integrated into write-config) describing detect-and-write behavior and re-run semantics.

### Scripts & fixtures

- **R11** A `scripts/resolve-model-tier.py` script MUST accept `--tier <name>` and config path and emit JSON
  `{ "tier", "modelId", "source" }` with the concrete platform model ID from `models.tiers`, exiting `20` on
  unknown tier or missing config; it MUST be invoked from fixture tests.
- **R12** `scripts/test/run-impl-fixtures.sh` (or a dedicated fixture runner) MUST assert four-tier example
  config passes `model-tier-check.py` and `resolve-model-tier.py deep` returns the Cursor Opus ID from the
  example.
- **R23** Fixture coverage MUST assert representative commands resolve expected tiers: `sw-prd` → `deep` → Opus
  ID; `sw-triage` → `cheap` → fast model ID; `sw-execute` → `build` → Composer ID; `sw-gaps` → `mid` →
  verified Cursor mid slug (Cursor catalog). `sw-doc` + `--delegate sw-prd` → `deep` → Opus ID.

## Technical Requirements

### Platform default catalogs (authoritative for setup)

**Cursor defaults** (primary dogfood platform):

| Tier | Dispatch ID | Primary use |
|------|-------------|-------------|
| `cheap` | `composer-2.5-fast` | Mechanical subagent delegation |
| `build` | `composer-2.5` | Most implementation tasks; `roles.builder` |
| `mid` | `gpt-5.5-medium` | Medium-effort reasoning; native panel mid-tier |
| `deep` | `claude-opus-4-8-thinking-high` | Doc pipeline, high-level writing, high-stakes review |

**Claude Code defaults** (all-Anthropic):

| Tier | Dispatch ID | Primary use |
|------|-------------|-------------|
| `cheap` | `claude-4.5-haiku-thinking` | Mechanical subagent delegation |
| `build` | `claude-4.6-sonnet-medium-thinking` | Most implementation tasks; `roles.builder` |
| `mid` | `claude-4.6-sonnet-medium-thinking` | Medium-effort (collapses to build on this platform) |
| `deep` | `claude-opus-4-8-thinking-high` | Doc pipeline, high-level writing, high-stakes review |

### Platform detection signals

| Signal | Platform |
|--------|----------|
| `CURSOR_AGENT` set | `cursor` |
| `CLAUDE_CODE` or `CLAUDE_CODE_SSE_PORT` set | `claude-code` |
| Ambiguous / neither | prompt user; default `cursor` when running inside Cursor |

### Routing registry shape

```json
"models": {
  "tiers": { "...": "..." },
  "aliases": { "fast": "cheap" },
  "roles": { "builder": "build", "reviewer": "build" },
  "routing": {
    "commands": {
      "sw-prd": "deep",
      "sw-execute": "build",
      "sw-doc": "inherit"
    },
    "skills": {
      "prd": "deep",
      "triage": "cheap"
    }
  }
}
```

- Keys use `sw-` command slug (no leading slash) and skill directory name under `skills/`.
- Values are semantic tier names only — never concrete model IDs.
- Orchestrator commands (`sw-doc`, `sw-ship`, `sw-deliver`, `sw-compound-ship`) use tier `inherit`.
- Full command and skill inventories are defined in brainstorm KD5 and KD6; `model-routing.defaults.json`
  is the single authored source. KD5 MUST include `sw-cleanup` (`cheap`) and `sw-caveman` (`cheap`) alongside
  all other shipped `sw-*` commands (36 commands at time of authoring).

### Resolver contract

```bash
# Direct tier lookup
python3 scripts/resolve-model-tier.py --tier deep --config .cursor/workflow.config.json

# Command routing lookup
python3 scripts/resolve-model-tier.py --command sw-prd --config .cursor/workflow.config.json

# Skill routing lookup
python3 scripts/resolve-model-tier.py --skill prd --config .cursor/workflow.config.json
```

Output: JSON `{ "tier", "modelId", "source" }` on stdout; exit `0` on success, `20` on resolution failure.

### Key files

| Area | Path |
|------|------|
| Routing defaults | `core/sw-reference/model-routing.defaults.json` (new) |
| Resolver | `scripts/resolve-model-tier.py` (new) |
| Tier check | `scripts/model-tier-check.py` (update four-tier order) |
| Schema | `.sw/config.schema.json`, `core/sw-reference/config.schema.json` |
| Example config | `.sw/workflow.config.example.json`, `core/sw-reference/workflow.config.example.json` |
| Setup command | `core/commands/sw-setup.md` |
| Tiering doc | `.sw/models-tiering.md`, `core/sw-reference/models-tiering.md` |
| Subagent dispatch | `core/rules/sw-subagent-dispatch.mdc` |
| All commands | `core/commands/sw-*.md` (~36 files) |
| Reasoning skills | `core/skills/*/SKILL.md` (~25 files) |
| Config guide | `docs/guides/configuration.md` |
| Fixtures | `scripts/test/fixtures/model-tier-*`, updates to `run-impl-fixtures.sh` |
| Dogfood config | `.cursor/workflow.config.json` |
| Emitter / dist | `platforms/*/emitter.py`, `dist/cursor/`, `dist/claude-code/` |

## Security & Compliance

- No API credentials in `workflow.config.json` — tier values are dispatch IDs only.
- `scripts/memory-redact.py` applies to any persisted setup summaries (existing guardrail).
- Platform detection MUST NOT execute arbitrary code or read secrets from env beyond documented markers.
- Routing defaults are committed plugin artifacts — no user transcript content.

## Testing Strategy

| Layer | Coverage |
|-------|----------|
| Schema | `models.routing` validates tier values against `models.tiers` keys or `inherit` sentinel |
| Key parity | `models.routing.commands` keys match `communication.routing.commands` keys (R27) |
| Coverage | Every shipped `sw-*` slug in `model-routing.defaults.json`; Model tier line matches defaults |
| Tier check | Four-tier order; reviewer ≥ builder; defaults file key coverage |
| Resolver | `--tier`, `--command`, `--skill` paths; inherit orchestrator child resolution |
| Setup fixtures | Scaffold writes `models` + routing; doctor repair when absent |
| Representative paths | `sw-prd`→deep→Opus; `sw-triage`→cheap→fast; `sw-execute`→build→Composer |
| Command coverage | Every `sw-*.md` has Model tier line (fixture or grep gate) |
| Emitter | `model-routing.defaults.json` copied to `dist/` trees |

Fixture runner: extend `scripts/test/run-impl-fixtures.sh` or add `scripts/test/fixtures/model-tier-routing.sh`.

## Success Criteria

1. Fresh `/sw-setup` writes valid four-tier `models` + routing for detected platform; config validates.
2. `model-tier-check.py` passes on example config with four tiers and seven `inherit` reviewers.
3. `resolve-model-tier.py --tier deep` prints Opus ID; representative command paths pass (R23).
4. Configuration guide, README, and `/sw-setup` doc describe model defaults.
5. All shipped commands and reasoning skills appear in `model-routing.defaults.json`; key-coverage fixture green.
6. Dogfood `.cursor/workflow.config.json` has Cursor catalog `models` block.
7. Doctor repair path tested when `models` absent.

## Rollout Plan

0. Update `CANONICAL_TIER_ORDER` in `model-tier-check.py` to include `mid` (atomic with schema/defaults).
1. Land schema + defaults JSON + resolver + tier-check updates.
2. Update `/sw-setup` scaffold and doctor paths; regenerate dist.
3. Stamp Model tier lines on all commands and reasoning skills.
4. Update docs (configuration guide, models-tiering, README).
5. Dogfood: add `models` block to Shipwright `.cursor/workflow.config.json`.
6. Verify fixtures green via existing gate test command in `verify.test`.

## Decision Log

- **D1 — Option A (detect-and-write single `models` block):** Rejected dual-map `models.platforms.*` for this
  phase; one catalog per setup run, overwrite on platform switch.
- **D2 — Four-tier vocabulary:** Added `mid` between `build` and `deep`; canonical order
  `cheap` < `build` < `mid` < `deep`.
- **D3 — Claude Code `mid` = `build`:** Acceptable for v1 — identical dispatch IDs until a distinct medium
  Anthropic model is designated.
- **D4 — Cursor `mid` dispatch ID:** Canonical slug `gpt-5.5-medium` (platform-accepted); verify via allowlist
  fixture; `gpt-5.5` rejected if not in platform model list.
- **D5 — Routing in config, not frontmatter:** `models.routing` seeded by setup; no per-command `model:` YAML.
- **D6 — Atomic child wins on delegation:** Orchestrators at `inherit` never downgrade delegated atomics (KD8).

## Open Questions

_None — resolved in Decision Log (D3, D4) and Technical Requirements (platform detection table)._
