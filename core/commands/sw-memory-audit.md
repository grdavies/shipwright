---
description: Read-only audit of a project's durable memories — flag mis-typed, mirrored, or low-signal entries and propose reclassification or collapse to pointer memories
alwaysApply: false
trigger: "/sw-memory-audit" or "audit recallium memories"
---

# `/sw-memory-audit`

Sweep a memory project for hygiene problems and propose fixes. **Read-only by default** — it never
mutates memory until you approve a proposal. Run it before any bulk `/sw-memory-import` so cleanup
precedes new writes.

**D1 — provider-agnostic.** This command is the sole human gate for `category: rule` on every
catalog-registered `memory.provider`. Route writes through `providers/<memory.provider>.md`; do not
invent a per-provider audit command.

**D2 — no dual-home unless in-repo.** Approved rule bodies persist in the configured provider.
Local `.cursor/sw-memory/rules/<id>.md` files are required only when `memory.provider` is `in-repo`.
Non-in-repo providers must not copy standing rule text into that directory.

## Inputs

- Project: `memory.project` from `.cursor/workflow.config.json` (or argument override).
- Optional `--apply` to enable mutations after you approve the proposal (default: propose-only).

## Procedure

1. Resolve provider + project via the `memory-preflight` skill (load `providers/<provider>.md`).
2. Page the project's memories using the adapter `search`/`list-recent` ops (recency OFF, broad query,
   paginate to cover the corpus). `expand` representative entries to inspect content.
3. Classify each memory against the canonical category map in `skills/memory/CAPABILITIES.md` and flag:
   - **mirror** — full-document copies of `.project_docs/**` PRDs/plans (should be a *pointer* memory:
     path + one-line gist, not the full doc),
   - **mis-typed** — content whose substance doesn't match its category (e.g. a decision stored as a
     generic note, a bug fix without `debug`),
   - **catch-all** — `feature`/`general`/`working-notes`/`project-*` used where a specific canonical
     category fits,
   - **missing links** — `debug`/`code-context` memories with no `relatedFiles`,
   - **duplicate** — near-identical memories that should be merged via `modify`,
   - **stale** — superseded content that should be `modify`-inactivated with a reason.
3b. **SoT conflict pass (R9, R11):** run the mechanical helper, then merge into the proposal:

```bash
python3 scripts/memory-sot-audit.py audit-conflicts
# optional one-time migration plan when switching memory.sourceOfTruth:
python3 scripts/memory-sot-audit.py legacy-reconcile-plan --target memory
```

Flag `decision`-class memories that contradict the active SoT (content-bearing under repo-SoT; pointer-only
under memory-SoT). Default `auto` + `in-repo` MUST report `noChange: true` when the corpus is clean.
Present legacy reconcile steps before applying a mode switch; never auto-mutate on this pass.
4. Produce a **proposal table**: id, current category, problem, proposed action (reclassify-to-X /
   collapse-to-pointer / merge-into-id / inactivate), and the proposed new content/tags where relevant.
5. Stop and present the proposal. Summarize counts per problem type.
6. Only if the user approves (or `--apply` was passed and the user confirms the batch): execute via the
   adapter `modify` op (update / inactivate), smallest-blast-radius first, reporting each change.

**Communication intensity:** ultra

**Model tier:** mid — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-memory-audit`.

## Sensitivity declassification (R29)

Lowering memory envelope `sensitivity` is the **sole human-gated path** for declassification.
Raising restriction (toward `secret`) is permitted without audit approval; lowering (declassification)
requires explicit operator approval through this command — no other workflow may lower sensitivity.

1. Identify envelopes whose stored `sensitivity` should be lowered (declassified).
2. Present the proposed `fromTier` → `toTier` transition in the audit proposal table with rationale.
3. On explicit approval, record the transition via `scripts/memory_sensitivity.py`:
   `record_declassification_approval` journals every approval (stable id, tiers, approver, timestamp).
4. Apply the lowered tier only after journaling — use `set_envelope_sensitivity` with a matching
   `approval` payload or adapter writes that route through the same setter.

Never lower sensitivity during bulk import, sync, or automated promotion without this audit gate.

## Guardrails

- Default is propose-only. Never mutate memory without explicit approval.
- Never delete; use soft-delete (`inactivate`) with a reason when the adapter supports it.
- Collapse mirrors to pointers — do not lose the canonical doc reference (keep the `.project_docs` path).
- Never reclassify a `rule` memory without explicit user direction.
- Route every read and write through the adapter; never call a provider tool directly.
- Resolve git↔provider authority per `python3 scripts/memory-sot.py resolve --class decision --json` — flag
  contradicting content-bearing `decision` memories; offer `legacy-reconcile-plan` on explicit mode switch.
- When a memory contradicts the authoritative side, propose collapse-to-pointer or promotion per SoT — do not
  silently rewrite authoritative git records from memory.
