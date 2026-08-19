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

1. Resolve provider + project via `memory-preflight`. **Bind before sync (PRD 279):** require an explicit
   write binding — config `memory.provider` + non-empty `memory.project`, or marker
   `.cursor/sw-memory.provider` with literal `in-repo` (basename project). Assert with
   `python3 scripts/sw_bootstrap.py memory_preflight.py -- assert-sync-store` (or
   `resolve-provider --for-write`) before any adapter `store`. Unbound repos **refuse** with a typed
   cause; there is no ambient Recallium write default and no soft-warn window.
2. Locate the transcript directory for this workspace (the platform's `agent-transcripts/*.jsonl`).
   Read the marker; compute the candidate set (new or changed since `processedMtimeMs`).
3. For each candidate transcript, read only the **delta** (events after the last processed point).
   Extract durable substance per the canonical category map: decisions + rationale, hard-won learnings,
   bug root-causes, design choices, notable review/CI patterns, distilled session recaps.
4. Filter aggressively. Skip routine, recoverable, or already-stored content. Search-before-store: if a
   near-duplicate memory exists, `modify` it (or skip) rather than adding another.
5. **Redact** each payload before store: pipe distilled text through
   `python3 scripts/sw_bootstrap.py memory-redact.py --destination committed` (R41 chokepoint — `--destination`
   is required; no default). Stamp `appliedRedaction` on the v2 envelope via
   `scripts/memory_redaction_provenance.py` (`build_applied_redaction_record` / `redact_with_provenance`) so
   the record carries destination tier applied, pattern-set version, and substitution count — distinct from
   `sensitivity`.
6. **Egress enforcement (R29):** `/sw-memory-sync` is a named egress enforcement point. Before any distilled
   memory leaves the project boundary, run `enforce_egress(..., egress_point="memory-sync",
   destination_tier="cross-project")` — missing provenance fails closed (payload treated as unredacted); a
   stricter destination than recorded re-redacts when payload text is available or refuses with a durable
   egress refusal entry carrying destination policy id and version. Cross-project copy uses the same contract
   with `egress_point="cross-project-copy"`.
7. Store each kept item via the adapter `store` op with the right canonical category, `relatedFiles`,
   stable tags (`surface:sync`, plus `prd-<n>`/`task-<n>` when inferable), and a deliberate importance.
   Project scope by default; global (`__global__`) only with an explicit config binding.
8. Update the marker (`processedMtimeMs`, `lastDistilledAt`) for each processed transcript.
9. **Supersede reconcile (R7):** `python3 scripts/reconcile.py supersede-reconcile --json` — for each
   entry in `docs/decisions/SUPERSEDED.log`, best-effort re-point the non-authoritative side:
   - **repo-SoT:** `modify` provider `decision` memories whose `relatedFiles` still reference a superseded path
     → replacement path (pointer only; never copy record body).
   - **memory-SoT:** when the provider id for the replacement is known, refresh the git snapshot
     `memoryPointer` on the superseded path via `scripts/memory-decision-snapshot.py write` (offline-safe;
     provider write remains best-effort).
10. Report: transcripts scanned, memories created/updated/skipped, supersede reconcile actions, and any items
   deferred for review.

**Communication intensity:** ultra

**Model tier:** mid — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-memory-sync`.

## Envelope v2 fields (R29)

Each stored record conforms to `scripts/memory_envelope_v2.py` (`schemaVersion: 2`). Required fields:
`stableId`, `projectId`, `category`, `status`, `scope`, `evidenceRefs`, `confidence`, `observedAt`,
`lastValidatedAt`, `validUntil`, `supersedes`, `contentHash`, `schemaVersion`, `sensitivity`,
`appliedRedaction`. Provider fidelity is recorded in catalog `envelopeFields` (native / sideChannel / lossy).
See `core/skills/memory/SKILL.md` for the full codec contract.

## Guardrails

- **Refuse unbound writes** — bind via `memory.provider`+`memory.project` or `.cursor/sw-memory.provider=in-repo`
  before sync; never ambient-default to Recallium for writes (PRD 279).
- Never store raw transcript text — only distilled substance. No secrets, tokens, or credentials.
- Cap volume: prefer a few high-signal memories over many low-signal ones (avoid re-creating bloat).
- Idempotent: re-running without new deltas must be a no-op (marker prevents reprocessing).
- Never write `rule`-category memories here (rules are explicit-user-request only).
- The marker is local per-repo state; do not commit it and do not share one marker across repos.
- If the transcript directory or marker is unreadable, report and stop — do not guess deltas.
