---
date: 2026-06-24
topic: pr-agent-review-provider
source_brainstorm: docs/brainstorms/2026-06-24-pr-agent-review-provider-requirements.md
frozen: true
frozen_at: 2026-06-24
---

# PRD 003: PR-Agent review provider

## Overview

Shipwright today ships one external AI review adapter (`coderabbit`). Teams that want open-source review tooling with bring-your-own-LLM vendor keys (OpenAI, Anthropic, Gemini) via [PR-Agent](https://github.com/The-PR-Agent/pr-agent) have no supported path through `/sw-setup`, the CI gate, `/sw-review`, or `/sw-stabilize`.

This PRD adds `pr-agent` as a second **opt-in** `review.provider` (additive to frozen [PRD 002](002-first-run-onboarding-ux/002-prd-first-run-onboarding-ux.md), which keeps the safe default `review.provider: none`). The integration follows the existing review-adapter contract (`providers/review/<id>.sh` for deterministic gate computation; `providers/review/<id>.md` for agent-mediated flows). Setup gathers LLM vendor preferences, scaffolds a GitHub Actions workflow, and provisions secrets when `gh` allows. **v1 external review is GitHub Action only** — PR-Agent runs on PR events; `/sw-review` phase 2 is skipped (DL-13).

**Dependency:** Land after PRD 002 defaults (`review.provider: none`) are in place. PRD 003 does not change the out-of-box default.

**Input:** [docs/brainstorms/2026-06-24-pr-agent-review-provider-requirements.md](../../brainstorms/2026-06-24-pr-agent-review-provider-requirements.md) (Full tier).

## Goals

1. **Adapter contract parity** — PR-Agent users get gate per-head barrier and stabilize inline findings harvest via the same adapter seams as CodeRabbit (non-inline harvest best-effort per R27).
2. **Guided onboarding** — `/sw-setup` configures `review.provider: pr-agent`, scaffolds `.github/workflows/pr-agent.yml`, and walks users through LLM vendor + secrets setup.
3. **Contract compliance** — `pr-agent.sh` emits normalized JSON per `providers/review/CAPABILITIES.md`; gate fixtures prove landed, in-flight, and unconfigured states.
4. **Zero regression** — Out-of-box default stays `review.provider: none` per PRD 002; existing repos and gate fixtures stay green.
5. **Credential hygiene** — LLM API keys live in GitHub secrets only for v1 Action path; never in `workflow.config.json` or committed workflow literals.
6. **Outcome signal** — A repo that opts into `pr-agent` via `/sw-setup` reaches first `landed` gate state within 30 minutes when secrets and workflow are correctly configured (dogfood metric).

## Non-Goals

- Changing the out-of-box `review.provider` default (remains `none` per PRD 002).
- PR-Agent deployment on GitLab, Bitbucket, Azure DevOps, or Gitea.
- v1 self-hosted PR-Agent servers, custom LLM base URLs, and self-hosted-runner-only deployments (GitHub Action + cloud LLM vendors only).
- `/sw-setup` workflow scaffolding for providers other than `pr-agent` (v1 exception is PR-Agent only).
- Webhook/app installation flows (GitHub Action only in v1).
- **PR-Agent CLI in `/sw-review` phase 2** (deferred to v2 — upstream has no CodeRabbit-style uncommitted review; DL-13 option c).
- Storing credentials in config, workflow files (beyond `${{ secrets.* }}`), or Shipwright memory.
- Migrating existing CodeRabbit repos to PR-Agent.
- Changes to phase 1 local review (`review.local` / `ce-code-review`).
- In-repo `configuration.toml` scaffolding for deep PR-Agent prompt customization (deferred).
- Org-level GitHub Environments, OIDC, or `/sw-upstream` pin automation (deferred).

## Requirements

Requirements carry forward from the brainstorm (`R1`–`R24`) with PRD additions (`R25`–`R27`). Each is testable.

### Adapter contract

- **R1** `providers/review/pr-agent.sh` MUST emit normalized JSON conforming to `providers/review/CAPABILITIES.md`, including `capabilities.perHeadState: true`.
- **R2** The executable adapter MUST derive `perHeadState` for the current PR head by inspecting GitHub check runs, PR reviews, and issue comments associated with PR-Agent (stable bot/login and body-marker heuristics documented in the adapter).
- **R3** The executable adapter MUST honor `prAgent.reviewGraceMinutes` (default 15) before transitioning absent signals to `unconfigured` (non-blocking). **Exception (onboarding):** When `prAgent.onboardingComplete` is `false` (set by `/sw-setup`, cleared on first `landed` or `skipped` per-head state on any PR), absent signals after grace MUST emit `in-flight` (yellow) with reason citing missing Action output — not `unconfigured` green.
- **R4** `providers/review/pr-agent.md` MUST document that `/sw-review` phase 2 is **skipped** when `review.provider` is `pr-agent` (v1), with a clear message that external review runs via GitHub Action on PR push. Phase 1 local review (`review.local`) is unchanged.
- **R5** The markdown adapter MUST document **inline** findings harvest for `/sw-stabilize`: paginate GraphQL `reviewThreads`; filter bot-authored unresolved threads; normalize to `inlineThreads[]` per `CAPABILITIES.md`. **Required for v1.**
- **R27** The markdown adapter SHOULD document **non-inline** harvest from PR-Agent summary/issue comments, normalized to `nonInline[]` per `CAPABILITIES.md`. **Best-effort for v1** until implementation spike confirms section headers; stabilize MUST NOT fail when non-inline parse returns empty.

### Configuration schema

- **R6** `workflow.config.json` MUST accept `review.provider: "pr-agent"` and resolve adapters at `providers/review/pr-agent.{sh,md}`.
- **R7** A `prAgent` config block MUST be added to `.sw/config.schema.json` (mirrored in `core/sw-reference/config.schema.json`) with at minimum: `reviewGraceMinutes` (integer, default 15), `llmVendor` (string enum: `openai` \| `anthropic` \| `gemini`), `model` (optional string), `actionRef` (string matching semver tag pattern `^v\d+\.\d+\.\d+$`), and `onboardingComplete` (boolean, default `false`; set `true` after first successful `landed` or `skipped` per-head state). Secrets MUST NOT be schema properties.
- **R8** `check-gate.py` MUST read grace minutes from `prAgent.reviewGraceMinutes` when `review.provider` is `pr-agent`.
- **R9** `workflow.config.example.json` MUST include an example showing `review.provider: "pr-agent"` and a sample `prAgent` block.

### `/sw-setup` behavior

- **R10** `/sw-setup` review-provider step MUST offer `none` (default per PRD 002), `coderabbit`, and `pr-agent`. Deprecated `review.enabled: false` is normalized to `none` in doctor mode — not a separate setup choice.
- **R11** When `pr-agent` is selected, setup MUST prompt for LLM vendor and optional model, writing non-secret preferences to the `prAgent` config block. Setup MUST surface a one-line notice that the user pays their LLM provider per review and that code diffs are sent to the selected vendor.
- **R12** When `pr-agent` is selected, setup MUST scaffold `.github/workflows/pr-agent.yml` from a Shipwright-maintained template, using `the-pr-agent/pr-agent@<actionRef>` wired to the selected LLM vendor env vars.
- **R13** Setup MUST attempt hybrid secrets provisioning: if `gh auth status` indicates sufficient scope, offer `gh secret set` for required keys; otherwise print manual secret-setup instructions.
- **R14** Setup MUST NOT write API keys or tokens into `workflow.config.json`, committed workflow files (except `${{ secrets.* }}` references), or Shipwright memory.
- **R15** Doctor mode MUST validate: presence of the scaffolded workflow file when provider is `pr-agent`; GitHub secrets presence via `gh secret list` (names only, when `gh` scoped); existing placeholder `verify.*` doctor behavior unchanged. Doctor MUST NOT require `pr-agent` CLI on `PATH` in v1.

### `/sw-review` phase 2

- **R16** When `review.provider` is `pr-agent`, `/sw-review` MUST skip phase 2 after phase 1 (if any) with message: `External review skipped — PR-Agent runs via GitHub Action on PR; open a PR and push to trigger review.` It MUST NOT invoke the PR-Agent CLI.
- **R17** When phase 2 is skipped for `pr-agent`, `/sw-review` MUST NOT write `sw-review.status.json` (same as when review is disabled — verification-gate treats review evidence as absent for phase 2).
- **R18** When `review.provider` is `none` or `review.enabled` is `false`, `/sw-review` MUST NOT invoke PR-Agent.

### Gate, stabilize, and documentation

- **R19** `check-gate.py` MUST invoke `providers/review/pr-agent.sh` when `review.provider` is `pr-agent` (same dynamic adapter resolution as other providers).
- **R20** Gate fixtures MUST include PR-Agent per-head state cases (landed, in-flight, unconfigured) under `scripts/test/fixtures/`.
- **R21** `PROVENANCE.md` MUST list PR-Agent under runtime dependencies with adapter paths and upstream docs link.
- **R22** `README.md` MUST mention `pr-agent` as a selectable `review.provider` value.
- **R23** `core/commands/sw-setup.md` MUST document workflow scaffolding for PR-Agent and qualify the "does not scaffold CI" non-goal with this exception.

### Distribution

- **R24** Plugin artifacts MUST land in `core/` and propagate to `dist/cursor/` and `dist/claude-code/` via the existing build/sync pipeline. Repo-root `scripts/test/` fixture and runner updates are in scope for Shipwright CI.

### PRD additions (documentation alignment)

- **R25** `core/skills/stabilize-loop/SKILL.md` and `core/skills/checks-gate/SKILL.md` MUST use provider-neutral prose ("review settled for current head") in success/wait branches while documenting that gate JSON field names (`coderabbitState`, `coderabbitLanded`) remain for backward compatibility and apply to any `review.provider`. `stabilize-loop` success predicate MUST key off `coderabbitLanded` as the provider-agnostic landed signal (not CodeRabbit-specific logic).
- **R26** A versioned workflow template MUST live at `core/templates/github/workflows/pr-agent.yml` (templated placeholders for vendor env vars and `actionRef`); setup copies/renders it — not hand-authored per repo from scratch.

## Technical Requirements

### Adapter architecture

```
workflow.config.json
  review.provider: "pr-agent"
  prAgent: { reviewGraceMinutes, llmVendor, model, actionRef, onboardingComplete }
        │
        ├─► check-gate.py ──► providers/review/pr-agent.sh ──► perHeadState JSON
        ├─► /sw-review phase 2 ──► skipped (v1; Action-only external review)
        └─► /sw-stabilize ──► providers/review/pr-agent.md ──► findings harvest
```

### `pr-agent.sh` signal heuristics (implementation guide)

The adapter mirrors `coderabbit.sh` structure. PR-Agent GitHub Action characteristics (from upstream docs):

| Signal | Source | Heuristic |
|--------|--------|-----------|
| Bot identity | Issue comments / reviews | `user.login` matching `github-actions[bot]` or PR-Agent–documented bot logins |
| In-flight | Issue comment body | Review/describe in progress markers (e.g. "Running PR Agent", tool invocation banners) |
| Landed | PR reviews + comments | Review summary posted for current head; actionable-comments sections present |
| Skipped | Issue comments | Explicit no-op / already-reviewed markers (define during implementation spike) |
| Check context | `gh pr checks` | Workflow named `PR Agent` or check name containing `pr-agent` / `pr_agent` |
| Reviewed head | GraphQL `reviews` | Last bot-authored review's `commit.oid` |

Implementation MUST document chosen markers in `pr-agent.sh` header comments and `pr-agent.md`. Spike against a live PR-Agent Action run before freezing adapter heuristics.

### `prAgent` config block (schema)

```json
"prAgent": {
  "reviewGraceMinutes": 15,
  "llmVendor": "openai",
  "model": "",
  "actionRef": "v0.30.0",
  "onboardingComplete": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `reviewGraceMinutes` | integer ≥ 0 | Grace before `unconfigured` when no PR-Agent signal |
| `llmVendor` | enum | `openai` \| `anthropic` \| `gemini` (v1) |
| `model` | string (optional) | Passed as `config.model` env in workflow when set |
| `actionRef` | string | Git ref for `the-pr-agent/pr-agent@<actionRef>` |
| `onboardingComplete` | boolean | `false` after setup until first `landed`/`skipped` on any PR; gates M5 onboarding yellow behavior |

Vendor → secret/env mapping for workflow scaffold:

| `llmVendor` | GitHub secret | Workflow env var |
|-------------|---------------|------------------|
| `openai` | `OPENAI_KEY` | `OPENAI_KEY: ${{ secrets.OPENAI_KEY }}` |
| `anthropic` | `ANTHROPIC_KEY` | `ANTHROPIC.KEY: ${{ secrets.ANTHROPIC_KEY }}` |
| `gemini` | `GEMINI_API_KEY` | `GOOGLE_AI_STUDIO.GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}` |

All variants include `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`, `github_action_config.auto_review: "true"`, and `github_action_config.pr_actions: '["opened", "reopened", "ready_for_review", "synchronize"]'` so per-head re-review runs on fix pushes.

### Workflow scaffold

Template at `core/templates/github/workflows/pr-agent.yml`:

- **Name:** `PR Agent` (workflow-level `name:` for stable `gh pr checks` heuristic).
- **Triggers:** `pull_request` types `[opened, synchronize, reopened, ready_for_review]` only (v1 — no `issue_comment` interactive tools; defer to follow-up amendment).
- **Fork policy (M4):** The LLM-backed job MUST run only on same-repo PRs: `if: github.event.pull_request.head.repo.full_name == github.event.pull_request.base.repo.full_name`. Fork PRs skip the Action (no secrets exposure). Setup MUST print a notice that external-contributor PRs will not receive automated PR-Agent review unless maintainers use a fork-safe pattern (documented in README).
- **Permissions:** `issues: write`, `pull-requests: write`, `contents: read` as default; spike may justify `contents: write` for same-repo PRs only.
- **Bot guard:** `if: ${{ github.event.sender.type != 'Bot' }}`.
- **Action:** `uses: the-pr-agent/pr-agent@${ACTION_REF}` (rendered from `prAgent.actionRef`; prefer full commit SHA in rendered workflow when spike confirms tag→SHA mapping).

Setup writes rendered file to `.github/workflows/pr-agent.yml`. If file already exists, setup MUST ask before overwrite (doctor repair path).

### `check-gate.py` grace lookup

When `review.provider` is `pr-agent`, read `prAgent.reviewGraceMinutes`; otherwise keep existing `coderabbit.reviewGraceMinutes` path. Gate output JSON keeps `coderabbitState` / `coderabbitLanded` field names (populated from any provider's adapter); `reviewProvider` field identifies the active adapter.

### `/sw-review` phase 2 (v1 — skipped)

Per **DL-13 (option c):** PR-Agent external review is Action-mediated only in v1. `/sw-review` runs phase 1 local review when configured, then skips phase 2 with the message in R16. Users who need pre-PR PR-Agent review may run the upstream CLI manually outside Shipwright (documented as optional in `pr-agent.md` — not part of the workflow contract).

### Stabilize findings harvest

`pr-agent.md` documents per R5/R27:

1. **Inline (required):** paginate GraphQL `reviewThreads`; filter bot-authored unresolved threads.
2. **Non-inline (best-effort):** fetch `pulls/<n>/reviews` and `issues/<n>/comments`; parse PR-Agent summary bodies when OQ5 headers are known. Empty non-inline parse is valid — stabilize proceeds on inline + gate only.

### Files touched (implementation checklist)

| Area | Paths |
|------|-------|
| Adapters | `core/providers/review/pr-agent.sh`, `pr-agent.md` |
| Schema | `core/sw-reference/config.schema.json`, `.sw/config.schema.json` |
| Example config | `core/sw-reference/workflow.config.example.json`, `.sw/workflow.config.example.json` |
| Setup | `core/commands/sw-setup.md` |
| Review | `core/commands/sw-review.md` |
| Gate | `core/scripts/check-gate.py` (grace lookup only if not already generic) |
| Stabilize docs | `core/commands/sw-stabilize.md` (provider-neutral harvest note) |
| Skills | `core/skills/stabilize-loop/SKILL.md`, `core/skills/checks-gate/SKILL.md` |
| Template | `core/templates/github/workflows/pr-agent.yml` |
| Tests | `scripts/test/fixtures/pr-agent-*.json`, `scripts/test/run-gate-fixtures.sh` |
| Docs | `PROVENANCE.md`, `README.md` |
| Dist | sync to `dist/cursor/`, `dist/claude-code/` |

## Security & Compliance

- **Secret handling:** Setup may call `gh secret set` only after explicit user confirmation. Never echo secret values to stdout/logs. Hybrid fallback prints secret *names* and GitHub UI path only.
- **Fork PR policy:** Same-repo guard on workflow job (see Workflow scaffold). Setup documents that fork PRs skip automated review. Prohibit `pull_request_target` unless separately threat-modeled.
- **Onboarding gate (M5):** `prAgent.onboardingComplete` + R3 exception — repos that chose `pr-agent` but never see Action output stay yellow until first `landed`/`skipped`.
- **Memory redaction:** Setup and review flows route durable writes through `scripts/memory-redact.py`; no raw PR-Agent output dumps to memory.
- **Third-party data flow:** PR-Agent sends code diffs to the selected LLM vendor. Setup MUST surface a one-line data-privacy notice linking to [PR-Agent data privacy docs](https://docs.pr-agent.ai/) during vendor selection.
- **Supply chain:** `actionRef` pins a semver tag — not `@main` — to reduce Action supply-chain drift. Doctor may warn when pin is behind latest release.

## Testing Strategy

### Gate fixtures

Extend `scripts/test/run-gate-fixtures.sh` with PR-Agent cases using existing `gh-stub.sh` fixture pattern:

| Fixture | Expected `perHeadState` | Expected verdict |
|---------|-------------------------|------------------|
| `pr-agent-landed` | `landed` | green (when checks clean) |
| `pr-agent-in-flight` | `in-flight` | yellow |
| `pr-agent-unconfigured` | `unconfigured` | green (past grace, non-blocking) |
| `pr-agent-skipped` | `skipped` | green (when checks clean) |

Temporarily set `review.provider: pr-agent` in test config (same pattern as `nocap-stub` case). Stub injects PR-Agent check names and comment bodies via `checks-pr-agent-*.json` / `comments-pr-agent-*.json` fixture naming. Phase 1 adapter merge is gated on live Action spike artifacts (DL-11) before fixtures freeze markers.

### Adapter unit tests

- `pr-agent.sh` stdout validates against JSON shape expected by `check-gate.py` (jq field presence).
- Grace window: `SW_GATE_NOW` + head timestamp fixtures prove `in-flight` → `unconfigured` transition.

### Regression

- Existing CodeRabbit fixtures (`green`, `yellow-pending`, `unconfigured`, `review-disabled`) remain green.
- `nocap-stub` never-green case unchanged.

### Manual smoke (post-implementation)

1. `/sw-setup` → select `pr-agent` → OpenAI → confirm workflow + config written.
2. Open PR → Action runs → `check-gate.py` reports `landed` after review comment.
3. Local changes → `/sw-review` skips phase 2 with pr-agent message; phase 1 local review still runs when enabled.
4. `/sw-stabilize` harvests at least one inline PR-Agent finding on a seeded PR.

## Rollout Plan

### Phase 1 — Adapters + schema (no setup yet)

- Land `pr-agent.sh` / `pr-agent.md` with fixture-driven heuristics.
- Add `prAgent` schema block and gate grace lookup.
- Gate fixtures green in CI.

### Phase 2 — Setup + workflow template

- Add `core/templates/github/workflows/pr-agent.yml`.
- Extend `/sw-setup` with provider choice, vendor prompts, hybrid secrets, workflow render.
- Doctor checks for workflow + GitHub secrets (not CLI).

### Phase 3 — Command docs + stabilize parity

- Update `/sw-review`, `/sw-stabilize`, stabilize-loop, checks-gate skills for provider-neutral language.
- PROVENANCE + README.

### Phase 4 — Dist sync + dogfood

- Run build/sync pipeline.
- Dogfood on Shipwright repo with `review.provider: pr-agent` on a test branch (optional; does not change repo default).

**Rollout safety:** Feature is opt-in at setup. No migration required. Out-of-box default remains `review.provider: none` per PRD 002.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | GitHub Action only in v1 | External review via Action on PR; `/sw-review` phase 2 deferred (DL-13). Phase 1 local review unchanged. |
| DL-2 | Setup scaffolds `.github/workflows/pr-agent.yml` | PR-Agent's primary path is Actions; reduces misconfiguration. Expands `/sw-setup` CI scope with explicit PR-Agent exception (R23). |
| DL-3 | Multi-vendor LLM (`openai`, `anthropic`, `gemini` v1) | Upstream supports multiple backends; OpenAI-only too narrow. |
| DL-4 | Hybrid `gh secret set` / manual fallback | Best UX when `gh` authenticated; no hard-fail otherwise. |
| DL-5 | Stabilize: inline required, non-inline best-effort | R5 split per doc-review M3; OQ5 no longer blocks v1 ship for inline harvest. |
| DL-6 | Default stays `none` (PRD 002) | PRD 003 is opt-in only; sequences after PRD 002; no default regression. |
| DL-7 | Pin Action via `prAgent.actionRef` semver tag | Resolves OQ1; avoids `@main` supply-chain risk. Default pin set at implementation to latest stable release at ship time. |
| DL-8 | No CLI doctor requirement in v1 | DL-13 option c: Action-only; no pip install path in setup/doctor. |
| DL-9 | Keep `coderabbitState` JSON field names in gate output | Resolves naming drift concern; `reviewProvider` already identifies adapter. R25 documents provider-neutral skill prose. |
| DL-10 | Workflow template in `core/templates/` | R26; single source for setup render; vendor placeholders substituted at scaffold time. |
| DL-11 | Bot heuristic spike before merge | Resolves OQ2 method: inspect live Action output; document markers in adapter header. Phase 1 merge gated on spike artifacts. |
| DL-12 | Amend PRD 002 non-goals at implementation | **Confirmed (product sign-off).** PRD 002 amendment required before shipping 003. |
| DL-13 | Skip `/sw-review` phase 2 in v1 (option c) | Upstream has no uncommitted-delta CLI parity with CodeRabbit; Action is authoritative for gate/stabilize. CLI integration deferred to v2 amendment. |
| DL-14 | Fork PR same-repo workflow guard | Doc-review M4: skip LLM job on fork PRs; setup notice. |
| DL-15 | Onboarding yellow until first landed | Doc-review M5: `onboardingComplete` + R3 exception. |
| DL-16 | Three LLM vendors in v1 | Doc-review M6 confirmed: `openai`, `anthropic`, `gemini`. |

## Open Questions

- none
