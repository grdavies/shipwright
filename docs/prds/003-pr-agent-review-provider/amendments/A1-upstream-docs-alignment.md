---
date: 2026-06-25
amends: docs/prds/003-pr-agent-review-provider/003-prd-pr-agent-review-provider.md
frozen: true
frozen_at: 2026-06-25
---

# Amendment A1: Upstream docs alignment (issue_comment, model presets, Action pin)

## Overview

Post-freeze review against [docs.pr-agent.ai](https://docs.pr-agent.ai/) and user decisions from the PRD 003
doc-review brainstorm. Adds `issue_comment` workflow triggers, curated per-vendor model presets (option C),
explicit `auto_review` + `auto_describe` (not `auto_improve`), and reaffirms semver `actionRef` pinning.
Confirms v2 CLI integration waits for upstream working-tree / uncommitted review support (decision D).

Does **not** reopen `/sw-review` phase 2 or DL-13 skip behavior for v1.

## Context

The parent PRD deferred `issue_comment` triggers and optional `model` free-text to reduce v1 scope. Upstream
install/usage docs now treat interactive PR comments and `config.model` slugs as first-class. PR-Agent CLI
remains **PR-URL or clean branch-diff only** — not CodeRabbit-style uncommitted delta — so DL-13 stands; CLI
waits for upstream (decision D).

## Goals

1. **Interactive reruns** — maintainers can comment `/review`, `/describe`, etc. on same-repo PRs without a push.
2. **Predictable model defaults** — setup offers `fast` / `quality` presets per `llmVendor`, mapped to current PR-Agent model slugs.
3. **Reproducible Action** — workflow uses `the-pr-agent/pr-agent@<semver>` from `prAgent.actionRef`, never `@main`.
4. **Balanced automation** — auto review + describe on PR events; defer auto improve (noise).

## Non-Goals

- `/sw-review` phase 2 PR-Agent CLI integration (waits for upstream uncommitted review — decision D).
- `auto_improve` in the scaffolded workflow (deferred; manual `/improve` via comment if desired).
- Replacing semver `actionRef` with `@main` or floating tags.
- In-repo `.pr_agent.toml` deep scaffolding (still deferred).

## Requirements

- **R28** The workflow template at `core/templates/github/workflows/pr-agent.yml` MUST include an
  `issue_comment` trigger with types `[created, edited]` in addition to `pull_request` triggers. The LLM-backed
  job MUST retain the same-repo fork guard and bot-sender guard from the parent PRD. Setup-rendered
  `.github/workflows/pr-agent.yml` MUST document that interactive commands (`/review`, `/describe`, `/ask`, …)
  are available on same-repo PRs per [upstream usage](https://docs.pr-agent.ai/usage-guide/automations_and_usage/).

- **R29** The `prAgent` config block MUST add `modelPreset` with enum `default` | `fast` | `quality` (default
  `default`). Setup MUST prompt for preset after `llmVendor` selection. A Shipwright-maintained preset table
  (e.g. `core/providers/review/pr-agent-model-presets.json` or equivalent single source) MUST map
  `(llmVendor, modelPreset)` → `config.model` slug strings compatible with PR-Agent env config. The workflow
  template MUST render `config.model: "<slug>"` from the resolved preset. Optional `model` (string) on the
  `prAgent` block, when non-empty, MUST override the preset slug at render time. **Supersedes** parent R7
  optional `model` semantics for rendering: preset is the primary path; `model` is an advanced override only.

- **R30** The workflow template MUST set `github_action_config.auto_review: "true"` and
  `github_action_config.auto_describe: "true"`. It MUST NOT enable `github_action_config.auto_improve` in the
  default scaffold (users may enable via `.pr_agent.toml` or workflow env edit). Gate and stabilize heuristics
  MUST treat **review** output as the authoritative per-head signal; describe output MUST NOT satisfy
  `landed` alone (DL-11 spike documents comment shapes).

- **R31** `prAgent.actionRef` MUST remain a semver tag matching `^v\d+\.\d+\.\d+$` (parent DL-7 / R7). Setup and
  the rendered workflow MUST use `the-pr-agent/pr-agent@${actionRef}` — never `@main` or a floating branch ref.
  Doctor mode SHOULD warn (non-blocking) when `actionRef` is behind the latest stable GitHub release tag.
  README/setup prose MUST note that upstream quickstart examples use `@main` for convenience; Shipwright pins
  for reproducibility.

- **R32** Product documentation (`README.md`, `pr-agent.md`) MUST state that PR-Agent CLI integration in
  `/sw-review` phase 2 is **explicitly deferred** until upstream supports working-tree / uncommitted review
  acceptable for Shipwright parity (decision D). v1 optional manual CLI (`--pr_url`) MAY be mentioned as an
  escape hatch outside the workflow contract.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `pr-agent-workflow-issue-comment` | Rendered template includes `issue_comment` + `pull_request`; fork/bot guards present | R28 |
| `pr-agent-model-presets` | Preset table resolves `(vendor, preset)` → `config.model` env; override wins | R29 |
| `pr-agent-workflow-auto-flags` | Template has auto_review + auto_describe true; auto_improve absent or false | R30 |
| `pr-agent-actionref-semver` | Template uses `@v*.*.*` from actionRef; grep rejects `@main` in scaffold | R31 |
| `pr-agent-cli-defer-doc` | `pr-agent.md` / README defer phase-2 CLI per decision D | R32 |

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-17 (PRD 003 A1) | v2 CLI waits for upstream uncommitted review (D) | PR-Agent CLI is PR-URL or clean branch-diff only; LocalGitProvider rejects dirty trees. No false CodeRabbit parity. |
| DL-18 (PRD 003 A1) | Add `issue_comment` trigger in v1 | Aligns with docs.pr-agent.ai install guide; enables `/review` reruns without push on same-repo PRs. |
| DL-19 (PRD 003 A1) | Curated `modelPreset` per vendor (C) | Avoids free-text slug errors at setup; Shipwright table updated on pin bumps. `model` override for power users. |
| DL-20 (PRD 003 A1) | `auto_review` + `auto_describe`; not `auto_improve` | Review drives gate; describe enriches PR metadata; improve deferred for noise. |
| DL-21 (PRD 003 A1) | Semver `actionRef` pin (reaffirm DL-7) | Upstream docs show `@main`; Shipwright keeps reproducible pins + optional doctor staleness warning. |
| DL-22 (PRD 003 A1) | Preset slug strings live in `pr-agent-model-presets.json` | Exact model IDs churn with upstream; table is implementation-maintained data, not frozen prose. Resolved at ship time from docs.pr-agent.ai. |
| DL-23 (PRD 003 A1) | Describe output shape deferred to DL-11 spike | Gate/stabilize parsers document whether describe posts issue comment vs PR-body-only during bot-marker spike. |

## Open Questions

- none
