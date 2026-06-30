---
date: 2026-06-25
topic: pr-agent-review-provider
prd: docs/prds/003-pr-agent-review-provider/003-prd-pr-agent-review-provider.md
frozen: true
frozen_at: 2026-06-25
---

# Task list — PRD 003 PR-Agent review provider

## Relevant Files

| Area | Canonical paths |
|------|-----------------|
| Adapters | `core/providers/review/pr-agent.sh`, `core/providers/review/pr-agent.md` |
| Contract | `core/providers/review/CAPABILITIES.md` |
| Schema | `.sw/config.schema.json`, `core/sw-reference/config.schema.json` |
| Example config | `.sw/workflow.config.example.json`, `core/sw-reference/workflow.config.example.json` |
| Gate | `core/scripts/check-gate.py` |
| Setup | `core/commands/sw-setup.md` |
| Review / stabilize | `core/commands/sw-review.md`, `core/commands/sw-stabilize.md` |
| Skills | `core/skills/stabilize-loop/SKILL.md`, `core/skills/checks-gate/SKILL.md` |
| Workflow template | `core/templates/github/workflows/pr-agent.yml` |
| Model presets | `core/providers/review/pr-agent-model-presets.json` |
| PRD 002 amendment | `docs/prds/002-first-run-onboarding-ux/amendments/A1-pr-agent-setup-exception.md` (new) |
| PRD 003 amendment | `docs/prds/003-pr-agent-review-provider/amendments/A1-upstream-docs-alignment.md` |
| Fixtures | `scripts/test/fixtures/pr-agent-*`, `scripts/test/run-gate-fixtures.sh` |
| Docs | `PROVENANCE.md`, `README.md` |
| Build chain | `python3 -m sw generate --all`, `dist/cursor/`, `dist/claude-code/` |

## Notes

- Effective spec union: parent PRD R1–R27 + amendment A1 R28–R32 (`spec-union.py`).
- **DL-11:** Bot heuristic spike against live PR-Agent Action output gates Phase 1 merge — document markers in adapter header before freezing heuristics in fixtures (includes describe vs review comment shape per A1 DL-23).
- **DL-12:** PRD 002 amendment (setup CI-scaffold exception) required before shipping 003.
- **DL-13:** v1 is Action-only; `/sw-review` phase 2 skipped — CLI deferred until upstream uncommitted review (A1 DL-17).
- **A1 DL-18–DL-21:** `issue_comment` trigger, model presets, auto review+describe (not improve), semver `actionRef` pin.
- Gate JSON keeps `coderabbitState` / `coderabbitLanded` field names (R25/DL-9); `reviewProvider` identifies adapter.
- `onboardingComplete` + R3 exception: yellow `in-flight` until first `landed`/`skipped` on any PR.

## Tasks

### 1. Adapters, schema & gate grace (L)

- [ ] 1.1 Spike PR-Agent Action bot markers (DL-11)
  - **File:** spike notes → `core/providers/review/pr-agent.sh` header comments
  - **Expected:** documented bot logins, in-flight/landed/skipped body markers, check-name heuristics from live Action run
  - **R-IDs:** R2

- [ ] 1.2 Implement `pr-agent.sh` executable adapter (R1, R2, R3, R19)
  - **File:** `core/providers/review/pr-agent.sh`
  - **Expected:** normalized JSON per `CAPABILITIES.md` with `capabilities.perHeadState: true`; derives `perHeadState` from checks/reviews/comments; honors `prAgent.reviewGraceMinutes`; R3 onboarding exception when `onboardingComplete` is false
  - **R-IDs:** R1, R2, R3, R19

- [ ] 1.3 Author `pr-agent.md` markdown adapter — review skip + stabilize harvest (R4, R5, R16, R17, R27, R32)
  - **File:** `core/providers/review/pr-agent.md`
  - **Expected:** phase-2 skip message documented; CLI deferred until upstream uncommitted review (DL-17); optional manual `--pr_url` escape hatch; inline GraphQL `reviewThreads` harvest (required); non-inline summary harvest (best-effort)
  - **R-IDs:** R4, R5, R16, R17, R27, R32

- [ ] 1.4 Add `prAgent` config block to schema (R6, R7, R29)
  - **File:** `.sw/config.schema.json`, `core/sw-reference/config.schema.json`
  - **Expected:** `review.provider` accepts `pr-agent`; `prAgent` block with `reviewGraceMinutes`, `llmVendor` enum (`openai`|`anthropic`|`gemini`), `modelPreset` enum (`default`|`fast`|`quality`), optional `model` override, `actionRef` semver pattern, `onboardingComplete`; no secret properties
  - **R-IDs:** R6, R7, R29

- [ ] 1.5 Update example config with `pr-agent` sample block (R9)
  - **File:** `.sw/workflow.config.example.json`, `core/sw-reference/workflow.config.example.json`
  - **Expected:** commented or alternate example showing `review.provider: "pr-agent"` and sample `prAgent` block
  - **R-IDs:** R9

- [ ] 1.6 Gate grace lookup for `pr-agent` provider (R8)
  - **File:** `core/scripts/check-gate.py`
  - **Expected:** reads `prAgent.reviewGraceMinutes` when `review.provider` is `pr-agent`; existing `coderabbit` path unchanged
  - **R-IDs:** R8

### 2. Gate fixtures & adapter tests (M)

- [ ] 2.1 Add PR-Agent gate fixtures (R20)
  - **File:** `scripts/test/fixtures/pr-agent-landed.json`, `pr-agent-in-flight.json`, `pr-agent-unconfigured.json`, `pr-agent-skipped.json`, stub comment/check fixtures; `scripts/test/run-gate-fixtures.sh`
  - **Expected:** fixtures assert `perHeadState` landed/in-flight/unconfigured/skipped; wired into `verify.test`; regression cases (`green`, `yellow-pending`, `unconfigured`, `nocap-stub`) remain green
  - **R-IDs:** R20

- [ ] 2.2 Grace window + onboarding fixture cases (R3)
  - **File:** `scripts/test/fixtures/pr-agent-onboarding-inflight.json`, grace-transition fixtures
  - **Expected:** `SW_GATE_NOW` + head timestamp prove `in-flight` → `unconfigured`; `onboardingComplete: false` stays yellow past grace
  - **R-IDs:** R3

- [ ] 2.3 Adapter JSON shape validation (R1)
  - **File:** `scripts/test/run-gate-fixtures.sh` or dedicated adapter fixture
  - **Expected:** `pr-agent.sh` stdout has required jq fields expected by `check-gate.py`
  - **R-IDs:** R1

### 3. Workflow template & `/sw-setup` (L)

- [ ] 3.1 PRD 002 amendment — setup CI-scaffold exception (DL-12, R23)
  - **File:** `docs/prds/002-first-run-onboarding-ux/amendments/A1-pr-agent-setup-exception.md`
  - **Expected:** frozen amendment qualifying PRD 002 non-goal "does not scaffold CI" with PR-Agent exception; freeze via `/sw-freeze`
  - **R-IDs:** R23

- [ ] 3.2 Author workflow template (R26, R28, R30, R31)
  - **File:** `core/templates/github/workflows/pr-agent.yml`
  - **Expected:** workflow name `PR Agent`; `pull_request` + `issue_comment` triggers; same-repo fork guard; bot guard; vendor env placeholders; `the-pr-agent/pr-agent@${ACTION_REF}` semver only (never `@main`); `GITHUB_TOKEN` + `auto_review` + `auto_describe` true; `auto_improve` absent/false; `config.model` from preset render
  - **R-IDs:** R26, R28, R30, R31

- [ ] 3.3 Extend `/sw-setup` review-provider step (R10, R11, R12, R13, R14, R29)
  - **File:** `core/commands/sw-setup.md` (+ setup implementation wiring)
  - **Expected:** offers `none`/`coderabbit`/`pr-agent`; vendor + `modelPreset` prompts; renders workflow from template + preset table; hybrid `gh secret set` / manual fallback; data-privacy notice; no secrets in config/memory
  - **R-IDs:** R10, R11, R12, R13, R14, R29

- [ ] 3.4 Doctor mode checks for `pr-agent` (R15, R31)
  - **File:** `core/commands/sw-setup.md` (doctor section)
  - **Expected:** validates scaffolded workflow presence; `gh secret list` names when scoped; non-blocking warning when `actionRef` behind latest release; no CLI-on-PATH requirement; existing `verify.*` doctor unchanged
  - **R-IDs:** R15, R31

- [ ] 3.5 Setup onboarding fixtures (R10–R15)
  - **File:** `scripts/test/fixtures/onboarding-ux/` or new `pr-agent-setup-*` fixtures
  - **Expected:** provider choice, workflow render, secret-name-only output, no credential leak in config
  - **R-IDs:** R10, R11, R12, R13, R14, R15

### 4. Command docs & provider-neutral skills (M)

- [ ] 4.1 Update `/sw-review` for `pr-agent` phase-2 skip (R4, R16, R17, R18)
  - **File:** `core/commands/sw-review.md`
  - **Expected:** skips phase 2 with R16 message; no `sw-review.status.json` for pr-agent phase 2; opt-out on `none`/`review.enabled:false` unchanged
  - **R-IDs:** R4, R16, R17, R18

- [ ] 4.2 Update `/sw-stabilize` harvest routing (R5, R27)
  - **File:** `core/commands/sw-stabilize.md`
  - **Expected:** resolves `providers/review/pr-agent.md` when provider is `pr-agent`; inline required, non-inline best-effort
  - **R-IDs:** R5, R27

- [ ] 4.3 Provider-neutral skill prose (R25)
  - **File:** `core/skills/stabilize-loop/SKILL.md`, `core/skills/checks-gate/SKILL.md`
  - **Expected:** "review settled for current head" wording; documents `coderabbitState`/`coderabbitLanded` as backward-compat field names; success predicate keys off `coderabbitLanded`
  - **R-IDs:** R25

- [ ] 4.4 Review/stabilize doc fixtures (R16, R18)
  - **File:** `scripts/test/run-code-review-fixtures.sh` or stabilize fixture extension
  - **Expected:** pr-agent provider skips phase 2; none/disabled does not invoke PR-Agent
  - **R-IDs:** R16, R18

### 5. User docs, provenance & dist sync (S)

- [ ] 5.1 Update `PROVENANCE.md` (R21)
  - **File:** `PROVENANCE.md`
  - **Expected:** PR-Agent listed under runtime dependencies with adapter paths and upstream docs link
  - **R-IDs:** R21

- [ ] 5.2 Update `README.md` (R22, R31, R32)
  - **File:** `README.md`
  - **Expected:** `pr-agent` documented as selectable `review.provider`; fork-PR notice; semver `actionRef` pin vs upstream `@main`; CLI phase-2 defer note; opt-in default unchanged (`none`)
  - **R-IDs:** R22, R31, R32

- [ ] 5.3 Regenerate dist trees (R24)
  - **File:** `dist/cursor/`, `dist/claude-code/`
  - **Expected:** `python3 -m sw generate --all` propagates all `core/` changes; parity manifests updated; emitter freshness gate green
  - **R-IDs:** R24

- [ ] 5.4 End-to-end verify gate (R1–R32)
  - **File:** `scripts/check-gate.py` (via `python3 scripts/check-gate.py` or `verify.test`)
  - **Expected:** full fixture suite green including new PR-Agent cases, A1 fixtures, and CodeRabbit regression
  - **R-IDs:** R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15, R16, R17, R18, R19, R20, R21, R22, R23, R24, R25, R26, R27, R28, R29, R30, R31, R32

### 6. Amendment A1 — upstream docs alignment (S)

- [ ] 6.1 Model preset table + render wiring (R29)
  - **File:** `core/providers/review/pr-agent-model-presets.json`, setup render path
  - **Expected:** `(llmVendor, modelPreset)` → `config.model` slug; optional `model` override wins; table documented in `pr-agent.md`
  - **R-IDs:** R29

- [ ] 6.2 Gate spike: review vs describe comment shapes (R30, DL-23)
  - **File:** `core/providers/review/pr-agent.sh` header comments, spike notes
  - **Expected:** documented whether describe posts issue comment vs PR-body-only; `landed` heuristics require review signal not describe-only
  - **R-IDs:** R30

- [ ] 6.3 Amendment A1 fixture suite (R28–R32)
  - **File:** `scripts/test/fixtures/pr-agent-workflow-*`, `scripts/test/run-gate-fixtures.sh` or dedicated runner
  - **Expected:** `pr-agent-workflow-issue-comment`, `pr-agent-model-presets`, `pr-agent-workflow-auto-flags`, `pr-agent-actionref-semver`, `pr-agent-cli-defer-doc` green
  - **R-IDs:** R28, R29, R30, R31, R32

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 1 |
| 5 | 2, 3, 4, 6 |
| 6 | 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.2, 2.3 | `run-gate-fixtures.sh` adapter JSON shape |
| R2 | 1.1, 1.2 | `pr-agent-landed` fixture bot heuristics |
| R3 | 1.2, 2.2 | `pr-agent-onboarding-inflight` grace fixture |
| R4 | 1.3, 4.1 | `sw-review` doc grep / review fixture phase-2 skip |
| R5 | 1.3, 4.2 | stabilize inline harvest doc fixture |
| R6 | 1.4 | config-schema validates `pr-agent` provider |
| R7 | 1.4 | config-schema `prAgent` block properties |
| R8 | 1.6 | gate grace lookup fixture with `pr-agent` config |
| R9 | 1.5 | example config fixture |
| R10 | 3.3, 3.5 | setup provider-choice fixture |
| R11 | 3.3, 3.5 | setup vendor prompt fixture |
| R12 | 3.2, 3.3 | workflow template render fixture |
| R13 | 3.3, 3.5 | hybrid secrets provisioning fixture |
| R14 | 3.3, 3.5 | no-secrets-in-config fixture |
| R15 | 3.4, 3.5 | doctor workflow + secrets fixture |
| R16 | 1.3, 4.1, 4.4 | review phase-2 skip fixture |
| R17 | 4.1 | no `sw-review.status.json` for pr-agent phase 2 |
| R18 | 4.1, 4.4 | review opt-out fixture (`none`/`disabled`) |
| R19 | 1.2 | `check-gate.py` invokes `pr-agent.sh` |
| R20 | 2.1 | `pr-agent-landed/in-flight/unconfigured/skipped` fixtures |
| R21 | 5.1 | PROVENANCE grep fixture |
| R22 | 5.2 | README provider mention fixture |
| R23 | 3.1, 3.3 | PRD 002 amendment + `sw-setup.md` doc fixture |
| R24 | 5.3 | emitter parity / `run-emitter-fixtures.sh` |
| R25 | 4.3 | stabilize-loop provider-neutral prose fixture |
| R26 | 3.2 | workflow template existence + placeholder render |
| R27 | 1.3, 4.2 | non-inline harvest best-effort stabilize fixture |
| R28 | 3.2, 6.3 | `pr-agent-workflow-issue-comment` fixture |
| R29 | 1.4, 3.3, 6.1, 6.3 | `pr-agent-model-presets` fixture |
| R30 | 3.2, 6.2, 6.3 | `pr-agent-workflow-auto-flags` + describe/review spike |
| R31 | 3.2, 3.4, 5.2, 6.3 | `pr-agent-actionref-semver` fixture |
| R32 | 1.3, 5.2, 6.3 | `pr-agent-cli-defer-doc` fixture |
