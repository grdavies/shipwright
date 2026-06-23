---
name: verification-gate
description: Evidence-over-claims gate that emits a three-state verdict (verified / not-verified / inconclusive) from structured status files. Complementary to checks-gate; never overrides CI truth.
---

# verification-gate

Reusable local verification gate (IM1). Consumes **structured** evidence pointers — not raw `/tmp` logs.
Complementary to `skills/checks-gate` (CI truth via `scripts/check-gate.sh`); never overrides a red/green
gate verdict.

## Three-state contract

| Verdict | Meaning | Typical exit |
| --- | --- | --- |
| `verified` | All required evidence present and passing | `0` |
| `not-verified` | Fresh, attributable failure (baseline proves failure is new) | `20` |
| `inconclusive` | Required evidence missing/invalid, no baseline for attribution, or pre-existing unchanged failure | `10` |

**No baseline → never `not-verified`.** A failing head without baseline degrades to `inconclusive`.

## Evidence typing

| Source | Path (default) | Required? |
| --- | --- | --- |
| Verify aggregate | `/tmp/pf-verify.status.json` | **Yes** — emitted by `/pf-verify` |
| Gate JSON | `/tmp/pf-gate.json` (or caller-supplied) | **When PR exists** (`--require-gate`) |
| Review status | `/tmp/pf-review.status.json` | **Optional** — absent-aware (review-disabled repos still reach `verified`) |

Producers must write stable, deterministic JSON — not raw command tee output.

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

## Canonical computation — `scripts/verify-evidence.sh`

```bash
bash scripts/verify-evidence.sh \
  --verify-status /tmp/pf-verify.status.json \
  [--gate-json /tmp/pf-gate.json --require-gate] \
  [--review-status /tmp/pf-review.status.json] \
  [--baseline-verify /path/to/baseline.verify.json] \
  [--baseline-gate /path/to/baseline.gate.json]
```

Prints verdict JSON to stdout. Exit code mirrors verdict (`0` / `10` / `20`).

## Baseline contract

Capture baseline **before** the change (merge base or pre-change head):

- `--baseline-verify` — prior verify status file
- `--baseline-gate` — prior gate JSON

New-vs-pre-existing attribution compares failure fingerprints (`exitCode` + `status` for verify; `verdict` +
`failingChecks` for gate). Unchanged failures → `inconclusive`, not `not-verified`.

## Reuse points

- `/pf-commit` / `/pf-ship` (U2) — pre-CI boundary gate
- `/pf-debug` / feedback closure (U9) — confirm fix verified

## Guardrails

- Never override `scripts/check-gate.sh` — advisory at merge gate; blocking only on fresh `not-verified` at pre-CI boundary (wired in U2).
- Redact any persisted evidence summary via `scripts/memory-redact.sh` (R41) before memory store.
- Deterministic: same inputs → identical verdict JSON.
