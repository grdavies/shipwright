# Shipwright reference artifacts

Authoritative JSON/YAML contracts under `core/sw-reference/` — consumed by harnesses, emitters, and
runtime gates. Do not duplicate semantics in command prose; link here instead.

## Gate manifest and kernel lineage (PRD 065)

| Artifact | Role |
| --- | --- |
| `gate-manifest.json` | Declarative gate registry: id, class, entrypoint, evidence contract, binding mode, failure routing |
| `gate-evidence.schema.json` | Per-gate evidence record shape; atomic tmp-file-plus-rename write contract |
| `kernel-classification.json` | Kernel/guideline lineage ids; manifest validator enforces R9-only add boundary |
| `build-chain-sot.json` | Source-of-truth map for `copy-to-core` / emitter parity |
| `architecture-doctrine.md` | Stable `AD-<n>` doctrine statements with rationale and observable signals (PRD 326) |
| `architecture-assessment.schema.json` | Per-repo assessment YAML contract (`pass`/`fail`/`waived`/`manual`) |

`scripts/gate_manifest_validate.py` fails closed on manifest↔lineage drift.
`scripts/architecture_assessment.py` evaluates doctrine + assessment YAML when
`architecture.assessment.mode` is `advisory` or `blocking` (default `off`). Config-resolvable class
promotion cannot demote the kernel floor (verification-gate, check-gate, gap-check, secret-scan).

## PRD 326 delivery order (R20)

Durable delivery-order note for `326-prd-workflow-quality-platform` (issue-store unit). Mirrors the
frozen task list `## Phase Dependencies` table in `tasks-326-workflow-quality-platform`.

**Ordering constraints:**

- **Phase 1** (PRD 323 surface verification on `main`, read-only) precedes all residual hardening
  (Phases 2–4).
- **ResearchEvidence chain** — Phases 5 → 6 → 7 → 8 are strictly serial.
- **Compiler chain** — Phases 9 → 10 are strictly serial.
- **Absorb closeout (Phase 13) is terminal** — must not run before Phases 2, 3, 4, 8, 10, 11, and 12
  are complete.

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 1 |
| 5 | 1 |
| 6 | 5 |
| 7 | 6 |
| 8 | 7 |
| 9 | 1 |
| 10 | 9 |
| 11 | 1 |
| 12 | 1 |
| 13 | 2, 3, 4, 8, 10, 11, 12 |

## Agent-gate attestation boundary (R32)

Some gates are **agent-classified** (execute, review, simplify, stabilize): the ship-loop driver emits
an `awaitAgent` contract and consumes a durable outcome artifact. Evidence for agent gates attests
**execution occurrence** (argv digest, head binding, pass/fail verdict) — not judgment quality.

Before config promotes an agent-authored gate to **mandatory**, operators must acknowledge that
attestation proves the step ran at the declared head, not that the output is correct. Mechanical gates
(behavioral-anomaly, build-chain, pre-PR smoke, decision-log, verification-gate) capture execution
proof directly via `scripts/ship_gate_handlers.py` and remain the sole writers of gate-evidence records.
