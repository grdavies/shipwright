---
date: 2026-06-25
topic: model-tier-runtime-binding
prd: docs/prds/012-model-tier-runtime-binding/012-prd-model-tier-runtime-binding.md
frozen: true
frozen_at: 2026-06-25
---

# Tasks — PRD 012 Model-tier runtime binding

Generated from the frozen PRD `012-prd-model-tier-runtime-binding.md` (effective union R1–R12). Phases are
dependency-ordered; the config/resolver foundation lands first, then the preflight, then the rule/skill
rewrite that depends on the preflight, then the optional hook, then docs/dist.

## Tasks

### 1. Config-driven per-agent tiers + resolver `--agent` (M)

- [x] 1.1 Add `models.routing.agents` to config + schema + defaults (R6)
  - **File:** `.cursor/workflow.config.json`, `.sw/config.schema.json`, `core/sw-reference/model-routing.defaults.json`
  - **Expected:** `models.routing.agents` map (agent id → semantic tier) present and schema-accepted; defaults cover doc-review personas (`build`) and native-panel specialists (high-stakes `deep`, others `mid`)
- [x] 1.2 `resolve-model-tier.py --agent <id>` with deterministic fallback (R1, R7)
  - **File:** `scripts/resolve-model-tier.py`
  - **Expected:** `--agent` resolves `models.routing.agents[id]` → `models.tiers` → concrete model ID (JSON: tier + modelId); unmapped agent falls back to `models.roles.reviewer` tier; single source for doc-review + native panel
- [x] 1.3 `model-tier-check.py` validates the agents map (R8)
  - **File:** `scripts/model-tier-check.py`
  - **Expected:** every `models.routing.agents` value is a known tier (or alias) and resolves to a concrete ID; fails closed on an unknown tier

### 2. Dispatch preflight + parent-floor (M)

- [x] 2.1 Add `scripts/reviewer-dispatch-check.py` preflight (R2, R3)
  - **File:** `scripts/reviewer-dispatch-check.py`
  - **Expected:** given target agent + resolved parent model, returns JSON `pass` only when a concrete model is resolved; otherwise exit 20 with `cause: no-model-resolved` + remediation; fixture-exercisable
- [x] 2.2 Mechanical R9 parent-floor in the preflight (R4)
  - **File:** `scripts/reviewer-dispatch-check.py`
  - **Expected:** parent model below `models.roles.builder` → exit 20 `cause: parent-below-builder` unless an explicit override is recorded; halts before any persona spawn

### 3. Rule + skill rewrite to call the preflight (S/M)

- [x] 3.1 Point per-agent tiers at `models.routing.agents`; reference the mechanical floor (R12)
  - **File:** `rules/sw-subagent-dispatch.mdc`
  - **Expected:** per-agent tier guidance reads from `models.routing.agents` (not a hand-maintained prose table); R9 section references `reviewer-dispatch-check.py`
- [x] 3.2 doc-review + native-panel dispatch call resolver + preflight before every spawn (R2, R3, R4)
  - **File:** `core/skills/doc-review/SKILL.md`, `core/commands/sw-doc-review.md`
  - **Expected:** dispatch section requires `resolve-model-tier.py --agent` + `reviewer-dispatch-check.py` before each persona/specialist Task; concrete `model:` stamped from the resolved ID
- [x] 3.3 Keep `model: inherit` in reviewer/persona agent files (R9)
  - **File:** `core/agents/sw-*-reviewer.md` (+ native panel specialist agents)
  - **Expected:** agent frontmatter retains `model: inherit`; no hardcoded model IDs introduced

### 4. Optional pre-tool hook (feasibility-gated) (M)

- [x] 4.1 `before-task-dispatch` hook injects resolved `modelId` (R5) — **registered (Option C, 2026-06-26)**
  - **File:** `core/hooks/before_task_dispatch.py`, `platforms/cursor/emitter.py`, `platforms/claude-code/emitter.py`, `core/sw-reference/model-tier-hook-feasibility.md`
  - **Expected:** on a Task call targeting a `sw-*-reviewer`/persona/native-panel agent, resolve via 1.2 and inject `modelId`; resolution failure logs + surfaces (never silent `inherit`); registered in both platform hooks.json files for forward compatibility
  - **Outcome:** Logic module + fixture pass; **registered** in `hooks.json` for Cursor (`preToolUse`) and Claude Code (`PreToolUse`). Platform mutation effectiveness unverified (Cursor DL-2 confirmed; Claude Code untested). Hook fails open; mutation attempts logged to stderr. Phase 2 `reviewer-dispatch-check.py` remains enforcement floor.

### 5. Fixtures, docs, dist propagation (M)

- [x] 5.1 Fixture suite for binding behaviors (R11)
  - **File:** `scripts/test/run-model-binding-fixtures.sh`, `.cursor/workflow.config.json`
  - **Expected:** fixtures named in the PRD Testing Strategy table exist and pass; suite registered in `verify.test`; hook fixture conditional on 4.1 shipping
- [x] 5.2 Documentation updates (R12)
  - **File:** `.sw/models-tiering.md`, `docs/guides/configuration.md`
  - **Expected:** binding contract + `models.routing.agents` documented; presence asserted by a fixture
- [x] 5.3 Emitter propagation + freshness gate (R10)
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `dist/` regenerated; `scripts/test/run-emitter-fixtures.sh` passes

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 1, 2 |
| 5 | 1, 2, 3, 4 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.2 | dispatch-binding-single-source |
| R2 | 2.1 | dispatch-preflight-no-model |
| R3 | 2.1 | dispatch-preflight-no-model |
| R4 | 2.2 | dispatch-preflight-parent-floor |
| R5 | 4.1 | task-dispatch-hook-injection |
| R6 | 1.1 | routing-agents-schema |
| R7 | 1.2 | resolve-model-tier-agent |
| R8 | 1.3 | model-tier-check-agents-map |
| R9 | 3.3 | reviewer-frontmatter-inherit |
| R10 | 5.3 | model-binding-emitter-freshness |
| R11 | 5.1 | run-model-binding-fixtures.sh (full suite) |
| R12 | 5.2 | model-binding-docs-presence |
