---
date: 2026-06-26
topic: generic-repo-portability
prd: docs/prds/018-generic-repo-portability/018-prd-generic-repo-portability.md
frozen: true
frozen_at: 2026-06-26
regenerated_at: 2026-06-26
union: R1-R33 (R3 superseded by R28 per amendment A1)
---

# Tasks — PRD 018 Generic-repo portability & onboarding hardening

Generated from the frozen PRD spec union (R1–R33; R3 superseded by R28 via amendment A1
`amendments/A1-init-config-consolidation.md`). The per-repo configuration command is **`/sw-init`**
(`core/commands/sw-init.md`); `/sw-setup` is a delegate-only deprecated alias. Four phases,
dependency-ordered for phase-mode delivery. Phase 1 (trust + verify + `/sw-init`) and Phase 3 (base-branch)
are independent and may run in parallel; Phase 2 stacks on Phase 1's emitter/sw-reference surface; Phase 4
consolidates after all.

## Tasks

### 1. Trust + verify + `/sw-init`: project-type detection, fixed presets, setup write, unconfigured signal, rename/configurator/version-stamp (L)

The headline pillar — first contact runs the user's real tests and the gate never silently passes a vacuous
verify. Includes the `/sw-setup`→`/sw-init` rename, single configurator, and the configured-version
stamp/drift refresh (amendment A1). Self-contained; no dependency on later phases.

- [ ] 1.1 Add root-level project-type detector (R1)
  - **File:** `scripts/detect-project-type.sh`
  - **Expected:** root-only manifest scan (package.json, pyproject.toml/setup.py/setup.cfg, go.mod, Cargo.toml, Gemfile, pom.xml/build.gradle, Makefile, ansible.cfg/galaxy.yml); emits JSON `{matches:[{type,confidence}], ambiguous:bool}`; multi-match flagged for disambiguation; zero-match → empty
  - **R-IDs:** R1
- [ ] 1.2 Add fixed per-ecosystem preset table (R20)
  - **File:** `core/sw-reference/verify-presets.json`
  - **Expected:** v1 presets for node/python/go/ansible/make (lint/typecheck/test/build where applicable); conservative empty defaults for ruby/jvm; values are literal commands, never derived from user manifest content
  - **R-IDs:** R20
- [ ] 1.3 Node allowlisted-key mapping + unsafe-command rejection (R20)
  - **File:** `scripts/detect-project-type.sh`, `core/commands/sw-setup.md`
  - **Expected:** Node maps only allowlisted script keys (`lint|test|build|typecheck`, names `^[a-zA-Z0-9_-]+$`) to `npm run <key>`; never embeds script values; proposals containing `; & | \` $ ( )` or destructive patterns are rejected/flagged and never auto-written
  - **R-IDs:** R20
- [ ] 1.4 Setup verify interaction (detect → propose → per-key edit → diff → confirm/write) (R1, R2, R23)
  - **File:** `core/commands/sw-setup.md`
  - **Expected:** new setup step after platform/models; proposal table; per-key edit/keep/skip; multi-match disambiguation menu; diff + explicit `write`/`cancel`; re-run is the documented edit path; writes real `verify.*`, never a vacuous placeholder
  - **R-IDs:** R1, R2, R23
- [ ] 1.5 Non-interactive `--accept-defaults` path (R4)
  - **File:** `core/commands/sw-setup.md`, `scripts/seed-model-config.sh` (or setup helper)
  - **Expected:** records detection + `verifyGaps[]` without inventing/writing derived verify; writing verify requires interactive confirm or explicit `--write-verify`
  - **R-IDs:** R4
- [ ] 1.6 Placeholder taxonomy + `verify-unconfigured` signal + blocking semantics (R28 ← supersedes R3)
  - **File:** `scripts/verify-evidence.sh`, `core/skills/verification-gate/SKILL.md`, `.sw/config.schema.json`
  - **Expected:** classify no-op verify (empty/`echo`/`:`/`true`/`exit 0`) as unconfigured; emit `verify-unconfigured` finding with CTA "run `/sw-init`"; add `verify.allowUnconfigured` boolean to schema; non-blocking+loud in manual flows, hard-block under `/sw-deliver`/autonomous unless opted in (DL-13)
  - **R-IDs:** R28
- [ ] 1.7 Surface `verify-unconfigured` across doctor/status/ready (R3, R24)
  - **File:** `core/commands/sw-setup.md`, `core/commands/sw-status.md`, `core/commands/sw-ready.md`
  - **Expected:** same `verify-unconfigured` line with CTA in each surface
  - **R-IDs:** R3, R24
- [ ] 1.8 Portability self-check + `gh`/Actions warning (R24, R25)
  - **File:** `core/commands/sw-setup.md`, `scripts/detect-platform.sh` (or setup helper)
  - **Expected:** single self-check summarizing verify-configured/gaps, base resolvable, `gh`/Actions availability, sw-reference paths present, no dev-harness refs, web knobs off; explicit warning when `gh`/Actions unavailable
  - **R-IDs:** R24, R25
- [ ] 1.9 Emit detector + presets so user installs can run setup (R12 partial)
  - **File:** `sw/emitter_base.py` / `platforms/*/emitter.py`
  - **Expected:** `scripts/detect-project-type.sh` ships (already emittable) and `core/sw-reference/verify-presets.json` is added to runtime-support emission; regenerate `dist/`
  - **R-IDs:** R12
- [ ] 1.10 Phase 1 fixtures (R17 partial)
  - **File:** `scripts/test/run-onboarding-ux-fixtures.sh` (extend) + new `scripts/test/run-portability-setup-fixtures.sh`
  - **Expected:** `setup-detect-project-type`, `setup-presets-fixed-table`, `setup-rejects-unsafe-commands`, `setup-writes-real-verify`, `setup-accept-defaults-no-write`, `gate-flags-unconfigured-verify`, `portability-self-check`, `init-command-rename`, `init-single-configurator`, `config-version-stamp`, `stale-config-notice-and-refresh`
  - **R-IDs:** R1, R2, R4, R20, R23, R24, R25, R28, R29, R30, R32
- [ ] 1.11 Rename `/sw-setup` → `/sw-init` + delegate-only alias + routing key (R28, R30)
  - **File:** `core/commands/sw-init.md` (canonical), `core/commands/sw-setup.md` (delegate-only alias), `core/sw-reference/model-routing.defaults.json`, `core/sw-reference/communication-routing.defaults.json`
  - **Expected:** `sw-init.md` carries the full command body; `sw-setup.md` prints a deprecation notice and delegates with identical behavior (no duplicate body); routing gains an `sw-init` key with `sw-setup` retained as a one-release alias; `/sw-init` is the interactive surface with the R4 `--accept-defaults` scriptable path via the same configurator
  - **R-IDs:** R28, R30
- [ ] 1.12 Single per-repo configurator source of truth (R29)
  - **File:** `scripts/sw-configure.sh` (or shared helper), `core/commands/sw-init.md`
  - **Expected:** one configurator invoked by `/sw-init` and the scriptable entry; install tooling holds no configuration logic
  - **R-IDs:** R29
- [ ] 1.13 Configured-version stamp + drift notice + non-destructive refresh (R32)
  - **File:** `core/commands/sw-init.md`, `scripts/sw-configure.sh`, `.sw/config.schema.json`, shared at-entry helper
  - **Expected:** write `configuredWith:{shipwrightVersion,schemaVersion}` (sources: installed plugin version + bundled config.schema.json revision); stale when either differs; surface notice across closed set (`/sw-init` doctor + R24 self-check + one shared at-entry helper; no beforeSubmitPrompt, no per-command dup); refresh additive + consent-gated per subtree; never auto-merge `verify.*`/user-set `defaultBaseBranch`/memory/review/tiers; bump stamp only after accepted refresh
  - **R-IDs:** R32

### 2. Clean install / dev-product boundary (M) — depends on Phase 1

Neutralize shipped artifacts, close the emit set, exclude dev scripts, add the dev-repo marker. Stacks on
Phase 1's emitter/sw-reference edits.

- [ ] 2.1 Neutralize shipped example config (R10)
  - **File:** `core/sw-reference/workflow.config.example.json`, `.sw/workflow.config.example.json`
  - **Expected:** `verify.test` is a neutral require-configuration sentinel (not echo-pass, not fixture path); no credential-shaped strings; `restBaseUrl` stays localhost example
  - **R-IDs:** R10
- [ ] 2.2 Relocate PR-test-plan manifest to `ci.*` (PRD 016-coordinated) (R10)
  - **File:** `.sw/config.schema.json`, `scripts/check-gate.sh`, CI generator, PRD 016 fixtures, dogfood `.cursor/workflow.config.json`
  - **Expected:** manifest reference moves from `verify.prTestPlanManifest` to `ci.prTestPlanManifest`; schema + check-gate + generator + 016 fixtures + dogfood config updated in this phase; PRD 016 single-source invariant preserved
  - **R-IDs:** R10
- [ ] 2.3 Exclude dev-only scripts from `dist/` (R11)
  - **File:** `sw/emitter_base.py`
  - **Expected:** `copy-to-core.sh`, `snapshot-tree.sh`, `model-routing-check.sh` excluded; `dist/` regenerated
  - **R-IDs:** R11
- [ ] 2.4 Reference audit — no shipped command references an excluded script (R11, R27)
  - **File:** `core/commands/**`, `core/skills/**` (audit), `scripts/test/run-portability-boundary-fixtures.sh`
  - **Expected:** grep proves no shipped command/skill references the excluded scripts; offending refs relocated behind the dev marker or removed
  - **R-IDs:** R11, R27
- [ ] 2.5 Closed sw-reference emit + `.sw/` tolerance + setup schema path (R12)
  - **File:** `sw/emitter_base.py` / `platforms/*/emitter.py`, `core/commands/sw-setup.md`, affected commands/skills
  - **Expected:** emit exactly `config.schema.json`, `layout.md`, neutral `workflow.config.example.json` (plus routing defaults + verify-presets); commands reference plugin-relative via plugin-root resolver or tolerate absent `.sw/`; `/sw-setup` schema path resolves in a user install; legacy `.sw/` tolerated one release
  - **R-IDs:** R12
- [ ] 2.6 Add dev-repo marker (R13, R14)
  - **File:** `.shipwright-dev`, `sw/emitter_base.py` (CI-generator gating), `core/commands/sw-setup.md` (template selection), docs
  - **Expected:** sentinel file (not a config field); gates only template selection/docs/emitter-CI-generator/example-neutralization; never gates any security control; workflow engine unchanged for marked repos
  - **R-IDs:** R13, R14
- [ ] 2.7 Regenerate dist + golden/snapshot parity (R27)
  - **File:** `dist/cursor/**`, `dist/claude-code/**`, golden manifest
  - **Expected:** `python3 -m sw generate --all`; golden/snapshot parity regenerated in the same change so parity fixtures pass with the new file set
  - **R-IDs:** R27
- [ ] 2.9 install.sh cwd-scoped opt-in `/sw-init` offer (R31)
  - **File:** `scripts/install.sh`, `core/scripts/install.sh`
  - **Expected:** when run inside a git repo, after the global copy print an opt-in reminder + `/sw-init` invocation hint for *that* repo only; never run the configurator, hold config logic, enumerate/init other repos, or act on the global copy; no-op outside a repo; no requirement on marketplace installs
  - **R-IDs:** R31
- [ ] 2.10 Phase 2 fixtures (R17 partial)
  - **File:** `scripts/test/run-portability-boundary-fixtures.sh`, extend emitter/parity fixtures
  - **Expected:** `example-config-neutral`, `dist-excludes-dev-scripts`, `no-shipped-ref-to-dev-scripts`, `swref-closed-emit-and-tolerance`, `dev-repo-marker`, `install-offers-init-in-repo`
  - **R-IDs:** R10, R11, R12, R13, R14, R27, R31

### 3. Base-branch resolution + fail-closed leak fixes (L) — independent (parallel with Phases 1–2)

Resolver, persistence, entry guard, disclosure, caller wiring, and the fail-closed secret-scan/frozen
contract. Touches a separate script surface from Phases 1–2.

- [ ] 3.1 Base resolver with precedence + user-set predicate (R5)
  - **File:** `scripts/resolve-base-branch.sh`
  - **Expected:** precedence `--base` → user-set `defaultBaseBranch` (distinct from schema default) → captured HEAD; emits resolved base name + SHA + source as JSON
  - **R-IDs:** R5
- [ ] 3.2 Entry guard + capture/persistence (name + SHA) (R7, R21)
  - **File:** `scripts/resolve-base-branch.sh`, `scripts/shipwright-state.sh`, `scripts/wave_deliver_loop.py`
  - **Expected:** single authoritative capture owner at entry, before worktree creation; persists name+SHA to repo-level run state; refuses detached/`<type>/<slug>` HEAD with actionable recovery copy; resume with missing/corrupt state halts `needs-base-replay` (no re-capture from feature HEAD); all worktrees in one run share the base
  - **R-IDs:** R7, R21
- [ ] 3.3 Wire callers to persisted base; trunk vs integration base (R6, R26)
  - **File:** `scripts/wave_spec_seed.py`, `scripts/wave_lifecycle.py`, `scripts/wave_terminal.py`, `scripts/wave_deliver.py`, `scripts/worktree.sh`
  - **Expected:** feature fork + terminal PR target use persisted trunk base (not live config at PR time); phase worktrees fork from the persisted integration branch `<type>/<slug>`; two base roles documented and distinct
  - **R-IDs:** R6, R26
- [ ] 3.4 Base disclosure at entry (R22)
  - **File:** `scripts/resolve-base-branch.sh`, `core/commands/sw-start.md`, `core/commands/sw-worktree.md`, deliver seed path
  - **Expected:** one-line disclosure naming source, e.g. `base: dev (captured from HEAD | --base | defaultBaseBranch)`
  - **R-IDs:** R22
- [ ] 3.5 Fail-closed base contract for secret-scan + frozen check (R8, R19)
  - **File:** `scripts/check-frozen.sh`, `scripts/secret-scan.sh`, `scripts/secret_scan.py`
  - **Expected:** resolve BASE_OID; require exists + ancestor-of-HEAD + ≠HEAD; diff `BASE..HEAD`; empty-diff/missing-base/git-error → block (non-zero, never pass); CI fallback chain (persisted/`GITHUB_BASE_REF` → user-set defaultBaseBranch → fail-closed); `--base` trusted-operator-only and recorded; secret-scan default scans full push range `merge-base..HEAD`; chosen base+source logged
  - **R-IDs:** R8, R19
- [ ] 3.6 Lifecycle relocation + prose generalization (R8, R9)
  - **File:** `scripts/wave_lifecycle.py`, commands/skills/scripts with "→ main" prose
  - **Expected:** primary-checkout relocation uses resolved base (not `"main"`); operator "→ main" strings render the resolved base
  - **R-IDs:** R8, R9
- [ ] 3.7 Phase 3 fixtures (R17 partial)
  - **File:** new `scripts/test/run-base-resolution-fixtures.sh`, extend `run-secret-scan-fixtures.sh` / branch-guard
  - **Expected:** `base-resolution-precedence`, `base-persist-name-and-sha`, `base-resume-needs-replay`, `base-shared-across-worktrees`, `base-drives-fork-and-pr`, `base-entry-guard-actionable`, `base-disclosed-at-entry`, `frozen-secretscan-failclosed`, `lifecycle-base-fallback`, `prose-base-generalized`
  - **R-IDs:** R5, R6, R7, R8, R9, R19, R21, R22, R26

### 4. Web neutrality, docs, dist consolidation, fixture closure (M) — depends on Phases 1, 2, 3

- [ ] 4.1 Web-config neutral defaults + opt-in docs (R15)
  - **File:** `.sw/config.schema.json` (defaults), `core/sw-reference/workflow.config.example.json`, `docs/guides/configuration.md`
  - **Expected:** `worktree.scaffold`, `verifyE2e`, review UI enrichers default off/neutral; documented as opt-in web-specific
  - **R-IDs:** R15
- [ ] 4.2 Documentation update (R18, R33)
  - **File:** `docs/guides/getting-started.md`, `docs/guides/configuration.md`, `README.md`, `core/commands/sw-init.md`, `rules/sw-naming.mdc`, base-branch references
  - **Expected:** covers project-type setup, base-branch model + visibility, neutral defaults, the GitHub ceiling, the dev/product boundary; uses `/sw-init` (noting `/sw-setup` deprecation); documents "global install once vs per-repo `/sw-init`" + version-drift refresh (R33 merged here, no parallel doc phase)
  - **R-IDs:** R18, R33
- [ ] 4.3 Final emitter regeneration + freshness (R16)
  - **File:** `dist/cursor/**`, `dist/claude-code/**`
  - **Expected:** `python3 -m sw generate --all`; emitter freshness gate green across all phase changes
  - **R-IDs:** R16
- [ ] 4.4 Fixture closure + cross-cutting suite registration (R17)
  - **File:** `.cursor/workflow.config.json` `verify.test` chain, new fixture runners
  - **Expected:** all new fixture runners registered in the dogfood verify chain; `web-config-neutral-defaults`, `portability-emitter-freshness`, `portability-docs-presence`, `init-docs-and-naming` present; full suite green
  - **R-IDs:** R15, R16, R17, R18, R33

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | none |
| 4 | 1, 2, 3 |

## Traceability

| R-ID | Task(s) | Test scenario |
|------|---------|---------------|
| R1 | 1.1, 1.4 | `setup-detect-project-type` |
| R2 | 1.4 | `setup-writes-real-verify` |
| R4 | 1.5 | `setup-accept-defaults-no-write` |
| R5 | 3.1 | `base-resolution-precedence` |
| R6 | 3.3 | `base-drives-fork-and-pr` |
| R7 | 3.2 | `base-entry-guard-actionable` |
| R8 | 3.5, 3.6 | `frozen-secretscan-failclosed` |
| R9 | 3.6 | `prose-base-generalized` |
| R10 | 2.1, 2.2 | `example-config-neutral` |
| R11 | 2.3, 2.4 | `dist-excludes-dev-scripts` |
| R12 | 1.9, 2.5 | `swref-closed-emit-and-tolerance` |
| R13 | 2.6 | `dev-repo-marker` |
| R14 | 2.6 | `dev-repo-marker` |
| R15 | 4.1 | `web-config-neutral-defaults` |
| R16 | 4.3 | `portability-emitter-freshness` |
| R17 | 1.10, 2.8, 3.7, 4.4 | `portability-docs-presence` |
| R18 | 4.2 | `portability-docs-presence` |
| R19 | 3.5 | `frozen-secretscan-failclosed` |
| R20 | 1.2, 1.3 | `setup-presets-fixed-table` / `setup-rejects-unsafe-commands` |
| R21 | 3.2 | `base-persist-name-and-sha` / `base-resume-needs-replay` |
| R22 | 3.4 | `base-disclosed-at-entry` |
| R23 | 1.4 | `setup-writes-real-verify` |
| R24 | 1.7, 1.8 | `portability-self-check` |
| R25 | 1.8 | `portability-self-check` |
| R26 | 3.3 | `base-drives-fork-and-pr` |
| R27 | 2.4, 2.7 | `dist-excludes-dev-scripts` / parity |
| R28 | 1.6, 1.11 | `init-command-rename` / `gate-flags-unconfigured-verify` (R28 supersedes R3) |
| R29 | 1.12 | `init-single-configurator` |
| R30 | 1.11, 1.5 | `init-single-configurator` |
| R31 | 2.9 | `install-offers-init-in-repo` |
| R32 | 1.13 | `config-version-stamp` / `stale-config-notice-and-refresh` |
| R33 | 4.2 | `init-docs-and-naming` |
