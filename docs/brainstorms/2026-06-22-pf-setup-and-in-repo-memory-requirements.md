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
in phase-flow's own directory. The in-repo provider becomes the fresh-install default — so the plugin works
with zero external dependencies — with an enforced redaction filter built in-scope as a hard predecessor;
Recallium becomes opt-in via setup. `/pf-setup` and the in-repo provider are two independently-sequenced
deliverables behind that redaction gate.

## Problem Frame

The plugin describes itself as self-contained — everything vendored in-tree, no runtime dependency on
installed plugins (foundation R2, memory #1999/#2000). Yet the memory seam currently has a hard runtime dependency on
Recallium, an external local service: it is the only memory provider (`providers/recallium.md`,
`providers/recallium-rules.sh`), and a freshly installed plugin cannot store or retrieve memory without it.

Configuration is also hand-authored. `.cursor/workflow.config.json` is copied from
`config/workflow.config.example.json` and edited by hand — exactly the friction hit this session, where the
config had to be created manually and a global install briefly gated unrelated workspaces. There is no
guided path from "plugin installed" to "plugin configured and working."

Together these mean the plugin's first-run experience contradicts its stated identity: it neither works out
of the box nor offers an on-ramp to make it work.

Configuration also drifts after first run — providers become unreachable, store directories go missing,
guardrail settings go stale — with no way to validate or repair an existing config. So **ongoing config
health** is a second objective alongside the first-run on-ramp.

## Key Decisions

- **In-repo memory is the fresh-install default, shipped in this effort.** A fresh install uses the in-repo
  provider so the plugin works immediately with no external service, and Recallium becomes opt-in via
  `/pf-setup`. The default flip ships here rather than being deferred — the enforced redaction filter (U5)
  is pulled into this effort's scope as a hard predecessor (see below).
- **Redaction (U5) is a hard predecessor, built in-scope.** Because in-repo memories are committed by
  default, a leaked secret would land in git history permanently. Deferring redaction and shipping committed
  memory opt-in in the interim would still leak for opted-in users (opt-in narrows who is exposed, not
  whether unredacted secrets can be committed). So the enforced redaction filter is built first, within this
  effort, before any committed in-repo memory path is enabled.
- **Zero-config default is carried by a per-repo provider marker the guardrail hook reads.** The in-repo
  provider is effective with no hand-authored config via a minimal in-tree, per-repo default marker that the
  fail-closed hook reads to identify the provider and engage enforcement. The marker is scoped per-repo,
  never global, preserving the global-install pass-through (an unconfigured workspace a global install
  touches is still not gated).
- **The provider lazily auto-creates its store.** The in-repo provider creates its store directory on first
  write, so memory works on a zero-config first run without `/pf-setup`. Setup validates and configures the
  store but is not a prerequisite. The store starts empty — no auto-seeded rules.
- **In-repo memories are committed and shared by default, with a per-user-local opt-out.** By default they
  live as versioned files reviewed in PRs — team-wide knowledge, modeled on the `/ce-compound`
  `docs/solutions/` philosophy. `/pf-setup` offers a per-user-local (gitignored) mode for teams that do not
  want AI memories committed. **Rule-class memories are always committed** regardless of this knob, because
  the offline fail-closed guardrail reads them from disk.
- **Rule-class memory stays human-gated; nothing is auto-seeded.** There is no automatic seeding of starter
  guardrail rules. Committed `category: rule` files must still pass `/pf-memory-audit` and appear in the
  repo-side allowlist before the hook treats them as active, and the allowlist edit is reviewed as a gate
  distinct from the rule file itself. The in-repo rules adapter validates frontmatter against the neutral
  schema and constrains/escapes rule content before injection; adapter trust of on-disk content is bounded
  by the allowlist plus a schema/length check, not by the file being committed.
- **The in-repo provider ships its own rules adapter, dispatched by provider.** The guardrail and
  session-start hooks select the rules adapter by `memory.provider` (resolved from the per-repo marker)
  rather than hardcoding the Recallium adapter, so the offline fail-closed path works for the in-repo
  provider.
- **The in-repo provider is edge-degraded (no edge-native links).** Frontmatter equals the neutral
  interchange schema so export/import is near-free and lossless; typed relationship links are out of scope
  (a possible future capability).
- **Own store, not `docs/solutions/`.** The in-repo provider keeps its own directory rather than reusing
  ce-compound's store. This avoids ce-compound's bug/knowledge taxonomy (which does not match phase-flow's
  canonical categories, including rule-class guardrails and code-context) and avoids a soft dependency on a
  sibling plugin's schema evolution. Files remain format-adjacent, so a future bridge stays possible.
- **Markdown + frontmatter that maps to the neutral interchange schema.** One markdown file per memory, with
  YAML frontmatter carrying the structured fields (category, tags, related files, importance, scope, links).
  The frontmatter fields are the seam's existing neutral interchange schema, so export/import is near-free,
  and the store is human-readable and PR-reviewable.
- **`/pf-setup` is a full scaffolder, initializer, environment doctor, and re-runnable validator** — not a
  one-shot first-run wizard. Ongoing config health (validate-and-repair) is an explicit objective.
- **Setup writes repo-local config.** Configuration is per-repo, consistent with the global-install
  pass-through behavior built this session (no config present → guardrail hook does not gate the workspace).
- **`/pf-setup` and the in-repo provider are two independently-sequenced deliverables** behind the single
  redaction predecessor.

## Requirements

### `/pf-setup` command

- R1. `/pf-setup` interactively scaffolds `.cursor/workflow.config.json` from the user's answers, validated
  against the config schema.
- R2. Setup offers interactive memory-provider selection between the in-repo provider and Recallium.
- R3. Setup offers interactive review-provider selection across CodeRabbit, none, and disabled (the
  review opt-out states built this session).
- R4. When the in-repo provider is selected, setup validates and configures its store; the provider itself
  lazily creates the store directory on first write, so memory works without setup. No starter guardrail
  rules are auto-seeded — the store starts empty.
- R5. Setup configures the guardrail knobs (`enforceBeforeSubmit`, `requireRuleClass`) with sensible
  defaults and lets the user adjust them.
- R6. Setup detects and validates the environment — whether the CodeRabbit CLI is present, whether Recallium
  is reachable, and whether CI checks exist — and surfaces recommendations based on what it finds.
- R7. Setup is re-runnable as a "doctor": run against an existing config, it validates and offers to repair
  rather than only scaffolding from scratch.

### In-repo memory provider

- R8. The in-repo provider stores each memory as a markdown file with YAML frontmatter in phase-flow's own
  directory; memories are committed and versioned by default (see R15 for the per-user-local opt-out).
- R9. Frontmatter carries the seam's neutral interchange fields so that memory export/import works without a
  separate serialization step.
- R10. The provider declares its capabilities honestly: it adds a `semanticSearch` capability flag (set
  false) so retrieval degrades to keyword plus frontmatter filtering via a flag-gated degradation path in the
  read recipe. Existing flags alone cannot express the absence of semantic search, so the new flag is
  required.
- R11. Rule-class memories are committed files that an executable, provider-dispatched rules adapter reads,
  so the fail-closed guardrail hook is satisfiable fully offline. Committed rule files remain human-gated
  (pass `/pf-memory-audit` and the repo-side allowlist, with the allowlist edit reviewed as a distinct gate),
  and the adapter validates frontmatter against the neutral schema and constrains/escapes rule content before
  injection.
- R12. The provider supplies the seam's required contract surface — a provider description doc and an
  executable adapter — mirroring the Recallium provider's structure.
- R13. The in-repo provider is edge-degraded: frontmatter equals the neutral interchange schema (no
  edge-native typed links), keeping export/import lossless. Typed relationship links are a possible future
  capability, out of scope here.
- R14. The in-repo provider is the fresh-install default, effective with no hand-authored config via a
  per-repo in-tree default marker the guardrail hook reads (so enforcement engages and the provider is
  identifiable offline). The default ships in this effort; the enforced redaction filter is a hard in-scope
  predecessor.
- R15. Memories are committed and shared by default; `/pf-setup` offers a per-user-local (gitignored) mode.
  Rule-class memories are always committed regardless of this setting, since the offline guardrail reads them
  from disk.

## Key Flows

- F1. First install, zero config
  - **Trigger:** Plugin installed; no hand-authored `.cursor/workflow.config.json` present.
  - **Steps:** The in-repo provider is the effective default via the per-repo in-tree marker; the provider
    lazily creates its store on first write; memory operations work immediately and the guardrail hook reads
    the marker to engage enforcement; the session-start surface hints that `/pf-setup` can customize
    providers and guardrails.
  - **Outcome:** The plugin is usable with no external dependency and no manual config editing, with the
    guardrail engaged.
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
  - **Trigger:** `beforeSubmitPrompt` hook fires in a repo using the in-repo provider (identified by the
    per-repo marker).
  - **Steps:** The hook dispatches the provider's rules adapter, which reads committed, allowlisted rule
    files from disk and validates their frontmatter/content; the hook evaluates guardrail state without any
    network call.
  - **Outcome:** Guardrail enforcement works entirely offline.
  - **Covered by:** R11, R14

## Scope Boundaries

- Semantic / vector search for in-repo memory is out of scope — retrieval is keyword plus frontmatter
  filtering only.
- Migrating existing Recallium memories into the in-repo store is out of scope for this work.
- Generating a CI workflow is out of scope — setup detects and recommends CI but does not scaffold it.
- Edge-native typed relationship links are out of scope — the in-repo provider is edge-degraded;
  frontmatter equals the neutral interchange schema (see Key Decisions).
- Reusing `docs/solutions/` as the backing store was considered and rejected (see Key Decisions).
- A raw-JSONL native store was considered and rejected in favor of markdown + frontmatter (see Key
  Decisions).

## Dependencies / Assumptions

- **Redaction is a hard predecessor, built in-scope for this effort.** Because in-repo memories are committed
  by default, a leaked secret would land in git history permanently — so the enforced redaction chokepoint
  (U5) is built first, within this effort, before any committed in-repo memory path (default or opt-in) is
  enabled.
- The memory seam's neutral interchange schema is stable enough to serve as the in-repo provider's native
  frontmatter shape.
- The provider seam contract (capabilities doc, provider description, executable adapter, `*.provider` config
  key) is the integration surface the new provider plugs into, mirroring Recallium.

## Outstanding Questions

### Deferred to planning

- Exact on-disk layout of the in-repo store (directory name, per-memory filename scheme, rules subfolder
  shape) and the shape of the per-repo default provider marker.
- Whether this repo migrates its own configuration from Recallium to the in-repo provider to dogfood the new
  default, and when.
- Keyword search mechanics (ripgrep invocation, frontmatter index vs scan) and how capability flags drive
  graceful degradation in the gate and commands.
- Session-start hint wording and trigger conditions for nudging `/pf-setup`.

## Sources / Research

- `providers/recallium.md`, `providers/recallium-rules.sh` — the existing memory provider and its executable
  rules adapter; the structural template the in-repo provider mirrors.
- `skills/memory/CAPABILITIES.md` — the memory seam's capability-flag contract the in-repo provider
  declares its capability flags against.
- `config/workflow.config.example.json`, `docs/config.schema.json` — the config shape `/pf-setup` scaffolds
  and validates.
- `hooks/before-submit-guardrails.py`, `hooks/pf_hook_util.py` — fail-closed guardrail hook and the
  config/guardrail helpers; the offline-rules path depends on these.
- `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` — the frozen foundation
  requirements establishing the self-contained identity this work reinforces.

## Review Decisions

### From 2026-06-22 review — resolved

All 13 findings from the 2026-06-22 multi-persona review were resolved and folded into the body above. The
calls:

1. **Zero-config guardrail inert** → a per-repo in-tree default provider marker the hook reads (R14, F1, F4,
   Key Decisions). Scoped per-repo, never global, preserving the global-install pass-through.
2. **Committed-but-opt-in secret leak** → redaction (U5) pulled in-scope as a hard predecessor; no committed
   in-repo path (default or opt-in) ships before it (Key Decisions, Dependencies).
3. **Seeded rule files bypass human gate** → no auto-seeding; committed rule files stay audit + allowlist
   gated, allowlist edit a distinct gate (R4, R11, Key Decisions).
4. **Store init gap** → the provider lazily auto-creates its store on first write; setup is not a
   prerequisite (R4, R14, Key Decisions).
5 & 6. **R13 hedged / edge-native round-trip** → R13 dropped; the provider is edge-degraded, frontmatter
   equals the interchange schema, round-trip lossless (R9, R13, Scope Boundaries).
7. **Hook hardcodes recallium adapter** → hooks dispatch the rules adapter by provider; the in-repo provider
   ships its own (R11, F4, Key Decisions).
8. **No "no semantic search" flag** → add a `semanticSearch` capability flag + flag-gated degradation (R10).
9. **Doctor role exceeds goal** → ongoing config health added as an explicit objective (Problem Frame, R7).
10. **Rule content injected without validation** → adapter validates frontmatter + constrains rule content
    before injection; trust bounded by allowlist + schema/length check (R11, Key Decisions).
11. **Headline default deferred** → resolved by #2; the default flip ships in-scope (Summary, Key Decisions).
12. **Committed-shared costs** → `/pf-setup` knob: committed-shared default vs per-user-local; rule-class
    always committed (R15, Key Decisions).
13. **Two deliverables bundled** → split into two independently-sequenced deliverables behind the redaction
    gate (Summary, Key Decisions).

Carried forward as advisory (not blocking): the JSONL/interchange terminology was normalized; the
keyword-only default capability tradeoff, the interchange-schema version/migration story, and the
"local service vs identity" framing remain noted for planning.
