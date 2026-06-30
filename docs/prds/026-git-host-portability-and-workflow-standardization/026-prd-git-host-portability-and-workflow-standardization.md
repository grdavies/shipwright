---
brainstorm: docs/brainstorms/2026-06-27-git-host-portability-and-workflow-standardization-requirements.md
date: 2026-06-27
topic: git-host-portability-and-workflow-standardization
frozen: true
frozen_at: 2026-06-27
---
# PRD 026 — Git host portability and workflow standardization

## Overview

Shipwright's source-control integration is GitHub-only and hard-coupled to the `gh` CLI at the
CI-readiness/merge gate, the terminal PR flow, and several helpers. This PRD makes that integration
portable across multiple git hosts (GitHub, GitLab, Bitbucket) and a fully local, no-remote mode by
introducing a **host/forge provider abstraction** that talks to each host over its REST API instead of
`gh`. In the same epic it adds a native, host-agnostic **git-workflow skill**, **hard-enforced conventions**
for branch names / commit messages / PR-merge bodies, and a **documentation-on-a-branch policy** so
brainstorm/PRD/doc work never accrues as local commits on the protected `main` branch.

The host abstraction is the foundation the rest of the epic builds on, so delivery is phased: adapter
foundation → GitHub gate abstraction over REST → no-remote local mode → GitLab/Bitbucket adapters plus
PR-automation fixes → git-workflow skill, convention enforcement, and docs-branch policy.

This PRD is derived from the frozen-intent brainstorm
(`docs/brainstorms/2026-06-27-git-host-portability-and-workflow-standardization-requirements.md`, R1–R34).
It extends prior portability work in **PRD 018 (generic-repo-portability)** — which abstracted base-branch
resolution and verify sentinels but not multi-host PR/CI — and folds in GAP-BACKLOG rows 41, 42, and 44
(PR automation) and the additive documentation-durability portion of row 23.

## Goals

- Remove the hard `gh` CLI dependency so the plugin installs and runs without any host CLI, simplifying
  installation and configuration.
- Support GitHub, GitLab, Bitbucket, and a first-class no-remote (local-only) mode through one host-provider
  abstraction that mirrors the existing memory/review provider pattern.
- Preserve the human merge gate and the review/CI/audit intent of global rule #1350 in every mode,
  including no-remote.
- Standardize and mechanically enforce branch names, commit messages, and PR/merge bodies.
- Move documentation authoring off the protected default branch and close the brainstorm-document data-loss
  window.
- Fix recurring PR-automation defects (phase-PR base targeting, branch-identity auto-close, `host-open-pr`
  cleanup blocking).
- Make host API access resilient to rate limiting across all hosts, so the workflow waits and resumes
  gracefully instead of failing when a limit is hit.

## Non-Goals

- Memory source-of-truth policy (owned by PRD 015).
- Operator-facing raw-git resume/handoff wording (owned by PRD 017).
- `copy-to-core` build-chain source-of-truth reconciliation (GAP-BACKLOG row 39).
- Multi-host abstraction of the CodeRabbit review adapter; `review.provider` is `none` today, and the
  CodeRabbit adapter remains GitHub-coupled and is explicitly out of scope for this epic.
- Replacing or reworking release-please semantic-version automation.
- Building a general-purpose git GUI or arbitrary git operation surface beyond the workflow's needs.
- A non-GitHub CI-results polling integration beyond what each host's REST checks/pipelines endpoint
  provides; deep CI-provider analytics are out of scope.

## Requirements

Requirements R1–R34 carry forward from the brainstorm with stable R-IDs; R35–R42 are added during PRD review
to cover host API rate-limit resilience.

### Host/forge provider abstraction

- **R1** A `host.provider` configuration key in `workflow.config.json` selects the host adapter, with the
  enumerated values `github`, `gitlab`, `bitbucket`, and `none`, resolved through the existing
  capability-manifest selection mechanism.
- **R2** Host adapters are authored under `core/providers/host/<id>.md` (agent procedures plus capability
  frontmatter) and, where a deterministic consumer requires machine output, `core/providers/host/<id>.sh`
  (emitting JSON on stdout), and the emitter propagates them into both `dist/` trees.
- **R3** The abstraction defines a stable host-operation verb set covering at minimum
  resolve-pr-for-branch, pr-create, pr-view, pr-list, checks-status, review-threads, repo-identity,
  ci-watch, and merge; each adapter declares per-verb capability flags so unsupported operations degrade
  explicitly rather than failing opaquely.
- **R4** The GitHub adapter implements the verb set over the GitHub REST API and replaces every direct `gh`
  invocation in `scripts/check-gate.py`, `scripts/wave_terminal.py`, `scripts/stabilize-merge-sync.py`,
  `scripts/wave_compound.py`, `scripts/cleanup_lib.py`, and `scripts/reconcile-status.py`.
- **R5** No host CLI (`gh`, `glab`, or equivalent) is a required installation prerequisite or an invoked
  runtime dependency of the workflow; the host HTTP API (REST, with GraphQL where REST lacks parity) accessed
  via `curl` plus a token is the sole supported transport.
- **R6** The host provider is auto-detected from the configured remote's URL for public hosts
  (github.com, gitlab.com, bitbucket.org) and is overridable via `host.provider`, with self-hosted instances
  configured through a host base URL.
- **R7** The remote name is configurable through a `host.remote` key (default `origin`), and the hard-coded
  `origin` literal is removed from `scripts/wave_merge.py`, `scripts/wave_terminal.py`,
  `scripts/stabilize-merge-sync.py`, `scripts/worktree.py`, and `scripts/cleanup_lib.py`.
- **R8** Authentication tokens are referenced by environment-variable name in configuration (for example
  `host.tokenEnv`), never stored as literal secrets in configuration, and a missing token degrades to the
  no-remote/offline path rather than leaking the value or aborting uncontrollably.

### No-remote / local-only mode

- **R9** Selecting `host.provider: none`, or detecting no remote, activates a local-only host adapter whose
  PR-oriented verbs are local-evidence equivalents or explicit no-ops.
- **R10** The existing `local_evidence_authorizing` path is generalized to the terminal (feature → trunk)
  tier: the terminal gate runs the full checks-gate locally, requires a green verdict, and emits a recorded
  local-merge-gate audit artifact capturing the head binding and gate evidence.
- **R11** In local mode the final merge into the trunk branch halts for explicit human action by default and
  never auto-merges the trunk.
- **R12** When no host CI is available, CI-watch degrades to relying on the local checks-gate evidence and
  requires no host CI polling.
- **R13** `scripts/check-gate.py` returns a local-evidence verdict instead of the blocked
  "no open PR for current branch" result when the host provider is `none` or local.

### Gate and prose abstraction

- **R14** `scripts/check-gate.py` obtains PR number, CI checks, unresolved review threads, and repository
  identity through the host-adapter verb set rather than direct `gh` calls, preserving its read-only,
  non-mutating contract.
- **R15** The terminal flow in `scripts/wave_terminal.py` performs PR prepare, create, list, view, and head
  push through the host adapter and the configurable remote, preserving the human merge gate
  (`neverAutoMergesMain`).
- **R16** `scripts/stabilize-merge-sync.py` obtains PR metadata and runs its conflict probe through the host
  adapter and configurable remote.
- **R17** Agent-facing prose in `sw-watch-ci`, `sw-stabilize`, `sw-pr`, `sw-ready`, `sw-cleanup`, and
  `sw-execute` commands, and in the `checks-gate`, `stabilize-loop`, and `conductor` skills, uses
  host-agnostic verbs with no literal `gh` invocations in agent instructions.

### Multi-host adapters and PR-automation fixes

- **R18** A GitLab adapter implements the verb set over the GitLab REST API (merge requests), with a
  configurable base URL for self-hosted GitLab.
- **R19** A Bitbucket adapter implements the verb set over the Bitbucket REST API (pull requests).
- **R20** In phase mode, PR/merge-request creation targets the integration branch `<type>/<slug>` from
  deliver state and fails closed when `SW_PHASE_MODE` is set and the resolved base is not the integration
  branch (GAP row 42).
- **R21** At `green-merged` and at terminal-wave assembly, deliver closes superseded phase PRs keyed on
  branch identity from deliver state rather than commit ancestry, idempotently, and only for phases recorded
  `green-merged` for the current run (GAP row 44, including the head-not-ancestor mode).
- **R22** Cleanup is not blocked by an open phase-head PR for phases recorded `green-merged` for the run; the
  superseded-PR close in R21 runs before branch and worktree cleanup (GAP row 41).

### Rate-limit resilience and retry

- **R35** Every host adapter detects throttling responses — GitHub `403` or `429` with
  `x-ratelimit-remaining: 0` or a secondary-rate-limit message, GitLab `429`, and Bitbucket `429`
  ("rate limit exceeded") — and classifies them as transient throttling, never surfacing a throttle as a
  hard workflow failure.
- **R36** On a throttle, the adapter computes the wait in a fixed priority order: first honor a `Retry-After`
  header when present (integer seconds or HTTP-date); otherwise, when remaining is `0`, wait until the reset
  header (`x-ratelimit-reset` or `RateLimit-Reset` in UTC epoch seconds, or `RateLimit-ResetTime` as an
  HTTP-date); otherwise apply exponential backoff with full jitter.
- **R37** Retries are bounded by a configurable maximum attempt count and a maximum cumulative wait; on
  exhaustion the verb returns a typed `rate-limited` outcome that the gate and conductor treat as a
  retriable, resumable halt with a clear operator message — never an unhandled crash or a silent stall.
- **R38** Adapters read rate-limit headers on every response and pre-emptively pause before issuing a call
  when near the limit — remaining at or below a configurable threshold, or Bitbucket
  `X-RateLimit-NearLimit: true` — to avoid tripping the limit rather than only reacting after a `429`.
- **R39** Host calls are issued serially (no concurrent requests to the same host), mutating requests
  (`POST`/`PATCH`/`PUT`/`DELETE`) are paced with a minimum inter-request delay (at least one second for
  GitHub), and CI-watch uses bounded poll intervals rather than tight loops, per each host's documented best
  practice.
- **R40** Because Bitbucket Cloud frequently omits `Retry-After` and a reset header on `429`, the Bitbucket
  adapter defaults to exponential backoff with full jitter against its rolling one-hour window and never
  assumes a reset header is present; per-host capability flags record which retry signals each host provides.
- **R41** Rate-limit behavior is configurable under a `host.rateLimit` object (maximum attempts, base and cap
  backoff, jitter, near-limit threshold, and minimum mutating-request spacing, with optional per-provider
  overrides) with documented defaults; effective limits are read from response headers at runtime, and
  self-hosted GitLab limits (which are admin-defined) are never hard-coded.
- **R42** Backoff and pre-emptive-pause events are logged (run log and gate output) with the attempt number,
  the computed wait, and the reason (`retry-after`, `reset`, `backoff`, or `near-limit`), and never include
  the token, so operators observe graceful waiting instead of silent stalls or failures.

### git-workflow skill and convention enforcement

- **R23** A native, sw-namespaced `skills/git-workflow` skill, informed by and crediting
  `netresearch/git-workflow-skill` under its CC-BY-SA-4.0 / MIT licenses, documents the Shipwright
  trunk-based-with-worktrees model, branch naming, Conventional Commits, and PR/merge conventions, and is
  host-agnostic.
- **R24** Branch names are enforced through `branch-name-guard` wired into worktree and branch creation and
  the gate, and non-conforming branch names fail closed.
- **R25** A commit-message validator enforces Conventional Commits types sourced from
  `release-please-config.json` at a commit path or hook, and non-conforming commit messages fail closed.
- **R26** Standardized PR/merge-request description and merge-commit body templates are defined, the host
  adapter applies them, and required template fields are enforced so missing fields fail closed.
- **R27** The conventions are documented once in the git-workflow skill and a dedicated
  `sw-git-conventions` rule and are referenced rather than duplicated elsewhere.

### Documentation-on-a-branch policy and durability

- **R28** Brainstorm, PRD, and documentation-pipeline authoring occurs on a dedicated `docs/<topic>` branch
  in its own worktree, and the workflow does not create local commits on the protected default branch.
- **R29** Tooling creates or resumes a docs worktree and branch for a documentation effort, and the doc
  commands operate within it.
- **R30** Documentation reaches the default branch through a docs-only PR consistent with branch protection,
  and the workflow never pushes directly to a protected default branch.
- **R31** Brainstorm documents are committed and durable on the docs branch, closing the data-loss window
  left by the current `scripts/wave_spec_seed.py` brainstorm exclusion.
- **R32** The durability model is reconciled with the shipped PRD 013: feature-branch spec-seed remains for
  the implementation handoff, while the canonical documentation durability target is the default branch via
  the docs-branch PR, so documentation is durable independent of whether any feature branch merges.

### Migration and operability

- **R33** Existing GitHub repositories continue to work after migration with no manual reconfiguration beyond
  providing a token environment variable, because the GitHub host is auto-detected.
- **R34** A doctor/setup check in `/sw-init` (and `sw-configure`) validates host provider, token presence,
  remote name, and branch-protection status, and warns without blocking when capability is degraded.

## Technical Requirements

- **TR1 — Adapter interface.** Each host adapter implements the R3 verb set behind a single dispatch entry
  (`scripts/host.sh <verb> [args]` resolving `host.provider` via `capability-select`). Verbs emit stable
  JSON on stdout; consumers (`check-gate.py`, `wave_terminal.py`, `stabilize-merge-sync.py`) parse JSON and
  never shell out to `gh` directly. The verb contract and JSON shapes live in
  `core/providers/host/CAPABILITIES.md`, mirroring `core/providers/review/CAPABILITIES.md`.
- **TR2 — Capability flags.** Adapters declare flags such as `pullRequests`, `reviewThreads`, `checksApi`,
  `ciWatch`, and `serverSideMerge`. The local (`none`) adapter declares `pullRequests: false` and routes the
  gate to local evidence. Consumers branch on flags, not on provider name.
- **TR3 — Config schema.** `.sw/config.schema.json` gains a `host` object: `provider`
  (`github|gitlab|bitbucket|none`), `remote` (string, default `origin`), `baseUrl` (string, optional, for
  self-hosted web/API base), `apiBaseUrl` (string, optional), `tokenEnv` (string, the environment
  variable name holding the token), and `rateLimit` (object, see TR10). All keys are optional with documented
  defaults; absence auto-detects.
- **TR4 — Transport.** Adapters call the host HTTP API with `curl` over HTTPS — REST for most verbs, and
  GraphQL where REST lacks parity (notably GitHub review-thread *resolution* state, which is GraphQL-only) —
  routed through the shared rate-limit retry wrapper (TR10) with explicit status-code handling. The token is
  read from `getenv(host.tokenEnv)` at call time and passed via an HTTP header supplied through a method that
  does not expose it in process arguments (for example a `curl` config/header file or stdin), never as a
  plaintext command-line argument. Responses are treated as untrusted input (TR9). No token value is ever
  written to logs, state, or memory.
- **TR5 — Local merge gate artifact.** R10 writes a `local-merge-gate` record (JSON) under the run directory
  capturing `verdict: green`, `source: local-evidence`, `head`, `gate` evidence, and a timestamp; the
  terminal flow consumes it as the authorization equivalent of a PR check-gate result, and the human merge
  halt remains.
- **TR6 — `origin` removal.** A repository-wide guard fixture asserts no hard-coded `origin` literal remains
  in the merge/push/sync/cleanup scripts enumerated in R7; all use `host.remote`.
- **TR7 — PR base/auto-close (R20–R22).** Phase-mode PR creation reads the integration branch from deliver
  state and fails closed on mismatch; superseded-PR close enumerates phase PR records from deliver state and
  closes by branch identity; cleanup ordering runs close-then-clean.
- **TR8 — Docs worktree tooling (R28–R31).** A docs entry (extending `/sw-worktree` or a doc-pipeline
  helper) provisions `docs/<topic>` worktrees; `wave_spec_seed.py` no longer leaves brainstorms
  uncommitted; the docs-only PR path reuses the living-doc write-serialization lock.
- **TR9 — Trust boundary.** Host REST responses, PR/issue bodies, and review-thread content are untrusted;
  any such content forwarded into agent context is wrapped per the dispatch redaction contract and never
  executed or interpolated into shell.
- **TR10 — Rate-limit retry policy (R35–R42).** A shared transport wrapper applies the retry/backoff loop
  for every adapter verb. Per-host signal map:

  | Host | Throttle status | Honor first | Reset header | Near-limit signal |
  | --- | --- | --- | --- | --- |
  | GitHub | `403` or `429` (remaining `0` / secondary message) | `retry-after` (secondary limits) | `x-ratelimit-reset` (UTC epoch) | `x-ratelimit-remaining` at or below threshold |
  | GitLab | `429` | `Retry-After` (seconds) | `RateLimit-Reset` (epoch) or `RateLimit-ResetTime` (HTTP-date) | `RateLimit-Remaining` at or below threshold |
  | Bitbucket | `429` | (often absent — use backoff) | (often absent) | `X-RateLimit-NearLimit: true` (under 20% remaining) |

  Wait computation: use `Retry-After` when present; otherwise the reset header when remaining is `0`;
  otherwise `min(cap, base * 2^attempt)` plus full jitter. The loop stops on `maxAttempts` or
  `maxCumulativeWait`, returning a `rate-limited` retriable outcome (R37). The wrapper always waits before
  the next attempt; continuing to call while throttled risks an integration ban on GitHub. Defaults live in
  `host.rateLimit` (TR3) and are overridable per provider.

## Security & Compliance

- Tokens are referenced by environment-variable name only (R8, TR3); literal secrets in configuration are
  prohibited and caught by the existing redaction chokepoint and secret-scan.
- The pre-push secret scan (`scripts/secret-scan.py`) and the range-scoped history-redaction guardrail
  remain in force across all hosts and the local mode.
- REST transport is HTTPS-only; self-hosted base URLs are validated as well-formed URLs before use.
- Tokens require least-privilege scopes (repository read plus pull-request/merge-request write); the doctor
  check (R34) reports missing or over-broad token presence without printing the value.
- The human merge gate to the trunk is preserved in every mode (R11, R15); no path auto-merges the default
  branch.
- Host REST responses are treated as untrusted input (TR9) and never interpolated into shell or executed.
- Rate-limit backoff and pause logs record only the attempt number and wait reason — never the token or raw
  response bodies (R42, TR10).

## Testing Strategy

- **Adapter selection** — fixtures assert `host.provider` resolves the correct adapter and capability flags,
  and that auto-detection maps remote URLs to providers (R1, R2, R6).
- **`gh` removal guard** — a fixture greps the enumerated runtime scripts and asserts zero direct `gh`
  invocations remain, and asserts the workflow runs with `gh` absent from `PATH` (R4, R5).
- **`origin` guard** — fixture asserts no hard-coded `origin` literal in the R7 scripts (TR6).
- **Local merge gate** — fixtures assert no-remote mode yields a local-evidence verdict (not "no open PR"),
  writes the local-merge-gate artifact, and halts for human merge (R9–R13, TR5).
- **Multi-host adapters** — fixtures exercise GitHub/GitLab/Bitbucket verbs against recorded/mocked REST
  responses (R4, R18, R19).
- **PR automation** — fixtures: phase-mode PR base equals the integration branch and fails closed on
  mismatch (R20); superseded phase PRs close by branch identity regardless of ancestry (R21); cleanup is not
  blocked by `host-open-pr` for recorded-merged phases (R22).
- **Rate-limit resilience** — fixtures simulate throttled responses per host: `Retry-After` honored;
  `remaining: 0` plus a reset header waited out; a Bitbucket `429` with no `Retry-After` falls back to
  jittered exponential backoff; a near-limit header triggers a pre-emptive pause; and max-attempt or
  max-cumulative-wait exhaustion returns a `rate-limited` retriable halt rather than crashing
  (R35–R42, TR10).
- **Convention enforcement** — fixtures for branch-name-guard rejection, commit-message validator rejection,
  and PR/merge template required-field enforcement (R24–R26).
- **Docs-branch policy** — fixtures assert doc authoring targets a `docs/<topic>` branch, never the default
  branch, brainstorms are committed/durable, and docs land via PR (R28–R32).
- **Migration/doctor** — fixture asserts an existing GitHub repo needs only a token env var and the doctor
  check reports degraded capability as a warning (R33, R34).
- **Token handling** — fixture asserts the token is not present in the adapter's process argument list and
  not emitted to logs/state (TR4).
- **Install-docs currency** — fixture asserts user-facing installation/setup docs do not list `gh` as a
  prerequisite once Phase 2 lands (R5, docs-currency).
- All new fixtures register in the PR test-plan manifest (`core/sw-reference/pr-test-plan.manifest.json`)
  and run in `verify.test`.

## Rollout Plan

Phased delivery; each phase ships behind passing fixtures and is independently mergeable.

- **Phase 1 — Host adapter foundation.** Config schema (`host.*`, including `host.rateLimit`), adapter
  contract (`core/providers/host/CAPABILITIES.md`), GitHub/local adapters scaffolded, capability-manifest
  selection, auto-detection, doctor check, and the shared rate-limit retry wrapper (core policy plus the
  GitHub/local signal mapping; GitLab and Bitbucket signal mapping completes in Phase 4). Requirements: R1,
  R2, R3, R6, R7, R8, R33, R34, R35, R36, R37, R38, R39, R41, R42, TR1–TR4, TR6, TR10.
- **Phase 2 — GitHub gate abstraction over REST.** Refactor `check-gate.py`, `wave_terminal.py`,
  `stabilize-merge-sync.py`, `wave_compound.py`, `cleanup_lib.py`, `reconcile-status.py`, and command/skill
  prose to the verb set; remove `gh`. Update user-facing installation/setup documentation (README and
  `/sw-init` guidance) to drop the `gh` prerequisite and document `host.tokenEnv`. Requirements: R4, R5, R14,
  R15, R16, R17.
- **Phase 3 — No-remote local mode.** Generalize local-evidence to the terminal tier; local merge gate
  artifact; CI-watch degradation. Requirements: R9, R10, R11, R12, R13, TR5.
- **Phase 4 — GitLab + Bitbucket + PR-automation fixes.** Two adapters (including their rate-limit signal
  mapping, R40) plus the R20–R22 fixes. Requirements: R18, R19, R20, R21, R22, R40, TR7.
- **Phase 5 — Workflow standardization.** git-workflow skill, convention enforcement, docs-branch policy and
  tooling, brainstorm durability. Requirements: R23, R24, R25, R26, R27, R28, R29, R30, R31, R32, TR8.

## Decision Log

- **D1.** One cohesive phased epic rather than separate PRDs — the host abstraction underpins the other
  themes; coupling them keeps the gate refactor and the dependent conventions/policy coherent.
- **D2.** Native REST transport (curl + token) rather than per-host CLIs or a hybrid — uniform across hosts
  and the only approach that removes the install prerequisite (the stated simplification goal).
- **D3.** Host/forge provider family mirrors the memory/review adapter pattern (capability frontmatter +
  capability-manifest selection) rather than a bespoke mechanism — reuses proven, tested infrastructure.
- **D4.** No-remote mode generalizes the existing `local_evidence_authorizing` path rather than introducing a
  new gate — lower risk, reuses the merge machinery, preserves rule #1350 intent.
- **D5.** Documentation-on-a-branch policy with PR to the default branch — protection-safe; keeps the default
  branch clean for worktree bases.
- **D6.** Documentation durability is additive over the shipped PRD 013 — close the brainstorm gap and make
  the default branch the canonical durability target, retaining feature-branch spec-seed for implementation
  handoff.
- **D7.** Native git-workflow skill informed by and crediting netresearch rather than vendoring it — avoids
  inheriting `gh` assumptions and a foreign structure; sw-namespaced and enforceable.
- **D8.** Hard mechanical enforcement of conventions (branch names, commit messages, PR/merge templates)
  rather than advisory guidance — matches the "set and enforce standard patterns" goal and is auditable.
- **D9.** GAP folding: rows 41/42/44 fold in under the host adapter; row 23 folds in as additive
  documentation-durability work; rows 25/33/39 remain in their own tracks.
- **D10.** (resolves brainstorm open question — auth granularity) A single `host.tokenEnv` names the token
  environment variable, with optional per-provider override keys; both classic and fine-grained tokens are
  accepted, with fine-grained least-privilege tokens recommended.
- **D11.** (resolves brainstorm open question — self-hosted base URLs) Self-hosted instances are configured
  via `host.baseUrl` (and optional `host.apiBaseUrl`); public hosts auto-detect.
- **D12.** (resolves brainstorm open question — drop `gh` vs fallback) `gh` is removed as a workflow
  dependency with no fallback; the host HTTP API via `curl`+token (REST, plus GraphQL where REST lacks
  parity) is the sole transport. This maximizes install simplicity; it is the most consequential decision and
  is the first item to revisit if API parity proves insufficient during Phase 2. (Review note: GitHub
  review-thread *resolution* state is GraphQL-only — handled by GraphQL-over-curl, still no `gh`.)
- **D13.** (resolves brainstorm open question — docs-branch concurrency) `docs/<topic>` worktrees reuse the
  existing per-worktree state and the living-doc write-serialization lock; no new concurrency primitive is
  introduced.
- **D14.** (resolves brainstorm open question — local-mode trunk semantics) Local mode targets
  `defaultBaseBranch` as trunk by default (configurable via the existing base resolver) and simulates
  protection by requiring the recorded green local-merge-gate artifact plus an explicit human merge.
- **D15.** (deferral decision) GitLab and Bitbucket REST *pagination* tuning is finalized during Phase 4
  against live API behavior; it is an implementation-level refinement and does not block freeze. Rate-limit
  resilience is no longer deferred — it is promoted to first-class requirements (R35–R42, TR10).
- **D16.** (deferral decision) Whether the R34 doctor check additionally probes token-scope sufficiency via a
  lightweight authenticated REST call is decided during Phase 1 implementation per each host's API support;
  it is an implementation-level refinement and does not block freeze.
- **D17.** (review-driven addition — rate-limit resilience) Host API rate limiting is handled by a shared,
  header-driven retry wrapper (R35–R42, TR10): honor `Retry-After`, then the reset header when remaining is
  `0`, then jittered exponential backoff; bounded by max attempts and cumulative wait; fail-soft to a
  retriable, resumable halt so the workflow never just fails on a limit. Grounded in published GitHub,
  GitLab, and Bitbucket best practices — including GitHub's ban risk for ignoring limits and Bitbucket's
  frequent absence of `Retry-After`, which mandates backoff-by-default.

## Open Questions

None. All brainstorm open questions are resolved in the Decision Log (D10–D14); the non-blocking
implementation refinements are recorded as deferral decisions (D15, D16); and rate-limit resilience is
specified as requirements (R35–R42, TR10, D17).
