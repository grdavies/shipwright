---
description: Export durable memories to provider-neutral JSONL or OKF bundle for portability, backup, or a provider swap
alwaysApply: false
trigger: "/sw-memory-export" or "export memories to jsonl or okf"
---

# `/sw-memory-export`

Dump the active provider's memories for a project into a provider-neutral interchange format
(defined in `skills/memory/CAPABILITIES.md`). This is the portability + backup primitive and the first
half of a provider swap. Exports include `category: rule` rows from the provider store.

## Inputs

- Project: `memory.project` (or argument override).
- Scope: `project` (default) or `global` or `both`.
- Format: `jsonl` (default) or `okf` — consult catalog `interchange.<format>` for the active provider.
- Output path:
  - `jsonl`: default `.cursor/shipwright/exports/memories-<project>-<date>.jsonl`
  - `okf`: default `.cursor/shipwright/exports/memories-<project>-<date>/` (bundle directory)

## Procedure

1. Resolve provider + project via `memory-preflight`.
2. Read `.sw/memory-provider-catalog.json` → `interchange.jsonl` / `interchange.okf` for the active
   provider. When the chosen format is `unsupported`, **skip export** and route to the no-migration
   switch path (`python3 scripts/memory_switch.py skip-ack ...`) — never fail open into a partial dump.
3. If the adapter declares `export: true`, call the native `export` op with `format`. Otherwise
   synthesize: page the adapter `search` op (recency OFF, broad query, paginate to exhaustion), `expand`
   to full content, and emit neutral interchange records.
4. **`--format jsonl`:** write one JSON object per line:

   ```json
   {"content":"...","category":"decision","tags":["prd-12","surface:execute"],"relatedFiles":["server/x.ts"],"importance":0.7,"scope":"project","createdAt":"<iso>","links":[]}
   ```

5. **`--format okf`:** write an OKF v0.1 bundle directory (`index.md`, per-category markdown files with
   YAML frontmatter mapping canonical `category` → OKF `type`). See `skills/memory/CAPABILITIES.md`.
6. Map the provider-native type back to the canonical category (inverse of the adapter's category map).
7. Report: record count, output path, byte size, and a content hash for snapshot verification.
8. For provider swaps, hand off to `python3 scripts/memory_switch.py migrate-export ...` so the export
   snapshot is preserved until import completes or partial-fails.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-memory-export`.

## Guardrails

- Neutral format only — no provider-specific fields. The output must be re-importable by any adapter.
- Never export raw transcripts (they are not memories and not part of this format).
- Redact nothing silently: if a memory appears to contain a secret, flag it in the report rather than
  exporting blindly; let the user decide.
- **Standing guidance contract (PRD 072 R7):** `AGENTS.md` is pointer-only; rule-class bodies are
  authoritative in the provider store. Export captures rule rows for portability — commit snapshots (or
  store hashes) before bulk rule edits so migration stays reversible.
- After export, confirm `python3 scripts/agents_md_thin.py` still passes — never duplicate rule bodies into
  `agentsFile`.
- Paginate to true exhaustion; a partial export must be reported as partial, never presented as complete.
- When catalog interchange mode is `synthesized`, warn that round-trip may be lossy (`memory_switch.py` fidelity check).
