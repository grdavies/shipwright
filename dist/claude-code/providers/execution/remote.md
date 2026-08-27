---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: graphExecution.execution.backend
        equals: remote
    metadata:
      providerFamily: execution
      adapterId: remote
      selectionFamily: providers
      status: spec-stub
      programPriority: P2
---

# Remote execution backend (PRD 333 phase 8 — P2 spec stub)

**Status:** specification + trust-matrix stub only — **not shipped**. Selecting
`graphExecution.execution.backend: remote` MUST fail closed with `not-enabled`
until green eval-corpus trust scenarios, conformance evidence, and explicit operator
promotion bind every mandatory trust dimension below.

Remote execution extends the `ExecutionBackend` contract (`scripts/graph/execution_backend.py`)
with cross-host workload dispatch. The host kernel retains authority over cache identity,
verdict eligibility, and credential capability sets (PRD 271 R10). Backend-reported copies
are advisory only.

## Trust and lifecycle matrix (v1.0.0)

| Dimension | Requirement | Normalized refusal |
| --- | --- | --- |
| `workload-identity` | Stable `(scope_identity, repository_identity, trust_domain, repo_state_identity)` binding for every submit | `identity-mismatch` |
| `isolation` | Workloads run in tenant-scoped sandboxes; no cross-workload filesystem or env bleed | `isolation-failure` |
| `least-privilege-credentials` | Broker-resolved credentials scoped to declared `allowedEndpoints` / `allowedProjectIds`; no ambient env tokens | `over-broad-credentials` |
| `input-output-integrity` | `input_hashes` and terminal `output_hash` verified before host adjudication | `integrity-mismatch` |
| `idempotency` | Duplicate `idempotency_key` returns the same durable handle without side effects | `idempotency-violation` |
| `cancellation` | Cancel surfaces `cancel-acknowledged` before terminal settlement; no orphan workloads | `cancellation-incomplete` |
| `audit-events` | Structured audit trail for submit, poll, cancel, and terminal phases with correlation ids | `missing-audit-evidence` |

Every dimension MUST pass an enablement test before any parity or shipped claim.

## Lifecycle phases (R9, R17)

Remote backends implement the standard `ExecutionBackend` surface:

1. **submit** — returns durable `ExecutionHandle` + idempotency acknowledgement
2. **poll** — non-terminal phases: `pending`, `running`, `cancel-requested`, `cancel-acknowledged`
3. **cancel** — cooperative teardown with acknowledged cancel before terminal
4. **result** — terminal envelope; host adjudicates under kernel authority

Handle durability survives process restart via a host-owned journal (see container backend
reference implementation). Generation fences refuse stale mutations.

## Credential scope (broker-only, R11)

| Scope | Purpose |
| --- | --- |
| `graph-remote-exec:submit` | Dispatch workload to remote runner |
| `graph-remote-exec:read` | Poll status and fetch terminal output |

Credentials resolve only through `credentials.resolver` /
`graphExecution.execution.remote.credentialRef` — never from committed config bodies or
ambient env outside a declared backend entry. `allowedEndpoints` and `allowedProjectIds`
on selector entries are mandatory; resolution refuses out-of-scope remotes and project ids.

## Corpus evidence prerequisites (R11, R17)

Trust claims require binding **all** eval-corpus scenarios:

| Scenario id | Exercises |
| --- | --- |
| `remote-exec-trust` | Identity binding, isolation probe, broker scope gate |
| `container-exec-conformance` | Shared ExecutionBackend conformance suite baseline |
| `handoff-continuity` | Cross-harness durable handle continuity |

Evidence records live under `scripts/test/fixtures/remote-execution-trust/` and MUST cite
`trustMatrixVersion: "1.0.0"`. The P2 stub adapter (`scripts/graph/remote_execution_backend.py`)
exposes conformance metadata only — it cannot enter `SHIPPED_EXECUTION_BACKENDS` or claim
`trustComplete: true`.

## Enablement gates (fail closed, R13, R18)

1. Green trust-matrix evaluation for every mandatory dimension on fixture workloads.
2. Corpus manifest includes all three remote-execution scenarios with holdout isolation.
3. Recorded conformance fixture `remote.ok.json` with green dimension outcomes.
4. Explicit operator promotion in a follow-on unit — no silent registry promotion.
5. Default workflow config MUST NOT select `remote`; factory defaults to `local-sync`.

Until all gates are green, `register_remote_execution_stub()` reports
`status: not-enabled` and every backend operation returns `not-enabled`.

## Configuration (future — not active)

| Key | Purpose |
| --- | --- |
| `graphExecution.execution.backend` | `remote` (blocked pre-ship) |
| `graphExecution.execution.remote.credentialRef` | Broker ref for remote runner API |
| `graphExecution.execution.remote.trustDomain` | Declared trust domain for workload identity |
| `graphExecution.execution.remote.auditRoot` | Host-owned audit journal directory |

## Operator surfaces

- `graph.execution_backend.execution_p2_stub_registration_footprint()` — conformance metadata for P2 stubs.
- `scripts/graph/remote_execution_backend.py` — stub registration (`register_remote_execution_stub`).

See also: `scripts/graph/execution_backend.py`, `.sw/program-priorities.json`
(`remote-execution` follows `gitlab-planning-store` in `providerFollowOn`).
