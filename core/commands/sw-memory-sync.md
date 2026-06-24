---
description: Distill new agent-transcript deltas into durable memories — the plugin-native replacement for the inherited continual-learning-index.json / agents-memory-updater flow
alwaysApply: false
trigger: "/sw-memory-sync" or "distill transcripts into memory"
---

# `/sw-memory-sync`

Mine new conversation-transcript deltas and store the high-signal substance as distilled memories.
This is Shipwright's own distillation flow; it replaces any inherited
`continual-learning-index.json` + `agents-memory-updater` mechanism in the consumer repo.

Raw transcripts stay where they are (`agent-transcripts/*.jsonl`) and are the canonical, re-distillable
source. `/sw-memory-sync` only writes the *distilled* sink into the memory provider.

## Marker (incremental, per-repo, local)

- Marker file: `<stateDir>/shipwright-memory-sync.json` where `<stateDir>` is the directory of the
  configured `stateFile` (default `.git/`). Local-only, never committed — like the state file.
- Shape: `{ "<transcript-id>": { "processedMtimeMs": <number>, "lastDistilledAt": "<iso>" } }`.
- A transcript is a candidate when it is new or its `mtimeMs` exceeds the recorded `processedMtimeMs`.

## Procedure

1. Resolve provider + project via `memory-preflight`.
2. Locate the transcript directory for this workspace (the platform's `agent-transcripts/*.jsonl`).
   Read the marker; compute the candidate set (new or changed since `processedMtimeMs`).
3. For each candidate transcript, read only the **delta** (events after the last processed point).
   Extract durable substance per the canonical category map: decisions + rationale, hard-won learnings,
   bug root-causes, design choices, notable review/CI patterns, distilled session recaps.
4. Filter aggressively. Skip routine, recoverable, or already-stored content. Search-before-store: if a
   near-duplicate memory exists, `modify` it (or skip) rather than adding another.
5. **Redact** each payload before store: pipe distilled text through `bash scripts/memory-redact.sh`
   (R41 chokepoint — same filter as `/sw-compound`).
6. Store each kept item via the adapter `store` op with the right canonical category, `relatedFiles`,
   stable tags (`surface:sync`, plus `prd-<n>`/`task-<n>` when inferable), and a deliberate importance.
   Project scope by default; global only on explicit user direction.
7. Update the marker (`processedMtimeMs`, `lastDistilledAt`) for each processed transcript.
8. Report: transcripts scanned, memories created/updated/skipped, and any items deferred for review.

## Guardrails

- Never store raw transcript text — only distilled substance. No secrets, tokens, or credentials.
- Cap volume: prefer a few high-signal memories over many low-signal ones (avoid re-creating bloat).
- Idempotent: re-running without new deltas must be a no-op (marker prevents reprocessing).
- Never write `rule`-category memories here (rules are explicit-user-request only).
- The marker is local per-repo state; do not commit it and do not share one marker across repos.
- If the transcript directory or marker is unreadable, report and stop — do not guess deltas.
