# Configuration

> **Redirect:** This public path is a durable stub. The canonical adopter guide lives at
> [`core/documentation/configuration.md`](../../core/documentation/configuration.md) and ships to
> `<install-root>/documentation/configuration.md` in packaged installs.

**Canonical guide:** [Configuration](../../core/documentation/configuration.md)

## Layout dual-home sync (`.sw/layout.md`)

Shipwright keeps a dual-home pair for the artifact layout contract:

| Path | Role |
| --- | --- |
| `.sw/layout.md` | Legacy / operator-facing layout contract |
| `core/sw-reference/layout.md` | Packaged reference mirror shipped with the plugin |

These two files **must stay byte-identical**. Commit hooks and CI refuse divergence.

### Sync procedure

1. Edit the authoritative content in one home (usually `.sw/layout.md` while iterating, or
   `core/sw-reference/layout.md` when packaging).
2. Copy the file bytes to the other home so both paths contain the exact same content:

   ```bash
   cp .sw/layout.md core/sw-reference/layout.md
   # or the reverse, depending on which side you edited
   ```

3. Verify before committing:

   ```bash
   python3 scripts/layout_sync_check.py --root .
   ```

4. Stage **both** paths together and commit. A one-sided stage still fails the pre-commit check
   if the working tree pair is divergent.

### Skip behavior

When **neither** file is present (consumer checkouts without the layout contract), the check
passes and is skipped. When only one side exists, the check fails closed.

### Attribution and lineage hashes

Shipwright records prompt-lineage hashes on independence assertions (PRD 351 R13 / TR4).

- **Algorithm:** SHA-256 hex digest (`hashlib.sha256(...).hexdigest()`).
- **Canonical context representation:** a filtered JSON object serialised with
  `json.dumps(filtered, sort_keys=True, ensure_ascii=True)` before hashing.
- **Fields excluded from hashing:**
  - Always: `raw_prompt`, `prompt`, `prompt_text`, `api_key`, `api_keys`, `user_id`,
    `user_token`, `user_identifying_token`
  - Plus every entry listed under `redaction.fields` in `workflow.config.json`
- **`attribution_schema_version`:** semver string on attribution records (currently `1.0.0`).
  Records lacking the field are marked `legacy: true` and excluded from comparison groups by
  default.
- **Implementation:** `scripts/graph/reviewer_metrics/selection.py` → `compute_lineage_hash`.

### Advisory routing (`models.routing.advisoryRouting`)

Optional block under `models.routing` (all fields optional; defaults shown):

```json
{
  "models": {
    "routing": {
      "advisoryRouting": {
        "enabled": true,
        "autoApply": false,
        "minSampleCount": 10,
        "maxFreshnessAgeDays": 30,
        "lookupTimeoutMs": 200
      }
    },
    "allowedModels": [],
    "excludedModels": []
  }
}
```

- `enabled` — when false, dispatch skips advisory lookup entirely.
- `autoApply` — default `false` (read-only advisory in preflight). When `true`, dispatch may
  select the recommended model; unavailable recommendations log `[advisory-fallback]` and fall
  back to normal tier logic. `autoApply: true` requires `enabled: true`.
- `minSampleCount` / `maxFreshnessAgeDays` — enforced centrally by
  `ModelPolicy.evaluate_advisory` (and again at dispatch).
- `lookupTimeoutMs` — advisory lookup budget (default 200 ms); timeout emits `[advisory-timeout]`
  and dispatch continues without advisory.
- Unknown keys under `models.routing` fail
  `python3 scripts/check-gate.py --section models.routing`.


### Advisory graduation and autoApply

Advisory routing ships **read-only** (`autoApply: false`) until steady-state
monitoring clears the SC-M1–SC-M7 gates. Do not enable auto-apply from a fresh
install.

**Pre-conditions for `autoApply: true`**

1. SC-M1–SC-M7 thresholds met on the monitoring dashboard (null-purity,
   telemetry-suspect ratio, verified-cost coverage, independence resolution,
   advisory surfacing).
2. At least **14 consecutive days** of production monitoring with no SC-M
   regressions.
3. `minSampleCount` set **explicitly** in `workflow.config.json` (do not rely on
   the default of `10` — `python3 scripts/check-gate.py --section models.routing` warns when
   auto-apply uses the default).
4. `advisoryRouting.enabled: true` (auto-apply is rejected when disabled).

**Rollback (no code revert)**

Set `advisoryRouting.enabled: false` (or `autoApply: false`) in
`workflow.config.json`. Dispatch immediately returns to tier-only selection;
no package rollback is required.

**Legacy records**

Set `includeLegacyRecords: true` only when you intentionally want schema-less
legacy attribution rows in comparison cohorts. Default is exclude-legacy.

**Read-only (default) snippet**

```json
{
  "models": {
    "routing": {
      "advisoryRouting": {
        "enabled": true,
        "autoApply": false,
        "minSampleCount": 10,
        "maxFreshnessAgeDays": 30
      }
    }
  }
}
```

**Auto-apply (after graduation) snippet**

```json
{
  "models": {
    "routing": {
      "advisoryRouting": {
        "enabled": true,
        "autoApply": true,
        "minSampleCount": 25,
        "maxFreshnessAgeDays": 14,
        "includeLegacyRecords": false
      }
    }
  }
}
```

Cross-reference: `scripts/dispatch-check.py` module docstring points here for
operator graduation guidance.
