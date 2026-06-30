---
date: 2026-06-25
topic: model-tier-runtime-binding
brainstorm: docs/brainstorms/2026-06-25-model-tier-runtime-binding-requirements.md
frozen: true
frozen_at: 2026-06-25
---

# PRD 012 — Model-tier runtime binding at sub-agent dispatch

## Overview

Shipwright's `workflow.config.json` carries a full model-tier policy (`models.tiers`, `models.routing`,
`models.roles`), but the policy is **not bound at the moment a sub-agent is dispatched**. Reviewer and
persona sub-agents declare `model: inherit`, which Cursor resolves from the *parent chat session* rather
than from `workflow.config.json`. In the PRD 010 run this caused `sw-*-reviewer` personas — routed to
`build` (`composer-2.5`) — to execute on the parent session model (Haiku 4.5). Tier policy that subagents
ignore is meaningless, and `scripts/model-tier-check.py` (a static, at-rest check) cannot observe a runtime
Task call to catch the drift.

This PRD makes tier routing **bind mechanically at dispatch** and moves per-agent tiers out of rule prose
into config. It derives from the frozen brainstorm
`docs/brainstorms/2026-06-25-model-tier-runtime-binding-requirements.md` (R1–R12) and closes two
GAP-BACKLOG rows: "Model tier routing not bound at Task dispatch (R9 procedural only)" and the
`models.routing.agents` half of "Model tier config deferrals". Two PRD 008 deferrals — the
`models.platforms.*` dual-map and an interactive `/sw-setup` model picker — stay out of scope.

## Goals

1. Every reviewer/persona/native-panel dispatch resolves and stamps a concrete platform model ID from
   `models.routing`/`models.tiers`; an agent that omits the step is stopped by a fail-closed preflight
   rather than silently running personas on the wrong tier.
2. The R9 parent-floor (no persona panels from a sub-builder parent) is enforced mechanically at dispatch,
   not by rule prose alone.
3. Per-agent tiers are config-driven via a new `models.routing.agents` map and `resolve-model-tier.py
   --agent`, replacing the procedural-only mapping in `sw-subagent-dispatch.mdc`.
4. Reviewer agent files keep `model: inherit` so per-repo `models.tiers` edits remain authoritative with no
   agent-file changes.

## Non-Goals

- Re-tiering: changing the semantic tier→model assignments (`models.tiers` values) or which personas exist.
- `models.platforms.*` dual-map in one config (Option B, rejected in PRD 008 D1) — remains deferred.
- An interactive model picker in `/sw-setup` — remains deferred (defaults + manual edit only).
- Replacing `model: inherit` in reviewer agent frontmatter with hardcoded model IDs (loses per-repo tier
  edits; see DL-3).
- Guaranteeing platform behavior: the optional pre-tool hook is best-effort and is not the correctness
  mechanism.

## Requirements

R-IDs are carried forward from the frozen brainstorm (stable namespace; do not renumber). Requirement text
receives only clarifying edits.

### Dispatch-time binding

- **R1** A single dispatch-time resolution contract MUST, given an agent or role identifier, return the
  concrete platform model ID to stamp on a Task call — single-sourced for doc-review personas and native
  panel specialists alike, with no divergent per-caller lookup.
- **R2** Before dispatching any reviewer or persona sub-agent (`sw-*-reviewer`, doc-review personas, native
  panel specialists), the dispatcher MUST resolve a concrete model ID via `scripts/resolve-model-tier.py`
  and pass it explicitly as the Task `model:`; it MUST NOT rely on `model: inherit` resolving from the
  parent chat session.
- **R3** A platform-independent dispatch-preflight check MUST fail closed when a reviewer/persona dispatch
  would proceed without a resolved concrete model, so the binding cannot be silently skipped by an agent
  that omits the procedure. The check MUST be exercisable by a fixture.
- **R4** The R9 parent-floor MUST be enforced mechanically at the preflight: when the resolved parent model
  is below `models.roles.builder`, the preflight MUST halt or require an explicit recorded override before
  any persona panel is spawned.
- **R5** An optional pre-tool hook MAY inject the resolved `modelId` onto Task calls targeting
  reviewer/persona agents where the platform supports mutating the call; the hook MUST fail observably (log
  plus surface) when it cannot resolve a model, and MUST NOT be the sole correctness mechanism — the R3
  preflight is the floor.

### Config-driven per-agent tiers

- **R6** `workflow.config.json` MUST gain a `models.routing.agents` map (agent identifier → semantic tier),
  and the config schema (`.sw/config.schema.json`) MUST accept it, so per-agent tiers are config-driven
  rather than living only in `sw-subagent-dispatch.mdc` prose.
- **R7** `scripts/resolve-model-tier.py` MUST support `--agent <id>`, resolving via `models.routing.agents`
  → `models.tiers`, with a deterministic default (the `models.roles.reviewer` tier) when an agent is
  unmapped — parity with the existing `--command` and `--skill` resolution paths.
- **R8** `/sw-setup` seeding and `core/sw-reference/model-routing.defaults.json` MUST include the
  `models.routing.agents` defaults, and `scripts/model-tier-check.py` MUST validate the agents map (each
  value is a known tier; each resolves to a concrete model ID).

### Reviewer frontmatter invariant

- **R9** Reviewer and persona agent files MUST keep `model: inherit`; the dispatch binding (R1–R5) is
  authoritative. The implementation MUST NOT replace `inherit` with hardcoded model IDs in agent
  frontmatter, which would lose per-repo tier edits.

### Cross-cutting

- **R10** All behavior authored in `core/` (rules, scripts, config defaults, and the hook if added) MUST be
  propagated to `dist/cursor` and `dist/claude-code` via `python3 -m sw generate --all`, with the emitter
  freshness gate (`scripts/test/run-emitter-fixtures.sh`) passing.
- **R11** New behaviors MUST be covered by fixtures: dispatch-preflight fail-closed on a missing model,
  parent-floor halt below builder tier, `--agent` resolution via `models.routing.agents`, `model-tier-check`
  agents-map validation, and (if the hook ships) hook injection plus observable failure.
- **R12** Documentation MUST be updated — `rules/sw-subagent-dispatch.mdc` (point per-agent tiers at
  `models.routing.agents`), `skills/doc-review/SKILL.md` (dispatch binding contract), `.sw/models-tiering.md`,
  and any guide describing model tiers — to describe the binding contract and the config-driven agents map.

## Technical Requirements

- **TR1 — Dispatch resolver contract.** Extend `scripts/resolve-model-tier.py` with `--agent <id>` that
  reads `models.routing.agents[id]` → `models.tiers[tier]` and prints the concrete platform model ID (plus
  the resolved tier) as JSON; unmapped agents fall back to `models.roles.reviewer`'s tier deterministically
  (R1, R7). This is the single source both doc-review and native-panel dispatch call.
- **TR2 — Dispatch preflight.** Add `scripts/reviewer-dispatch-check.py` (or a verb on an existing dispatch
  helper) that, given the target agent and the resolved parent model, returns a JSON verdict:
  `pass` only when a concrete model ID is resolved and the parent model is at or above
  `models.roles.builder`; otherwise `fail` (exit 20) with `cause` (`no-model-resolved` or
  `parent-below-builder`) and remediation. `/sw-doc-review` and native-panel dispatch MUST call it before
  spawning personas (R2, R3, R4).
- **TR3 — Optional pre-tool hook.** Add a `core/hooks/` pre-tool hook (e.g. `before-task-dispatch.py`) that,
  on a Task call targeting a `sw-*-reviewer` / persona / native-panel agent, resolves the model via TR1 and
  injects `modelId`; on resolution failure it logs and surfaces (does not silently allow `inherit`). The
  hook is registered only where the platform supports Task-call mutation; correctness does not depend on it
  (R5). Feasibility is recorded in the Decision Log (DL-2).
- **TR4 — Config + schema.** Add `models.routing.agents` to `workflow.config.json`, `.sw/config.schema.json`,
  and `core/sw-reference/model-routing.defaults.json` with defaults for the doc-review personas
  (`sw-coherence-reviewer`, `sw-feasibility-reviewer`, `sw-scope-guardian-reviewer`, `sw-product-reviewer`,
  `sw-adversarial-reviewer` → `build`; `sw-security-reviewer`, `sw-design-reviewer` → `build`) and native
  panel specialists (high-stakes → `deep`, others → `mid`) (R6, R8).
- **TR5 — Tier-check validation.** Extend `scripts/model-tier-check.py` to validate `models.routing.agents`:
  every value is one of `models.tiers` keys (or an alias) and resolves to a concrete model ID; fail closed
  on an unknown tier (R8).
- **TR6 — Rule + skill rewrite.** Update `rules/sw-subagent-dispatch.mdc` so the per-agent tier table points
  at `models.routing.agents` and the R9 parent-floor references the mechanical preflight (TR2); update
  `skills/doc-review/SKILL.md` dispatch section to call the resolver + preflight before every persona spawn
  (R12).
- **TR7 — Emitter propagation.** Regenerate `dist/` via `python3 -m sw generate --all`; freshness gate must
  pass (R10).

## Security & Compliance

- **No secret surface.** Model IDs and tiers are non-secret configuration; the resolver, preflight, and hook
  read config only and introduce no credentials or network calls.
- **Fail-closed enforcement.** The dispatch preflight (TR2) and the hook (TR3) both fail closed/observable —
  they never silently downgrade a persona dispatch to an unresolved `inherit` (R3, R5).
- **Least privilege unchanged.** No change to memory, git, or provider trust boundaries; this PRD governs
  model selection at dispatch only.

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (notably the model
and dispatch fixture suites).

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `resolve-model-tier-agent` | `resolve-model-tier.py --agent <id>` resolves via `models.routing.agents` → concrete ID | R1, R7 |
| `resolve-model-tier-agent-default` | unmapped agent falls back deterministically to the reviewer-role tier | R7 |
| `dispatch-preflight-no-model` | preflight fails closed (exit 20, `no-model-resolved`) when no concrete model resolves | R2, R3 |
| `dispatch-preflight-parent-floor` | preflight halts (`parent-below-builder`) when parent model is below `models.roles.builder` | R4 |
| `dispatch-binding-single-source` | doc-review and native-panel dispatch resolve through the one TR1 contract | R1 |
| `routing-agents-schema` | `.sw/config.schema.json` accepts `models.routing.agents`; defaults present | R6, R8 |
| `model-tier-check-agents-map` | `model-tier-check.py` rejects an invalid agents-map tier; passes a valid one | R8 |
| `reviewer-frontmatter-inherit` | reviewer/persona agent files retain `model: inherit` (no hardcoded IDs) | R9 |
| `task-dispatch-hook-injection` | (if hook ships) hook injects resolved `modelId`; fails observably on resolution error | R5 |
| `model-binding-emitter-freshness` | `dist/` regenerated and fresh | R10 |
| `model-binding-docs-presence` | `sw-subagent-dispatch.mdc`, doc-review skill, `.sw/models-tiering.md` describe binding + agents map | R12 |

R11 is satisfied by this fixture set itself. The `task-dispatch-hook-injection` fixture is conditional on
the hook shipping (TR3 / DL-2); if the platform cannot mutate Task calls, the R3 preflight fixtures remain
the correctness floor. Per-R traceability is finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/model-tier-runtime-binding`, delivered in dependency-ordered phases:
  (1) resolver `--agent` + config/schema/defaults `models.routing.agents` + tier-check validation; (2)
  dispatch preflight + parent-floor; (3) rule + doc-review skill rewrite to call the preflight; (4) optional
  pre-tool hook (feasibility-gated); (5) docs + dist + fixtures.
- **Backward compatible.** Absent `models.routing.agents` → `resolve-model-tier.py --agent` falls back to
  the reviewer-role tier, so existing repos keep working; the new map is additive.
- **Feasibility gate for the hook.** Phase 4 ships only if a Cursor pre-tool hook can observe and mutate a
  Task call's `model:`; otherwise the R3 preflight (Phase 2) stands as the enforcement floor and the hook is
  re-deferred with a note (DL-2).
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Bind the concrete model at dispatch; keep `model: inherit` in agent files | Makes per-repo `models.tiers` authoritative without hardcoding IDs into agent frontmatter; closes the runtime gap that static CI cannot see (R1–R3, R9). |
| DL-2 | Two enforcement layers: a platform-independent preflight floor (TR2) plus an optional best-effort pre-tool hook (TR3) | Cursor's ability to mutate a Task call's `model:` is uncertain; a hook-only design would leave the gap open if unsupported. The preflight guarantees fail-closed enforcement regardless (adversarial + feasibility lenses). |
| DL-3 | Do NOT replace `inherit` with stamped concrete IDs in reviewer frontmatter | The structural alternative (gap item 3) loses per-repo tier edits unless re-seeded; rejected as primary mechanism (scope-guardian lens). |
| DL-4 | Add `models.routing.agents` config map; `resolve-model-tier.py --agent` | Moves per-agent tiers from `sw-subagent-dispatch.mdc` prose into config (gap item 2), single-sourcing the dispatch contract (R6, R7). |
| DL-5 | Enforce the R9 parent-floor mechanically at the preflight | Prose-only R9 is exactly what regressed; the floor must be mechanical and fixture-checkable (R4). |
| DL-6 | Keep `models.platforms.*` dual-map and the `/sw-setup` interactive picker deferred | Neither is on the binding critical path; in-scope creep would exceed the gap (product + scope-guardian lenses). |

## Open Questions

None. The pre-tool hook's platform-capability uncertainty is resolved structurally by the two-layer design
(R3 preflight floor + R5 optional hook) and recorded in DL-2; the hook ships only behind the Phase 4
feasibility gate.
