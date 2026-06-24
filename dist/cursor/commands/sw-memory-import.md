---
description: Import durable memories into the active provider — from neutral JSONL (provider swap) or from repo knowledge (AGENTS.md learned sections + .project_docs pointers). Idempotent.
alwaysApply: false
trigger: "/sw-memory-import" or "import memories"
---

# `/sw-memory-import`

Ingest memories into the active provider. Two source modes:

- `--source jsonl <path>` — replay a provider-neutral JSONL export (second half of a provider swap).
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

## `--source jsonl`

- Parse each line as the neutral object from `skills/memory/CAPABILITIES.md`.
- Map canonical `category` → the adapter's native type; preserve `tags`, `relatedFiles`, `importance`,
  `scope`, `links`.
- Validate before writing; a malformed line is reported and skipped, never silently dropped.

## `--source repo`

- From `agentsFile` (default `AGENTS.md`): split the learned sections (e.g. *Learned User Preferences*,
  *Learned Workspace Facts*) into discrete memories. Choose the canonical category per item (most are
  `learning` or `decision`); set `relatedFiles` from paths named in the bullet; tag `prd-<n>` when present.
- From `prdsDir`/`tasksDir` and other `.project_docs/**`: create **pointer** memories only — the file
  path plus a one-line gist. Never copy full document bodies into memory.
- Do **not** import `Standing Instructions` as memories — those stay in `agentsFile`.

## Guardrails

- Idempotent and dry-run-first. Never write without showing the intended batch and getting approval.
- Pointers, not mirrors, for `.project_docs/**` — keep the canonical doc as the source of truth.
- Never import secrets/credentials. Never create `rule` memories unless the user explicitly directs it.
- Default scope project; global only on explicit direction.
- `--source repo` is the *write* half of migration. It does **not** thin `AGENTS.md` — thinning is a
  separate, gated step (Phase 1c) behind the regression gate + committed export snapshot.
- Route all writes through the adapter; never call a provider tool directly.
