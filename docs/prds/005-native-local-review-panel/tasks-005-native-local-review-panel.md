---
date: 2026-06-24
topic: native-local-review-panel
prd: docs/prds/005-native-local-review-panel/005-prd-native-local-review-panel.md
frozen: true
frozen_at: 2026-06-24
---

# Task list — PRD 005 native local review panel

## Relevant Files

| Area | Canonical paths |
|------|-----------------|
| Native adapter | `core/providers/code-review/native.md` (new) |
| Contract | `core/providers/code-review/CAPABILITIES.md` |
| Review automation | `core/rules/code-review-automation.mdc` |
| Dispatch rule | `rules/sw-subagent-dispatch.mdc` |
| Commands | `core/commands/sw-review.md`, `core/commands/sw-ship.md`, `core/commands/sw-doc.md` |
| Gap-check | `core/skills/gap-check/` (or command wiring) |
| Selection / apply / resolve | `scripts/code-review-select.sh`, `scripts/code-review-apply-check.sh`, `scripts/review-local-resolve.sh` |
| Config | `.sw/config.schema.json`, `core/sw-reference/config.schema.json`, `.sw/workflow.config.example.json` |
| Naming | `rules/sw-naming.mdc` |
| User guides | `docs/guides/configuration.md`, `docs/guides/getting-started.md` |
| Memory | `scripts/memory-redact.sh`, `rules/memory-guardrails.mdc` |
| State / branch resolver | `scripts/shipwright-state.sh`, `scripts/wave.sh` (shared `<type>/<slug>` derivation, A2) |
| Fixtures | `scripts/test/fixtures/code-review-*`, `scripts/test/fixtures/doc-afterTasks-*`, `scripts/test/run-code-review-fixtures.sh`, `scripts/test/run-persona-selection-fixtures.sh`, `scripts/test/run-doc-fixtures.sh` |
| Build chain | `scripts/copy-to-core.sh`, `python3 -m sw generate --all` |
| Dist | `dist/cursor/`, `dist/claude-code/` |

## Notes

- Effective spec union: parent PRD R1–R75 + amendment A1 R76–R79 + amendment A2 R80–R83 (`spec-union.sh`).
- Deterministic fixtures invoke `code-review-select.sh`, `code-review-apply-check.sh`, and
  `review-local-resolve.sh`; doc-grep fixtures cover prompt/checklist content only.
- `ce-code-review` adapter must stay green (R3 regression); update "apply-check rejects P1" → unvalidated vs
  validated P1 (R22/R61).
- Phase-mode `/sw-deliver` dogfood exercises R67; amendment A1 wires `doc.afterTasks` → `/sw-deliver run`,
  amendment A2 seeds the frozen `docs/prds/<n>-<slug>/` commit onto `<type>/<slug>` before that dispatch.
- Personas are inline prompts in `native.md`, not separate `core/agents/` files.

## Tasks

### 1. Contract, config & deterministic scripts (L)

- [ ] 1.1 Author `native.md` adapter shell (R1, R2, R4, R47)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** normalized result contract documented; no `ce-code-review` dependency; report-and-apply boundary; canonical selection signal table stub
  - **R-IDs:** R1, R2, R4, R47

- [ ] 1.2 Update `CAPABILITIES.md` for advisory scope-fidelity + apply boundary (R5, R13, R21)
  - **File:** `core/providers/code-review/CAPABILITIES.md`
  - **Expected:** advisory local completeness signal permitted; gap-check binding ownership preserved; validated-P1 + expanded deny-list + symlink boundary documented
  - **R-IDs:** R5, R13, R21

- [ ] 1.3 Update `code-review-automation.mdc` framing (R13, R17)
  - **File:** `core/rules/code-review-automation.mdc`
  - **Expected:** advisory scope-fidelity; phase-1 default-on independent of `review.provider`
  - **R-IDs:** R13, R17

- [ ] 1.4 Pin deny-list, counting algo, fix-size bound in `native.md` (R48, R55, R60)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** path globs + content markers (diff + suggested_fix, case-insensitive); expanded key/CI/IaC classes; executable-line counter spec; numeric fix-size bound
  - **R-IDs:** R48, R55, R60

- [ ] 1.5 Pin native UI/UX checklist in `native.md` (R72, R73)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** WCAG 2.2 AA-anchored checklist; concrete `ui-ux` globs + CSS-in-JS markers + mobile globs; `review.local.ui.enrich` enum documented
  - **R-IDs:** R72, R73

- [ ] 1.6 Pin P1 validator contract in `native.md` (R49, R62)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** fresh-context validator spec (diff + neutral location only; no shared memory); same-model FP limit noted
  - **R-IDs:** R49, R62

- [ ] 1.7 Add `scripts/code-review-select.sh` (R7, R33, R47, R51, R61)
  - **File:** `scripts/code-review-select.sh`
  - **Expected:** given diff JSON/path → deterministic roster JSON; core + gated specialists per signal table
  - **R-IDs:** R7, R33, R47, R51, R61

- [ ] 1.8 Add `scripts/review-local-resolve.sh` (R14, R15, R16, R35, R61)
  - **File:** `scripts/review-local-resolve.sh`
  - **Expected:** merges schema defaults; fires phase-1 independent of `review.provider`; opt-out on `enabled:false` / `provider:none`
  - **R-IDs:** R14, R15, R16, R35, R61

- [ ] 1.9 Extend `scripts/code-review-apply-check.sh` (R19, R22, R48, R55, R56, R57, R60, R61)
  - **File:** `scripts/code-review-apply-check.sh`
  - **Expected:** `--validated` admits P1; expanded deny-list + content markers; security-control markers; symlink/`.git`/TOCTOU/write-field validation; fix-size lines/hunks
  - **R-IDs:** R19, R22, R48, R55, R56, R57, R60, R61

- [ ] 1.10 Schema + example config defaults (R3, R32, R68, R73)
  - **File:** `.sw/config.schema.json`, `core/sw-reference/config.schema.json`, `.sw/workflow.config.example.json`
  - **Expected:** `review.local.provider` default `native`; `review.local.apply` enum default `auto`; `review.local.ui.enrich` enum; populated `review.local` example block
  - **R-IDs:** R3, R32, R68, R73

- [ ] 1.11 Backpressure clause in dispatch rule (R28, R61, R65)
  - **File:** `rules/sw-subagent-dispatch.mdc`
  - **Expected:** capacity error → bounded retry (backpressure); native apply-loop vs circuit-breaker relationship reconciled
  - **R-IDs:** R28, R61, R65

- [ ] 1.12 Phase-1 contract + schema fixtures (R1–R5, R32, R33, R47, R48, R60, R61)
  - **File:** `scripts/test/fixtures/code-review-*`, `scripts/test/run-code-review-fixtures.sh`
  - **Expected:** `native-panel-selection-deterministic`, `native-resolve-default`, `native-resolve-opt-out`, `native-schema-default`, `native-line-count-algo`, deny-list per-class cases green
  - **R-IDs:** R1, R2, R3, R4, R5, R32, R33, R47, R48, R55, R60, R61

### 2. Roster, selection & calibration (M)

- [ ] 2.1 Always-on core panel prompts (R6, R27)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** `correctness`, `maintainability`, `scope-fidelity`, `testing`, `security` inline prompts; high-stakes at deep tier dispatch
  - **R-IDs:** R6, R27

- [ ] 2.2 Gated specialist prompts + signals (R7, R8, R9, R36–R42, R51, R53)
  - **File:** `core/providers/code-review/native.md`, `scripts/code-review-select.sh`
  - **Expected:** specialists fire per table; `previous-comments` excluded; `reliability` folds silent-failure; no simplifier persona; `ai-native` includes `core/` paths + untrusted-LLM trigger
  - **R-IDs:** R7, R8, R9, R36, R37, R38, R39, R40, R41, R42, R51, R53

- [ ] 2.3 Panel announce record (R10, R42)
  - **File:** `core/providers/code-review/native.md`, `core/commands/sw-review.md`
  - **Expected:** activation record lists core + gated + matched signals per specialist
  - **R-IDs:** R10, R42

- [ ] 2.4 Calibration catalog + injection fencing in every prompt (R43, R44, R58)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** review-traps embedded; diff fenced as data; deterministic gating never model-delegated
  - **R-IDs:** R43, R44, R58

- [ ] 2.5 Reviewer attestation + fail-closed empty handling (R5, R66)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** files-examined heartbeat required; unattested empty → `degraded`; core-roster spawn failure blocks pass
  - **R-IDs:** R5, R66

- [ ] 2.6 Selection + specialist + calibration fixtures (R6–R10, R33, R41, R43–R46, R51, R53, R72)
  - **File:** `scripts/test/fixtures/code-review-*`, `scripts/test/run-code-review-fixtures.sh`
  - **Expected:** `native-panel-core`, `native-panel-data-migration-gate`, `native-panel-adversarial-threshold`, `native-panel-no-previous-comments`, `native-panel-announce`, `native-calibration-traps`, `native-uiux-fires`, `native-type-design-fires`, `native-comment-accuracy-fires`, `native-ai-native-fires`, `native-reliability-silent-failure`, `native-uiux-native-only`, `native-uiux-enrich-degrade`, `native-attestation` green
  - **R-IDs:** R6, R7, R8, R9, R10, R33, R36, R37, R38, R39, R40, R41, R42, R43, R44, R45, R46, R51, R52, R53, R72

### 3. Apply rails & autonomy (L)

- [ ] 3.1 Apply-policy + severity classification wiring (R19, R20, R44, R59, R68)
  - **File:** `core/providers/code-review/native.md`, `core/commands/sw-review.md`
  - **Expected:** `apply:auto|surface|off` honored; P0 never applied; behavior-altering/security-relevant surfaces; receiving-review YAGNI check
  - **R-IDs:** R19, R20, R44, R59, R68

- [ ] 3.2 Security deny-list + security-logic apply gates (R21, R48, R55, R56)
  - **File:** `scripts/code-review-apply-check.sh`, `core/providers/code-review/native.md`
  - **Expected:** per-class path + marker fixtures; security-reviewer-touched + control-marker surface-only
  - **R-IDs:** R21, R48, R55, R56

- [ ] 3.3 Symlink / `.git` / write-field apply rails (R57)
  - **File:** `scripts/code-review-apply-check.sh`
  - **Expected:** realpath containment; no symlink component; `.git/**` denied; patch target must match validated `file`
  - **R-IDs:** R57

- [ ] 3.4 P1 validation wave dispatch (R22, R49, R62)
  - **File:** `core/providers/code-review/native.md`, `core/commands/sw-review.md`
  - **Expected:** validator subagent at deep tier; fresh context; unvalidated P1 surfaced only
  - **R-IDs:** R22, R49, R62

- [ ] 3.5 Per-fix checkpoint, dirty-tree, ordering (R23, R64)
  - **File:** `core/providers/code-review/native.md`, `core/commands/sw-review.md`
  - **Expected:** refuse dirty tree or snapshot; apply+verify per fix; line re-anchor; failed verify reverts only panel hunks
  - **R-IDs:** R23, R64

- [ ] 3.6 Circuit-breaker + phase-mode blocked status (R24, R65, R67)
  - **File:** `core/providers/code-review/native.md`, `core/commands/sw-ship.md`, `rules/sw-subagent-dispatch.mdc`
  - **Expected:** normalized failure signature + absolute attempt cap; phase-mode P1 → `blocked` not auto-applied; breaker → `blocked` not interactive escalate
  - **R-IDs:** R24, R65, R67

- [ ] 3.7 External annotation additive-only + dedup/cap (R25, R70, R71)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** `contests applied fix` annotation; no external suppression; overlapping findings deduped; specialist soft cap
  - **R-IDs:** R25, R70, R71

- [ ] 3.8 Verify scope documentation (R63)
  - **File:** `core/providers/code-review/native.md`
  - **Expected:** verify-green necessary not sufficient; auto-apply restricted to verify-validatable fix classes
  - **R-IDs:** R63

- [ ] 3.9 Apply-rails fixture suite (R19–R25, R34, R44, R57–R59, R64–R67, R68)
  - **File:** `scripts/test/fixtures/code-review-*`, `scripts/test/run-code-review-fixtures.sh`
  - **Expected:** `native-apply-policy`, `native-apply-p0-surface`, `native-apply-p2p3-happy`, `native-apply-security-surface`, `native-apply-security-logic`, `native-apply-symlink`, `native-apply-p1-validated`, `native-apply-injection`, `native-apply-dirty-tree`, `native-apply-revert-on-fail`, `native-apply-circuit-breaker`, `native-apply-fix-persists`, `native-phase-mode-p1-blocked`, `native-dedup` green; ce-code-review regression green
  - **R-IDs:** R19, R20, R21, R22, R23, R24, R25, R34, R44, R57, R58, R59, R64, R65, R66, R67, R68, R71

### 4. Gating, framing, phase-mode & run report (M)

- [ ] 4.1 Wire `review-local-resolve.sh` into commands (R14, R15, R16, R26, R35)
  - **File:** `core/commands/sw-review.md`, `core/commands/sw-ship.md`
  - **Expected:** phase-1 fires default-on incl. `review.provider:none`; additive `haltOn:[]` gate; only `review.local` opt-out
  - **R-IDs:** R14, R15, R16, R26, R35

- [ ] 4.2 Reword `sw-review.md` / `sw-ship.md` framing (R17, R18, R54)
  - **File:** `core/commands/sw-review.md`, `core/commands/sw-ship.md`
  - **Expected:** phase-1 default-on independent of phase-2; halt/surface semantics; `--fast`/`--skip-local` one-run skip announced
  - **R-IDs:** R17, R18, R54

- [ ] 4.3 Run-report contract + scope-fidelity advisory (R11, R12, R50, R69)
  - **File:** `core/providers/code-review/native.md`, `core/commands/sw-review.md`
  - **Expected:** report under `runDir` with roster, counts, human-triage block, change digest, one-shot revert; advisory labels gap-check as binding
  - **R-IDs:** R11, R12, R50, R69

- [ ] 4.4 Gap-check advisory handoff (R75)
  - **File:** `core/skills/gap-check/` (or `core/commands/sw-ship.md`)
  - **Expected:** gap-check reads run-report advisory block; does not alter binding verdict
  - **R-IDs:** R75

- [ ] 4.5 Model tiering + backpressure doc-grep (R27, R28)
  - **File:** `core/providers/code-review/native.md`, `rules/sw-subagent-dispatch.mdc`
  - **Expected:** no semantic tier in frontmatter; backpressure clause present
  - **R-IDs:** R27, R28

- [ ] 4.6 Gating + report fixtures (R11, R12, R14–R18, R26, R35, R50, R54, R67, R69, R75)
  - **File:** `scripts/test/fixtures/code-review-*`, `scripts/test/run-code-review-fixtures.sh`
  - **Expected:** `native-doc-framing`, `native-scope-fidelity-advisory`, `native-run-report`, `native-skip-local-flag` green
  - **R-IDs:** R11, R12, R14, R15, R16, R17, R18, R26, R35, R50, R54, R67, R69, R75

### 5. Memory, instrumentation, distribution & regression (M)

- [ ] 5.1 Memory redaction + artifact scrub wiring (R29, R30)
  - **File:** `core/providers/code-review/native.md`, `core/commands/sw-review.md`
  - **Expected:** finding-derived writes through `memory-redact.sh`; run report + temp dirs scrubbed post-parse
  - **R-IDs:** R29, R30

- [ ] 5.2 Phase-2 load + contested-apply instrumentation (R74)
  - **File:** `core/providers/code-review/native.md` (or run-report schema)
  - **Expected:** counts panel-touched vs untouched phase-2 findings; contested-apply rate emitted in run report
  - **R-IDs:** R74

- [ ] 5.3 Regenerate `core/` + `dist/` + wire verify.test (R31)
  - **File:** run `scripts/copy-to-core.sh`, `python3 -m sw generate --all`; `.cursor/workflow.config.json` `verify.test`
  - **Expected:** emitter/parity fixtures green; `run-code-review-fixtures.sh` appended if missing; no hand-edits under `dist/`
  - **R-IDs:** R31

- [ ] 5.4 Memory + dist fixtures (R29, R30, R31, R74)
  - **File:** `scripts/test/fixtures/code-review-*`, `scripts/test/run-code-review-fixtures.sh`
  - **Expected:** `native-memory-redaction`, `native-dist-parity` green; full `verify.test` chain green
  - **R-IDs:** R29, R30, R31, R74

### 6. `doc.afterTasks` → `/sw-deliver run` + frozen-spec seed (S) — Amendments A1 + A2

- [ ] 6.1 Update `sw-doc.md` boundary dispatch (R76, R77, R79)
  - **File:** `core/commands/sw-doc.md`
  - **Expected:** `confirm`/`auto` dispatch `/sw-deliver run <frozen-tasks>`; `stop` prints same as next command; agent `auto` records override in `shipwright-state.sh` before dispatch; never inline implementation
  - **R-IDs:** R76, R77, R79

- [ ] 6.2 Update naming rule + user guides (R78)
  - **File:** `rules/sw-naming.mdc`, `docs/guides/configuration.md`, `docs/guides/getting-started.md`
  - **Expected:** `/sw-doc` boundary prose names `/sw-deliver run` for stop/confirm/auto; no legacy chain as primary path
  - **R-IDs:** R78

- [ ] 6.3 Doc-afterTasks fixture suite (R76–R79)
  - **File:** `scripts/test/fixtures/doc-afterTasks-*`, `scripts/test/run-doc-fixtures.sh`
  - **Expected:** `doc-afterTasks-stop-deliver`, `doc-afterTasks-confirm-deliver`, `doc-afterTasks-auto-deliver`, `doc-afterTasks-guides-deliver` green; wired into `verify.test`
  - **R-IDs:** R76, R77, R78, R79

- [ ] 6.4 Seed frozen spec commit at `doc.afterTasks` boundary (R80, R81, R82)
  - **File:** `core/commands/sw-doc.md`
  - **Expected:** on `confirm`/`auto`, commit the docs-only `docs/prds/<n>-<slug>/` set (PRD + frozen tasks + amendments) onto `<type>/<slug>` idempotently **before** `/sw-deliver run`; `<type>/<slug>` derived via the same resolver `/sw-deliver` uses (no divergent re-impl; resolver extraction is a PRD 004 follow-up); `stop` stays print-only and prints the docs-only commit command + `/sw-deliver run`, naming the branch and never seeding onto `main`
  - **R-IDs:** R80, R81, R82

- [ ] 6.5 Brainstorm exclusion + seed-commit run-record (R83)
  - **File:** `core/commands/sw-doc.md`, `scripts/shipwright-state.sh`
  - **Expected:** seed commit excludes `docs/brainstorms/**` and any untracked/ignored path; agent `--after-tasks=auto` records the seed commit (branch + SHA) via `shipwright-state.sh` before dispatch (parity with R79)
  - **R-IDs:** R83

- [ ] 6.6 Seed-commit fixture suite (R80–R83)
  - **File:** `scripts/test/fixtures/doc-afterTasks-*`, `scripts/test/run-doc-fixtures.sh`
  - **Expected:** `doc-afterTasks-seed-confirm-auto`, `doc-afterTasks-seed-stop`, `doc-afterTasks-seed-branch-derivation`, `doc-afterTasks-seed-brainstorm-excluded` green; wired into `verify.test`
  - **R-IDs:** R80, R81, R82, R83

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |
| 5 | 4 |
| 6 | 1 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | native-dist-parity: native.md adapter exists and conforms to CAPABILITIES contract |
| R2 | 1.1 | native-dist-parity: native adapter has no ce-code-review dependency |
| R3 | 1.10, 1.12 | native-schema-default + ce-code-review regression fixtures green |
| R4 | 1.1 | native-apply-p2p3-happy: report-and-apply boundary documented |
| R5 | 1.2, 2.5 | native-attestation: fail-closed skipped/degraded without findings |
| R6 | 2.1, 2.6 | native-panel-core |
| R7 | 1.7, 2.2, 2.6 | native-panel-selection-deterministic |
| R8 | 2.2, 2.6 | native-panel-data-migration-gate + native-panel-adversarial-threshold |
| R9 | 2.2, 2.6 | native-panel-no-previous-comments |
| R10 | 2.3, 2.6 | native-panel-announce |
| R11 | 4.3, 4.6 | native-scope-fidelity-advisory |
| R12 | 4.3, 4.6 | native-scope-fidelity-advisory: no binding completeness verdict |
| R13 | 1.2, 1.3 | native-doc-framing: CAPABILITIES + automation rule advisory signal |
| R14 | 1.8, 4.1 | native-resolve-default: fires when review.provider is none |
| R15 | 1.8, 4.1 | native-resolve-opt-out |
| R16 | 1.8, 4.1 | native-resolve-default: absent review.local uses schema default |
| R17 | 1.3, 4.2 | native-doc-framing: sw-review.md default-on framing |
| R18 | 4.2, 4.6 | native-doc-framing: sw-ship.md in-chain + halt/surface semantics |
| R19 | 1.9, 3.1, 3.9 | native-apply-p2p3-happy |
| R20 | 3.1, 3.9 | native-apply-p0-surface |
| R21 | 1.2, 3.2, 3.9 | native-apply-security-surface |
| R22 | 1.9, 3.4, 3.9 | native-apply-p1-validated |
| R23 | 3.5, 3.9 | native-apply-revert-on-fail |
| R24 | 3.6, 3.9 | native-apply-circuit-breaker |
| R25 | 3.7, 3.9 | native-apply-fix-persists |
| R26 | 4.1 | native-doc-framing: additive haltOn empty default |
| R27 | 2.1, 4.5 | native-tiering |
| R28 | 1.11, 4.5 | native-dispatch-backpressure |
| R29 | 5.1, 5.4 | native-memory-redaction |
| R30 | 5.1, 5.4 | native-memory-redaction: run report scrubbed |
| R31 | 5.3, 5.4 | native-dist-parity |
| R32 | 1.10, 1.12 | native-schema-default |
| R33 | 1.7, 1.12, 2.6 | native-panel-selection-deterministic |
| R34 | 3.9 | apply-rails fixture suite (P0/security/P1/revert/breaker) |
| R35 | 1.8, 4.1, 4.6 | native-resolve-default + native-resolve-opt-out |
| R36 | 2.2, 2.6 | native-uiux-fires |
| R37 | 2.2, 2.6 | native-uiux-native-only |
| R38 | 2.2, 2.6 | native-type-design-fires |
| R39 | 2.2, 2.6 | native-comment-accuracy-fires |
| R40 | 2.2, 2.6 | native-ai-native-fires |
| R41 | 2.2, 2.6 | native-reliability-silent-failure |
| R42 | 2.2, 2.3 | native-panel-announce: specialist selection reasons |
| R43 | 2.4, 2.6 | native-calibration-traps |
| R44 | 2.4, 3.1 | native-apply-injection + receiving-review discipline |
| R45 | 2.6 | native-uiux-fires + type-design + comment-accuracy + ai-native fires/silent |
| R46 | 2.6 | native-uiux-native-only |
| R47 | 1.1, 1.7 | native-panel-selection-deterministic: canonical table in native.md |
| R48 | 1.4, 1.9, 3.2 | native-apply-security-surface: per-class deny-list |
| R49 | 1.6, 3.4 | native-apply-p1-validated: validation wave |
| R50 | 4.3, 4.6 | native-scope-fidelity-advisory: forwarded to gap-check |
| R51 | 1.7, 2.2 | native-panel-selection-deterministic: pinned specialist globs |
| R52 | 1.5, 2.6 | native-uiux-enrich-degrade |
| R53 | 2.2, 2.6 | native-ai-native-fires: core/ plugin paths |
| R54 | 4.2, 4.6 | native-skip-local-flag |
| R55 | 1.4, 1.9, 3.2 | native-apply-security-surface: expanded deny-list classes |
| R56 | 1.9, 3.2, 3.9 | native-apply-security-logic |
| R57 | 1.9, 3.3, 3.9 | native-apply-symlink |
| R58 | 2.4, 3.9 | native-apply-injection |
| R59 | 3.1, 3.9 | native-apply-p2p3-happy: behavior-altering surfaces |
| R60 | 1.4, 1.9, 1.12 | native-line-count-algo + native-panel-adversarial-threshold boundary |
| R61 | 1.7, 1.8, 1.9, 1.11 | deterministic script fixtures invoke select/resolve/apply-check |
| R62 | 1.6, 3.4 | native-apply-p1-validated: validator independence |
| R63 | 3.8 | native-apply-p2p3-happy: verify scope documented in native.md |
| R64 | 3.5, 3.9 | native-apply-dirty-tree + native-apply-revert-on-fail |
| R65 | 1.11, 3.6, 3.9 | native-apply-circuit-breaker |
| R66 | 2.5, 3.9 | native-attestation |
| R67 | 3.6, 3.9, 4.6 | native-phase-mode-p1-blocked |
| R68 | 1.10, 3.1, 3.9 | native-apply-policy |
| R69 | 4.3, 4.6 | native-run-report |
| R70 | 3.7, 3.9 | native-dedup |
| R71 | 3.7, 3.9 | native-apply-fix-persists: external findings not suppressed |
| R72 | 1.5, 2.6 | native-uiux-native-only: WCAG baseline checklist |
| R73 | 1.5, 1.10, 2.6 | native-uiux-fires + native-uiux-enrich-degrade |
| R74 | 5.2, 5.4 | run-report contested-apply + phase-2-load instrumentation |
| R75 | 4.4, 4.6 | native-scope-fidelity-advisory: gap-check read step |
| R76 | 6.1, 6.3 | doc-afterTasks-confirm-deliver + doc-afterTasks-auto-deliver |
| R77 | 6.1, 6.3 | doc-afterTasks-stop-deliver |
| R78 | 6.2, 6.3 | doc-afterTasks-guides-deliver |
| R79 | 6.1, 6.3 | doc-afterTasks-auto-deliver: agent override recorded |
| R80 | 6.4, 6.6 | doc-afterTasks-seed-confirm-auto |
| R81 | 6.4, 6.6 | doc-afterTasks-seed-branch-derivation |
| R82 | 6.4, 6.6 | doc-afterTasks-seed-stop |
| R83 | 6.5, 6.6 | doc-afterTasks-seed-brainstorm-excluded |
