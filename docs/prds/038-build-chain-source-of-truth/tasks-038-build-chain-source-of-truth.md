---
date: 2026-06-29
topic: build-chain-source-of-truth
prd: docs/prds/038-build-chain-source-of-truth/038-prd-build-chain-source-of-truth.md
frozen: true
frozen_at: 2026-06-29
---

# Tasks — PRD 038 Build-chain source of truth & parity enforcement

Generated from frozen PRD spec union (R1–R16). Phases follow Rollout Plan.

## Tasks

### 1. SoT manifest + copy-to-core hardening — M

- [ ] 1.1 Add machine-readable SoT manifest
  - **File:** `core/sw-reference/build-chain-sot.json`
  - **Expected:** documents harness/core/dist/golden roles + `coreAuthoredAllowlist` per R1/R2; lint-validated (R12)
  - **R-IDs:** R1, R2, R12
- [ ] 1.2 Harden `copy-to-core.sh` orphan handling
  - **File:** `scripts/copy-to-core.sh`
  - **Expected:** reads `build-chain-sot.json`; fail-closed on orphans outside allowlist/deprecated (R3); replaces ad-hoc `--exclude` list with manifest (R4); `--force` for fixtures only (R16)
  - **R-IDs:** R3, R4, R13, R16
- [ ] 1.3 Relocate or register core-only sw-reference artifacts
  - **File:** `core/sw-reference/build-chain-sot.json`, `.sw/` or allowlist entries
  - **Expected:** every GAP-032 core-only artifact (e.g. `pr-test-plan.manifest.json`, `capability-index.json`) in allowlist or `.sw/` (R4)
  - **R-IDs:** R4
- [ ] 1.4 Add SoT lint + orphan fail-closed fixtures
  - **File:** `scripts/build-chain-sot-lint.py`, `scripts/test/run-build-chain-sot-fixtures.sh`
  - **Expected:** `build-chain-sot-lint` + `copy-to-core-orphan-fail-closed` pass (R12, R3)
  - **R-IDs:** R12

### 2. CI + verify.test wiring — S

- [ ] 2.1 Wire core-scripts parity into CI
  - **File:** `.github/workflows/ci.yml`
  - **Expected:** `bash scripts/test/run-core-scripts-parity-fixtures.sh` required step (R5, R14)
  - **R-IDs:** R5, R14
- [ ] 2.2 Register core-scripts parity in verify.test
  - **File:** `core/sw-reference/pr-test-plan.manifest.json` and/or `.cursor/workflow.config.json`
  - **Expected:** same gate locally and in PR test-plan CI (R6)
  - **R-IDs:** R6
- [ ] 2.3 Add CI/verify registration fixtures
  - **File:** `scripts/test/run-build-chain-sot-fixtures.sh`
  - **Expected:** `ci-yml-includes-core-scripts-parity` + `verify-test-registers-core-scripts-parity` green (R5, R6)
  - **R-IDs:** R5, R6

### 3. Unified sync entrypoint + operator docs — M

- [ ] 3.1 Implement `build-chain-sync.py`
  - **File:** `scripts/build-chain-sync.py`
  - **Expected:** runs `copy-to-core` → `sw generate --all` → golden re-snapshot when dist changes (R7, D6); idempotent fixture (R8)
  - **R-IDs:** R7, R8
- [ ] 3.2 Document build-chain SoT map
  - **File:** `.sw/layout.md`, `docs/guides/workflows.md`
  - **Expected:** SoT table/diagram; repo trees vs plugin install path (R1, R10); `build-chain-sync.py` usage (R7)
  - **R-IDs:** R1, R7, R10
- [ ] 3.3 Propagate scripts to core/dist
  - **File:** `core/scripts/`, `dist/**` via `copy-to-core` + emitter
  - **Expected:** new scripts + manifest land in `core/` and both dist trees
  - **R-IDs:** R13

### 4. One-shot resync + gap close — S

- [ ] 4.1 Run one-shot resync commit (clear GAP-054 latent drift)
  - **File:** `core/`, `dist/`, `scripts/test/fixtures/parity/cursor-golden.manifest`
  - **Expected:** `host_github.sh` and any other `scripts/`↔`core/scripts/` drift resolved in one commit (R9)
  - **R-IDs:** R9
- [ ] 4.2 Close GAP-032 and GAP-054
  - **File:** `docs/prds/GAP-BACKLOG.md`
  - **Expected:** both rows `resolved — PRD 038` after merge (R11)
  - **R-IDs:** R11
- [ ] 4.3 Optional deliver advisory hook
  - **File:** `scripts/check-gate.py` or deliver docs (advisory only)
  - **Expected:** when `scripts/**` touched, notice suggests `build-chain-sync.py` — no hard block (R15)
  - **R-IDs:** R15

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 2, 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1, 3.2 | `build-chain-sot-lint`; layout SoT section |
| R2 | 1.1 | allowlist encodes core-authored paths |
| R3 | 1.2, 1.4 | `copy-to-core-orphan-fail-closed` |
| R4 | 1.3, 1.2 | manifest replaces ad-hoc excludes |
| R5 | 2.1, 2.3 | `ci-yml-includes-core-scripts-parity` |
| R6 | 2.2, 2.3 | `verify-test-registers-core-scripts-parity` |
| R7 | 3.1, 3.2 | `build-chain-sync.py` runs full chain |
| R8 | 3.1 | `build-chain-sync-idempotent` |
| R9 | 4.1 | resync clears `host_github.sh` drift |
| R10 | 3.2 | layout plugin-install vs repo trees |
| R11 | 4.2 | GAP-032/054 resolved |
| R12 | 1.1, 1.4 | `build-chain-sot-lint` |
| R13 | 1.2, 3.3 | copy-to-core reads manifest |
| R14 | 2.1 | CI ordering catches scripts-only PR |
| R15 | 4.3 | advisory notice only |
| R16 | 1.2 | `--force` restricted/documented |
| D1 | 1.1 | successor PRD not amendment |
| D2 | 1.2, 2.1 | scripts/ forward SoT |
| D3 | 1.1, 1.2 | manifest replaces excludes |
| D4 | 1.2 | fail-closed orphans |
| D5 | 2.1 | existing parity fixture in CI |
| D6 | 3.1, 4.1 | golden in sync script |

## Relevant Files

- `core/sw-reference/build-chain-sot.json` — SoT manifest + allowlist
- `scripts/copy-to-core.sh` — orphan fail-closed sync
- `scripts/build-chain-sync.py` — unified entrypoint
- `scripts/test/run-core-scripts-parity-fixtures.sh` — existing parity gate
- `.github/workflows/ci.yml` — CI wiring
- `.sw/layout.md` — operator SoT map

## Notes

- Phase 2 and 3 both depend on Phase 1 but can run in parallel after manifest lands.
- One-shot resync (4.1) should be the final commit before gap close to avoid CI red on intermediate states.
