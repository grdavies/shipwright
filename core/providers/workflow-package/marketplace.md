---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: graphExecution.packages.registry
        equals: marketplace
    metadata:
      providerFamily: workflow-package
      adapterId: marketplace
      selectionFamily: providers
      status: spec-stub
      programPriority: P3
---

# WorkflowPackage marketplace registry (PRD 333 phase 10 — P3 spec stub)

**Status:** specification + registry resolver stub only — **not shipped**. Selecting
`graphExecution.packages.registry: marketplace` MUST fail closed with `not-enabled`
until green eval-corpus marketplace scenarios, conformance evidence, and explicit operator
promotion bind every mandatory trust dimension below.

The marketplace registry extends local catalog resolution (`scripts/graph/packages/resolver.py`)
with remote registry fetch, digest pinning, signer policy, revocation, transitive dependency
closure, reproducible resolution, and durable audit evidence. Trust anchors remain
out-of-band (`.cursor/sw-package-trust-anchors.json`) — never sourced from packs or
registries (PRD 272 R21).

## Trust and resolution policy (v1.0.0)

| Dimension | Requirement | Normalized refusal |
| --- | --- | --- |
| `digest-pinning` | Lockfile pins MUST include 64-hex `contentDigest`; discovery≠trust | `pin-mismatch` |
| `signer-policy` | Packages MUST carry signed provenance from an active trust-anchor key | `unsigned-package` |
| `revocation` | Revoked or expired signer keys refuse install and resolution | `revoked-signer` |
| `transitive-dependency-policy` | Full transitive closure MUST be pinned, signed, and policy-approved | `transitive-policy-refused` |
| `reproducible-resolution` | Same pin + lock digest MUST yield identical resolved artifacts | `non-reproducible-resolution` |
| `audit-evidence` | Structured install/resolve audit trail with correlation ids | `missing-audit-evidence` |

Every dimension MUST pass an enablement test before any shipped or parity claim.

## Pinned reference contract (R10, R21)

Marketplace references are lock-pinned tuples — floating ranges or tag-only refs are refused:

| Field | Requirement | Normalized refusal |
| --- | --- | --- |
| `pin` | Canonical `name@semver` identity | `unpinned-reference` |
| `digest` | 64-hex SHA-256 of unsigned package body | `pin-mismatch` |
| `signerKeyId` | Active trust-anchor key id bound in lockfile | `unsigned-package` |
| `dependencies` | Explicit transitive pins covering full closure | `transitive-policy-refused` |
| `registryUrl` | Optional bounded HTTPS registry endpoint (broker-scoped) | `malformed-registry` |

The P3 stub validates pinned references locally and returns `not-enabled` — it performs
no remote resolution, download, or installation.

## Signer policy and revocation (R11, R21)

| Policy | Behavior |
| --- | --- |
| Active keys | `status: active` with valid `notBefore`/`notAfter` window |
| Revoked keys | Immediate fail-closed refusal — no grace install |
| Expired keys | Refused; operator must re-pin under a current key |
| Unknown keys | Refused — trust anchors are operator-configured only |

Signer verification reuses `graph.packages.trust.verify_package_signature` and
`TrustAnchorStore.require_active_key`. Registry metadata MUST NOT override anchor status.

## Transitive dependency policy (R21)

1. Lockfile MUST enumerate every direct and transitive dependency pin.
2. `validate_lock_transitive_closure` MUST pass before any install claim.
3. Dependencies outside the declared closure are refused (`transitive-policy-refused`).
4. Lock edits require the same human approval record as pack approval (R21).

## Reproducible resolution (R10, R18)

Resolution is reproducible when:

1. Pin identity, digest, and signer binding match the lockfile entry.
2. Canonical JSON serialization yields a stable `contentDigest`.
3. Repeated resolution of the same lock produces identical `ResolvedPackage` tuples.
4. Registry index drift or metadata-only changes without digest change are ignored.

Non-reproducible resolution (digest drift, identity mismatch, or index ambiguity) MUST
fail closed with `non-reproducible-resolution`.

## Audit evidence (R11)

Every future shipped install MUST retain:

| Event | Fields |
| --- | --- |
| `resolve` | `pin`, `digest`, `signerKeyId`, `registryUrl`, `correlationId` |
| `verify` | trust-anchor key status, signature outcome |
| `closure` | transitive pin set, closure validation verdict |
| `refusal` | normalized refusal code, dimension, operator replay hint |

Evidence records MUST cite `trustPolicyVersion: "1.0.0"`. Partial evidence MUST NOT
produce `trustComplete: true` or enter a shipped registry.

## Corpus evidence prerequisites (R11)

Marketplace trust claims require binding **all** eval-corpus scenarios:

| Scenario id | Exercises |
| --- | --- |
| `marketplace-trust-resolution` | Digest pinning, signer policy, revocation refusal |
| `package-transitive-closure` | Transitive dependency policy and lock closure |
| `marketplace-revocation-handling` | Revoked signer + audit evidence retention |

Evidence records live under `scripts/test/fixtures/workflow-package-marketplace/` and MUST
cite `trustPolicyVersion: "1.0.0"`. The P3 stub adapter (`scripts/graph/packages/marketplace.py`)
exposes conformance metadata only — it cannot enter `SHIPPED_PACKAGE_REGISTRIES` or claim
`trustComplete: true`.

## Enablement gates (fail closed, R13, R18)

1. Green trust-policy evaluation for every mandatory dimension on fixture packages.
2. Corpus manifest includes all three marketplace scenarios with holdout isolation.
3. Recorded conformance fixture `marketplace.ok.json` with green dimension outcomes.
4. Registry credentials resolve only through broker (`graphExecution.packages.marketplace.credentialRef`).
5. Explicit operator promotion in a follow-on unit — no silent registry promotion.
6. Default workflow config MUST NOT select `marketplace`; factory defaults to `local-catalog`.

Until all gates are green, `register_marketplace_registry_stub()` reports
`status: not-enabled` and every resolve/install operation returns `not-enabled` with no
remote mutation.

## Configuration (future — not active)

| Key | Purpose |
| --- | --- |
| `graphExecution.packages.registry` | `marketplace` (blocked pre-ship) |
| `graphExecution.packages.marketplace.credentialRef` | Broker ref for read-only registry API |
| `graphExecution.packages.marketplace.registryUrl` | Bounded HTTPS registry endpoint |
| `graphExecution.packages.marketplace.auditRoot` | Host-owned audit journal directory |

## Operator surfaces

- `graph.packages.resolver.package_p3_stub_registration_footprint()` — conformance metadata for P3 stubs.
- `scripts/graph/packages/marketplace.py` — stub registration (`register_marketplace_registry_stub`).

See also: `scripts/graph/packages/resolver.py`, `scripts/graph/packages/trust.py`,
`.sw/program-priorities.json` (`workflow-package-marketplace` follows `upstream-provenance`
in `providerFollowOn`).
