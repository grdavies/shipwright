# Kernel classification (single source of record)

**Owner:** `core/sw-reference/kernel-classification.json` (`kernelVersion`).

Authoritative kernel vs plan-policy boundary (PRD 022 R1–R3, R28). Unclassified concerns are kernel-owned.

## Canonical phase chain

`canonicalPhaseChains.sw-ship` single-sources `SHIP_CHAIN` in `scripts/ship_phase_steps.py` and the `/sw-ship` prose chain.

## Completeness lint

`scripts/kernel_classification_lint.py` fails when orchestrator registry steps are unclassified or ordering/membership invariants break.
