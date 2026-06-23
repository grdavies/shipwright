---
date: 2026-06-22
topic: pf-setup-and-in-repo-memory
---

# /pf-setup and In-Repo Memory Provider

## Summary

Add a `/pf-setup` command that interactively scaffolds `.cursor/workflow.config.json` — selecting
memory and review providers, initializing their stores, configuring the guardrail knobs, detecting and
validating the environment, and re-runnable as a "doctor" against an existing config. Alongside it, add a
new **in-repo memory provider** that stores committed, human-readable markdown-with-frontmatter memories
in phase-flow's own directory. The in-repo provider becomes the default on a fresh install so the plugin
works with zero external dependencies, and Recallium becomes opt-in via setup.

## Problem Frame

The plugin describes itself as self-contained — everything vendored in-tree, no runtime dependency on
installed plugins (R2, memory #1999/#2000). Yet the memory seam currently has a hard runtime dependency on
Recallium, an external local service: it is the only memory provider (`providers/recallium.md`,
`providers/recallium-rules.sh`), and a freshly installed plugin cannot store or retrieve memory without it.

Configuration is also hand-authored. `.cursor/workflow.config.json` is copied from
`config/workflow.config.example.json` and edited by hand — exactly the friction hit this session, where the
config had to be created manually and a global install briefly gated unrelated workspaces. There is no
guided path from "plugin installed" to "plugin configured and working."

Together these mean the plugin's first-run experience contradicts its stated identity: it neither works out
of the box nor offers an on-ramp to make it work.

## Key Decisions

- **In-repo memory is the target install default.** Once redaction is live, a fresh install uses the in-repo
  provider so the plugin works immediately with no external service, and Recallium becomes opt-in via
  `/pf-setup`. Until then it ships committed-but-opt-in (see the redaction-sequencing decision below).
- **In-repo memories are committed and shared.** They live as versioned files reviewed in PRs — team-wide
  knowledge, modeled on the `/ce-compound` `docs/solutions/` philosophy rather than per-user local state.
- **Own store, not `docs/solutions/`.** The in-repo provider keeps its own directory rather than reusing
  ce-compound's store. This avoids ce-compound's bug/knowledge taxonomy (which does not match phase-flow's
  canonical categories, including rule-class guardrails and code-context) and avoids a soft dependency on a
  sibling plugin's schema evolution. Files remain format-adjacent, so a future bridge stays possible.
- **Markdown + frontmatter that maps to the neutral interchange schema.** One markdown file per memory, with
  YAML frontmatter carrying the structured fields (category, tags, related files, importance, scope, links).
  The frontmatter fields are the seam's existing neutral JSONL schema, so export/import is near-free, and the
  store is human-readable and PR-reviewable.
- **`/pf-setup` is a full scaffolder, initializer, environment doctor, and re-runnable validator** — not a
  one-shot first-run wizard.
- **Setup writes repo-local config.** Configuration is per-repo, consistent with the global-install
  pass-through behavior built this session (no config present → guardrail hook does not gate the workspace).
- **Redaction is unblocked by sequencing, not by gating this work.** In-repo memory ships first as
  committed-but-opt-in; the flip to in-repo-as-the-fresh-install-default is held until an enforced redaction
  filter (U5) is live. This keeps committed memory safe without making redaction a hard predecessor that
  blocks the whole effort. Working assumption — planning may revisit if it prefers to pull redaction into
  this scope.

## Requirements

### `/pf-setup` command

- R1. `/pf-setup` interactively scaffolds `.cursor/workflow.config.json` from the user's answers, validated
  against the config schema.
- R2. Setup offers interactive memory-provider selection between the in-repo provider and Recallium.
- R3. Setup offers interactive review-provider selection across CodeRabbit, none, and disabled (the
  review opt-out states built this session).
- R4. When the in-repo provider is selected, setup initializes its store — creating the directory and seeding
  starter guardrail rules.
- R5. Setup configures the guardrail knobs (`enforceBeforeSubmit`, `requireRuleClass`) with sensible
  defaults and lets the user adjust them.
- R6. Setup detects and validates the environment — whether the CodeRabbit CLI is present, whether Recallium
  is reachable, and whether CI checks exist — and surfaces recommendations based on what it finds.
- R7. Setup is re-runnable as a "doctor": run against an existing config, it validates and offers to repair
  rather than only scaffolding from scratch.

### In-repo memory provider

- R8. The in-repo provider stores each memory as a markdown file with YAML frontmatter in phase-flow's own
  directory; memories are committed and versioned.
- R9. Frontmatter carries the seam's neutral interchange fields so that memory export/import works without a
  separate serialization step.
- R10. The provider declares its capabilities honestly: no semantic search, with retrieval degrading to
  keyword plus frontmatter filtering, surfaced through the existing capability flags.
- R11. Rule-class memories are stored as committed files that an executable rules adapter reads, so the
  fail-closed guardrail hook is satisfiable fully offline.
- R12. The provider supplies the seam's required contract surface — a provider description doc and an
  executable adapter — mirroring the Recallium provider's structure.
- R13. The in-repo provider may be edge-native: typed relationship links carried in frontmatter, rather than
  the edge-degraded behavior of the Recallium adapter.
- R14. The in-repo provider is the target fresh-install default (effective with no config, so memory
  operations work without setup having been run). Flipping it on as the default is gated on the redaction
  filter being live; until then the provider ships available but opt-in.

## Key Flows

- F1. First install, zero config (target state, once redaction is live)
  - **Trigger:** Plugin installed; no `.cursor/workflow.config.json` present.
  - **Steps:** The in-repo provider is the effective default; memory operations work immediately; the
    session-start surface hints that `/pf-setup` can customize providers and guardrails.
  - **Outcome:** The plugin is usable with no external dependency and no manual config editing.
  - **Covered by:** R8, R14

- F2. Guided setup
  - **Trigger:** User runs `/pf-setup`.
  - **Steps:** Setup walks provider selection (memory, review), guardrail configuration, and store
    initialization; detects the environment; writes a schema-valid repo-local config.
  - **Outcome:** A working, validated configuration with the chosen providers initialized.
  - **Covered by:** R1, R2, R3, R4, R5, R6

- F3. Re-run / doctor
  - **Trigger:** User runs `/pf-setup` in a repo that already has a config.
  - **Steps:** Setup validates the existing config and store, reports problems (unreachable provider, missing
    store dir, stale guardrail settings), and offers targeted repair.
  - **Outcome:** An existing config is verified or repaired without a full rescaffold.
  - **Covered by:** R7

- F4. Offline fail-closed guardrail
  - **Trigger:** `beforeSubmitPrompt` hook fires in a repo using the in-repo provider.
  - **Steps:** The rules adapter reads committed rule files from disk; the hook evaluates guardrail state
    without any network call.
  - **Outcome:** Guardrail enforcement works entirely offline.
  - **Covered by:** R11

## Scope Boundaries

- Semantic / vector search for in-repo memory is out of scope — retrieval is keyword plus frontmatter
  filtering only.
- Migrating existing Recallium memories into the in-repo store is out of scope for this work.
- Generating a CI workflow is out of scope — setup detects and recommends CI but does not scaffold it.
- Reusing `docs/solutions/` as the backing store was considered and rejected (see Key Decisions).
- A raw-JSONL native store was considered and rejected in favor of markdown + frontmatter (see Key
  Decisions).

## Dependencies / Assumptions

- **Redaction is a prerequisite for shipping committed-by-default memory.** The redaction chokepoint (U5)
  was deferred this session as doc-only. Because in-repo memories are committed, a leaked secret would land
  in git history permanently — so an enforced redaction filter must precede in-repo memory being the default.
- The memory seam's neutral interchange schema is stable enough to serve as the in-repo provider's native
  frontmatter shape.
- The provider seam contract (capabilities doc, provider description, executable adapter, `*.provider` config
  key) is the integration surface the new provider plugs into, mirroring Recallium.

## Outstanding Questions

### Deferred to planning

- Exact on-disk layout of the in-repo store (directory name, per-memory filename scheme, rules subfolder
  shape) and how relationship links are encoded in frontmatter.
- Whether this repo migrates its own configuration from Recallium to the in-repo provider to dogfood the new
  default, and when.
- Keyword search mechanics (ripgrep invocation, frontmatter index vs scan) and how capability flags drive
  graceful degradation in the gate and commands.
- Session-start hint wording and trigger conditions for nudging `/pf-setup`.

## Sources / Research

- `providers/recallium.md`, `providers/recallium-rules.sh` — the existing memory provider and its executable
  rules adapter; the structural template the in-repo provider mirrors.
- `providers/review/CAPABILITIES.md` — capability-flag contract and per-head state vocabulary the in-repo
  provider declares against.
- `config/workflow.config.example.json`, `docs/config.schema.json` — the config shape `/pf-setup` scaffolds
  and validates.
- `hooks/before-submit-guardrails.py`, `hooks/pf_hook_util.py` — fail-closed guardrail hook and the
  config/guardrail helpers; the offline-rules path depends on these.
- `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` — the frozen foundation
  requirements establishing the self-contained identity this work reinforces.
