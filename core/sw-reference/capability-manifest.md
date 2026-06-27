# Capability manifest contract

Per-capability **capability** frontmatter declares when a skill, persona, provider, rule, or hook is
*eligible* for a phase/signal context. The block is the **source of truth**; an emitter-generated,
freshness-gated index aggregates declarations (TR2). Until the index and selector are authoritative, these
declarations are **inert** — they do not change runtime selection.

## Frontmatter placement

Add a top-level YAML key **`capability`** to existing frontmatter on canonical source files under `core/`:

```yaml
---
name: sw-coherence-reviewer
description: …
model: inherit
capability:
  version: 1
  triggers:
    - type: always_on
      selectionFamily: doc-review
  metadata:
    personaId: coherence
    selectionFamily: doc-review
---
```

Markdown without other frontmatter (e.g. provider adapters) may use a minimal fence:

```yaml
---
capability:
  version: 1
  triggers:
    - type: config_flag
      key: review.provider
      equals: coderabbit
  metadata:
    providerFamily: review
    adapterId: coderabbit
---
```

Validate against `core/sw-reference/capability-manifest.schema.json`.

## Applicable source kinds

| Canonical path prefix | Derived `kind` | Executable |
| --- | --- | --- |
| `core/skills/**` | `skill` | no |
| `core/agents/**` | `persona` | no |
| `core/rules/**` | `rule` | no |
| `core/providers/**` | `provider` | **yes** |
| `core/hooks/**` | `hook` | **yes** |

**Anti-spoof (R27, TR1):** `kind` is **derived from the canonical source path prefix** at index time — never
author-declared alone. Author-time lint rejects `kind`/path mismatch and index rows whose `sourcePath` does
not reference an existing artifact.

## Absence default (back-compat)

**No `capability` block ⇒ not signal-selected.** Existing capabilities without a block are omitted from
manifest-driven selection until authors add triggers. Orchestrator prose remains authoritative until parity
migration cuts over (Phase 6).

## Fields

### `version` (required)

Integer schema version. Current: **`1`**.

### `triggers` (required when block present)

Non-empty array of trigger predicates. Types:

| `type` | Purpose |
| --- | --- |
| `always_on` | Explicit always-applicable trigger (e.g. six doc-review core personas). Lint-visible; no silent default. |
| `phase_default` | Default binding for a phase/command when no higher-precedence signal fires. |
| `triage_tag` | Match triage-derived tag set in `signal_context`. |
| `text_token` | Whole-token (or substring) match over frozen `body_snapshot` or `derived_tags`. |
| `heading` | Section-heading match in frozen body. |
| `link_pattern` | URL substring match in frozen body (e.g. design-tool links). |
| `path_glob` | Glob match over `file_paths`, `doc_path`, or change-digest paths. |
| `change_digest` | Predicate over persisted diff digest (code-review specialist gating). |
| `config_flag` | Match `workflow.config.json` resolved value (`equals`, `notEquals`, `absent`, `configured`). |
| `any_of` / `all_of` | Compound triggers over nested leaf predicates. |

Each trigger may carry `selectionFamily` to group migration parity fixtures (`doc-review`, `code-review`,
`providers`, `subagent-dispatch`, etc.).

### `precedence` (optional)

| Field | Meaning |
| --- | --- |
| `tier` | `override` > `signal` > `default` (R11). |
| `priority` | Optional numeric tie-break within tier (lower wins before capability-id lexicographic order). |

### `metadata` (optional)

Selection presentation and cross-refs — **not** execution authorization:

- `personaId`, `specialistId`, `providerFamily`, `adapterId`, `skill`, `command`
- `gated` — signal-gated persona/specialist
- `modelTierRef` — pointer to `models.routing`; resolution stays in `resolve-model-tier.sh` / `dispatch-check.sh`
- `gateRef` — named chokepoint for executables (`check-gate.sh`, `memory-preflight`, `hooks.json` slot)

## Precedence and conflict policy (R11)

Resolution order at selection time:

1. **Config override** — CLI `--personas` / `--all` and explicit config overrides.
2. **Signal match** — trigger predicates over the versioned, snapshotted `signal_context` (R10).
3. **Default** — `phase_default` / `always_on` triggers.

Remaining ties resolve via documented **total order**:

1. Precedence `tier` (override > signal > default)
2. Optional `precedence.priority` (lower numeric wins)
3. **Capability id lexicographic** — equal-precedence overlaps cannot depend on emitter or filesystem order.

Author-time lint (Phase 3) fails closed on ambiguous overlaps that lack a precedence resolution.

## Executable vs non-executable trust boundary (R27)

| Class | Drop-in (R12) | Manifest effect | Execution |
| --- | --- | --- | --- |
| **Non-executable** (skill, persona, rule) | **Yes** — frontmatter-only | Eligibility for dispatch/prose injection | N/A |
| **Executable** (provider, hook) | **No** — trust/config gate still required | Eligibility by signal only | Must pass named gate |

Selector output is **non-authorizing**:

- Providers → `check-gate.sh` / `review-local-resolve.sh` + `providers/<family>/` adapter
- Hooks → emitter-registered `hooks.json` slots only
- Memory → `memory-preflight` / `providers/<memory.provider>.md`

A manifest entry (or config override) **never** elevates trust. Unknown or unconfigured executables resolve
`eligible: true, executable: true, authorized: false` in selector output.

**Kernel/safety hooks** (`beforeSubmitPrompt` guardrails, memory/redaction) are **excluded** from manifest
selection and reordering (TR5). Manifest hooks augment non-safety slots only.

## Doc-review persona triggers (migration reference)

Six **always-on** core personas carry explicit `always_on` triggers:

- `sw-coherence-reviewer`, `sw-feasibility-reviewer`, `sw-scope-guardian-reviewer`
- `sw-product-reviewer`, `sw-adversarial-reviewer`, `sw-docs-currency-reviewer`

**Signal-gated:**

- `sw-security-reviewer` — `text_token` over security enumeration (sync with `skills/triage/SKILL.md`)
- `sw-design-reviewer` — `any_of` text-token UI terms, structural headings, or design-tool link patterns

Orchestration prose in `skills/doc-review/SKILL.md` and related commands points here and to
`scripts/doc-review-select.sh` / `scripts/capability-select.sh` — not duplicate trigger tables.

## Index row shape (emitter, TR2)

The committed `core/sw-reference/capability-index.json` aggregates:

```json
{
  "id": "persona.sw-coherence-reviewer",
  "kind": "persona",
  "sourcePath": "core/agents/sw-coherence-reviewer.md",
  "executable": false,
  "capability": { "version": 1, "triggers": [ … ] }
}
```

Lint rejects phantom `sourcePath` values and `kind`/path prefix mismatches.

## `signal_context` contract (R10)

The selector consumes a **versioned, fully static** `signal_context` — not the live working tree. Validate
against `core/sw-reference/signal-context.schema.json`. Slots and **fail-closed defaults**:

| Slot | Default when absent/unset |
| --- | --- |
| `version` | `1` (required) |
| `tier` | `null` |
| `doc_path` | `null` |
| `body_snapshot` | `""` |
| `derived_tags` | `[]` (missing triage → empty tag set) |
| `file_paths` | `[]` |
| `change_digest` | `null` |
| `config` | `{}` (unset provider keys → none via lookup) |
| `phase_type` | `null` |
| `conductor_mode` | `null` |
| `overrides` | `{}` (`--personas` / `--all` at selection time) |

**Resume (R10):** on first selection with `--run-dir`, the normalized `signal_context` is atomically written to
`<run-dir>/signal-context.json`. A mid-run `--resume` replays that snapshot instead of re-reading mutated
files.

**Run-log surfacing (R21):** when `--run-dir` / `SW_RUN_DIR` is set, each selection appends a
`capability-selection` record to `.cursor/sw-deliver-runs/run.log` and `<run-dir>/run.log` with `inputsHash`,
`resolvedCapabilities`, `precedenceTrace`, `activationRecord`, and `at` timestamp.

**Selector output:** canonical JSON with `membershipHash` (sorted capability ids) separated from per-entry
presentation fields. Each row carries `eligible`, `executable`, `authorized`, `gateRef`, `refusalReason`.
Identical inputs ⇒ byte-identical output (`scripts/capability-select.sh`).

## Related artifacts

| Artifact | Role |
| --- | --- |
| `capability-manifest.schema.json` | JSON Schema for the `capability` block |
| `capability-index.json` | Emitter-generated aggregate (Phase 2) |
| `signal-context.schema.json` | Versioned selector inputs (Phase 4) |
| `scripts/capability-select.sh` | Deterministic selector (Phase 4) |
| `scripts/capability-manifest-lint.sh` | Author-time lint (Phase 3) |
