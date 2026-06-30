---
brainstorm: docs/brainstorms/2026-06-30-cross-platform-python-standardization-requirements.md
date: 2026-06-30
topic: cross-platform-python-standardization
frozen: true
frozen_at: 2026-06-30
visibility: public
---
# PRD 042 — Cross-platform Python standardization

## Overview

Shipwright's runtime under `scripts/` is ~111 production `bash` scripts plus 137 `bash` test harnesses
(~248 `.sh` total) orchestrating ~95 Python modules; that surface is mirrored into `core/scripts/` and
re-emitted under `dist/`, for ~603 `.sh` repo-wide. The command/skill layer invokes work through
`bash scripts/*.sh`, the git hooks are bash, and code shells out to `rsync`, `jq`, `curl`, and residual
`gh` CLI calls. This couples the plugin to a POSIX/bash environment and external tools absent by default
on Windows — even though **`python3` is already a hard (but undocumented) runtime dependency** (most
shell scripts call it; `wave.sh` alone fronts 20+ Python modules).

This PRD makes the plugin run natively on Windows (PowerShell/cmd) with **only Python (≥ 3.9) and git**
required, by porting the entire shell surface to a stdlib-first Python runtime, eliminating
`rsync`/`jq`/`curl`/`gh`, consolidating the duplicated and legacy logic the audit surfaced
(`pr-list`↔`pr-view` field drift, legacy `append-log`, twin INDEX reconcilers, ~22 half-migrated
`.sh`/`.py` pairs), standardizing logging and a condition-based event-wait primitive, and
hard-enforcing "Python-first, zero shell scripts" going forward.

It is delivered as one phased epic; phases are sliced into **bounded, independently-mergeable,
domain-sized units** (foundation → host/transport → gate & dispatchers → hooks/security/providers →
remaining production + consolidations → test harness + docs + enforcement flip), with consolidations
executed inside the relevant domain port rather than as a separate phase (D9/D12). Exact unit
boundaries are finalized in `/sw-tasks`. It extends **PRD 018 (generic-repo-portability)** and **PRD 026
(git-host portability)** — completing PRD 026's unfinished `gh` elimination (R4/R17 leaked back in
Phase-5 additions) rather than redoing the host abstraction. It is derived from the frozen-intent
brainstorm (`docs/brainstorms/2026-06-30-cross-platform-python-standardization-requirements.md`,
R1–R35); R36–R45 are added during PRD review.

## Goals

- Make the plugin install and run natively on Windows (PowerShell/cmd) with only Python and git, no
  `pip install` step, and no `bash`/`rsync`/`jq`/`curl`/`gh`.
- Convert the entire shell surface (production scripts, dispatchers, host/provider adapters, git
  hooks, and test harnesses) to a stdlib-first Python runtime that preserves the JSON-on-stdout
  contract, exit codes, and fail-closed guardrail behavior.
- Finish eliminating the `gh` CLI (transport and agent prose) left incomplete after PRD 026.
- Standardize one logging convention and one condition-based event-wait primitive, removing fixed
  `sleep` timers on external-wait paths and the dead `checks.watch.*` config gap.
- Consolidate duplicated and legacy logic under regression fixtures.
- Correct the dependency documentation and mechanically enforce "Python-first, zero shell" going
  forward.

## Non-Goals

- Changing workflow behavior, gate semantics, the human merge gate, or any guardrail intent. This is
  a portability/standardization refactor; consolidations normalize output but preserve intent under
  fixtures.
- Re-architecting the host-provider abstraction, the deliver conductor, the planning-unit model, or
  the capability manifest beyond what porting and the named consolidations require.
- **Unifying the planning-INDEX schema or lifecycle.** R22 resolves the *reconciler code paths* and
  shared helpers into one Python surface; it does not merge the legacy PRD-INDEX and planning-INDEX
  data models, regions, or ownership contracts (PRD 032/035 boundaries stand).
- **Re-opening gap-unit / planning-graph semantics.** The gap-capture and planning-graph contracts
  (`planning_gap_capture.py`, `planning-graph.sh reconcile`, PRD 033/035) are ported as-is; their
  schemas, edges, and autonomy postures are out of scope.
- Multi-host abstraction of the CodeRabbit review provider's *semantics* (PRD 026 non-goal); R9 only
  removes its `gh` transport, not its GitHub coupling.
- Adding new host providers, CI integrations, or memory/review providers.
- Replacing release-please semantic-version automation.
- Supporting Python versions below 3.9.
- True event-driven waiting (filesystem watch / webhooks) beyond condition-based polling.
- Long-lived `.sh` compatibility shims or an auto-generated back-compat dispatch layer — explicitly
  rejected (D8 strict hard-cut; migration handled by R34/R42 upgrade gate, not shims).

## Requirements

R1–R35 carry forward from the brainstorm with stable R-IDs. R36–R45 are added during PRD review.

### Portability foundation and entrypoint model

- **R1** The plugin runs end-to-end on Windows in a native shell (PowerShell or cmd) with only
  Python (≥ 3.9) and git installed — no `bash`, `rsync`, `jq`, `curl`, or `gh` required, and no
  `pip install` step.
- **R2** Every command and skill that today invokes `bash scripts/*.sh` is rewritten to invoke the
  corresponding Python entrypoint via a single portable convention that resolves the interpreter
  cross-platform via a **fail-closed interpreter probe**: it selects a CPython ≥ 3.9 (accepting
  `python`, `python3`, or the Windows `py -3` launcher), rejects Python 2 and the non-functional
  Microsoft Store `python` stub, and exits with a clear remediation message when no conforming
  interpreter is found.
- **R3** Git hooks (`pre-commit`, `pre-push`, `commit-msg`, and their helpers) are Python entrypoints
  that execute on Windows under git's hook runner without a user-installed bash, preserving their
  current fail-closed behavior (frozen-file guard, secret-scan, commit-message guard, index-region
  guard, planning-privacy guard, completed-unit guard).
- **R4** Cursor and Claude-Code hook adapters and emitters remain functional cross-platform, and the
  `dist/cursor/` and `dist/claude-code/` trees contain no `.sh` files after the phase that ports them.
- **R5** Installation works on Windows without `rsync` or bash: `install.sh` and `copy-to-core.sh` are
  replaced by Python that performs the mirror copy (`shutil.copytree(dirs_exist_ok=True)`) plus
  orphan pruning equivalent to `rsync -a --delete`, preserving the existing `--force` / exclusion
  behavior, and installs the git hooks via R40's launcher.
- **R40** A committed **cross-platform git-hook launcher** is the canonical hook-installation
  mechanism: a Python-shebang hook entry plus a Windows-executable shim (e.g. a `.cmd`/`py -3`
  wrapper resolved through R2) so git's bundled hook runner executes each hook on POSIX and native
  Windows without a user-installed bash. The launcher is specified and proven by a **Windows
  hook-invocation fixture in the foundation phase**, and all later hook ports gate on it. The ported
  `pre-push` secret-scan invocation is fail-closed: a missing, unreadable, or erroring scanner exits
  non-zero (never silently passes).

### Dependency elimination

- **R6** No workflow code path invokes `rsync`; all tree-copy/sync operations use Python stdlib
  (`shutil` / `pathlib`).
- **R7** No workflow code path invokes `jq`; all JSON parsing/emitting uses the Python `json` module.
  JSON emitted on stdout preserves **semantic parity** (same keys, values, and types) with today's
  output for every consumer, under defined normalization rules (R38). Byte-for-byte parity is required
  only where a recorded golden exists; a one-time golden re-snapshot is permitted when normalization
  changes formatting, accompanied by a recorded breaking-change note.
- **R8** No workflow code path invokes `curl`; all host HTTP/REST/GraphQL transport uses
  `urllib.request` (or the vendored escape-hatch client per R12), preserving the PRD 026 token-header
  handling (token never passed as a process argument, never logged) and the rate-limit retry/backoff
  contract (PRD 026 R35–R42).
- **R9** No workflow code path invokes the `gh` CLI. The residual direct `gh` usages are removed:
  `scripts/docs_pr.sh` and `scripts/docs-merge.sh` route PR operations through the host-adapter verb
  set; the `host_lib.py` branch-protection probe uses REST via the host transport; and the CodeRabbit
  adapter's `gh api` calls are replaced with host-verb / transport access. This completes **PRD 026
  R4/R17**.
- **R10** Agent-facing prose and config that still reference a banned tool are scrubbed, completing
  **PRD 026 R17** — zero literal `gh`/`curl`/`jq`/`rsync`/`bash scripts/` invocations across
  `core/commands/`, `core/skills/`, `core/rules/`, `core/providers/`, `docs/guides/` (`workflows.md`,
  `commands.md`), the `documentation/` mirror, and config samples
  (`workflow.config.example.json`, `deterministic-regen-paths.json`, `models-tiering.md`,
  `pull_request_template.md`). A prose/config fixture (R43) asserts closure across all named trees.
- **R11** `scripts/capability_index.py` (the lone historical `PyYAML` site, already on the stdlib
  `yaml_structured` helper) and every other module use only stdlib parsing; no module imports a
  non-stdlib package unless vendored per R12, enforced by an import-guard with coverage across the
  enforced trees.
- **R12** Any third-party Python dependency is permitted only if it is pure-Python, vendored into the
  repository (importable without `pip install`), and declared with a justification in a dependency
  manifest; a gate fails when an undeclared or non-vendored third-party import is introduced.

### Standardized cross-cutting infrastructure

- **R13** A shared stdlib logging helper emits to stderr only, never stdout; log level is controlled
  by `SW_LOG_LEVEL` (default `WARNING`); and no script writes log output to stdout, so the
  JSON-on-stdout consumer contract is preserved.
- **R14** Workflow-significant events are appended in a structured form to the existing run log
  (`.cursor/sw-*-runs/run.log`); logging never emits tokens, secrets, or raw untrusted response
  bodies (reuses the existing redaction chokepoint).
- **R15** A single `poll_until` helper implements all bounded in-process waits with configurable
  interval, exponential backoff, full jitter, and a hard timeout, reading bounds from the existing
  `checks.watch.*` and `deliver.watchdog.*` config. The fixed-`sleep` ban is scoped to
  **external-wait / event-poll paths** (enumerated in a call-site map per R16); incidental
  non-waiting sleeps outside that map are out of scope.
- **R16** All current external-wait use cases route through the standardized mechanism, enumerated in
  a committed call-site map: CI checks settling, phase `status.json` appearance, lock acquisition, PR
  mergeable state, parallel-wave batch completion, and host-API rate-limit waiting
  (`host_ratelimit.py` is refactored onto the shared helper). The map is the authoritative scope for
  the R15 sleep ban.
- **R17** Agent-level self-wake (`notify_on_output` sentinels) is retained only for long external CI
  waits where the agent must yield its turn, and its poll cadence/ceiling read the same
  `checks.watch.*` config as the in-process helper (single source of timing truth).
- **R18** Every ported Python module and its CLI entrypoints carry detailed docstrings (module-level
  purpose plus per-public-function/CLI-command documentation) and expose `--help` via a standardized
  `argparse`-based CLI convention.

### Consolidation and legacy cleanup

- **R19** `pr-list` is unified onto the full `pr-view` field shape across all host adapters (including
  `mergeable`, `isDraft`, `mergeStateStatus`, and merge fields), and all `pr-list` consumers receive
  the complete shape; a fixture asserts field parity between list and view.
- **R20** The legacy non-idempotent `append-log` path is retired; a single idempotent COMPLETION-LOG
  writer is used everywhere (including `wave_compound.py`), and a fixture asserts no duplicate rows on
  resume.
- **R21** The duplicate `.sh`/`.py` sibling pairs identified in the audit (~22 direct pairs plus
  related wrappers) collapse to one Python module each, with the shell wrapper removed and all callers
  updated.
- **R22** The two INDEX reconciliation **code paths** (`reconcile-status.py` legacy PRD INDEX vs
  `planning-graph reconcile` planning INDEX) are ported and resolved into one coherent Python
  reconciler surface with shared helpers and overlapping logic deduplicated, behavior covered by
  fixtures. This does **not** merge the two INDEX schemas, regions, or lifecycle contracts (see
  Non-Goals).
- **R23** An audit enumerates every `.sh` file across `scripts/`, `scripts/test/`, `core/scripts/`,
  `core/hooks/`, `core/providers/`, and `dist/`, classifies each (port / consolidate / delete as
  superseded), and records the disposition so no script is silently dropped or duplicated.

### Full shell → Python port

- **R24** All production `scripts/*.sh` (thin wrappers, heredoc-Python gates, dispatchers such as
  `wave.sh` / `host.sh` / `planning-graph.sh`, and substantive logic such as `check-gate.py` /
  `reconcile-status.py` / `worktree.py`) are ported to Python, preserving each script's stdout JSON
  contract, exit codes, and fail-closed semantics.
- **R25** The host provider adapters (`host_github.sh`, `host_gitlab.sh`, `host_bitbucket.sh`,
  `host_local.sh`, `host_transport.sh`, and the `host.sh` dispatcher) are ported to Python over
  stdlib transport, preserving the PRD 026 verb set, capability flags, per-host rate-limit signal
  mapping, and trust-boundary handling.
- **R26** The provider adapters under `core/providers/` (review and verify `.sh` adapters) are ported
  to Python while preserving the capability-frontmatter provider-selection contract.
- **R27** The `scripts/test/` shell fixture harnesses (137 files) are ported to a Python test runner
  that preserves coverage, the PR test-plan manifest registration, and `verify.test` integration.
- **R28** Each ported script updates all references in the same change — command/skill prose,
  `copy-to-core` / build-chain map (`build-chain-sot.json`), `dist/` emitter output, golden parity
  manifest, and any git-hook wiring — with no `.sh` shim left behind (hard-cut). Applied **per phase**
  for the scripts that phase touches.
- **R29** After each phase, the build chain (`copy-to-core` → `python3 -m sw generate --all` → golden
  re-snapshot) reproduces cleanly for the surfaces that phase touched and the emitter freshness /
  golden parity fixtures pass.
- **R41** A **per-phase reference-closure merge gate** fixture fails closed when, for any tree the
  phase has ported, (a) a stale `bash scripts/<ported>.sh` reference remains anywhere in the enforced
  trees, or (b) any module shells out to bash/sh/cmd targeting a plugin script via `subprocess`,
  `os.system`, or `os.popen`. The gate reads the audit ledger (TR12) to know which targets are
  closed.

### Enforcement and going-forward policy

- **R30** A guard script and a `verify.test` fixture fail closed when any shell-script file
  (`.sh`, `.bash`, `.ps1`) exists in the enforced plugin trees once the port completes (zero-shell end
  state, no allowlist), and the guard runs in CI.
- **R31** A Python-first rule (`rules/sw-python-first.mdc`) and updated contributor documentation
  state the policy: new workflow logic is authored in Python; introducing a shell-script file fails
  the gate; shelling out to bash/sh in enforced trees fails the gate (R41); third-party deps require
  vendoring + manifest declaration (R12).
- **R32** The build-chain source-of-truth (`build-chain-sot.json`) and `.sw/layout.md` are updated to
  describe the Python entrypoint model, so the documented build chain matches the implemented one.

### Documentation and migration

- **R33** User-facing documentation (`README.md` install/prerequisites, `docs/guides/` getting-started
  + configuration, CONTRIBUTING, and the `documentation/` mirror) is corrected to list Python (≥ 3.9)
  and git as the only runtime prerequisites and to remove `rsync`/`gh`/`jq`/`curl` from prerequisites;
  the README "Python is only for developing Shipwright" statement is fixed.
- **R34** Migration is explicit (no shims, D8): after upgrading, an existing installation is restored
  to a working state by a **one-shot reinstall** (the Python `install`/`copy-to-core` of R5, which
  reinstalls hooks via R40). The doctor/health check **detects a stale pre-port layout** (leftover
  `.sh` hooks/entrypoints or missing Python hooks) and prints precise remediation; it also warns when
  Python is missing or below the 3.9 floor.
- **R42** Upgrades are gated against in-flight work: when a `/sw-deliver` run's durable state is
  non-terminal, the upgrade/doctor path refuses to proceed and instructs the operator to finish or
  abort the in-flight run before completing the migration. No long-lived compatibility shim is
  introduced (D8 preserved); the accepted trade-off is a brief, operator-acknowledged migration window
  rather than a back-compat layer.
- **R35** A documentation-currency fixture asserts that once a phase removes a dependency
  (`rsync`/`gh`/`jq`/`curl`), no user-facing doc continues to list it as a prerequisite.

### Review-driven additions (R36–R39, R43–R45)

- **R36** The security-critical filters — `secret-scan` (pre-push), `memory-redact`, the redaction
  chokepoint, and `redaction-guard` — are ported to Python preserving their exact pattern corpus and
  fail-closed exit semantics. **Behavioral** parity fixtures (not corpus-diff only) assert: pre-push
  scans the correct diff range and exits non-zero on a planted secret; the memory allowlist path exits
  2 on a violation; the `git-push` chain blocks on scanner failure; and `redaction-guard` strips the
  same fields — so no secret class or redaction behavior regresses.
- **R37** `python3 -m sw generate` (the `sw/` emitter package) remains the single content build path
  and gains no shell dependency; the emitter produces a no-shell `dist/` and the golden parity
  manifest is regenerated to reflect the Python entrypoints. The dist-no-shell obligation is enforced
  for each surface in the phase that ports it (consistent with R4/R28), not deferred to a final phase.
- **R38** Ported scripts produce deterministic, reproducible output under documented normalization
  rules — stable JSON key ordering (`sort_keys` policy), fixed separators, defined float/number and
  path-separator normalization, and stable file-enumeration order — so the build chain, golden parity,
  and guard fixtures remain reproducible across POSIX and Windows. Byte-determinism is required for
  golden-parity verbs/gates; other emitters require semantic determinism (R7).
- **R39** CI (`.github/workflows`) runs the workflow through the Python entrypoints. A Windows job is
  added incrementally (R45) and the existing POSIX job is preserved.
- **R43** A prose/config closure fixture enforces R10 across `core/commands/`, `core/skills/`,
  `core/rules/`, `core/providers/`, `docs/guides/`, the `documentation/` mirror, and the named config
  samples — asserting zero `gh`/`curl`/`jq`/`rsync`/`bash scripts/` literals in those trees.
- **R44** Host transport hardens against SSRF for self-hosted configurations: a configured
  `host.baseUrl` / `apiBaseUrl` is validated (HTTPS-only; reject loopback, link-local, and
  cloud-metadata addresses unless explicitly allowlisted), redirects are constrained to same-host
  HTTPS, and the transport never logs the token or raw response bodies (reinforces R8/R14/TR3).
- **R45** A minimal Windows smoke CI job lands in the **foundation phase** (interpreter probe R2, one
  ported git hook via R40, and one JSON gate) and expands each phase to cover that phase's newly
  ported surface, reaching the full representative slice (TR11) by the final phase — so R1 is proven
  incrementally rather than only at the end.

## Technical Requirements

- **TR1 — Entrypoint convention (R2, R3, R40).** A single documented invocation convention replaces
  `bash scripts/<name>.sh`. Commands/skills call Python modules by a stable name; a committed resolver
  performs the R2 fail-closed interpreter probe (CPython ≥ 3.9; accept `python`/`python3`/`py -3`;
  reject Python 2 and the Store stub) and the correct module path cross-platform. Git hooks install
  via the R40 launcher (Python-shebang hook + Windows `.cmd`/`py -3` shim) under `core.hooksPath` or
  copied hook files. No agent prose contains the literal `bash scripts/`.
- **TR2 — Shared runtime library (R13–R18).** A small internal package (e.g. `scripts/_sw/`) provides:
  `logging_setup` (stderr handler, `SW_LOG_LEVEL`, run-log append, redaction-aware), `poll_until`
  (interval/backoff/jitter/timeout reading `checks.watch.*` / `deliver.watchdog.*`), `jsonio`
  (normalization-rule-compliant `json.dumps` for stdout per R38), `cli` (argparse scaffold + `--help`
  + docstring conventions), and `proc` (cross-platform subprocess helpers that never invoke a shell).
  Every ported module uses these rather than re-implementing.
- **TR3 — HTTP transport (R8, R44).** `urllib.request` replaces `curl`: requests use an explicit
  `ssl.create_default_context()` with verification on; the token is set via an HTTP header on the
  `Request` object (never a process argument); only `https` schemes are accepted; redirects are
  constrained to same-host HTTPS (R44); the PRD 026 rate-limit retry/backoff wrapper is reimplemented
  on top of the shared `poll_until`. Responses are treated as untrusted (PRD 026 TR9) and never
  interpolated into a shell or executed; transport exceptions and logs are redaction-scrubbed (no
  token, no raw body).
- **TR4 — JSON contract (R7, R38).** `jq` is removed; all emit/parse uses `json` via the `jsonio`
  helper with the R38 normalization rules. A contract fixture asserts **semantic parity** per
  verb/gate, and **byte parity** for the subset with recorded goldens; golden re-snapshots are
  permitted only with a recorded breaking-change note.
- **TR5 — Mirror copy (R5, R6).** A Python copier replicates `rsync -a --delete` semantics
  (recursive copy, orphan prune, exclusion globs, symlink handling) for `install` and `copy-to-core`,
  with the existing `--force` and dev-only orphan-check behavior preserved and unit-fixture covered.
- **TR6 — Dependency manifest + gate (R12, R11).** A committed manifest enumerates allowed Python
  imports beyond the standard library (empty by default). A guard fails closed on any import not in
  stdlib and not declared/vendored. No `PyYAML` (or other non-stdlib) import remains; if a vendored
  dep is later required it lives under a single `sys.path`-injected vendor package.
- **TR7 — Host adapter port (R25, R9, R44).** Each host adapter becomes a Python module behind the
  `host` dispatch entry, implementing the PRD 026 verb set (`resolve-pr-for-branch`, `pr-create`,
  `pr-view`, `pr-list`, `checks-status`, `review-threads`, `repo-identity`, `ci-watch`, `merge`) over
  `urllib`, with capability flags, per-host rate-limit signal mapping, SSRF-hardened base-URL handling
  (R44), and `pr-list` emitting the full `pr-view` shape (R19). The local (`none`) adapter and
  local-evidence gate are preserved.
- **TR8 — Build-chain coherence (R28, R29, R37, R41).** `copy-to-core`, the `sw/` emitter,
  `build-chain-sot.json`, and the golden parity manifest are updated together as scripts port; emitter
  freshness, golden parity, and per-phase reference-closure (R41) fixtures gate every phase. The
  `core/scripts/` mirror and `dist/` trees contain no shell scripts for ported surfaces.
- **TR9 — Enforcement gate (R30, R31, R41).** A guard enumerates the enforced trees and exits non-zero
  on any `.sh`/`.bash`/`.ps1` file and on any `subprocess`/`os.system`/`os.popen` shell-out to a
  plugin script (R41). It runs in warn mode while the port is in flight and flips to hard-fail (zero
  allowlist) in the final phase; it is registered in `verify.test` and the PR test-plan manifest.
- **TR10 — Consolidation fixtures (R19–R22).** Regression fixtures cover: `pr-list`/`pr-view` field
  parity; idempotent COMPLETION-LOG (no duplicate rows on re-run/resume); single reconciler behavior
  across legacy PRD INDEX and planning INDEX (code-path consolidation only); and `.sh`/`.py` pair
  collapse (callers resolve to the single Python module).
- **TR11 — Windows CI (R1, R39, R45).** A Windows CI job installs only Python + git and runs a
  representative slice (interpreter resolution, a gate evaluation, a host verb against a mocked REST
  endpoint, a `poll_until` wait, a git-hook invocation) to prove the no-bash path end-to-end; it is
  built up incrementally per R45 and reaches the full slice by the final phase.
- **TR12 — Per-script audit ledger (R23, R41).** A committed machine-readable ledger lists every `.sh`
  with its disposition (`port` → target module, `consolidate` → target, `delete` → superseded-by). A
  fixture reconciles it against the tree so the count of remaining `.sh` only ever decreases and no
  file is dropped without a recorded disposition; the reference-closure gate (R41) reads it to know
  which targets are closed.
- **TR13 — Cross-platform hook launcher (R3, R40).** The committed launcher contract: a hook entry
  with a portable Python shebang plus a Windows-executable shim that re-invokes through the R2 probe,
  installed by R5. A Windows hook-invocation fixture in the foundation phase proves a planted
  violation is caught fail-closed under git's native Windows hook runner before any other hook ports.

## Security & Compliance

- The human merge gate to trunk is preserved in every mode; no path auto-merges the default branch.
- `secret-scan`, `memory-redact`, the redaction chokepoint, and `redaction-guard` port to Python with
  **behavioral** parity proven by fixture (R36); pre-push secret scanning is fail-closed (R40) and
  range-scoped history-redaction guardrails remain in force.
- Host tokens are referenced by env-var name only, sent via HTTP header (never a process argument),
  and never logged or written to state/memory (PRD 026 R8/TR4 preserved under `urllib`).
- HTTP transport is HTTPS-only with explicit TLS context; redirects are same-host HTTPS only and
  self-hosted base URLs are SSRF-validated (R44); host REST responses remain untrusted input (PRD 026
  TR9) and are never interpolated into a shell or executed.
- Logging is stderr-only and redaction-aware; tokens, secrets, and raw response bodies are never
  emitted (R13, R14, TR3).
- The zero-shell enforcement gate plus the no-`subprocess`-shell-out rule (R30/R41) reduce the shell
  injection / quoting surface across the plugin and tighten the Python trust boundary (PRD 026 TR9).

## Testing Strategy

- **Windows portability (R1, R39, R45, TR11, TR13)** — Windows CI job with only Python + git proves,
  incrementally per phase, the interpreter probe, git-hook launcher, gate, host verb (mocked REST),
  and `poll_until` paths run without bash.
- **Entrypoint convention (R2, R3, R40, TR1)** — fixtures assert no agent prose contains
  `bash scripts/`, the interpreter probe selects a conforming CPython and rejects Python 2 / Store
  stub, and hooks fire fail-closed on synthetic violations cross-platform.
- **Dependency elimination (R6–R9, R11, R43, TR3, TR5, TR6)** — guards assert zero
  `rsync`/`jq`/`curl`/`gh` invocations and zero non-stdlib/undeclared imports across the enforced
  trees; the prose/config closure fixture (R43) asserts zero banned-tool literals; the workflow runs
  with `gh`, `jq`, and `rsync` absent from `PATH`.
- **JSON contract (R7, R38, TR4)** — per-verb/gate fixtures assert semantic parity and (where goldens
  exist) byte parity against recorded output under the normalization rules.
- **Mirror copy (R5, TR5)** — fixtures cover recursive copy, orphan prune, exclusions, symlinks, and
  `--force` behavior for install/copy-to-core.
- **Standardized infra (R13–R18, TR2)** — fixtures assert logs go to stderr (stdout stays pure JSON),
  `SW_LOG_LEVEL` gating, run-log append redaction, and `poll_until` interval/backoff/timeout behavior;
  a guard asserts no fixed `sleep` remains on the enumerated external-wait call-site map (R16).
- **Host adapter parity (R25, R19, R44, TR7)** — GitHub/GitLab/Bitbucket/local verbs against mocked
  REST responses; `pr-list`↔`pr-view` field parity; rate-limit signal handling preserved; SSRF
  base-URL rejection and redirect constraints.
- **Consolidation (R19–R22, TR10)** — pr-list parity, idempotent COMPLETION-LOG (no duplicate rows on
  resume), single reconciler code path.
- **Security parity (R36, R44)** — behavioral secret-scan/redact/redaction-guard parity (planted
  secret blocks pre-push, allowlist exit-2, git-push chain blocks on scanner failure); token never in
  process args or logs; transport redaction.
- **Reference closure (R41, TR12)** — per-phase fixture asserts no stale `bash scripts/<ported>.sh`
  reference and no `subprocess`/`os.system` shell-out to ported scripts in enforced trees.
- **Build chain (R28, R29, R37, TR8)** — `copy-to-core` + emitter + golden parity reproduce with no
  shell step; `dist/`/`core/scripts/` contain no shell for ported surfaces.
- **Audit ledger (R23, TR12)** — fixture reconciles the ledger against the tree; remaining `.sh` count
  monotonically decreases; no undisposed file.
- **Migration (R34, R42)** — doctor detects a stale pre-port layout and prints remediation; the
  upgrade path refuses to proceed while a `/sw-deliver` run is non-terminal.
- **Enforcement (R30, R31, R41, TR9)** — guard warns mid-port, hard-fails on any shell-script file or
  shell-out in the final phase.
- **Docs currency (R33, R35, R43)** — fixture asserts user docs list only Python + git and never
  re-list a removed dependency.
- All new fixtures register in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.

## Success Criteria

- **Windows-native:** a clean Windows machine with only Python ≥ 3.9 + git installs and runs the full
  workflow (gate, host verb, hooks, poll) with no `bash`/`rsync`/`jq`/`curl`/`gh` and no `pip install`
  — proven by green Windows CI (R1, R45, TR11).
- **Dependency-free (beyond Python + git):** zero `rsync`/`jq`/`curl`/`gh` invocations and zero
  non-stdlib/undeclared imports in the enforced trees; banned-tool literals absent from agent prose
  and config (R6–R12, R43).
- **Zero shell end state:** no `.sh`/`.bash`/`.ps1` in the enforced trees and no shell-out to plugin
  scripts; the enforcement guard is hard-fail in CI (R30, R31, R41).
- **Behavior preserved:** JSON contracts, exit codes, fail-closed guardrails, secret-scan/redaction
  behavior, host verb set, and the human merge gate are unchanged under fixtures (R7, R36, R44,
  PRD 026 preserved).
- **Consolidated:** `pr-list`↔`pr-view` parity, idempotent COMPLETION-LOG, single reconciler code
  path, and collapsed `.sh`/`.py` pairs are fixture-locked (R19–R22).
- **Documented + enforced going forward:** prerequisites docs corrected; Python-first rule active;
  every remaining `.sh` has a recorded disposition and the count only decreases (R23, R31, R33, TR12).
- **Standardized infra in use:** one logging convention (stderr + run log) and one `poll_until`
  primitive back every external wait on the call-site map; no fixed `sleep` on those paths (R13–R17).

## Rollout Plan

Phased delivery; each phase ships behind passing fixtures and is **independently mergeable**, sliced
into **bounded, domain-sized units** (boundaries finalized in `/sw-tasks`, D12). Consolidations execute
inside the relevant domain port, not as a standalone phase (D9). Dependency elimination is performed
**as Python ports** (hard-cut, D8) — never as edits to soon-to-be-deleted shell. Each phase applies
per-phase reference-closure (R41), build-chain reproduction for touched surfaces (R29), dist-no-shell
for ported surfaces (R37), and expands the Windows smoke job (R45).

- **Phase 1 — Foundation.** Shared runtime library `scripts/_sw/` (logging R13–R14, `poll_until`
  R15–R17, jsonio R38, cli/docstrings R18, shell-free `proc`), fail-closed interpreter probe + R40
  cross-platform hook launcher proven by a Windows hook fixture (R2, TR1, TR13), dependency manifest +
  import guard (R12, R11), full per-script audit ledger (R23, TR12), enforcement guard in **warn**
  mode + reference-closure scaffold (R30/R41 warn), and the minimal Windows smoke job (R45). To get
  the build chain onto Python early, port `install`/`copy-to-core` removing `rsync` here (R5, R6, TR5).
  Requirements: R2, R5, R6, R11, R12, R13, R14, R15, R16, R17, R18, R23, R40, R45, TR1, TR2, TR5, TR6,
  TR12, TR13.
- **Phase 2 — Host layer & `gh`/`curl` elimination.** Port host transport + all adapters to `urllib`
  with SSRF hardening (R8, R25, R44, TR3, TR7), finish `gh` removal in
  `docs_pr`/`docs-merge`/`host_lib`/CodeRabbit (R9), scrub agent prose + config (R10, R43), unify
  `pr-list` onto `pr-view` (R19). Requirements: R8, R9, R10, R19, R25, R43, R44, TR3, TR7.
- **Phase 3 — Gate & dispatcher core.** Port `check-gate`, `wave.sh` + `wave_*` dispatch surface,
  `planning-graph`, and resolve the twin INDEX reconciler code paths (R22); eliminate `jq` on these
  surfaces (R7). Requirements: R7 (incremental), R22, R24 (gate/dispatcher subset), TR4, TR10.
- **Phase 4 — Hooks, security filters, providers.** Port git hooks on the R40 launcher (R3),
  secret-scan/memory-redact/redaction-guard/git-push with behavioral parity (R36), `core/providers/`
  adapters (R26); ensure `dist/`/`core/scripts/` carry no shell for these surfaces (R4). Requirements:
  R3, R4, R26, R36, R40 (consume).
- **Phase 5 — Remaining production port + consolidations.** Port remaining `scripts/*.sh` (R24
  remainder), retire legacy `append-log` (R20), collapse `.sh`/`.py` sibling pairs (R21), complete
  `jq` elimination (R7). Requirements: R7 (complete), R20, R21, R24 (remainder).
- **Phase 6 — Test harness, docs, enforcement flip, migration.** Port the 137 `.sh` test harnesses to
  a Python runner (R27), update build-chain SoT + layout + emitter + golden parity (R28, R29, R32,
  R37, R38), correct user docs + doctor + migration gate (R33, R34, R35, R42), reach full Windows CI
  (R39, R45, R1), and flip enforcement to hard-fail zero-shell (R30, R31, R41). Requirements: R1, R27,
  R28, R29, R30, R31, R32, R33, R34, R35, R37, R38, R39, R42, R45, TR8, TR9, TR11.

## Decision Log

- **2026-06-30** D1 — One phased Python-first standardization epic rather than a big-bang rewrite or
  several disconnected PRDs — the phases share one entrypoint/build-chain migration and are most
  coherent under one frozen intent.
- **2026-06-30** D2 — Native Windows, zero bash dependency — every entrypoint (commands/skills, hooks,
  install, build chain, tests) invokes Python directly; "Git Bash acceptable" was rejected because it
  still requires bash plus extra installs.
- **2026-06-30** D3 — Python stdlib-first with a vendored escape hatch (pure-Python, no runtime
  `pip install`, declared in a manifest), floor 3.9 — preserves the "no dependency except Python / no
  install step" promise while leaving a governed relief valve.
- **2026-06-30** D4 — Two-layer condition-based event-wait (`poll_until` for bounded in-process waits +
  retained agent self-wake for long external CI), one config source (`checks.watch.*`); fixed `sleep`
  timers prohibited on the enumerated external-wait call-site map.
- **2026-06-30** D5 — Behavior-normalizing consolidation, fixture-guarded — unify `pr-list` onto
  `pr-view`, retire legacy `append-log`, collapse `.sh`/`.py` pairs, single reconciler code path; each
  change covered by a regression fixture.
- **2026-06-30** D6 — Hard enforcement, zero shell at completion with no allowlist; the guard runs
  warn-mode mid-port and hard-fails in the final phase, and also bans shelling out to bash/sh (R41).
- **2026-06-30** D7 — Logging to stderr + run log; stdout JSON contract preserved; `SW_LOG_LEVEL`
  default `WARNING`; secrets never logged.
- **2026-06-30** D8 — Hard-cut per phase, **no `.sh` shims and no auto-generated back-compat layer** —
  porting a script updates all references in the same change; migration is handled by an explicit
  upgrade gate + reinstall (D14), not compatibility shims. (User-confirmed during PRD review.)
- **2026-06-30** D9 — Dependency elimination and consolidation are executed as Python ports inside the
  relevant domain port (not as a separate phase, and not as edits to shell that will be deleted),
  consistent with D8.
- **2026-06-30** D10 — This epic completes PRD 026's `gh` elimination (R4/R17 regression in Phase-5
  additions and agent prose) rather than re-opening the host abstraction; the host verb set and
  rate-limit contract are preserved, only the transport (curl→urllib) and residual call sites change.
- **2026-06-30** D11 — Security-critical filters (secret-scan, redaction, redaction-guard) are ported
  with fixture-proven **behavioral** parity, because a silent regression here is a security risk.
- **2026-06-30** D12 — Rollout is sliced into bounded, independently-mergeable, domain-sized units
  rather than a few coarse phases; the indicative phase map above is a guide and exact unit boundaries
  are finalized in `/sw-tasks`. (Panel: feasibility/scope/product/coherence.)
- **2026-06-30** D13 — JSON parity is **semantic-by-default with byte-parity where goldens exist**
  (R7/R38/TR4), with normalization rules and a permitted one-time golden re-snapshot — not blanket
  byte-for-byte equivalence, which was deemed brittle across platforms.
- **2026-06-30** D14 — Strict no-shim migration confirmed (user choice): the upgrade requires
  finishing/aborting in-flight `/sw-deliver` runs and a one-shot reinstall; the doctor detects stale
  pre-port layout and prints remediation (R34/R42). The brief migration window is the accepted cost of
  D8.
- **2026-06-30** D15 — The cross-platform git-hook launcher (R40/TR13) is a committed, fixture-proven
  artifact decided up front in the foundation phase (resolving brainstorm Q3), because all hook ports
  depend on it and Windows hook execution is a known risk.
- **2026-06-30** D16 — The interpreter selection is a fail-closed probe (R2/TR1) rejecting Python 2 and
  the Microsoft Store stub and supporting `py -3`, rather than assuming `python`/`python3` on PATH.
- **2026-06-30** D17 — Enforcement breadth extends beyond `*.sh` to `.bash`/`.ps1` and to
  `subprocess`/`os.system` shell-outs to plugin scripts (R30/R41), closing the obvious evasions of a
  name-only `.sh` ban.
- **2026-06-30** D18 — Vendoring is deferred-by-default (resolves former Q1): no third-party Python
  dependency is vendored unless a phase demonstrates a concrete stdlib gap; the R12 manifest stays
  empty at v1 and the import-guard fails closed on any undeclared import. Implementation latitude only
  — not a freeze blocker.
- **2026-06-30** D19 — The ported test-runner shape is an implementation decision in the test-harness
  phase (resolves former Q2): stdlib `unittest` versus a bespoke runner mirroring the current fixture
  protocol, constrained to preserve coverage, PR test-plan registration, and `verify.test` integration
  (R27). Latitude only — not a freeze blocker.

## Open Questions

None — all questions are resolved or recorded as bounded deferrals in the Decision Log (D18 vendoring,
D19 test-runner shape; D15 resolved the former interpreter/hook-launcher question).
