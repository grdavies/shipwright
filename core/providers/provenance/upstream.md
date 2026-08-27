---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: provenance.upstream.analyzer
        equals: enabled
    metadata:
      providerFamily: provenance
      adapterId: upstream-provenance
      selectionFamily: providers
      status: spec-stub
      programPriority: P2
---

# Upstream provenance analyzer (PRD 333 phase 9 — P2 spec stub)

**Status:** specification + analyzer stub only — **not shipped**. Enabling
`provenance.upstream.analyzer: enabled` MUST fail closed with `not-enabled`
until green eval-corpus lineage scenarios, conformance evidence, and explicit operator
promotion bind every mandatory evidence dimension below.

Automated upstream provenance resolves how a consumer repository relates to an
authoritative upstream remote: identity binding, revision ancestry, patch lineage,
confidence scoring, ambiguity handling, unavailable-upstream degradation, and durable
evidence retention. The P2 phase defines inputs and evidence contracts only — no
network analysis or parity claims are implemented here.

## Automated inputs contract (v1.0.0)

| Input | Requirement | Normalized refusal |
| --- | --- | --- |
| `remoteUrl` | Canonical HTTPS or `git@host:path` remote without embedded credentials | `malformed-remote` |
| `revision` | 7–40 lowercase hex git object id (commit SHA) | `malformed-revision` |
| `localRevision` | Optional local HEAD for ancestry comparison | `malformed-revision` |
| `patchSeries` | Optional ordered patch refs (`base..tip`) for lineage claims | `malformed-patch-lineage` |
| `candidateRemotes` | Optional bounded list when ambiguity probing is requested | `ambiguous-upstream` |

Inputs MUST be validated before any future analysis stage. The P2 stub validates
bounded inputs and returns `not-enabled` without contacting remotes or providers.

## Evidence contract (R7, R11, R13, R18)

Every shipped provenance claim MUST retain and cite **all** dimensions:

| Dimension | Records | Normalized refusal |
| --- | --- | --- |
| `remote-identity` | Canonical remote URL, host, owner/repo binding | `identity-mismatch` |
| `revision-ancestry` | Common ancestor, ahead/behind counts, merge-base SHA | `ancestry-unresolved` |
| `patch-lineage` | Patch series order, cherry-pick markers, fork divergence class | `patch-lineage-incomplete` |
| `confidence` | Scored 0.0–1.0 with explicit contributing signals | `confidence-below-threshold` |
| `ambiguity` | Ranked candidate remotes when multiple upstreams match | `ambiguous-upstream` |
| `unavailable-upstream` | Shallow clone, missing remote, or auth refusal handling | `upstream-unavailable` |
| `evidence-retention` | Bounded JSON record + digest with retention policy id | `missing-evidence-retention` |

Evidence records MUST cite `evidenceContractVersion: "1.0.0"`. Partial dimension sets
MUST NOT produce `provenanceComplete: true` or any parity claim.

## Unavailable-upstream handling (fail closed)

When a remote is unreachable, credentials are refused, or history is too shallow:

1. Emit `upstream-unavailable` with explicit cause (`network`, `auth`, `shallow-history`).
2. Do **not** infer ancestry or patch lineage from local state alone.
3. Retain the input envelope and refusal record for operator replay.
4. Refuse `provenanceComplete` until a successful corpus-backed replay exists.

## Corpus evidence prerequisites (R11)

Provenance claims require binding **all** eval-corpus scenarios:

| Scenario id | Exercises |
| --- | --- |
| `upstream-lineage-resolve` | Remote identity + revision ancestry on fixture remotes |
| `patch-lineage-fork` | Patch series / fork divergence classification |
| `upstream-unavailable-handling` | Shallow/unreachable upstream refusal + retention |

Evidence records live under `scripts/test/fixtures/upstream-provenance/` and MUST
cite `evidenceContractVersion: "1.0.0"`. The P2 stub (`scripts/upstream_provenance.py`)
exposes conformance metadata only — it cannot claim `provenanceComplete: true` or
enter a shipped analyzer registry.

## Enablement gates (fail closed, R13, R18)

1. Green eval-corpus execution for all three upstream-provenance scenarios with holdout isolation.
2. Recorded conformance fixture `upstream-provenance.ok.json` with green dimension outcomes.
3. Remote identity broker scope validated (`provenance-upstream:read` only — no mutation scopes).
4. Explicit operator promotion in a follow-on unit — no silent registry promotion.
5. Default workflow config MUST NOT set `provenance.upstream.analyzer: enabled`.

Until all gates are green, `register_upstream_provenance_stub()` reports
`status: not-enabled` and every analyze dispatch returns `not-enabled` with no network
mutation or parity claim.

## Configuration (future — not active)

| Key | Purpose |
| --- | --- |
| `provenance.upstream.analyzer` | `enabled` (blocked pre-ship) |
| `provenance.upstream.credentialRef` | Broker ref for read-only upstream probe |
| `provenance.upstream.retentionPolicy` | Evidence retention policy id |
| `provenance.upstream.confidenceThreshold` | Minimum confidence for operator surfacing |

## Operator surfaces

- `scripts/upstream_provenance.py register` — conformance metadata for P2 stub.
- `scripts/upstream_provenance.py analyze` — validates bounded inputs; returns `not-enabled`.
- `python3 scripts/sw_bootstrap.py upstream_provenance.py -- analyze ...` — bootstrap dispatch.

See also: `.sw/program-priorities.json` (`upstream-provenance` follows `remote-execution`
in `providerFollowOn`).
