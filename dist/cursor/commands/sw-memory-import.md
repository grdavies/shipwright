---
description: Import durable memories into the active provider — from neutral JSONL/OKF (provider swap) or from repo knowledge (AGENTS.md learned sections + .project_docs pointers). Standing policy is rule-class SoT; AGENTS.md is pointer-only. Idempotent.
alwaysApply: false
trigger: "/sw-memory-import" or "import memories"
---

# `/sw-memory-import`

Ingest memories into the active provider. Two source modes:

- `--source jsonl <path>` — replay a provider-neutral JSONL export (second half of a provider swap).
- `--source okf <path>` — replay a provider-neutral OKF bundle directory export.
- `--source repo` — mine the consumer repo's knowledge into typed memories (the migration step used by
  Phase 1c): AGENTS.md learned sections → typed memories; `.project_docs/**` → **pointer** memories.

Both modes are idempotent (search-before-store) and tagged with a `migration-bootstrap` session so the
batch is identifiable and re-runnable.

## Procedure (common)

1. Resolve provider + project via `memory-preflight`. Confirm target project and scope before writing.
2. Run a dry-run first: produce the full list of intended writes (category, tags, relatedFiles, a
   content preview, and whether it is new vs. an update of an existing near-duplicate). Stop and present.
3. On approval, write via the adapter `store`/`modify` ops. Search-before-store on each item; `modify`
   an existing near-duplicate instead of adding a second. Tag every item `session: migration-bootstrap`.
4. Report: created / updated / skipped counts, and any items deferred for manual review.

## `--source jsonl` / `--source okf`

- Resolve catalog `interchange.<format>` for the active provider. When the format is `unsupported`,
  **skip import** and surface the no-migration acknowledgement path — do not write partial records.
- **Dry-run first (required):** `python3 scripts/memory_switch.py migrate-import --dry-run ...` previews
  the batch (count, paths, near-duplicates). **Confirm** only after operator approval:
  `python3 scripts/memory_switch.py migrate-import --confirm ...`.
- **`jsonl`:** parse each line as the neutral object from `skills/memory/CAPABILITIES.md`.
- **`okf`:** walk the bundle directory; map OKF `type` → canonical `category`; preserve unknown
  frontmatter keys.
- Map canonical `category` → the adapter's native type; preserve `tags`, `relatedFiles`, `importance`,
  `scope`, `links`.
- Validate before writing; a malformed record is reported and skipped, never silently dropped.
- On partial failure, preserve the source export snapshot (`memory_switch.py` state) until fidelity is
  reconciled or the operator acknowledges loss.

## `--source repo`

- **Standing guidance (PRD 072 R7):** substantive policy lives in provider `rule`-class memory
  (`.cursor/sw-memory/rules/` for in-repo; adapter `rules-load` for others). `agentsFile` is a thin
  pointer/retrieval file only — never import standing policy bullets from it; dual-home fail-open is
  rejected. Validate with `python3 scripts/agents_md_thin.py --root <repo>`.
- From `agentsFile` (default `AGENTS.md`): import **learned** sections only (e.g. *Learned User Preferences*,
  *Learned Workspace Facts*) into discrete memories. Choose the canonical category per item (most are
  `learning` or `decision`); set `relatedFiles` from paths named in the bullet; tag `prd-<n>` when present.
- From `prdsDir`/`tasksDir` and other `.project_docs/**`: create **pointer** memories only — the file
  path plus a one-line gist. Never copy full document bodies into memory.
- Do **not** import standing-guidance rule bodies from `agentsFile` — edit committed rule files (in-repo)
  or promote via `/sw-memory-audit` instead.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-memory-import`.

## Guardrails

- Idempotent and dry-run-first. Never write without showing the intended batch and getting approval.
- Pointers, not mirrors, for `.project_docs/**` — keep the canonical doc as the source of truth.
- Never import secrets/credentials. Never create `rule` memories unless the user explicitly directs it.
- Default scope project; global only on explicit direction.
- `--source repo` is the *write* half of migration for **learned** sections only. Standing guidance
  thinning is complete when `agents_md_thin.py` passes — do not re-home policy into `agentsFile`.
- Never create `rule` memories from `agentsFile` import; rule-class edits require explicit user direction
  and `/sw-memory-audit` allowlist updates.
- Route all writes through the adapter; never call a provider tool directly.
