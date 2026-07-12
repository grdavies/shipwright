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

`scripts/gate_manifest_validate.py` fails closed on manifest↔lineage drift. Config-resolvable class
promotion cannot demote the kernel floor (verification-gate, check-gate, gap-check, secret-scan).

## Agent-gate attestation boundary (R32)

Some gates are **agent-classified** (execute, review, simplify, stabilize): the ship-loop driver emits
an `awaitAgent` contract and consumes a durable outcome artifact. Evidence for agent gates attests
**execution occurrence** (argv digest, head binding, pass/fail verdict) — not judgment quality.

Before config promotes an agent-authored gate to **mandatory**, operators must acknowledge that
attestation proves the step ran at the declared head, not that the output is correct. Mechanical gates
(behavioral-anomaly, build-chain, pre-PR smoke, decision-log, verification-gate) capture execution
proof directly via `scripts/ship_gate_handlers.py` and remain the sole writers of gate-evidence records.
