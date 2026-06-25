# Configuration

Shipwright configures **per target repo** — open your project and run `/sw-setup`.

## `/sw-setup`

Run `/sw-setup` in your **target project repo**. It walks through four questions and writes
`.cursor/workflow.config.json`. Re-run at any time — it acts as a **doctor** against an existing
config, validating, reporting drift, and offering targeted repair without a full rescaffold.

### Step 1 — Memory provider

| Choice | `memory.provider` | Notes |
|--------|-------------------|-------|
| **in-repo** (default) | `in-repo` | Committed markdown store; zero external dependency |
| recallium | `recallium` | External REST store; requires a reachable `memory.connection.restBaseUrl` |

For **in-repo**, choose commit mode:
- `committed` (default) — store lives in `.cursor/sw-memory/`; PR-reviewable
- `local` — gitignored at `.cursor/sw-memory-local/`

For **recallium**: setup warns if the health check fails but still allows save.

### Step 2 — Review provider

| Choice | `review.provider` | Notes |
|--------|-------------------|-------|
| **none** (default) | `none` | Review gating off; CI can still pass without external review |
| coderabbit | `coderabbit` | AI review on PRs; install CodeRabbit CLI for local flows |

Canonical opt-out: `review.provider: "none"`. Do not use `review.enabled: false` (deprecated).

### Step 3 — Doc→implementation boundary

| Mode | `doc.afterTasks` | Behavior |
|------|-----------------|----------|
| **confirm** (default) | `confirm` | Show frozen task list; require `proceed` or `yes`; seed frozen spec onto `<type>/<slug>`; dispatch `/sw-deliver run <frozen-tasks>` |
| stop | `stop` | Halt after frozen tasks (print-only); print docs-only seed command onto `<type>/<slug>` and `/sw-deliver run <frozen-tasks>` |
| auto | `auto` | Seed frozen spec onto `<type>/<slug>` and dispatch `/sw-deliver run <frozen-tasks>` without a second prompt |

### Step 4 — Guardrails

| Setting | Default | Meaning |
|---------|---------|---------|
| `guardrails.enforceBeforeSubmit` | `true` | Memory guardrails run before prompts submit |
| `guardrails.requireRuleClass` | `false` | Set `true` in mature repos requiring allowlisted rules |

### Step 4b — Model tier defaults

Detect platform (`cursor` or `claude-code`) and seed the `models` block:

| Key | Purpose |
|-----|---------|
| `models.tiers` | Four semantic tiers → concrete dispatch IDs (`cheap`, `build`, `mid`, `deep`) |
| `models.aliases` | e.g. `fast` → `cheap` |
| `models.roles` | `builder` and `reviewer` floors (reviewer ≥ builder) |
| `models.routing` | Per `sw-*` command and skill tier; `inherit` for orchestrators |

Scaffold writes the full block from `scripts/seed-model-config.sh` and
`core/sw-reference/model-routing.defaults.json`. Doctor offers add/repair without overwriting user-edited tiers
unless confirmed. See `.sw/models-tiering.md` for platform catalogs and resolver usage.

### Deliver autonomy (`deliver.autonomy`)

| Key | Default | Meaning |
|-----|---------|---------|
| `deliver.autonomy.mode` | `autonomous` | `autonomous` — minimal legitimate-halt set; `supervised` — adds per-phase acknowledgement halts |
| `deliver.autonomy.maxRunMinutes` | unset | Run-level wall-clock ceiling → consolidated halt |
| `deliver.autonomy.maxIterations` | `500` | In-turn `deliver-loop` hard stop |

**Legitimate halts:** terminal merge to `main`; remediation budget exhausted; merge conflict /
destructive git; `doc.afterTasks: confirm` or supervised mode; phase liveness timeout; CI/external wait
exhausted; run-level budget. Every halt emits one report with an exact resume command.

**Living-doc currency:** mechanical reconcile of `docs/prds/INDEX.md`, `COMPLETION-LOG.md`, and
`GAP-BACKLOG.md` on the feature branch; `docs-currency` gate hard-blocks terminal merge on drift.

**PRD frontmatter:** Full-tier PRDs require resolvable `brainstorm:`; `/sw-freeze` verifies linkage.
Writable brainstorms may carry forward `prd:` references.

### Step 5 — Environment doctor (warnings only)

- CodeRabbit CLI on `PATH` when `review.provider` is `coderabbit`
- Recallium reachable when `memory.provider` is `recallium`
- Placeholder `verify.*` commands → recommends configuring real lint/typecheck/test commands
- Missing memory dirs → offers `mkdir -p` repair

### Step 6 — Write config

Validates against `core/sw-reference/config.schema.json`, then writes `.cursor/workflow.config.json`.

## Manual config

```bash
mkdir -p .cursor
cp core/sw-reference/workflow.config.example.json .cursor/workflow.config.json
# edit memory.project, verify.*, providers
```

## All config keys

| Key | Purpose |
|-----|---------|
| `doc.afterTasks` | After frozen tasks: `stop` \| `confirm` (default) \| `auto` |
| `communication.defaultIntensity` | Caveman chat intensity when no active command (`full` default) |
| `communication.routing.commands` | Per `sw-*` command intensity: `normal` \| `lite` \| `full` \| `ultra` \| `inherit` |
| `models.tiers` | Semantic tier → platform model ID (`cheap`, `build`, `mid`, `deep`) |
| `models.aliases` | Tier aliases (e.g. `fast` → `cheap`) |
| `models.roles` | `builder` and `reviewer` policy floors |
| `models.routing.commands` | Per `sw-*` command model tier (`inherit` for orchestrators) |
| `models.routing.skills` | Per skill directory model tier |
| `deliver.remediation.maxAttempts` | Auto-remediation budget per blocked phase before clean halt (default **2**) |
| `memory.provider` | `in-repo` (default) or `recallium` |
| `memory.autoSync` | Stop-hook thresholds for `/sw-memory-sync` scheduling |
| `review.provider` | AI review adapter — default **`none`**; `coderabbit` opt-in |
| `verify.lint` | Command `/sw-verify` runs for linting |
| `verify.typecheck` | Command `/sw-verify` runs for type checking |
| `verify.test` | Command `/sw-verify` runs for tests |
| `coderabbit.reviewGraceMinutes` | Gate grace window before absent review = settled |
| `checks.treatNeutralAsPass` | NEUTRAL CI checks count as pass unless allowlisted |
| `checks.neutralAllowlist` | Check names that stay blocking even if neutral |
| `guardrails.enforceBeforeSubmit` | Memory guardrails run before prompts submit |
| `guardrails.requireRuleClass` | Require allowlisted rules before prompts proceed |

See `core/sw-reference/config.schema.json` for the full schema.

## Communication routing (caveman intensity)

Shipwright injects bundled `core/communication/caveman-core.md` on every session start. Intensity applies to
**orchestration chat only** — artifact files (brainstorm, PRD, tasks, commits, PR bodies) always use normal
complete prose.

| Intensity | Chat style |
|-----------|------------|
| `normal` | Standard prose; caveman off (e.g. doc-review, freeze, ready) |
| `lite` | Tight professional (e.g. brainstorm, prd, tasks) |
| `full` | Classic caveman — default workhorse |
| `ultra` | Max compression (e.g. triage, verify, commit) |

`/sw-setup` seeds the full command map from `core/sw-reference/communication-routing.defaults.json`. Override
for the current chat with `/sw-caveman <normal|lite|full|ultra>` until the next command dispatch.

Wenyan variants are not supported in Shipwright — attach the external user skill manually if needed.

## Model tier routing

`/sw-setup` seeds `models.tiers` from the detected platform catalog and the full command/skill map from
`core/sw-reference/model-routing.defaults.json`. Each `sw-*` command documents its tier in
`**Model tier:**` prose; resolve at runtime:

```bash
bash scripts/resolve-model-tier.sh --command sw-prd
bash scripts/resolve-model-tier.sh --command sw-doc --delegate sw-prd
```

Orchestrators (`sw-doc`, `sw-ship`, `sw-deliver`, `sw-compound-ship`) route at `inherit` — always resolve the
delegated child command. Full policy: `.sw/models-tiering.md`.

## Zero-config fast path

A repo can work without `workflow.config.json` if you commit:

```text
.cursor/sw-memory.provider    # file containing: in-repo
.cursor/sw-memory/memories/   # empty
.cursor/sw-memory/rules/      # empty
```

The fail-closed hook engages via the marker. Run `/sw-setup` when you want full config.

## Optional integrations

| Integration | Config | When to enable |
|-------------|--------|----------------|
| **CodeRabbit** | `review.provider: "coderabbit"` | AI review on PRs |
| **Recallium** | `memory.provider: "recallium"` | External memory store instead of in-repo markdown |
| **Sentry** | Production signals via `/sw-feedback` or `/sw-debug` | Route production errors into the debug workstream |

Provider **credentials** come from the environment or your secret store — never commit secrets.
