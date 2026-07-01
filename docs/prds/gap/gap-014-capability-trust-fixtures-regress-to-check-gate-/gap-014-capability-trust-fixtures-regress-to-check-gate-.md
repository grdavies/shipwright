---
id: gap-014-capability-trust-fixtures-regress-to-check-gate-
type: gap
status: open
title: Capability trust fixtures regress to check-gate.sh during deliver
visibility: public
tags: [source:feedback, signal:feedback-prd-041-capability-fixture-sh-regression-2026-07-01, prd-041, prd-042]
source_pr: 284
absorbs: []
---

# Capability trust fixtures regress to check-gate.sh during deliver

_Captured from PRD 041 deliver session (`feedback-prd-041-capability-fixture-sh-regression-2026-07-01`)._

## Summary

During PRD 041 deliver, uncommitted changes appeared on the primary checkout reverting capability-trust
fixture `gateRef` values from `check-gate.py` back to **`check-gate.sh`**, contradicting **PRD 042**
cross-platform Python standardization (R31 zero-shell / python-first).

## Affected paths (observed)

- `scripts/test/fixtures/capability-select/trust-config-override/capability-index.json`
- `scripts/test/fixtures/capability-select/trust-config-override/core/providers/review/override-target.md`
- `scripts/test/fixtures/capability-select/trust-index-tamper/capability-index.json`
- `scripts/test/fixtures/capability-select/trust-unconfigured-provider/capability-index.json`
- `scripts/test/fixtures/capability-select/trust-unconfigured-provider/core/providers/review/unconfigured.md`
- `scripts/test/fixtures/capability-lint/schema-valid/core/sw-reference/kernel-classification.json`

## Relationship to existing backlog

| Item | Overlap |
|------|---------|
| **GAP-054** (scheduled PRD 035 A1) | scripts↔core parity in CI — broader surface |
| **PRD 042** | Authoritative python-first policy |
| **GAP-077/078** | Primary checkout pollution under concurrent deliver |

## Remediation direction

1. **CI guard:** fail if capability fixture `gateRef` contains `.sh` where `.py` is canonical.
2. **Deliver hygiene:** refuse phase ship commit if primary-checkout fixture drift detected (optional doctor).
3. Restore fixtures to `check-gate.py`; add regression fixture `capability-gateref-no-shell`.

## Schedule

Triage to **PRD 042** follow-on or **PRD 035 A1** emitter/verify hygiene.
