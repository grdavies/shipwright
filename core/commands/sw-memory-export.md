---
description: Export a project's durable memories to provider-neutral JSONL for portability, backup, or a provider swap
alwaysApply: false
trigger: "/sw-memory-export" or "export memories to jsonl"
---

# `/sw-memory-export`

Dump the active provider's memories for a project into the provider-neutral JSONL interchange format
(defined in `skills/memory/CAPABILITIES.md`). This is the portability + backup primitive and the first
half of a provider swap. It is also the committed snapshot that gates AGENTS.md Mode-B thinning.

## Inputs

- Project: `memory.project` (or argument override).
- Scope: `project` (default) or `global` or `both`.
- Output path: default `.cursor/shipwright/exports/memories-<project>-<date>.jsonl` (argument override).

## Procedure

1. Resolve provider + project via `memory-preflight`.
2. If the adapter declares `export: true`, call the native `export` op. Otherwise synthesize: page the
   adapter `search` op (recency OFF, broad query, paginate to exhaustion), `expand` to full content, and
   emit one neutral JSON object per memory.
3. Write each line as:

   ```json
   {"content":"...","category":"decision","tags":["prd-12","surface:execute"],"relatedFiles":["server/x.ts"],"importance":0.7,"scope":"project","createdAt":"<iso>","links":[]}
   ```

   Map the provider-native type back to the canonical category (inverse of the adapter's category map).
4. Report: line count, output path, byte size, and a content hash for snapshot verification.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --command sw-memory-export`.

## Guardrails

- Neutral format only — no provider-specific fields. The output must be re-importable by any adapter.
- Never export raw transcripts (they are not memories and not part of this format).
- Redact nothing silently: if a memory appears to contain a secret, flag it in the report rather than
  exporting blindly; let the user decide.
- This export is the artifact a Mode-B AGENTS.md thinning depends on — commit it (or store its hash)
  before any thinning so the migration is reversible.
- Paginate to true exhaustion; a partial export must be reported as partial, never presented as complete.
