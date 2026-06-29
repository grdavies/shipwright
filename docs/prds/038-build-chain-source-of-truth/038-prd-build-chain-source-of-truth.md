---
date: 2026-06-29
topic: build-chain-source-of-truth
absorbs: [GAP-032, GAP-054]
depends: [004, 009, 018, 021]
frozen: true
frozen_at: 2026-06-29
---

# PRD 038 — Build-chain source of truth & parity enforcement

## Overview

Shipwright's consumer-repo build chain is `scripts/` (harness) → `core/` (emitter input) → `dist/` (committed
install trees) → golden manifest parity. Runtime deliver and CI gates execute from **repo-root `scripts/`**
(`wave.sh` → `$ROOT/scripts/*`), while committed plugin artifacts under `core/` and `dist/` are refreshed by
`scripts/copy-to-core.sh` and `python3 -m sw generate --all`.

Two open gap classes block reliable propagation:

1. **GAP-032** — `copy-to-core.sh` uses destructive `rsync --delete` for `core/sw-reference/` while `.sw/` is a
   strict subset; core-only artifacts (e.g. `pr-test-plan.manifest.json`, `capability-index.json`) are
   authored under `core/sw-reference/` and risk deletion on sync. Separately, harness changes can land in
   `scripts/` without a matching `core/scripts/` commit — caught only if `run-core-scripts-parity-fixtures.sh`
   is run manually.
2. **GAP-054** — latent `scripts/`↔`core/scripts/` drift (e.g. PR #178 `host_github.sh` `merged_at` fix) stays
   green in CI because `ci.yml` runs emitter + `dist`↔golden parity only; the existing core-scripts parity
   fixture is **not wired into CI or `verify.test`**, so stale-but-mutually-consistent `core/`+`dist`+golden
   trees pass until someone runs the full build chain.

PRD 004 established `copy-to-core`; PRD 009 added the core-scripts parity fixture (GAP-006); PRD 018 defined
portability boundaries; PRD 021 added emitter freshness for manifest artifacts. **None of them** closes the
SoT policy gap or CI enforcement hole. This PRD is a **successor** (parents complete) — not an amendment.

It closes GAP-032 and GAP-054 and reduces recurrence of the GAP-050/051 deterministic-regen conflict class
by making propagation mechanical and CI-visible.

## Goals

- Publish a single authoritative **build-chain SoT map** (what is authored where vs generated).
- Harden `copy-to-core.sh` so destructive sync cannot silently delete legitimate `core/sw-reference/`
  artifacts.
- Wire **`scripts/`↔`core/scripts/` parity into CI** (required check) and `verify.test`.
- Provide one operator entrypoint to run the full sync chain (`copy-to-core` → `generate --all` → golden
  re-snapshot when needed).
- One-shot resync current latent drift on `main` (including GAP-054 `host_github.sh` lineage).

## Non-Goals

- Changing the Cursor plugin install tree (`~/.cursor/plugins/local/shipwright/`) — out of repo scope.
- Making `scripts/` a generated artifact (harness remains repo-root SoT per PRD 004).
- Auto-running the full build chain on every deliver phase by default (optional hook only in v1).
- Replacing `deterministic-regen-paths.json` merge auto-remediation (PRD 036) — complementary only.
- Relocating every `core/sw-reference/` artifact into `.sw/` in one shot — only artifacts that must survive
  `copy-to-core` without hand excludes (phased relocation + manifest).

## Requirements

### Source-of-truth policy

- **R1** The build-chain SoT map is documented in `.sw/layout.md` and encoded in a machine-readable manifest
  `core/sw-reference/build-chain-sot.json` (committed). It MUST state, at minimum:
  - `scripts/` — canonical harness source (runtime entrypoints); MUST NOT be hand-edited only in `core/scripts/`.
  - `core/commands|skills|rules|agents|providers/` — mirrored from repo-root siblings via `copy-to-core`.
  - `core/scripts/` — mirrored from `scripts/` (with documented excludes: `test/`, `check-frozen.sh`).
  - `.sw/` — canonical operator-edited sw-reference **inputs** (subset).
  - `core/sw-reference/` — union of `.sw/` sync output **plus** an explicit **core-authored allowlist** (R2).
  - `dist/{cursor,claude-code}/` — emitter output only; never hand-edited.
  - `scripts/test/fixtures/parity/cursor-golden.manifest` — committed golden; updated only via the sanctioned
    snapshot command (R7).
- **R2** `core/sw-reference/build-chain-sot.json` MUST include a `coreAuthoredAllowlist` array listing paths
  under `core/sw-reference/` (and any other `core/` paths) that are **not** copied from `.sw/` but are
  legitimate committed sources (e.g. `capability-index.json`, `pr-test-plan.manifest.json`,
  `deterministic-regen-paths.json`). `copy-to-core.sh` MUST consult this manifest instead of growing ad-hoc
  `--exclude` lists.
- **R3** `copy-to-core.sh` MUST be **fail-closed on orphan deletion**: before `rsync --delete` on
  `core/sw-reference/`, compute orphans (present in `core/sw-reference/` but neither in `.sw/` sync output nor
  `coreAuthoredAllowlist`). If orphans exist outside an explicit `deprecatedAllowlist`, exit non-zero with a
  list of paths and remediation (add to allowlist, relocate to `.sw/`, or run with documented `--force` for
  fixtures/CI only).
- **R4** Relocate or register every current core-only sw-reference artifact identified in GAP-032 into either
  `.sw/` (preferred for operator-edited config) or `coreAuthoredAllowlist` (preferred for emitter-generated
  index files). The ad-hoc exclude list in `copy-to-core.sh` is removed once the manifest subsumes it.

### Parity enforcement (GAP-054)

- **R5** `scripts/test/run-core-scripts-parity-fixtures.sh` MUST run in **CI** (`.github/workflows/ci.yml`) as a
  required job step — same class as emitter and dist↔golden parity.
- **R6** `run-core-scripts-parity-fixtures.sh` MUST be registered in `verify.test` (via
  `pr-test-plan.manifest.json` or direct `workflow.config.json` entry) so local `/sw-stabilize` and PR test-plan
  CI enforce the same gate.
- **R7** A single sanctioned entrypoint `scripts/build-chain-sync.sh` (name fixed in tasks) runs, in order:
  `copy-to-core.sh` → `python3 -m sw generate --all` → golden manifest re-snapshot when `dist/` changed. It
  exits non-zero on any step failure. Documented in `.sw/layout.md` and `docs/guides/workflows.md`.
- **R8** A fixture `build-chain-sync-idempotent` proves a second consecutive `build-chain-sync.sh` run produces
  no git diff (idempotent on a clean tree after first sync).

### One-shot resync & operator clarity

- **R9** Implementation MUST include a one-shot commit on the feature branch that runs `build-chain-sync.sh`
  and commits resulting `core/`, `dist/`, and golden manifest changes so latent drift (GAP-054 `host_github.sh`
  class) is cleared on merge.
- **R10** `.sw/layout.md` MUST include a diagram or table clarifying the three trees operators confuse:
  repo `scripts/`+`core/`+`dist/` (build chain) vs `~/.cursor/plugins/local/shipwright/` (plugin install) —
  explicitly stating `copy-to-core` does not read from the install path (GAP-032 E).
- **R11** On ship, GAP-032 and GAP-054 flip to `resolved — PRD 038` via gap-resolve / manual reconcile.

## Technical Requirements

- **R12** `build-chain-sot.json` is validated by a lint script (`scripts/build-chain-sot-lint.sh` or folded
  into an existing manifest linter) — every `coreAuthoredAllowlist` path must exist on disk; no duplicate entries.
- **R13** `copy-to-core.sh` reads `core/sw-reference/build-chain-sot.json` at runtime (fail closed if missing
  after this PRD ships).
- **R14** CI job ordering: core-scripts parity runs **after** checkout and **before** or alongside emitter
  freshness — a PR that updates `scripts/foo.sh` without `core/scripts/foo.sh` MUST fail CI even when
  `dist`↔golden is internally consistent.
- **R15** Optional v1 deliver hook: when a phase task list touches `scripts/**` and the PR test-plan includes
  build-chain fixtures, `check-gate.sh` advisory notice suggests `build-chain-sync.sh` — not a hard block in v1.

## Security & Compliance

- **R16** Build-chain scripts operate on tracked files only; `--force` orphan override is logged and restricted
  to fixture/CI invocations (documented in script `--help`).

## Testing Strategy

- `core-scripts-parity` fixture passes on clean `main` after resync (R5/R6).
- `copy-to-core-orphan-fail-closed` fixture: synthetic orphan under `core/sw-reference/` → non-zero exit (R3).
- `build-chain-sot-lint` fixture: allowlist paths exist (R12).
- `build-chain-sync-idempotent` (R8).
- `ci-yml-includes-core-scripts-parity` fixture: `ci.yml` references the runner (R5).
- `verify-test-registers-core-scripts-parity` fixture (R6).
- No regression: emitter freshness + dist↔golden parity remain green (R14 ordering).

## Rollout Plan

1. **SoT manifest + copy-to-core hardening** — `build-chain-sot.json`, lint, fail-closed orphans, migrate
   excludes to allowlist (R1–R4, R12–R13).
2. **CI + verify.test wiring** — `ci.yml` + manifest registration (R5–R6, R14).
3. **`build-chain-sync.sh` + docs** — unified entrypoint + layout diagram (R7–R8, R10).
4. **One-shot resync commit** — clear GAP-054 latent drift (R9).
5. **Gap close** — GAP-032, GAP-054 (R11).

## Decision Log

- **D1** Successor PRD, not amendments to PRD 004/009/018/021 — all complete; this closes post-ship gaps.
- **D2** Harness SoT stays `scripts/` (not inverted to `core/scripts/`) — runtime already uses repo-root
  paths; CI parity enforces forward sync direction.
- **D3** `coreAuthoredAllowlist` manifest replaces growing `rsync --exclude` lists in `copy-to-core.sh` — scales
  for consumer repos and is lint-validated.
- **D4** Orphan deletion is fail-closed (R3), not silent `--delete` — closes GAP-032 destructive-sync hazard.
- **D5** CI wires existing `run-core-scripts-parity-fixtures.sh` rather than a new diff algorithm — minimal
  change, closes GAP-054 enforcement hole (D5 implements GAP-054 item 2).
- **D6** Golden re-snapshot is part of `build-chain-sync.sh` when `dist/` changes — prevents
  dist↔golden-passing / scripts↔core-failing split.

## Open Questions

- None — GAP-032 investigation options A–E are resolved by R1–R4 and D2–D4. Proceed to implementation.
