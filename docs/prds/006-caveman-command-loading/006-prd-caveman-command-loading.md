---
date: 2026-06-25
topic: caveman-command-loading
source_brainstorm: docs/brainstorms/2026-06-24-caveman-command-loading-requirements.md
frozen: true
frozen_at: 2026-06-25
---

# PRD 006: Caveman command loading (always-on, task-gated intensity)

## Overview

Shipwright's `sessionStart` hook injects `core/hooks/session-context.md`, which tells every agent to treat
startup context as if the user sent a phantom **`/caveman`** slash command, inlines a partial caveman rules
block at fixed **full** intensity, and never varies intensity by active command. No `/caveman` command ships in
the plugin; the full skill lives outside Shipwright (`~/.agents/skills/caveman/SKILL.md`). That produces phantom
slash-command queuing in the Cursor UI, duplicate rule injection when users attach the external skill, and a
fidelity conflict with frozen doc artifacts (R30).

This PRD replaces the phantom-slash pattern with an **always-on bundled caveman-core** injected on every
`sessionStart`, **task-gated intensity** resolved from `communication.routing` in `workflow.config.json`, and
a registered **`/sw-caveman`** manual override. Intensity vocabulary is closed at four values only:
`normal` | `lite` | `full` | `ultra`. Wenyan variants are explicitly out of scope.

**Input:** [docs/brainstorms/2026-06-24-caveman-command-loading-requirements.md](../../brainstorms/2026-06-24-caveman-command-loading-requirements.md) (Full tier).

## Goals

1. **Eliminate phantom `/caveman`** — no session-context reference to non-existent slash commands; registered
   override is `/sw-caveman` in the `sw-` namespace.
2. **Always-on, bundled policy** — `caveman-core.md` (≤35 lines) ships in `core/` and is injected on every
   `sessionStart` without loading the user-level caveman skill or any external path.
3. **Task-gated intensity** — active `sw-*` command resolves intensity from `communication.routing`; orchestrators
   with `inherit` defer to the active atomic command's intensity.
4. **Artifact fidelity preserved** — frozen brainstorm, PRD, task, amendment, commit, and PR bodies remain normal
   complete prose regardless of chat intensity (R30).
5. **Closed four-level vocabulary** — schema, routing defaults, `caveman-core.md`, and `/sw-caveman` accept only
   `normal` | `lite` | `full` | `ultra`; wenyan excluded everywhere in Shipwright.
6. **Setup seeds routing** — `/sw-setup` writes `communication.defaultIntensity` and the full command map from
   `core/sw-reference/communication-routing.defaults.json`.
7. **Green fixtures** — doc, gate, and emitter fixtures verify routing resolution, phantom-slash absence, and
   schema rejection of wenyan values.

## Non-Goals

- Wenyan caveman variants (`wenyan-lite`, `wenyan-full`, `wenyan-ultra`) in any Shipwright surface.
- Loading or bundling `~/.agents/skills/caveman/SKILL.md`.
- Compressing artifact file content (brainstorm, PRD, tasks, amendments, commit bodies, PR descriptions).
- A fifth intensity tier or runtime extension of the enum.
- Changing model-tier routing (`models.routing`) — this PRD only adds the parallel `communication.routing`
  dimension; key alignment is required (R14) but model-tier behavior is unchanged.
- Auto-attaching the user's external caveman skill on session start.

## Requirements

Requirements R1–R15 carry forward from the brainstorm with stable R-IDs. R16–R22 are PRD hardening from
anticipated integration and test gaps.

### Bundled core & session injection

- **R1** Ship `core/communication/caveman-core.md` defining only `normal` | `lite` | `full` | `ultra` (≤35
  lines; no wenyan; includes persistence rule, four intensity level definitions, Auto-Clarity, and artifact
  boundaries).
- **R2** `build_session_context()` in `core/hooks/guardrail_core.py` MUST inject `caveman-core.md` content on
  every `sessionStart` (best-effort; self-contained — no runtime skill path dependency).
- **R3** `core/hooks/session-context.md` MUST NOT reference `/caveman`, `stop caveman`, or any non-existent
  slash command; it MUST describe always-on caveman policy and intensity resolution from routing.
- **R12** Emitter (`python3 -m sw generate`) MUST copy `caveman-core.md`, updated `session-context.md`,
  `sw-caveman.md`, and `communication-routing.defaults.json` to `dist/cursor/` and `dist/claude-code/`.

### Schema & routing

- **R4** Config schema intensity enum MUST be exactly `normal` | `lite` | `full` | `ultra` — no wenyan values;
  invalid values MUST fail schema validation.
- **R5** `core/sw-reference/communication-routing.defaults.json` MUST list default intensity per `sw-*` command
  per the KD2 table in the brainstorm; `/sw-setup` seeds into `workflow.config.json`.
- **R6** Active command MUST resolve intensity from `communication.routing.commands`; orchestrator entries with
  `inherit` defer to the active atomic command's resolved intensity.
- **R14** `communication.routing.commands` keys MUST cover every shipped `sw-*` command; when
  `models.routing.commands` is present in config, keys MUST match exactly (missing keys in either map are a
  fixture failure).
- **R16** `communication.defaultIntensity` MUST default to `"full"` when absent; session hook uses this when no
  active command is known at `sessionStart`.

### Command surfaces

- **R7** Every `core/commands/sw-*.md` MUST include a **Communication intensity** line documenting its routed
  intensity (`normal` | `lite` | `full` | `ultra` | `inherit`).
- **R9** `core/commands/sw-caveman.md` MUST accept only `normal` | `lite` | `full` | `ultra` as args; default
  (no arg) shows current resolved intensity; override persists until next command dispatch; references bundled
  `caveman-core.md` only (no user skill load).
- **R15** Commands routed to `normal` (`sw-doc-review`, `sw-freeze`, `sw-ready`) MUST suspend caveman compression
  for orchestration chat turns while artifact outputs remain full-fidelity prose.

### Artifact & doc fidelity

- **R8** Doc-pipeline artifact **file content** (brainstorm, PRD, tasks, amendments) MUST use full fidelity
  regardless of chat intensity; existing `sw-brainstorm` guardrail prose remains authoritative for requirements
  text.

### Exclusions & setup

- **R10** Shipwright MUST NOT reference, load, or document wenyan caveman variants anywhere in `core/`, `dist/`,
  or setup defaults.
- **R13** `docs/guides/configuration.md` MUST document the four intensities, `communication.routing`, and
  `/sw-caveman` override semantics.

### Fixtures & verification

- **R11** Fixture coverage MUST assert: no `` `/caveman` `` in `session-context.md`; `sw-prd` → `lite`;
  `sw-triage` → `ultra`; `sw-doc-review` → `normal`; schema rejects wenyan intensity in routing JSON.
- **R17** Add `scripts/communication-resolve.py` (or equivalent) that given a command name outputs resolved
  intensity JSON for deterministic fixture invocation.
- **R18** `scripts/test/run-doc-fixtures.sh` (or a dedicated `run-communication-fixtures.sh`) MUST include the
  R11 scenarios; exit non-zero on failure.
- **R19** `build_session_context()` output MUST NOT contain the substring `` `/caveman` `` (fixture grep).

### Integration hardening

- **R20** `guardrail_core.py` session assembly MUST splice resolved intensity into injected context when an
  active command is known from hook payload or state; otherwise inject `defaultIntensity`.
- **R21** Plugin manifest (`.cursor-plugin/plugin.json` or emitter registration) MUST register `sw-caveman` so
  Cursor slash UI resolves the command.
- **R22** `dist/` freshness gate (`scripts/test/run-emitter-fixtures.sh`) MUST pass after `core/` changes and
  `python3 -m sw generate --all`.

## Technical Requirements

### New files

| Path | Purpose |
|------|---------|
| `core/communication/caveman-core.md` | Bundled four-level policy (≤35 lines) |
| `core/sw-reference/communication-routing.defaults.json` | Default per-command intensity map |
| `core/commands/sw-caveman.md` | Manual override command |
| `scripts/communication-resolve.py` | Deterministic intensity resolver for fixtures |

### Modified files

| Path | Change |
|------|--------|
| `core/hooks/session-context.md` | Remove phantom `/caveman`; describe routing-based intensity |
| `core/hooks/guardrail_core.py` | Inject caveman-core; resolve intensity |
| `.sw/config.schema.json` + `core/sw-reference/config.schema.json` | `communication` object with routing + enum |
| `.sw/workflow.config.example.json` | Example `communication` block |
| `core/commands/sw-*.md` (all) | **Communication intensity** line |
| `core/commands/sw-setup.md` | Seed communication routing |
| `docs/guides/configuration.md` | Document communication routing |
| `platforms/*/emitter.py` | Copy new artifacts to dist |
| Fixture scripts under `scripts/test/` | R11 scenarios |

### Intensity routing table (authoritative defaults)

| Intensity | Commands |
|-----------|----------|
| `normal` | `sw-doc-review`, `sw-freeze`, `sw-ready` |
| `lite` | `sw-brainstorm`, `sw-prd`, `sw-tasks`, `sw-amend`, `sw-retro` |
| `full` | `sw-execute`, `sw-debug`, `sw-stabilize`, `sw-review`, `sw-gaps`, `sw-simplify`, `sw-compound`, `sw-compound-ship` |
| `ultra` | `sw-triage`, `sw-verify`, `sw-commit`, `sw-pr`, `sw-watch-ci`, `sw-worktree`, `sw-status`, `sw-setup`, `sw-start`, `sw-memory-sync`, `sw-memory-import`, `sw-memory-export`, `sw-memory-audit`, `sw-feedback-close` |
| `inherit` | `sw-ship`, `sw-deliver`, `sw-debug`, `sw-feedback`, `sw-doc` — resolve from active atomic child |

Orchestrator examples: `/sw-doc` → `/sw-prd` resolves `lite`; `/sw-ship` → `/sw-execute` resolves `full`.
`communication-routing.defaults.json` MUST enumerate all 34 shipped `sw-*` commands (R5).

### Config shape

```json
"communication": {
  "defaultIntensity": "full",
  "routing": {
    "commands": {
      "sw-brainstorm": "lite",
      "sw-prd": "lite",
      "sw-tasks": "lite",
      "sw-amend": "lite",
      "sw-doc-review": "normal",
      "sw-freeze": "normal",
      "sw-ready": "normal",
      "sw-execute": "full",
      "sw-triage": "ultra",
      "sw-verify": "ultra"
    },
    "skills": {}
  }
}
```

Full command map lives in `communication-routing.defaults.json` (R5).

## Security & Compliance

- Session hook injection is best-effort (documented); bundled core must not load external skill paths (trust
  boundary: no arbitrary filesystem reads from user skill dirs).
- No secrets in `caveman-core.md` or routing defaults.
- Intensity policy does not weaken frozen-artifact immutability or memory guardrails.
- `session` and `token` appear in this feature's domain (session hook, token-waste concern) — changes do not
  alter auth/session security semantics; communication style only.

## Testing Strategy

| Scenario | Verification |
|----------|--------------|
| Phantom slash absent | Grep fixture: `session-context.md` has no `` `/caveman` `` |
| Routing resolution | `communication-resolve.py sw-prd` → `lite`; `sw-triage` → `ultra`; `sw-doc-review` → `normal` |
| Wenyan rejection | Schema validation fails on `wenyan-full` in routing JSON |
| Session output | `build_session_context()` fixture: no phantom slash; includes caveman-core content |
| Command metadata | Every `sw-*.md` has **Communication intensity** line |
| Emitter | `run-emitter-fixtures.sh` green after generate |
| Doc fixtures | `run-doc-fixtures.sh` includes communication scenarios |

## Rollout Plan

1. Land `caveman-core.md`, routing defaults, schema, and resolver script.
2. Update session hook and `session-context.md`; remove phantom references.
3. Add `sw-caveman.md`; register in plugin manifest.
4. Stamp **Communication intensity** on all `sw-*` commands.
5. Update `/sw-setup` seeding and configuration guide.
6. Add fixtures; run full verify gate; regenerate `dist/`.
7. No migration required for repos without `communication` block — schema defaults + session `defaultIntensity`
   apply until `/sw-setup` seeds.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Always-on bundled caveman-core | Maintainer direction; eliminates opt-in friction and phantom slash |
| DL-2 | Four-level vocabulary only | Maintainer confirmed `normal`/`lite`/`full`/`ultra` sufficient; wenyan never used |
| DL-3 | Task-gated via `communication.routing` | Parallels model-tier routing; command-aware intensity |
| DL-4 | `/sw-caveman` manual override only | `sw-` namespace; does not load user skill |
| DL-5 | `normal` for doc-review, freeze, ready | Synthesis and irreversible handoff need complete prose in chat |
| DL-6 | Artifacts always full fidelity | R30 split: chat compression vs written outputs |

## Open Questions

None — brainstorm Open Questions section is empty; maintainer confirmed four-level vocabulary and wenyan exclusion.
