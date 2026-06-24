---
date: 2026-06-23
topic: universal-cross-platform-portability
frozen: false
reviewed: 2026-06-24
---

> **Review note (2026-06-24).** Re-checked against `main` after the bulk of phase-flow v2 landed.
> The portability architecture itself (`core/`, `platforms/`, `pf/`, `dist/`) is still entirely
> unbuilt — these decisions stand unchanged. What landed that touches this doc is the *artifact
> consolidation* (PR #12): config and reference files moved out of `config/` into `.pf/`, workflow
> artifacts consolidated under `docs/`, and a `docs/decisions/` record surface now exists. Path
> references, the `core/` extraction boundary, and the final Outstanding Question are updated below to
> reflect this; the architecture and migration plan are otherwise intact.

# Universal Cross-Platform Portability

## Summary

Make phase-flow v2 a universal development-workflow plugin that runs across many AI coding platforms —
Cursor, Claude Code, Codex (App and CLI), GitHub Copilot, Factory Droid, Qwen Code, OpenCode, Pi, and
Antigravity CLI — without a per-platform rewrite and without losing the hook-dependent safety model.

The plugin's value (the `pf-` workflow, gates, memory discipline, review personas, stabilize/RCA loops)
already lives in portable Markdown, Bash, and Python. Only the *wiring* layer is Cursor-specific:
the manifest, the `hooks.json` lifecycle, command/skill/rule registration, and provider transport. The
design separates a platform-agnostic **`core/`** (single source of truth) from per-platform **capability
descriptors + emitters**, unified by a Python **`pf` CLI** that generates the native wiring at install and
doubles as a runtime hook-polyfill where a platform has no hooks of its own.

Fidelity is explicitly **two-tier**: hook-capable platforms (Cursor, Claude Code) get full parity with
genuine fail-closed guardrails; the rest get best-effort support whose *actual* guarantee is reported
honestly rather than overstated.

## Problem Frame

phase-flow v2 is currently a self-contained Cursor plugin. Its workflow logic is portable, but it is
delivered through Cursor-only mechanisms:

- `.cursor-plugin/plugin.json` (Cursor manifest),
- `hooks/hooks.json` with Python hooks on `sessionStart` / `beforeSubmitPrompt` / `stop` and the
  `CURSOR_PLUGIN_ROOT` env var,
- `.mdc` rules, `.md` slash commands, `SKILL.md` skills, and Cursor agents,
- provider adapters (memory, review) that assume MCP tool calls.

The single highest-risk coupling is **hooks**. The fail-closed guardrail guarantee (R32/R39 in the unified
workflow brainstorm) — a session halts rather than running unguarded when the memory provider is
unreachable — is enforced entirely inside `beforeSubmitPrompt` / `sessionStart`. Most target platforms have
no equivalent hook. A naive "support everything equally" port would collapse to a lowest-common-denominator
rewrite that discards exactly this safety model.

The goal is therefore not uniform behavior everywhere. It is: write the workflow once, deliver it natively
on each platform's own extension surface, preserve full safety where the platform can enforce it, and
degrade *honestly and visibly* where it cannot.

---

## Key Decisions

- **Two-tier fidelity.** **Tier-1** = hook-capable platforms (Cursor + Claude Code) receive full parity,
  including native hooks and therefore genuine fail-closed guardrails. **Tier-2** = every other listed
  platform receives best-effort support over its available surface (commands / skills / `AGENTS.md`) with
  degraded, honestly-reported guardrails. *Rejected:* full parity on all platforms (per-platform hook shims
  are too costly to build and maintain), and a lowest-common-denominator rewrite (it would discard the
  hook-dependent safety model that is the plugin's differentiator).

- **Tier-2 fail-closed is polyfilled by a thin wrapper CLI.** A Python `pf` CLI provides a `pf run` launcher
  that performs the preflight/guardrail check externally and then hands off to the platform's own agent
  process. Sessions launched through the wrapper get fail-closed at launch; a session that bypasses the
  wrapper falls back to fail-open with a loud in-context warning, because without a native hook the wrapper
  cannot be forced.

- **Capability-flag model — core never branches on platform name.** Every platform difference reduces to a
  fixed set of capability flags in a per-platform descriptor (`hooks`, `skills`, `commands`, `rules`,
  `subagents`, `mcp`, `memoryXport`). `core/` and the emitters branch only on capabilities, so adding a
  platform is "describe its capabilities + supply an emitter," never "edit the workflow."

- **A canonical `core/` plus per-platform emitters, unified by the CLI (the "A+C blend").** A single
  platform-agnostic `core/` is the source of truth for command bodies, skill bodies, rule text, agents,
  scripts, provider logic, and guardrail logic. Each platform contributes a capability descriptor and an
  emitter that wires `core/` into that platform's native shape. The `pf` CLI is the single entrypoint that
  generates/links the wiring at install and serves as the Tier-2 runtime wrapper. *Rejected:* a standalone
  build generator with no unified CLI (A alone), hand-maintained per-platform adapter directories (B —
  drift risk as registration surfaces grow), and pure install-time generation with nothing committed
  (C alone — per-platform output becomes invisible in the repo).

- **Transport-agnostic memory.** The memory provider adapter splits into a transport-neutral capability
  mapping and a swappable transport (MCP / HTTP / local CLI). Transport is selected automatically by the
  platform's `mcp` flag, so memory — and the guardrails that depend on it — work on non-MCP platforms via
  HTTP/CLI driven by the wrapper CLI.

- **Three-level guardrail enforcement, reported honestly.** Enforcement is a spectrum keyed to the `hooks`
  capability: **Native** (Tier-1 hook blocks every prompt), **Wrapper** (`pf run` blocks at launch only),
  and **Advisory** (bypassed Tier-2 — guardrail text is injected but nothing is enforced). `pf doctor`
  states the real guarantee per platform; the plugin never claims "guarded" where it is not.

- **Python CLI, reusing the existing runtime.** `pf` is implemented in Python (already required by the
  hooks) and shells out to the existing Bash scripts where appropriate — no new toolchain, no rewrite of
  proven logic.

- **Byte-parity migration.** Because a working Cursor plugin exists today, the Cursor emitter must first
  reproduce the current Cursor tree byte-for-byte, gated by a parity test, before the repo flips to a
  generated-source model. Cursor never regresses during the migration, and the plugin keeps dogfooding
  itself on Cursor throughout.

---

## Architecture Overview

Three layers plus generated output:

```text
core/                     # platform-agnostic source of truth
  commands/ skills/ rules/ agents/ scripts/
  providers/recallium/
    adapter.md            # abstract op -> recallium operation (transport-neutral)
    transport.mcp         # ops via MCP tool calls
    transport.http        # ops via REST (memory.connection.restBaseUrl)
    transport.cli         # ops via a local recallium CLI, shelled out by pf
  guardrails/             # redaction chokepoint, rule-class injection, reachability policy
platforms/
  cursor/      { descriptor, emitter }
  claude-code/ { descriptor, emitter }
  codex-cli/   { descriptor, emitter }   opencode/ ...   (one dir per target)
pf/                       # Python CLI: install / doctor / run
dist/
  cursor/                 # generated + committed (preserves today's workflow)
  claude-code/ ...        # generated (committed or built on install)
PROVENANCE.md  README.md
```

Capability descriptor (per platform):

```text
capabilities = {
  hooks:       native | wrapper | none     # sessionStart / beforeSubmit / stop
  skills:      native | command-emulated | none
  commands:    slash-md | prompt-file | none
  rules:       mdc | agents-md | claude-md | gemini-md | none
  subagents:   native | emulated | none
  mcp:         yes | no
  memoryXport: mcp | http | cli            # how pf reaches the provider
}
```

```mermaid
flowchart TB
  CORE[core/ : single source of truth] --> EMIT{platform emitter\n(driven by capability flags)}
  DESC[platforms/&lt;p&gt;/descriptor] --> EMIT
  EMIT --> T1[Tier-1 dist: native hooks,\nskills, commands, rules]
  EMIT --> T2[Tier-2 dist: commands/skills/AGENTS.md,\nno native hooks]
  CLI[pf CLI] --> EMIT
  CLI --> DOCTOR[pf doctor:\ncapability + enforcement matrix]
  CLI --> RUN[pf run -- &lt;agent&gt;\nTier-2 hook polyfill]
  RUN --> MEM[(memory: MCP | HTTP | CLI)]
  T1 -.native hook.-> MEM
```

**Current repo state (2026-06-24) already prefigures the `core/`-vs-wiring split.** The artifact
consolidation moved all platform-agnostic *contracts and reference* into `.pf/` (`layout.md` — the
single-source path contract every `pf-` command resolves from; `config.schema.json`;
`models-tiering.md`; `workflow.config.example.json`) and all workflow *artifacts* under `docs/`
(`brainstorms/`, `prds/`, `decisions/`), while Cursor-specific *wiring* stays in `.cursor-plugin/`,
`hooks/`, and the consumer-repo runtime config `.cursor/workflow.config.json`. The neutral-contract /
native-wiring boundary this design needs at M1 is therefore partly drawn already: `.pf/` and `docs/`
are strong `core/` candidates, and `.cursor-*` is the Cursor emitter's output. This de-risks M1 but
does not change the target architecture — `core/`, `platforms/`, `pf/`, and `dist/` remain unbuilt.

---

## The `pf` CLI

One binary, three responsibilities:

- **`pf install <platform>` (and `--all`)** — reads `core/` plus the platform descriptor, runs that
  platform's emitter, and writes the native wiring to the platform's expected location (Cursor →
  `.cursor-plugin/` + `hooks.json`; Claude Code → `.claude/` + settings hooks; Codex / OpenCode →
  `AGENTS.md` + command/prompt files). Idempotent; re-run to regenerate after editing `core/`. On a
  platform that can run in Advisory mode, install requires a one-time explicit acknowledgement of the
  reduced guarantee.
- **`pf doctor`** — prints, per installed platform, the capability flags, what is native vs polyfilled vs
  unavailable, and the guardrail enforcement level (Native / Wrapper / Advisory). This is the auditable
  "no silent unguarded session" surface.
- **`pf run -- <platform-agent-cmd>`** (Tier-2 only) — polyfills the hook lifecycle around the agent
  process: pre-launch runs the `sessionStart` + `beforeSubmitPrompt` equivalent (resolve memory over the
  selected transport, run rule-class injection and guardrail preflight; refuse to launch if memory is
  unreachable and guardrails are required), hands off to the agent with guardrail context injected via the
  platform's prompt mechanism, and post-run schedules `/pf-memory-sync` per the configured thresholds.
  Tier-1 platforms ignore `pf run` because their native hooks already do this.

---

## Guardrail Enforcement Tiers

| Level | Platforms | Mechanism | Fail-closed? |
|-------|-----------|-----------|--------------|
| Native | Tier-1: Cursor, Claude Code | platform hook runs preflight + rule injection on every prompt | Yes — true per-prompt block |
| Wrapper | Tier-2 launched via `pf run` | CLI runs preflight before hand-off; refuses launch if memory unreachable + guardrails required | Yes, at launch only (no per-prompt re-check) |
| Advisory | Tier-2 bypassed (bare agent cmd) | guardrail text injected via `AGENTS.md` / system prompt; nothing enforced | No — fail-open; `pf doctor` reports "unenforced" |

The shared guardrail logic (redaction chokepoint, rule-class injection, the reachability /
`requireRuleClass` policy already in `hooks/before-submit-guardrails.py`) lives once in `core/guardrails/`.
All three levels invoke the same logic; only the trigger differs (native hook event vs `pf run` pre-launch
vs none). Rule-class promotion stays human-gated everywhere.

An inherent platform limit, stated explicitly so it is not mistaken for a bug: Native blocks every prompt,
but Wrapper blocks only at launch. A long Tier-2 session whose memory provider dies mid-session does not
re-block, because there is no per-prompt hook to re-run. `pf doctor` reports this so the user knows the
real guarantee on each platform.

---

## Requirements

### Architecture and source of truth

- **P1.** A single platform-agnostic `core/` is the source of truth for all command bodies, skill bodies,
  rule text, agents, scripts, provider logic, and guardrail logic. No workflow content is authored anywhere
  but `core/`.
- **P2.** Each supported platform is described by a capability descriptor (flags: `hooks`, `skills`,
  `commands`, `rules`, `subagents`, `mcp`, `memoryXport`) plus an emitter. `core/` and emitters branch only
  on capability flags, never on platform name.
- **P3.** Adding a platform requires only a new descriptor, a new emitter, and its golden test — with zero
  edits to `core/`. This is the load-bearing proof that the abstraction holds.
- **P4.** When a capability is both absent and not polyfillable for a platform, the emitter refuses to emit
  rather than producing a half-working install.

### Fidelity tiers

- **P5.** Tier-1 (Cursor, Claude Code) receives full parity including native hooks and genuine fail-closed
  guardrails. Tier-2 (Codex App/CLI, Copilot, Factory Droid, Qwen Code, OpenCode, Pi, Antigravity CLI)
  receives best-effort support over its available surface.
- **P6.** Every platform's actual guarantee — capability flags and guardrail enforcement level — is reported
  by `pf doctor`. The plugin never claims a guarantee it cannot deliver on a given platform.

### The `pf` CLI

- **P7.** `pf` is implemented in Python, reuses the existing hook/script runtime, and shells out to existing
  Bash where appropriate; it introduces no new language toolchain.
- **P8.** `pf install <platform>` / `--all` generates and links the platform-native wiring from `core/` +
  descriptor, idempotently, to the platform's expected location.
- **P9.** `pf doctor` renders the per-platform capability and guardrail-enforcement matrix as an auditable
  report.
- **P10.** `pf run -- <agent-cmd>` polyfills the hook lifecycle on Tier-2: pre-launch preflight
  (memory resolution + rule-class injection + guardrail check, fail-closed at launch when memory is
  unreachable and guardrails are required), guardrail-context hand-off, and post-run memory-sync scheduling.

### Memory transport

- **P11.** The memory provider adapter separates the transport-neutral capability mapping (the existing
  `skills/memory/CAPABILITIES.md` operations) from a swappable transport: MCP, HTTP, or local CLI.
- **P12.** Transport is selected automatically by the platform `mcp` flag — MCP where available, otherwise
  HTTP (preferred, using `memory.connection.restBaseUrl`) or local CLI — so memory and guardrails function
  on non-MCP platforms, driven by the wrapper CLI.
- **P13.** A provider exposing only an MCP surface (no HTTP/CLI) is reported by `pf doctor` as
  MCP-platforms-only rather than silently assumed universal.

### Guardrail enforcement

- **P14.** Guardrail logic (redaction chokepoint, rule-class injection, reachability / `requireRuleClass`
  policy) lives once in `core/guardrails/` and is invoked identically by all three enforcement levels;
  it is never reimplemented per platform.
- **P15.** Enforcement levels are Native (per-prompt block), Wrapper (launch-time block), and Advisory
  (no enforcement, text-only). The Wrapper-vs-Native difference (launch-only vs per-prompt) is documented
  as an inherent platform limit, not a defect.
- **P16.** On a platform that can run in Advisory mode, `pf install` requires a one-time explicit
  acknowledgement of the reduced guarantee, after which `pf doctor` continues to surface it.
- **P17.** Rule-class promotion remains human-gated on every platform and tier.

### Migration

- **P18.** A parity harness snapshots the current Cursor tree, and the Cursor emitter must reproduce it
  byte-for-byte (test-gated) before any source flip.
- **P19.** Migration is phased so Cursor never regresses: M0 parity harness → M1 extract `core/` →
  M2 flip Cursor to generated source (install from `dist/cursor/`) → M3 add Claude Code (second Tier-1) →
  M4 add the `pf` CLI + transport split + first Tier-2 platform → M5+ add remaining Tier-2 platforms.
- **P20.** Provenance (the existing `PROVENANCE.md` / `/pf-upstream` discipline) extends to track each
  platform emitter's source, and the frozen-spec/amendment model governs this migration plan itself.

### Testing

- **P21.** The existing `scripts/test/` fixture harness is extended with: emitter parity (Cursor
  byte-match), capability-schema conformance (no orphan flags), per-platform generation golden trees,
  a guardrail-enforcement matrix (Native blocks; `pf run` refuses on unreachable memory; Advisory injects
  text + reports unenforced), memory transport round-trip (MCP vs HTTP equivalence under the same
  capability contract), and a `pf doctor` output golden snapshot.

---

## Key Flows

- **PF1. Install on a Tier-1 platform.** `pf install cursor` (or `claude-code`) → emitter reads `core/` +
  descriptor → writes native manifest, hooks, and registered commands/skills/rules → native hooks enforce
  fail-closed guardrails. Covered by P2, P5, P8, P14, P18.
- **PF2. Install + run on a Tier-2 platform.** `pf install codex-cli` (acknowledge Advisory once) →
  emitter writes commands/skills + `AGENTS.md` guardrail text → user runs `pf run -- codex` → CLI preflight
  resolves memory over HTTP/CLI, injects rule-class guardrails, fails closed at launch if memory is
  unreachable, then hands off. Covered by P5, P10, P11, P12, P15, P16.
- **PF3. Author once, propagate everywhere.** Edit a command/skill/rule/guardrail in `core/` → re-run
  `pf install --all` → every platform's wiring regenerates with no per-platform hand-patching; golden tests
  flag any unintended output diff. Covered by P1, P3, P21.
- **PF4. Audit the guarantee.** `pf doctor` → per-platform capability + enforcement-level matrix, including
  MCP-only-provider and Advisory-mode flags. Covered by P6, P9, P13.

---

## Success Criteria

- **Zero Cursor regression.** The Cursor workflow is byte-identical before and after migration (P18 parity
  test green throughout).
- **Cheap platform addition.** Adding a platform is one descriptor + one emitter + one golden test with
  `core/` untouched — the operational proof the abstraction holds (P3).
- **Honest guarantees.** Fail-closed is genuinely enforced on every Tier-1 platform; on Tier-2 the actual
  guarantee (launch-time or advisory) is correctly reported by `pf doctor`, with no false "guarded" claims
  (P6, P15).
- **Non-MCP reach.** Memory and guardrails function on at least one non-MCP Tier-2 platform via HTTP
  transport (P12).
- **Single-edit propagation.** One `core/` edit reaches all platforms through regeneration with no
  per-platform hand-patching (PF3).

---

## Scope Boundaries

### In scope

The capability/emitter/CLI architecture; Tier-1 full support for Cursor and Claude Code; the memory
transport split (MCP / HTTP / CLI); the `pf` CLI (`install`, `doctor`, `run`); the three-level guardrail
enforcement model; and migration phases M0–M5 including the first one or two Tier-2 platforms.

### Phase-2 (kept, sequenced after the model is proven)

The long tail of Tier-2 platforms — Pi, Antigravity CLI, Factory Droid, Qwen Code, and any others — added
incrementally once the descriptor/emitter model is validated on the first one or two Tier-2 targets. Nothing
here is dropped; it is sequencing guidance.

### Out of scope / outside this product's identity

- Marketplace publishing or distribution of the universal package.
- Forcing fail-closed where a platform physically cannot enforce it — without native hooks, Wrapper and
  Advisory are the ceiling, by platform limitation rather than choice.
- Inventing per-platform features beyond what `core/` expresses (no platform-specific behavior forks).
- Exercising a non-recallium memory provider — the provider abstraction is preserved but only recallium is
  wired, consistent with the existing unified-workflow brainstorm's deferral.

---

## Dependencies / Assumptions

- Python is available on every target platform's host (already required by the current hooks); the `pf` CLI
  adds no new runtime.
- The configured memory provider is reachable over at least one of MCP, HTTP, or local CLI. recallium runs
  locally over HTTP (`memory.connection.restBaseUrl`, default `http://localhost:8001`), so the HTTP
  transport is viable for Tier-2 here.
- Each Tier-2 platform exposes at least a command/prompt surface and an `AGENTS.md`-style instruction file;
  a platform with no usable surface at all is out of scope (P4 refusal).
- Claude Code's hook and skill model is close enough to Cursor's to serve as the second Tier-1 platform
  with a native (not wrapper) enforcement path; this is validated during M3.
- The byte-parity assumption (P18) holds only if the current Cursor tree is fully reconstructible from
  `core/` + the Cursor emitter; any Cursor artifact that cannot be reproduced this way must be captured as
  emitter input during M1.

---

## Outstanding Questions

### Deferred to planning

- The exact capability-flag vocabulary and descriptor schema (file format, validation rules), including how
  `skills=command-emulated` and `subagents=emulated` are concretely emitted on platforms that lack natives.
- Per-platform mapping tables: where each platform expects its manifest, hooks, commands, skills, and rules
  on disk, and the `AGENTS.md` section contract for guardrail-text injection.
- The `core/` extraction boundary: precisely which current files are portable bodies vs Cursor-specific
  wiring, and how rule frontmatter (`.mdc`) is represented neutrally and re-emitted per platform. The
  2026-06-24 consolidation already isolated a platform-agnostic reference tree in `.pf/` (`layout.md`,
  `config.schema.json`, `models-tiering.md`, `workflow.config.example.json`) and workflow artifacts
  under `docs/` — open question is whether `.pf/` becomes part of `core/` (regenerated/linked per
  platform) or stays a repo-level shared contract that emitters merely point at, and how the
  consumer-repo runtime config `.cursor/workflow.config.json` is templated per platform.
- The memory transport interface contract (request/response shape) shared by MCP / HTTP / CLI, and how the
  HTTP transport authenticates if a future provider is not a local, credential-free service.
- Whether `dist/<platform>` trees are committed or built on install (committed for Cursor per M2; open for
  the rest), and the implications for review and diff noise.
- The `pf run` hand-off mechanics per Tier-2 platform (how guardrail context is actually injected into each
  agent's prompt, and how post-run memory-sync scheduling is triggered without a native stop hook).
- ~~How this portability work relates to the missing forward-supersession-pointer gap recorded in the
  dev-cycle-standard gap analysis — i.e., whether founding decisions like the two-tier model need an
  explicit decision-record surface with forward links.~~ **Resolved 2026-06-24:** the decision-record
  surface now exists (`docs/decisions/` with `INDEX.md`, append-only `SUPERSEDED.log`, numbered records
  001–007, and sibling `.amendments/` dirs), authored via `/pf-prd --type decision` and frozen by
  `/pf-freeze`. The remaining (now-narrowed) decision: whether the load-bearing founding decisions here
  — two-tier fidelity (Key Decision 1), the capability-flag model (Key Decision 3), and the A+C blend
  (Key Decision 4) — should be promoted into `docs/decisions/` records (next free number is 008) so
  they get forward-supersession links, rather than living only inside this brainstorm. Recommended at
  the point this work is planned, not now.

---

## Sources / Research

Internal:

- The current phase-flow v2 Cursor plugin: `.cursor-plugin/plugin.json`, `hooks/hooks.json` and the Python
  hooks (`session-start.py`, `before-submit-guardrails.py`, `memory-sync-stop.py`), `skills/memory/` +
  `providers/recallium.md`, `scripts/check-gate.sh`, and the `scripts/test/` fixture harness.
- The `.pf/` reference tree introduced by the 2026-06-24 consolidation (`.pf/layout.md` path contract,
  `.pf/config.schema.json`, `.pf/workflow.config.example.json`, `.pf/models-tiering.md`) and the
  runtime config at `.cursor/workflow.config.json` — the platform-agnostic contracts that the `core/`
  extraction boundary must classify.
- `docs/brainstorms/2026-06-24-artifact-consolidation-under-docs-requirements.md` — the consolidation
  that relocated config/reference into `.pf/` and workflow artifacts under `docs/`.
- `docs/decisions/` (INDEX.md, SUPERSEDED.log, records 001–007) — the decision-record surface that
  resolves this doc's final Outstanding Question.
- `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` — the founding requirements
  (R1–R43), in particular R32/R39 (fail-closed guardrails), R36 (swappable provider seam), and R40
  (provenance / upstream refresh) that this design extends to a cross-platform setting.
- `docs/brainstorms/2026-06-23-dev-cycle-standard-gap-analysis-requirements.md` — the decision-record /
  forward-supersession-pointer gap referenced in Outstanding Questions.

External (patterns / context; not runtime dependencies):

- Cross-platform agent extension surfaces: the `AGENTS.md` convention (Codex, OpenCode, and others),
  Anthropic Agent Skills / `SKILL.md` (Claude Code, Copilot, Cursor), and per-platform hook models
  (Cursor `hooks.json`; Claude Code settings hooks) — the divergence that motivates the capability-flag
  abstraction.
