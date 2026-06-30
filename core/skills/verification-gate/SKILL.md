---
name: verification-gate
description: Evidence-over-claims gate that emits a three-state verdict (verified / not-verified / inconclusive) from structured status files. Complementary to checks-gate; never overrides CI truth.
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: verify
      command: sw-verify
  metadata:
    skill: verification-gate
    selectionFamily: verify
---

# verification-gate

Reusable local verification gate (IM1). Consumes **structured** evidence pointers — not raw `/tmp` logs.
Complementary to `skills/checks-gate` (CI truth via `scripts/check-gate.py`); never overrides a red/green
gate verdict.


**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --skill verification-gate`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Three-state contract

| Verdict | Meaning | Typical exit |
| --- | --- | --- |
| `verified` | All required evidence present and passing | `0` |
| `not-verified` | Fresh, attributable failure (baseline proves failure is new) | `20` |
| `inconclusive` | Required evidence missing/invalid, no baseline for attribution, or pre-existing unchanged failure | `10` |

**No baseline → never `not-verified`.** A failing head without baseline degrades to `inconclusive`.

### `inconclusiveClass` (when verdict is `inconclusive`)

| Class | Semantics | Consumer policy |
| --- | --- | --- |
| `missing-required` | Required verify/gate missing, invalid, or rejected by `safe_read` — **suspicious** | **Block** (`sw-commit`) / **halt** (`sw-ship`) |
| `no-baseline` | Head fails but no baseline to attribute — **benign** | Logged override required (`sw-commit`); log+continue (`sw-ship`) |
| `unattributed` | Pre-existing unchanged or undetermined — **neutral** | Logged override required (`sw-commit`); log+continue (`sw-ship`) |

## Evidence typing

| Source | Path (default) | Required? |
| --- | --- | --- |
| Verify aggregate | `$RUN_DIR/sw-verify.status.json` (`sw-tmp.py resolve`, else `/tmp`) | **Yes** — emitted by `/sw-verify` |
| Gate JSON | caller-supplied | **When PR context** (`--pr-context on/auto` or `--require-gate`) |
| Review status | `$RUN_DIR/sw-review.status.json` | **Optional** — absent-aware (review-disabled repos still reach `verified`) |

Producers write into the private run dir (`scripts/sw-tmp.py init` at ship start; mode `0700`, files `600`).
`safe_read` rejects symlinks, foreign-owned, or group/world-writable evidence files.

### Verify status shape

```json
{
  "exitCode": 0,
  "status": "pass",
  "commands": [{ "name": "test", "exitCode": 0, "status": "pass" }]
}
```

`status` is `pass` when `exitCode == 0`, else `fail`.

### Review status shape

Same as verify status. When the file is absent, review evidence is treated as `absent` (not a blocker).

## Canonical computation — `scripts/verify-evidence.py`

```bash
python3 scripts/verify-evidence.py \
  --verify-status "$RUN_DIR/sw-verify.status.json" \
  [--gate-json /path/to/gate.json --require-gate] \
  [--pr-context on|off|auto] \
  [--review-status "$RUN_DIR/sw-review.status.json"] \
  [--baseline-verify /path/to/baseline.verify.json] \
  [--baseline-gate /path/to/baseline.gate.json]
```

`--pr-context auto` (default) derives gate requirement from offline signals: upstream divergence, CI env
(`GITHUB_HEAD_REF`, PR number), shipwright-state PR field, or a supplied gate path. Pin `--pr-context off` in
fixtures for determinism.

Prints verdict JSON to stdout. Exit code mirrors verdict (`0` / `10` / `20`). Schema:
`references/verdict-schema.json`.

## Baseline contract

Capture baseline **before** the change (merge base or pre-change head) at a **caller-owned canonical path**
(longer-lived than the per-run dir):

```bash
python3 scripts/verify-baseline.py capture \
  --from "$RUN_DIR/sw-verify.status.json" \
  --to .shipwright/baseline.verify.json \
  [--gate-from gate.json --gate-to .shipwright/baseline.gate.json]
```

Attribution compares per-command identity sets when `commands[]` is present (sorted `{name, status}`); legacy
files without `commands[]` fall back to `{exitCode, status}`. Gate dimension uses `verdict` + `failingChecks`.
Rejected baseline reads → `missing-required`, never silent downgrade.

## Consumer contract

- **`sw-ship`** — halt on `not-verified` and `missing-required`; log+continue on `no-baseline` / `unattributed`.
- **`sw-commit`** — proceed on `verified`; block on `missing-required`; logged override on `no-baseline` /
  `unattributed`.

### Override record

Append via `scripts/shipwright-state.py override-add` (never shallow `write` — it clobbers `overrides[]`):

`{who: git user.email, when: ISO-8601, verdictOverridden, inconclusiveClass, reason}` — `reason` redacted via
`scripts/memory-redact.py`; duplicate fields in commit trailer `Verification-Override:`. Override never
suppresses red `check-gate.py`/CI.

## Reuse points

- `/sw-commit` / `/sw-ship` — pre-CI boundary gate
- `/sw-debug` / feedback closure — confirm fix verified

## Guardrails

- Never override `scripts/check-gate.py` — advisory at merge gate; blocking only on fresh `not-verified` at pre-CI boundary.
- **`verify-unconfigured`** (R28) — `scripts/verify-unconfigured.py` classifies vacuous verify (`echo`, `:`, `true`, empty). Hard-blocks under `SW_PHASE_MODE` / `/sw-deliver` unless `verify.allowUnconfigured: true`. CTA: run `/sw-init`.
- Redact any persisted evidence summary via `scripts/memory-redact.py` (R41) before memory store.
- Deterministic: same inputs → identical verdict JSON (document env/state as inputs when using `--pr-context auto`).
