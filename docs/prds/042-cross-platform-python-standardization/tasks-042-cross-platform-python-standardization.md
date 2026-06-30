---
prd: docs/prds/042-cross-platform-python-standardization/042-prd-cross-platform-python-standardization.md
date: 2026-06-30
topic: cross-platform-python-standardization
frozen: true
frozen_at: 2026-06-30
visibility: public
---
# Tasks — PRD 042 Cross-platform Python standardization

Single-pass task list from the frozen PRD (R1–R45). Phases are bounded, independently-mergeable,
domain-sized units (D12); exact file inventories within each unit are confirmed against the audit ledger
(R23) at execution time. Every phase applies per-phase reference-closure (R41), build-chain reproduction
for touched surfaces (R29), dist-no-shell for ported surfaces (R37), and expands the Windows smoke job
(R45). Migration is strict hard-cut with no shims (D8/D14).

## Tasks

### 1. Foundation — runtime library, interpreter probe, hook launcher, ledger, guards (L)

Establishes the Python runtime substrate every later phase depends on, and moves the build/install chain
off `rsync` early so subsequent ports build cleanly.

- [x] 1.1 Shared runtime package skeleton + docstring/CLI convention (R18)
  - **File:** `scripts/_sw/__init__.py`, `scripts/_sw/cli.py`
  - **Expected:** `argparse` scaffold with `--help`, module + per-command docstrings; importable without `pip`
  - **R-IDs:** R18
- [ ] 1.2 Structured logging helper — stderr only, `SW_LOG_LEVEL`, run-log append, redaction-aware (R13, R14)
  - **File:** `scripts/_sw/logging_setup.py`
  - **Expected:** logs to stderr (stdout stays pure JSON); `SW_LOG_LEVEL` default `WARNING`; run-log append never emits tokens/secrets/raw bodies
  - **R-IDs:** R13, R14
- [ ] 1.3 `poll_until` event-wait primitive (R15, R16, R17)
  - **File:** `scripts/_sw/poll.py`, `scripts/_sw/waitmap.json`
  - **Expected:** interval/backoff/full-jitter/hard-timeout reading `checks.watch.*` / `deliver.watchdog.*`; committed external-wait call-site map; `notify_on_output` cadence reads same config
  - **R-IDs:** R15, R16, R17
- [ ] 1.4 `jsonio` deterministic emitter + normalization rules (R38)
  - **File:** `scripts/_sw/jsonio.py`
  - **Expected:** `sort_keys`, fixed separators, float/path-separator normalization, stable enumeration order; documented rules
  - **R-IDs:** R38
- [ ] 1.5 Cross-platform `proc` helper (no shell) (R30 support)
  - **File:** `scripts/_sw/proc.py`
  - **Expected:** subprocess wrappers that never invoke a shell and never target bash/sh
  - **R-IDs:** R30
- [ ] 1.6 Fail-closed interpreter probe + entrypoint resolver (R2)
  - **File:** `scripts/_sw/interpreter.py`, `scripts/_sw/run.py`
  - **Expected:** selects CPython ≥ 3.9 (`python`/`python3`/`py -3`), rejects Python 2 and MS Store stub, clear remediation on failure
  - **R-IDs:** R2
- [ ] 1.7 Cross-platform git-hook launcher + Windows hook fixture (R40, R3 prerequisite)
  - **File:** `scripts/_sw/hook_launcher.py`, `hooks/launcher.cmd`, `scripts/test/windows-hook-invocation.test`
  - **Expected:** Python-shebang hook + Windows `.cmd`/`py -3` shim; fixture proves planted violation blocked fail-closed under git's native Windows hook runner
  - **R-IDs:** R40
- [ ] 1.8 Python mirror-copy library replacing `rsync` (R6)
  - **File:** `scripts/_sw/mirror.py`
  - **Expected:** `rsync -a --delete` semantics (recursive copy, orphan prune, exclusion globs, symlinks)
  - **R-IDs:** R6
- [ ] 1.9 Port `install`/`copy-to-core` to Python (no rsync/bash) + hook install via launcher (R5)
  - **File:** `scripts/install.py`, `scripts/copy-to-core.py` (remove `install.sh`, `copy-to-core.sh`)
  - **Expected:** Windows install with only Python+git; `--force`/exclusion/dev-orphan-check preserved; installs hooks via R40
  - **R-IDs:** R5
- [ ] 1.10 Stdlib-only parsing; remove non-stdlib imports + import guard (R11, R12)
  - **File:** `scripts/capability_index.py`, `scripts/_sw/depmanifest.json`, `scripts/dep-import-guard.py`
  - **Expected:** no non-stdlib import remains; manifest empty by default; guard fails closed on undeclared/non-vendored import
  - **R-IDs:** R11, R12
- [ ] 1.11 Per-script audit ledger + reconcile fixture (R23)
  - **File:** `core/sw-reference/script-port-ledger.json`, `scripts/test/script-ledger-reconcile.test`
  - **Expected:** every `.sh` listed with disposition (port/consolidate/delete); fixture asserts remaining `.sh` count monotonically decreases; no undisposed file
  - **R-IDs:** R23
- [ ] 1.12 Enforcement guard (warn mode) + reference-closure scaffold (R30 warn, R41 scaffold)
  - **File:** `scripts/zero-shell-guard.py`, `scripts/test/reference-closure.test`
  - **Expected:** enumerates enforced trees, warns on `.sh`/`.bash`/`.ps1` and on `subprocess`/`os.system` shell-out to plugin scripts; reads ledger
  - **R-IDs:** R30, R41
- [ ] 1.13 Minimal Windows smoke CI job (R45)
  - **File:** `.github/workflows/windows-smoke.yml`
  - **Expected:** Python+git only; runs interpreter probe, one ported hook, one JSON gate
  - **R-IDs:** R45

### 2. Host layer & `gh`/`curl` elimination (L)

- [x] 2.1 Host HTTP transport on `urllib` with TLS + SSRF hardening (R8, R44)
  - **File:** `scripts/_sw/host_transport.py`
  - **Expected:** `ssl.create_default_context()`, token via header (never argv/logs), HTTPS-only, same-host redirect constraint, loopback/link-local/metadata rejection unless allowlisted; rate-limit retry on `poll_until`
  - **R-IDs:** R8, R44
- [ ] 2.2 Port host adapters + dispatcher to Python (R25)
  - **File:** `scripts/_sw/host/github.py`, `gitlab.py`, `bitbucket.py`, `local.py`, `scripts/host.py` (remove `host_*.sh`, `host.sh`)
  - **Expected:** PRD 026 verb set, capability flags, per-host rate-limit mapping, local `none` adapter + local-evidence gate preserved
  - **R-IDs:** R25
- [ ] 2.3 Unify `pr-list` onto full `pr-view` shape (R19)
  - **File:** `scripts/_sw/host/_shape.py`, `scripts/test/pr-list-view-parity.test`
  - **Expected:** `pr-list` emits `mergeable`/`isDraft`/`mergeStateStatus`/merge fields; fixture asserts list↔view field parity
  - **R-IDs:** R19
- [ ] 2.4 Remove residual direct `gh` usages (R9)
  - **File:** `scripts/docs_pr.py`, `scripts/docs-merge.py`, `scripts/host_lib.py`, `core/providers/review/coderabbit.*`
  - **Expected:** PR ops + branch-protection probe + CodeRabbit `gh api` route through host verbs/transport; zero `gh` invocations
  - **R-IDs:** R9
- [ ] 2.5 Scrub `gh`/`curl`/`jq`/`rsync`/`bash scripts/` from agent prose + config (R10, R43)
  - **File:** `core/commands/**`, `core/skills/**`, `core/rules/**`, `core/providers/**`, `docs/guides/workflows.md`, `docs/guides/commands.md`, `documentation/**`, config samples; `scripts/test/prose-config-closure.test`
  - **Expected:** fixture asserts zero banned-tool literals across all named trees
  - **R-IDs:** R10, R43

### 3. Gate & dispatcher core (L)

- [x] 3.1 Port `check-gate` and `wave.sh` + `wave_*` dispatch surface to Python (R24 subset)
  - **File:** `scripts/check-gate.py`, `scripts/wave.py` (+ wave_* modules) (remove ported `.sh`)
  - **Expected:** stdout JSON contract, exit codes, fail-closed semantics preserved
  - **R-IDs:** R24
- [ ] 3.2 Eliminate `jq` on gate/dispatcher surfaces via `json` (R7 incremental)
  - **File:** ported gate/dispatcher modules, `scripts/test/json-contract-gate.test`
  - **Expected:** no `jq`; semantic parity (+ byte parity where goldens exist)
  - **R-IDs:** R7
- [ ] 3.3 Resolve twin INDEX reconciler code paths into one Python surface (R22)
  - **File:** `scripts/reconcile.py` (consolidates `reconcile-status.sh` + `planning-graph reconcile` code paths), `scripts/test/single-reconciler.test`
  - **Expected:** shared helpers, deduplicated logic; INDEX schemas/regions/lifecycle unchanged; fixture covers both INDEX behaviors
  - **R-IDs:** R22
- [ ] 3.4 JSON contract fixtures for ported verbs/gates (TR4 support)
  - **File:** `scripts/test/json-contract-*.test`
  - **Expected:** per-verb/gate semantic-parity diff; byte parity where goldens exist
  - **R-IDs:** R7

### 4. Hooks, security filters, providers (L)

- [x] 4.1 Port git hooks onto the R40 launcher (R3)
  - **File:** `hooks/pre-commit.py`, `hooks/pre-push.py`, `hooks/commit-msg.py` + helpers (remove `.sh` hooks)
  - **Expected:** execute on Windows under git hook runner without bash; all fail-closed guards preserved
  - **R-IDs:** R3
- [ ] 4.2 Port security filters with behavioral parity (R36)
  - **File:** `scripts/secret-scan.py`, `scripts/memory-redact.py`, `scripts/redaction-guard.py`, `scripts/test/secret-scan-behavioral.test`
  - **Expected:** planted secret blocks pre-push; allowlist exit-2; git-push chain blocks on scanner failure; redaction-guard strips same fields
  - **R-IDs:** R36
- [ ] 4.3 Port `core/providers/` review+verify adapters to Python (R26)
  - **File:** `core/providers/review/*.py`, `core/providers/verify/*.py` (remove `.sh`)
  - **Expected:** capability-frontmatter provider-selection contract preserved
  - **R-IDs:** R26
- [ ] 4.4 No-shell `dist/`/`core/scripts/` for hook + Cursor/Claude adapter surfaces (R4)
  - **File:** `dist/cursor/**`, `dist/claude-code/**`, emitter wiring
  - **Expected:** adapters/emitters functional cross-platform; `dist/cursor/`+`dist/claude-code/` contain no `.sh`
  - **R-IDs:** R4

### 5. Remaining production port + consolidations (L)

- [x] 5.1 Port remaining production `scripts/*.sh` to Python (R24 remainder)
  - **File:** remaining `scripts/*.py` (worktree, reconcile-status, etc.; remove `.sh`)
  - **Expected:** stdout JSON, exit codes, fail-closed semantics preserved per ledger
  - **R-IDs:** R24
- [ ] 5.2 Complete `jq` elimination across all surfaces (R7 complete)
  - **File:** remaining ported modules, `scripts/test/no-jq-guard.test`
  - **Expected:** zero `jq` invocations workflow-wide
  - **R-IDs:** R7
- [ ] 5.3 Retire legacy non-idempotent `append-log` (R20)
  - **File:** `scripts/_sw/completion_log.py`, `scripts/wave_compound.py`, `scripts/test/completion-log-idempotent.test`
  - **Expected:** single idempotent COMPLETION-LOG writer; fixture asserts no duplicate rows on resume
  - **R-IDs:** R20
- [ ] 5.4 Collapse `.sh`/`.py` sibling pairs (R21)
  - **File:** ~22 sibling pairs → single Python module each; update all callers; `scripts/test/pair-collapse.test`
  - **Expected:** one module per pair; callers resolve to the Python module
  - **R-IDs:** R21

### 6. Test harness, build chain, docs, migration, enforcement flip (XL)

- [x] 6.1 Port `scripts/test/` shell harnesses to a Python runner (R27)
  - **File:** `scripts/test/_runner.py`, ported `*.test` (137 files)
  - **Expected:** coverage preserved; PR test-plan manifest registration; `verify.test` integration
  - **R-IDs:** R27
- [ ] 6.2 Update build-chain SoT + layout + emitter + golden parity (R28, R29, R32, R37, R38, TR8)
  - **File:** `build-chain-sot.json`, `.sw/layout.md`, `sw/` emitter, golden parity manifest
  - **Expected:** per-phase reference updates closed; build chain reproduces; emitter produces no-shell `dist/`; goldens regenerated; deterministic output
  - **R-IDs:** R28, R29, R32, R37, R38
- [ ] 6.3 Correct user docs prerequisites + currency fixture (R33, R35)
  - **File:** `README.md`, `docs/guides/**`, `CONTRIBUTING*`, `documentation/**`, `scripts/test/docs-currency.test`
  - **Expected:** Python (≥3.9)+git only; `rsync`/`gh`/`jq`/`curl` removed; fixture asserts no doc re-lists a removed dependency
  - **R-IDs:** R33, R35
- [ ] 6.4 Migration: doctor stale-layout detection + in-flight upgrade gate (R34, R42)
  - **File:** `scripts/doctor.py`, `scripts/upgrade-gate.py`, `scripts/test/migration-gate.test`
  - **Expected:** doctor detects leftover `.sh` hooks/entrypoints + prints remediation; warns on missing/old Python; upgrade refuses while `/sw-deliver` state non-terminal; no shim
  - **R-IDs:** R34, R42
- [ ] 6.5 Python-first rule + contributor policy (R31)
  - **File:** `rules/sw-python-first.mdc`, `CONTRIBUTING*`
  - **Expected:** new logic Python-only; shell-file/shell-out fails gate; vendoring requires manifest
  - **R-IDs:** R31
- [ ] 6.6 Flip enforcement to hard-fail zero-shell + reference-closure (R30, R41)
  - **File:** `scripts/zero-shell-guard.py`, `core/sw-reference/pr-test-plan.manifest.json`
  - **Expected:** guard hard-fails on any `.sh`/`.bash`/`.ps1` or shell-out; runs in CI; registered in `verify.test`
  - **R-IDs:** R30, R41
- [ ] 6.7 Full Windows CI slice proving R1 (R1, R39, R45)
  - **File:** `.github/workflows/windows-smoke.yml`, `.github/workflows/*`
  - **Expected:** Windows job runs interpreter+hook+gate+host-verb(mocked REST)+poll end-to-end; POSIX job preserved; workflow runs via Python entrypoints
  - **R-IDs:** R1, R39, R45

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 1, 2 |
| 5 | 1, 3 |
| 6 | 1, 2, 3, 4, 5 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 6.7 | windows-smoke.yml end-to-end no-bash slice |
| R2 | 1.6 | interpreter-probe.test (reject py2/Store stub, accept py -3) |
| R3 | 4.1 | git-hooks-crossplatform.test fail-closed guards |
| R4 | 4.4 | dist-no-shell.test (cursor/claude-code trees) |
| R5 | 1.9 | install-windows.test (no rsync/bash, hooks installed) |
| R6 | 1.8 | mirror-copy.test (rsync -a --delete parity) |
| R7 | 3.2 | json-contract-gate.test + no-jq-guard.test |
| R8 | 2.1 | host-transport.test (urllib, TLS, token-header) |
| R9 | 2.4 | no-gh-guard.test (docs_pr/docs-merge/host_lib/coderabbit) |
| R10 | 2.5 | prose-config-closure.test |
| R11 | 1.10 | no-nonstdlib-import.test |
| R12 | 1.10 | dep-import-guard.test (undeclared import fails closed) |
| R13 | 1.2 | logging-stderr.test (stdout pure JSON) |
| R14 | 1.2 | runlog-redaction.test |
| R15 | 1.3 | poll-until.test (interval/backoff/jitter/timeout) |
| R16 | 1.3 | external-wait-callsite-map.test (no fixed sleep on map) |
| R17 | 1.3 | notify-on-output-config.test (shared timing source) |
| R18 | 1.1 | cli-docstring-help.test |
| R19 | 2.3 | pr-list-view-parity.test |
| R20 | 5.3 | completion-log-idempotent.test |
| R21 | 5.4 | pair-collapse.test |
| R22 | 3.3 | single-reconciler.test (both INDEX behaviors) |
| R23 | 1.11 | script-ledger-reconcile.test |
| R24 | 3.1 | gate-dispatcher-contract.test + ledger disposition |
| R25 | 2.2 | host-adapter-parity.test (mocked REST, verb set) |
| R26 | 4.3 | provider-selection.test |
| R27 | 6.1 | python-test-runner.test (coverage + manifest registration) |
| R28 | 6.2 | reference-update-per-phase.test |
| R29 | 6.2 | build-chain-reproduce.test (emitter freshness + golden parity) |
| R30 | 6.6 | zero-shell-guard.test (hard-fail) |
| R31 | 6.5 | python-first-policy.test |
| R32 | 6.2 | build-chain-sot-layout.test |
| R33 | 6.3 | docs-prerequisites.test (Python+git only) |
| R34 | 6.4 | doctor-stale-layout.test |
| R35 | 6.3 | docs-currency.test (no re-listed removed dep) |
| R36 | 4.2 | secret-scan-behavioral.test (planted secret, exit-2, push chain) |
| R37 | 6.2 | emitter-no-shell-dist.test |
| R38 | 1.4 | json-determinism.test (normalization rules) |
| R39 | 6.7 | ci-python-entrypoints.test (POSIX preserved) |
| R40 | 1.7 | windows-hook-invocation.test |
| R41 | 1.12 | reference-closure.test (no stale bash ref / shell-out) |
| R42 | 6.4 | migration-gate.test (in-flight deliver refuses upgrade) |
| R43 | 2.5 | prose-config-closure.test (commands/skills/rules/providers/docs/config) |
| R44 | 2.1 | ssrf-redirect-hardening.test |
| R45 | 1.13 | windows-smoke-incremental.test |

## Relevant Files

- `scripts/_sw/` — shared runtime library (logging, poll, jsonio, cli, proc, interpreter, host transport).
- `core/sw-reference/script-port-ledger.json` — per-script disposition ledger (R23).
- `scripts/zero-shell-guard.py` — enforcement + reference-closure guard (R30/R41).
- `.github/workflows/windows-smoke.yml` — incremental Windows proof of R1 (R45).
- `build-chain-sot.json`, `sw/` emitter, golden parity manifest — build-chain coherence (TR8).

## Notes

- Within-phase file inventories are reconciled against the R23 ledger at execution; counts in the PRD are
  indicative. Each phase is independently mergeable behind passing fixtures (D12).
- Hard-cut, no shims (D8/D14): every port updates all references in the same change; migration relies on
  the doctor + upgrade gate (6.4), not compatibility shims.
