---
date: 2026-06-26
topic: generic-repo-portability
brainstorm: docs/brainstorms/2026-06-26-generic-repo-portability-requirements.md
frozen: true
frozen_at: 2026-06-26
---

# PRD 018 — Generic-repo portability & onboarding hardening

## Overview

**Operator promise: drop Shipwright into your repo, run `/sw-setup`, and on day one your real tests run and
the verification gate never lies about them.** Today neither holds for a non-plugin adopter: `/sw-setup` never
configures `verify.*`, so a fresh repo passes the gate with a vacuous `echo` placeholder (a trust bug — the
gate reports success when nothing ran), and the shipped example config + several commands point at *this
plugin's own* dev harness and `.sw/` files that a user install does not contain.

This PRD makes Shipwright generic-repo-ready. The headline pillars, in priority order:

1. **Run-your-tests + a gate that never lies** — project-type-aware `/sw-setup` proposes real `verify.*`
   commands for the detected toolchain, and an unconfigured/placeholder verify is explicitly surfaced rather
   than silently passing.
2. **Use the branch you're on** — base-branch resolution (`--base` → user-set `defaultBaseBranch` →
   captured-HEAD-at-entry, persisted) so a `dev`-primary user works zero-config, with the residual hardcoded
   `main` leaks fixed *without weakening secret-scan or frozen-artifact enforcement*.
3. **Clean install / no dogfood pollution** — neutralize shipped artifacts that reference the dev harness,
   close the emit set, and add a dev-repo marker.
4. **Web-config neutrality** — frontend-only knobs stay opt-in.

**Honest ceiling (DL-7):** "any repo" means **any GitHub repo with local verify commands** — the CI-readiness
gate observes GitHub Actions via `gh`; non-GitHub CI is out of scope and `/sw-setup` warns when `gh`/Actions
are unavailable.

**Priority (DL-8):** this PRD should land **before PRD 017** — external adoption is blocked until verify and
install neutrality exist; delegation/parallelism (017) optimizes throughput for repos that are already
configured.

It derives from the frozen brainstorm `docs/brainstorms/2026-06-26-generic-repo-portability-requirements.md`
(R1–R18) and extends the namespace with R19–R27 for panel-driven obligations.

### Relationship to prior PRDs

- **PRD 002 (first-run onboarding)** explicitly excluded verify/CI from `/sw-setup`. PRD 018 *extends* setup
  with verify detection only; it does not amend PRD 002's `doc.afterTasks`/review defaults or its other steps.
- **PRD 016 (PR test-plan CI)** owns `prTestPlanManifest` and the CI generator. PRD 018 does **not** amend
  PRD 016; R10/TR6 only neutralize the *shipped example* and relocate the manifest reference to a
  Shipwright-CI-only `ci.*` key, updating PRD 016's `check-gate.py`/generator/fixtures in the same phase to
  preserve its single-source invariant.

## Goals

1. A fresh repo (including non-JS: Python, Ansible, Go, …) runs `/sw-setup` and ends with correct, real
   `verify.*` commands for its toolchain.
2. An unconfigured or placeholder verify is never a silent pass — it is surfaced consistently across the gate,
   `/sw-setup` doctor, `/sw-status`, and `/sw-ready`.
3. A user on a non-`main` primary branch works zero-config: feature branches fork from, and the terminal PR
   targets, the branch they started on; fixed-trunk repos can pin it explicitly; the resolved base is visible.
4. Repointing secret-scan / frozen-artifact checks off `origin/main` strictly preserves (never weakens)
   enforcement, with a fail-closed contract.
5. A user install contains no dev-only scripts, no example config pointing at this plugin's fixtures, and no
   command that breaks on a missing `.sw/` file; dogfooding stays on the standard workflow behind a dev-repo
   marker.

## Non-Goals

- A separate release-branch model (`dev → main` promotion, cherry-pick, staging) — deferred (DL-5).
- **Non-GitHub CI providers** — the readiness gate stays GitHub/`gh`-based (DL-7).
- **Monorepo / multi-package per-subdir verify detection** — root-level detection only; ambiguous repos get a
  disambiguation prompt, not per-package orchestration.
- Removing web-app features (`worktree.scaffold`, `verifyE2e`, review UI enrichers) — kept opt-in.
- Amending frozen PRD 002 or PRD 016 — coordinated, not amended (see Relationship).
- Expanding the `sw-reference` emit surface beyond the **closed set** in TR8.
- Auditing/rewiring every residual `defaultBaseBranch` reader beyond the R8/TR4 inventory — out-of-list
  readers are a documented follow-up, not silent scope.
- A `/sw-setup` redesign beyond verify configuration + the existing PRD 002 steps.
- Changing the memory/model/caveman contracts or the `core/ → dist/` emit architecture itself.

## Requirements

R1–R18 carry forward from the frozen brainstorm (stable; no renumber). R19–R27 are panel-driven additions.

### Project-type-aware setup verify configuration

- **R1** `/sw-setup` MUST detect the repo's project type(s) from **root-level** manifest markers and propose
  concrete `verify.*` presets; the user confirms or edits before write. Detection markers cover at least Node
  (`package.json`), Python (`pyproject.toml`/`setup.py`/`setup.cfg`), Go (`go.mod`), Rust (`Cargo.toml`), Ruby
  (`Gemfile`), JVM (`pom.xml`/`build.gradle`), Make (`Makefile`), Ansible (`ansible.cfg`/`galaxy.yml`).
  Multiple matches → a disambiguation prompt; zero/ambiguous → sensible empty defaults, never a guess.
- **R2** On confirmation, `/sw-setup` MUST write real `verify.*` commands to `.cursor/workflow.config.json`;
  it MUST NOT leave a vacuous placeholder. "Vacuous" is defined by a placeholder taxonomy (R3).
- **R3** The verification gate, `/sw-setup` doctor, `/sw-status`, and `/sw-ready` MUST surface an unconfigured
  verify via a distinct `verify-unconfigured` signal with an actionable CTA ("run /sw-setup"). A **placeholder
  taxonomy** MUST classify no-op verify (empty, `echo …`, `:`, `true`, `exit 0`) as unconfigured so the
  echo-ban cannot be trivially bypassed. **Blocking semantics (DL-13):** the signal is non-blocking and loud
  in interactive/manual flows, but MUST hard-block under `/sw-deliver` and autonomous mode unless the repo
  opts in via `verify.allowUnconfigured: true` (schema-backed). An automated run MUST NOT reach a green gate
  on a vacuous verify without that explicit opt-in.
- **R4** `/sw-setup` MUST support a non-interactive `--accept-defaults` path that records detection results and
  `verifyGaps[]` **without inventing or writing derived verify commands**; writing verify requires explicit
  interactive confirmation (or an explicit `--write-verify` with confirmation).

### Base-branch resolution

- **R5** Base-branch resolution MUST follow precedence: explicit `--base <branch>` → `defaultBaseBranch` **only
  when user-set** (a value distinct from the schema default, tracked by a "user-set" predicate, not merely
  present) → otherwise the branch captured from HEAD at workflow entry. The resolved base MUST be persisted at
  entry, before any feature branch/worktree is created.
- **R6** The persisted resolved base MUST drive both (a) the ref feature branches/worktrees fork from
  ("trunk base") and (b) the terminal PR target, replacing the static `defaultBaseBranch` read at terminal-PR
  time. The phase-fork parent ("integration base", `<type>/<slug>`) is a distinct role (R26).
- **R7** Workflow entry MUST guard against unsafe capture: detached HEAD, or HEAD already on a Shipwright
  `<type>/<slug>` / worktree branch, MUST be refused or require explicit `--base`, with an **actionable error**
  naming the detected condition, the current branch, and the exact recovery command.
- **R8** The hardcoded-`main` leaks MUST be wired to the resolved base under the R19 fail-closed contract:
  `scripts/check-frozen.py`, `scripts/secret-scan.py`/`secret_scan.py`, and `scripts/wave_lifecycle.py`
  (primary-checkout relocation) MUST use the resolved base, never an unconditional `origin/main` or `"main"`
  fallback that weakens enforcement.
- **R9** Operator-facing "→ main" prose in commands/skills/scripts MUST be generalized to the resolved base.

### Neutralization + dev/product boundary

- **R10** The shipped **example** config MUST NOT reference this plugin's dev harness: `verify.test` MUST be a
  neutral require-configuration sentinel, and the PR-test-plan manifest reference MUST move out of the generic
  `verify` block into a Shipwright-CI-only `ci.*` key (coordinated with PRD 016).
- **R11** Dev-only scripts (`copy-to-core.sh`, `snapshot-tree.py`, `model-routing-check.py`) MUST NOT ship in
  `dist/`; no shipped command/skill may reference an excluded script (reference audit required).
- **R12** Shipped commands/skills MUST NOT depend on files absent from a user install: the closed set of
  referenced `sw-reference` files (R20/TR8) MUST be emitted plugin-relative, or commands MUST tolerate absence
  gracefully. The `/sw-setup` schema-validation path MUST resolve to a file present in a user install
  (plugin-relative via the existing plugin-root resolver), tolerating legacy `.sw/` for one release.
- **R13** An explicit **dev-repo marker** (a sentinel file, e.g. `.shipwright-dev`, **not** a
  `workflow.config.json` field) MUST identify this repository as the plugin-dev repo, used only for template
  selection, docs, emitter/CI-generator gating, and example-neutralization — **never** to gate any security
  control (secret-scan, frozen guard, push chokepoint).
- **R14** Dogfooding MUST continue on the standard Shipwright workflow; the marker MUST NOT special-case the
  workflow engine for this repo. Dev-repo CI MUST assert the marker is present and that no shipped command
  references a dev-only script.

### Web-app config neutrality

- **R15** `worktree.scaffold`, `verifyE2e`, and review UI enrichers MUST default off/neutral and be documented
  as opt-in web-specific features.

### Panel-driven obligations

- **R19** Secret-scan and frozen-artifact checks MUST enforce a **fail-closed base contract**: resolve to a
  base OID; verify the OID exists (`git cat-file -e`) and is an ancestor of HEAD (`git merge-base
  --is-ancestor`) and is not equal to HEAD; diff `BASE..HEAD`; an empty diff, a missing/unresolvable base, or
  any git failure MUST **block** (non-zero), never pass. In CI the fallback chain is: persisted base / PR
  metadata (`GITHUB_BASE_REF`) → user-set `defaultBaseBranch` → fail-closed. An explicit `--base` is
  **trusted-operator-only**; the default secret-scan path MUST scan the full push range
  (`merge-base..HEAD`), not a narrowable single base.
- **R20** Verify-command proposals MUST come from a **fixed per-ecosystem preset table** (e.g.
  `core/sw-reference/verify-presets.json`). Node MAY map only allowlisted script keys
  (`lint|test|build|typecheck`, names matching `^[a-zA-Z0-9_-]+$`) to `npm run <key>`; it MUST NOT embed
  manifest script **values** or any arbitrary manifest string. Proposed commands containing shell
  metacharacters (`; & | \` $ ( )`) or destructive patterns MUST be rejected/flagged and never auto-written.
- **R21** Base capture MUST have a single authoritative owner at workflow entry; the resolved base **name and
  SHA** MUST be persisted to repo-level run state before worktree creation. On resume with missing/corrupt
  state, the workflow MUST halt (`needs-base-replay`) and require `--base` or a trunk re-entry — it MUST NOT
  silently re-capture from a feature HEAD. All worktrees in one run MUST share the single persisted base.
- **R22** The resolved base MUST be disclosed at workflow entry in one line, naming the source (e.g.
  `base: dev (captured from HEAD | --base | defaultBaseBranch)`).
- **R23** `/sw-setup` MUST specify the verify interaction: run detection after platform/models; present a
  `verify.*` proposal table; allow per-key edit/keep/skip; show a diff and require explicit `write`/`cancel`;
  re-running setup is the documented edit path (doctor shows current vs proposed and overwrites only on
  confirm).
- **R24** `/sw-setup` (scaffold + doctor) MUST emit a single portability self-check summarizing: verify
  configured (real vs gaps), base resolvable, `gh`/Actions availability, `sw-reference` paths present, no
  dev-harness references, web knobs off — surfaced before first `/sw-ship`.
- **R25** `/sw-setup` MUST warn when `gh` or GitHub Actions are unavailable, stating that the CI-readiness gate
  requires them (the honest ceiling, DL-7).
- **R26** The two base roles MUST be modeled distinctly: **trunk base** (captured at entry, terminal PR target)
  vs **integration base** (`<type>/<slug>` phase-fork parent). Phase worktrees fork from the persisted
  integration branch, which itself was created from the trunk base; neither re-reads live config at PR time.
- **R27** Excluding dev scripts and emitting `sw-reference` files MUST keep `dist/` parity green: the golden
  manifest / snapshot parity MUST be regenerated in the same change, and a reference-audit fixture MUST
  confirm no shipped command references an excluded script.

### Cross-cutting

- **R16** All `core/` behavior MUST propagate to `dist/cursor` and `dist/claude-code` via `python3 -m sw
  generate --all`, freshness gate passing.
- **R17** New behaviors MUST be covered by fixtures (see Testing Strategy).
- **R18** Documentation MUST be updated (getting-started, configuration, README, `sw-setup.md`, base-branch
  references) covering: project-type setup, the base-branch model + visibility, neutral defaults, the GitHub
  ceiling, and the dev/product boundary.

## Technical Requirements

- **TR1 — Detection + fixed preset table.** `scripts/detect-project-type.py` (root-only) emits matched types +
  confidence; proposals come from `core/sw-reference/verify-presets.json` (v1 presets: Node, Python, Go,
  Ansible, Make; conservative empty defaults for Ruby/JVM). Node allowlisted-key mapping only; no value
  embedding; metacharacter/destructive rejection (R1, R20).
- **TR2 — Setup verify flow.** Extend `core/commands/sw-setup.md` with the R23 interaction (table → per-key
  edit → diff → confirm/write), the `--accept-defaults` path writing `verifyGaps[]` and no derived verify
  (R2, R4), and the R24 portability self-check + R25 `gh`/Actions warning.
- **TR3 — Unconfigured-verify signal + blocking semantics.** Teach `scripts/verify-evidence.py` /
  verification-gate to apply the R3 placeholder taxonomy and emit a `verify-unconfigured` finding consumed by
  gate, doctor, `/sw-status`, `/sw-ready`; add a `verify.allowUnconfigured` boolean to the config schema and
  enforce the DL-13 hard-block under `/sw-deliver`/autonomous unless opted in (R3).
- **TR4 — Base resolver + persistence.** `scripts/resolve-base-branch.py` implements R5 precedence (with the
  user-set predicate), R7 entry guard, and R21 capture/persistence (name + SHA to repo-level deliver state,
  propagated to worktree `parentBranch` on provision). Callers consume the persisted base:
  `wave_spec_seed.py`, `wave_lifecycle.py`, `wave_terminal.py`, `wave_deliver.py`, `worktree.py`. Audit (and
  either wire or explicitly defer) the residual readers: `stabilize-merge-sync.py`, `sw-assert-worktree.py`,
  `reconcile-status.py`, `wave_preflight.py`. Distinguish trunk vs integration base (R6, R26).
- **TR5 — Fail-closed leak wiring.** Route `check-frozen.py`, `secret-scan.py`/`secret_scan.py`
  (pre-push diff), and `wave_lifecycle.py` through `resolve-base-branch.py` under the R19 contract (OID
  validation, ancestor check, empty-diff/missing-base → block, CI fallback chain, `--base` trusted-only,
  push-range default for secret scan) (R8, R19).
- **TR6 — Example neutralization + manifest relocation (PRD 016-coordinated).** Rewrite shipped example
  config (`verify.test` neutral sentinel); move the manifest reference to `ci.prTestPlanManifest`; update the
  schema, `check-gate.py`, the CI generator, and PRD 016 fixtures + dogfood config in the **same phase** so
  016's single-source invariant holds (R10).
- **TR7 — Emitter exclusion + parity.** Extend `sw/emitter_base.py` exclusions for the three dev scripts;
  regenerate `dist/` and the golden/snapshot manifest in the same change; add the reference-audit fixture
  (R11, R27).
- **TR8 — Closed sw-reference emit + `.sw/` tolerance.** Emit exactly `config.schema.json`, `layout.md`, and
  the neutral `workflow.config.example.json` (plus the already-emitted routing defaults) via
  `_copy_runtime_support`/`EMITTABLE_DIRS`; reference plugin-relative via the plugin-root resolver; fix the
  `/sw-setup` schema path; tolerate legacy `.sw/` one release (R12).
- **TR9 — Dev-repo marker.** Add the `.shipwright-dev` sentinel; wire template selection, docs, and
  emitter/CI-generator gating to it; assert in dev-repo CI; document for contributors. Marker never touches
  security controls (R13, R14).
- **TR10 — Web-config neutral defaults + docs (R15).**
- **TR11 — Emitter + docs + fixtures (R16–R18, R22, R24–R27).**

## Security & Compliance

- **Fail-closed base contract (R19/TR5) — the critical control.** Repointing secret-scan / frozen checks off
  `origin/main` MUST NOT open a bypass. The contract: resolve to a base OID; require it exists, is an ancestor
  of HEAD, and ≠ HEAD; diff `BASE..HEAD`; **empty diff, missing/unresolvable base, attacker-narrowed base, CI
  shallow clone, or any git error → block (exit non-zero), never pass**. `--base` is trusted-operator-only and
  is recorded; the default secret-scan path scans the full push range (`merge-base..HEAD`). The chosen base +
  source is logged in the verdict. Fixtures cover self-base, missing remote, shallow clone, first-commit, and
  explicit `--base=feature`.
- **Untrusted-manifest → command-execution (R20).** `verify.*` runs via `shell=True`; proposals therefore come
  from a fixed preset table, Node maps only allowlisted *key names* (never script values), metacharacters and
  destructive patterns are rejected, and `--accept-defaults` never auto-writes derived verify. Trust model:
  `verify.*` is operator-trusted only after explicit confirmation; detection is read-only until confirm.
- **Marker is advisory, never a security gate (R13).** Secret-scan, frozen guard, and the `git-push.py` push
  chokepoint MUST ignore the dev-repo marker. A user repo that accidentally contains the marker MUST NOT have
  any guardrail weakened.
- **No new secret surface.** Detection reads existing manifest filenames/contents read-only; presets, marker,
  and neutralized example carry no credentials (the neutralization MUST avoid credential-shaped placeholders
  that trip the secret scanner). `restBaseUrl` stays a localhost example.
- **Unchanged guardrails.** Memory redaction, freeze guardrails, and the bare-branch worktree guard remain;
  the worktree guard follows the resolved base.

## Testing Strategy

All fixtures extend the existing harness (`onboarding-ux`, `state`, `branch-guard`, `secret-scan`,
`emitter`/`parity`, setup suites). Concurrency/binding-style assertions are integration-style, not doc-grep.

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `setup-detect-project-type` | root markers matched (Node/Python/Go/Rust/Ruby/JVM/Make/Ansible); multi-match → disambiguation; none → empty | R1 |
| `setup-presets-fixed-table` | proposals come from `verify-presets.json`; Node maps allowlisted keys only; no value embedding | R1, R20 |
| `setup-rejects-unsafe-commands` | metacharacter/destructive proposals rejected/flagged, never auto-written | R20 |
| `setup-writes-real-verify` | confirmation writes real `verify.*`; no vacuous placeholder remains | R2 |
| `gate-flags-unconfigured-verify` | placeholder taxonomy (empty/`echo`/`:`/`true`/`exit 0`) → `verify-unconfigured` in gate + doctor + status + ready | R3, R24 |
| `setup-accept-defaults-no-write` | `--accept-defaults` records `verifyGaps[]`, writes no derived verify | R4 |
| `base-resolution-precedence` | `--base` → user-set `defaultBaseBranch` → captured HEAD; schema-default `main` does NOT block capture | R5 |
| `base-persist-name-and-sha` | base name+SHA persisted to repo-level state at entry, before worktree creation | R21 |
| `base-resume-needs-replay` | missing/corrupt state on resume halts `needs-base-replay`; no re-capture from feature HEAD | R21 |
| `base-shared-across-worktrees` | all worktrees in one run share the single persisted base | R21 |
| `base-drives-fork-and-pr` | feature branches fork from, terminal PR targets, the persisted trunk base | R6, R26 |
| `base-entry-guard-actionable` | detached/`<type>/<slug>` HEAD refused with actionable recovery copy | R7 |
| `base-disclosed-at-entry` | one-line base disclosure with source | R22 |
| `frozen-secretscan-failclosed` | OID/ancestor/≠HEAD checks; empty-diff/missing-base/shallow/`--base=feature` all block; push-range default | R8, R19 |
| `lifecycle-base-fallback` | `wave_lifecycle.py` relocates to resolved base, not `"main"` | R8 |
| `prose-base-generalized` | "→ main" operator strings render the resolved base | R9 |
| `example-config-neutral` | shipped example `verify.test` neutral; manifest under `ci.*`, not `verify`; no credential-shaped strings; PRD 016 wiring intact | R10 |
| `dist-excludes-dev-scripts` | `dist/` excludes the three dev scripts; golden/snapshot parity regenerated | R11, R27 |
| `no-shipped-ref-to-dev-scripts` | no shipped command/skill references an excluded dev script | R11, R27 |
| `swref-closed-emit-and-tolerance` | exactly schema/layout/example emitted; commands resolve plugin-relative or tolerate absent `.sw/`; setup schema path exists in a user install | R12, R8 |
| `dev-repo-marker` | sentinel present here / absent in user repo; gates nothing security-related; engine path unchanged | R13, R14 |
| `web-config-neutral-defaults` | scaffold/verifyE2e/enrichers default off/neutral; documented opt-in | R15 |
| `portability-self-check` | `/sw-setup` emits the single portability audit incl. `gh`/Actions warning | R24, R25 |
| `portability-emitter-freshness` | `dist/` regenerated and fresh | R16 |
| `portability-docs-presence` | docs cover setup, base model+visibility, neutral defaults, GitHub ceiling, boundary | R18 |

R17 is satisfied by this fixture set. Per-R traceability finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `feat/generic-repo-portability`, phases dependency-ordered. Each phase states its
  user-visible value:
  1. **Trust + verify (headline first)** — detection + fixed presets + setup write + `verify-unconfigured`
     signal + portability self-check (R1–R4, R20, R23–R25, TR1–TR3). *Value:* first contact actually runs the
     user's tests and never lies. (Brought to Phase 1 per the product finding that the headline must not wait.)
  2. **Clean install / boundary** — example neutralization + manifest relocation (PRD 016-coordinated), dist
     dev-script exclusion + parity, closed sw-reference emit + `.sw/` tolerance + setup schema path, dev-repo
     marker (R10–R14, R27, TR6–TR9). *Value:* a user install no longer references the dev harness.
  3. **Base-branch resolution + fail-closed leak fixes** — resolver + persistence + entry guard + disclosure +
     caller wiring + fail-closed secret-scan/frozen/lifecycle (R5–R9, R19, R21, R22, R26, TR4–TR5). *Value:*
     non-main trunks work without weakening security.
  4. **Web neutrality + docs + dist + fixtures** (R15–R18, TR10–TR11).
- **Live acceptance gate.** Before ship, a supervised end-to-end smoke on a **real external non-JS repo**
  (e.g. a Python or Ansible project): `/sw-setup` proposes correct verify, `/sw-verify` runs the real suite,
  workflow starts on a non-`main` branch with a visible resolved base, and `frozen-secretscan-failclosed`
  fixtures are green. Fixtures prove mechanics; the live repo proves the product.
- **Backward compatible.** A user-set `defaultBaseBranch` still works (precedence tier 2); existing user
  configs are untouched; neutralization changes only the template.
- **Migration note.** Plugin-relative schema/sw-reference resolution may require a reinstall / minimum plugin
  version; doctor detects a missing schema and prints the install command; legacy `.sw/` tolerated one release.
- **Bootstrap caution.** First delivery supervised (`doc.afterTasks: confirm`) until portability fixtures +
  the live acceptance gate are green.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Project-type detection + fixed-table presets in `/sw-setup` | Answers "run the user's tests" with least burden while staying correct and safe; fixed table (not manifest-derived) avoids an injection vector (operator + security lenses). |
| DL-2 | Base precedence `--base` → user-set `defaultBaseBranch` → captured-HEAD-at-entry (name+SHA persisted) | HEAD can't be read at PR time; capture-at-entry + persistence gives zero-config "use my branch" with a determinism override; SHA persistence survives rename/delete (operator + adversarial lenses). |
| DL-3 | Neutralize shipped artifacts AND add a sentinel dev-repo marker | Removes concrete leaks and prevents the dogfood config being mistaken for the template; sentinel (not config field) avoids a parallel dev config regime (operator + scope lenses). |
| DL-4 | Single phased PRD, **trust/verify first** then boundary then base | Product finding: the headline win (real verify) must not wait behind install cleanup (product lens). |
| DL-5 | Defer the release-branch (`dev → main`) model | Resolved base already targets non-main trunks; promotion/cherry-pick/staging is a release-please/manual concern outside the PR gate (scope lens). |
| DL-6 | Web-app config stays opt-in/neutral, not removed | Off by default already; removal would regress web users (scope lens). |
| DL-7 | CI gate stays GitHub/`gh`-based; ceiling stated as "any GitHub repo" | The gate observes CI rather than running it; arbitrary CI is a separate large surface — but the ceiling is now honest in Goals, not hidden in Non-Goals (product + feasibility lenses). |
| DL-8 | Ship PRD 018 before PRD 017 | External onboarding is blocked until verify + install neutrality land; delegation optimizes already-configured repos (product lens). |
| DL-9 | Repointing secret-scan/frozen base is governed by a fail-closed contract (R19) | Naively diffing a resolved/captured base is fail-open (empty diff, shallow clone, attacker `--base`); the contract makes "never weaker than origin/main" explicit (security + adversarial lenses). |
| DL-10 | Manifest relocates to `ci.*`, coordinated with PRD 016 (not amended) | Keeps PRD 016's single-source invariant while neutralizing the generic `verify` block (scope + coherence lenses). |
| DL-11 | Closed sw-reference emit set (schema, layout, example) | Prevents emit-surface creep from an open "all referenced files" rule (scope lens). |
| DL-12 | trunk base vs integration base modeled distinctly | Phase worktrees fork from `<type>/<slug>`, not the trunk; conflating them would mis-target forks/PRs (feasibility lens). |
| DL-13 | Unconfigured verify: non-blocking + loud in manual flows; hard-block under `/sw-deliver` + autonomous mode unless `verify.allowUnconfigured: true` | Protects automated runs from a silent vacuous pass (the trust bug) while not blocking early manual exploration; the opt-in is an explicit, schema-backed escape hatch (resolves OQ1; product vs design lenses). |

## Open Questions

None blocking. Implementation-level details (exact preset commands per ecosystem, the precise repo-level
state key for the persisted base, and the `verify.allowUnconfigured` schema placement) are finalized in
`/sw-tasks`.
