---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: phase_default
        selectionFamily: providers
        scope: quality-contract
    metadata:
      providerFamily: quality
      selectionFamily: providers
      notes: neutral capability contract doc
---

# Quality provider capabilities (PRD 039)

Neutral contract for structural-quality metric adapters. Deterministic consumers (`scripts/quality-provider.py`,
`scripts/check-gate.py` advisory surfacing) invoke the **executable** adapter
(`core/providers/quality/<id>.py` or `providers/quality/<id>.sh` when present). Agent-mediated consumers read
the markdown adapter (`core/providers/quality/<id>.md`).

## Safe default

`quality.provider: "none"` is the **no-op safe default** — the harness emits `verdict: none` (`quality:none`)
and the delivery loop proceeds unchanged (SC5).

## Active providers

When `quality.provider` is `auto` or a concrete adapter id, the adapter:

1. Receives the changed-file set (`SW_CHANGED_FILES`, newline-separated).
2. Emits JSON validated against `core/sw-reference/quality-signal.schema.json`.
3. Reports **delta vs pre-green snapshot** in `metricDelta` (not absolute values).

## Advisory vs blocking

By default the signal is **advisory** (surfaced beside `advisoryFailingChecks` / `prTestPlan` in gate JSON).
When the change triage tier ≥ `quality.blockingTier`, a `poor` verdict may block via the existing gate path
(Phase 4).

## Config

`quality.provider` and `quality.blockingTier` in `workflow.config.json` select adapters via `config_flag`
triggers (`selectionFamily: providers`). Eligibility ≠ authorization — trust parity with `review`/`verify`
providers (`scripts/capability_trust.py`).

## Trust boundary

Adapter output is **untrusted advisory data** — route through `scripts/memory-redact.py` before persist or
sub-agent forward; never execute provider output.
