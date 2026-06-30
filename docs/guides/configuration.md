# Configuration

Shipwright configures **per target repo** — open your project and run `/sw-init` (`/sw-setup` is a
deprecated alias with identical behavior).

## `/sw-init`

Run `/sw-init` in your **target project repo**. It walks through setup and writes
`.cursor/workflow.config.json`. Re-run at any time — it acts as a **doctor** against an existing
config, validates project-type detection, surfaces **version drift** when `configuredWith` differs from
the installed plugin, and offers consent-gated refresh without overwriting user-set verify or base branch.

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
| **confirm** (default) | `confirm` | Show frozen task list, then a dedicated **Implementation checkpoint** (heading + direct question + paused-state line); require `proceed` or `yes`; seed frozen spec onto `<type>/<slug>`; dispatch `/sw-deliver run <frozen-tasks>`. Un-acked returns re-emit the checkpoint. |
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
| `models.routing.agents` | Per reviewer/persona/native-panel agent id → semantic tier (`build`/`mid`/`deep`) |

Scaffold writes the full block from `scripts/seed-model-config.py` and
`core/sw-reference/model-routing.defaults.json`. Doctor offers add/repair without overwriting user-edited tiers
unless confirmed. See `.sw/models-tiering.md` for platform catalogs, `models.routing.agents`, and resolver usage.

**Dispatch binding (PRD 012):** before spawning reviewer/persona Tasks, resolve
`python3 scripts/resolve-model-tier.py --agent <id>` and run
`python3 scripts/reviewer-dispatch-check.py --agent <id> --parent-model <parent-concrete-id>`;
stamp the resolved concrete `model:` on the Task (do not rely on `model: inherit` from the parent session).

### Deliver autonomy (`deliver.autonomy`)

| Key | Default | Meaning |
|-----|---------|---------|
| `deliver.autonomy.mode` | `autonomous` | `autonomous` — minimal legitimate-halt set; `supervised` — adds per-phase acknowledgement halts |
| `deliver.autonomy.maxRunMinutes` | unset | Run-level wall-clock ceiling → consolidated halt |
| `deliver.autonomy.maxIterations` | `500` | In-turn `deliver-loop` hard stop |

**Legitimate halts:** terminal merge to `main`; remediation budget exhausted; merge conflict /
destructive git; `doc.afterTasks: confirm` or supervised mode; phase liveness timeout; CI/external wait
exhausted; run-level budget. Every halt emits one report with an exact resume command.

**Living-doc currency:** mechanical reconcile of the unified `docs/planning/INDEX.md` (post-cutover)
plus legacy projections `docs/prds/INDEX.md`, `COMPLETION-LOG.md`, and `GAP-BACKLOG.md` on the feature
branch; `docs-currency` gate hard-blocks terminal merge on drift. Resolve paths via `planningDir` with
legacy `prdsDir`/`tasksDir` aliases until migration cutover.

### Planning visibility (PRD 034)

Per-unit bodies carry `visibility: public|private|memory`. When a unit omits `visibility`, the repo-level
**profile** supplies the default via `scripts/planning_visibility.py` (wrapped by `scripts/visibility-resolve.py`).

| Key | Values | Meaning |
|-----|--------|---------|
| `planning.visibilityProfile` | `all-private` \| `specs-public` (default) \| `all-public` | Closed-world default profile (schema-validated). |
| `planning.privacyAck` | object | Durable acknowledgement gate when the origin remote is **public** (see below). |
| `planning.store.backend` | `in-repo-public` (default) \| `local-synced` \| `memory` | Pluggable planning-unit body backend (PRD 034 R5/R18). Pinned per deliver run at provision. |

**Public-repo-aware default (R3):** `/sw-init` probes `origin`. A **public** remote selects `all-private` and
sets `planning.privacyAck.required: true` until the operator acknowledges before the first tracked spec commit.
A private, absent, or inconclusive remote selects `specs-public`. Resolved profile + ack are written to
`.cursor/workflow.config.json` and `.cursor/hooks/state/planning-visibility.json` when seeding with `--write`.

Under `specs-public`, advisory classes (`brainstorm`, `decision`, `learnings`, `gap`) default to `private`;
spec classes (`prd`, `tasks`, `amendment`) default to `public`. Per-unit `visibility` always wins.

**Fail-closed limits (R24):** unknown or unresolved visibility tokens normalize to `private`. Regex/body
redaction at emission points is **not** semantic anonymization — use `all-private` plus `local/synced` store
for truly sensitive specs; keep codenames out of INDEX titles (opaque title) or in private/memory backends.
The memory backend routes bodies through the existing memory adapter and redaction chokepoint — it is never
labeled encrypted or anonymized.

Fixture suite: `python3 scripts/test/run_visibility_fixtures.py` (registered as `visibility-fixtures` in the PR test-plan manifest).

**Visibility-driven `.gitignore` (R13):** regenerate tracking rules from the resolver via
`python3 scripts/gitignore-generate.py --write`. The generated block is delimited by
`# BEGIN visibility-generated` / `# END visibility-generated` markers in `.gitignore`.

Fixture suite: `python3 scripts/test/run_planning_visibility_acceptance_fixtures.py` (registered as
`planning-visibility-acceptance-fixtures` — emitter parity, public-unit no-regression, doc-impact acceptance).

### Planning autonomy (PRD 035)

Posture for planning graph bookkeeping vs content decisions. PRD 033 reads this key and soft-enforces
scheduler confirm when a lower-priority unit is selected under `maintenance-only`.

| Key | Values | Meaning |
|-----|--------|---------|
| `planning.autonomy` | `maintenance-only` (default) \| `full-conductor` | Mechanical reconciler/INDEX `derived` runs without prompts; pull-in, amendments, priority changes are proposed and human-confirmed by default |
| `planning.fullConductor.confidenceThreshold` | number (default `0.85`) | Minimum edge confidence before auto-absorb under `full-conductor` |
| `planning.fullConductor.mutationBudget` | integer (default `10`) | Per-session autonomous mutation cap → legitimate halt `planning-mutation-budget` |
| `planning.fullConductor.undoWindowSeconds` | integer (default `3600`) | Reversible undo window before reconciler materializes absorption |

**`full-conductor` bounds (R8–R9):** elevates only **gap/absorption-class** decisions; never auto-absorbs
`private`/`memory` units; enqueues handoffs only (no nested `/sw-deliver`, `/sw-doc`, or orchestrator dispatch);
never weakens merge-to-`main`. See `core/skills/conductor/SKILL.md` **Bounded planning full-conductor**.

Fixture suite: `python3 scripts/test/run_planning_035_doc_impact_fixtures.py` (`doc-currency-035`, `no-regression-035`).


### Orchestration plan policy (`orchestration.planPolicy`)

| Value | Default | Meaning |
|-------|---------|---------|
| `canonical` | **yes** | Byte-identical to pre-022 behavior; hardcoded chains and plan-time waves only |
| `proposed` | no | Agent may propose phase step plans and wave batching within guideline latitude; validated by `wave.py plan validate` |

- **Kill-switch:** per-repo instant revert to canonical behavior; composes orthogonally with
  `deliver.autonomy.mode` and `deliver.phaseAckCadence`.
- **Seeding:** `/sw-init` writes `orchestration.planPolicy: canonical`; doctor surfaces current vs default
  and never overwrites an explicit `proposed` without confirm.
- **Resume:** runs honor the **recorded** `planPolicy` on persisted plans over live config; re-validated against
  the current kernel envelope on resume (fail-closed).
- **Default canonical:** nothing observable changes until you set `proposed` **and** pass the PRD-023
  pilot guards (TR0 gate, per-run acknowledgement, safe target branch). `/sw-deliver` is the live pilot;
  PRD-024 fans out to other orchestrators. Call-site map:
  `docs/prds/022-kernel-classification-and-plan-validation/call-site-map.md`.

**PRD 024 fan-out (all four orchestrators):** `/sw-deliver`, `/sw-debug`, `/sw-doc`, and `/sw-feedback`
read `orchestration.planPolicy` (default `canonical`). Enabling `proposed` on non-deliver orchestrators
remains TR0 + metric-gated (PRD 023).

| Program rule | Meaning |
| --- | --- |
| **R35** | Inconclusive R31 (insufficient N) = non-positive → program exit (no deferred fan-out) |
| **R36** | Variance probe at authoring: `canonical ≡ proposed` → **consistency-only** (manifest + selector; proposed pack deferred); `/sw-doc` **defaults consistency-only** |
| **R37** | Debug/feedback = episodic scratch; deliver/doc handoff = durable run-state |

**Fixture suites:** `python3 scripts/test/run_fanout_fixtures.py` (program gate, per-orchestrator parity,
consistency-only, halts, R21/R22/R23); `python3 scripts/test/run_dispatch_foundation_fixtures.py` (A2 parallel
preflight + command-tier binding, R38/R39).

Mechanical validation:

```bash
python3 scripts/wave.py plan validate --tier phase --phase-type ship --proposal <path|json>
python3 scripts/wave.py plan validate --tier wave --proposal <path|json> --plan .cursor/sw-deliver-plan.json
python3 scripts/wave.py plan validate --tier orchestrator --orchestrator-type debug --proposal <path|json>
```

### `/sw-cleanup` agent-driven confirm

`/sw-cleanup` defaults to dry-run. The agent presents the `wouldRemove` set and asks for explicit confirm
before running `python3 scripts/cleanup.py --confirm --yes` (or `SW_CLEANUP_CONFIRM=1`) on your behalf.
All fail-closed protections (unmerged branches, in-flight deliver, indeterminate squash, no `rm -rf`) are
unchanged — only the apply trigger moves from manual bash to agent-on-ack.

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
| `planningDir` | Canonical planning-unit tree (`docs/planning` post-cutover; legacy paths until migration `--verify`) |
| `prdsDir` | Legacy PRD directory alias (defaults to `docs/prds` until `planningDir` cutover) |
| `tasksDir` | Frozen task-list alias (defaults to `prdsDir` until cutover) |
| `decisionsDir` | Decision-record root |
| `doc.afterTasks` | After frozen tasks: `stop` \| `confirm` (default) \| `auto` |
| `communication.defaultIntensity` | Caveman chat intensity when no active command (`full` default) |
| `communication.routing.commands` | Per `sw-*` command intensity: `normal` \| `lite` \| `full` \| `ultra` \| `inherit` |
| `models.tiers` | Semantic tier → platform model ID (`cheap`, `build`, `mid`, `deep`) |
| `models.aliases` | Tier aliases (e.g. `fast` → `cheap`) |
| `models.roles` | `builder` and `reviewer` policy floors |
| `models.routing.commands` | Per `sw-*` command model tier (`inherit` for orchestrators) |
| `models.routing.skills` | Per skill directory model tier |
| `models.routing.agents` | Per reviewer/persona/native-panel agent id → semantic tier |
| `deliver.remediation.maxAttempts` | Auto-remediation budget per blocked phase before clean halt (default **2**) |
| `memory.provider` | `in-repo` (default) or `recallium` |
| `memory.sourceOfTruth` | `auto` (default), `repo`, or `memory` — authority for **decision** records only (`auto`: external provider → memory, in-repo → repo) |
| `memory.autoSync` | Stop-hook thresholds for `/sw-memory-sync` scheduling |
| `review.provider` | AI review adapter — default **`none`**; `coderabbit` opt-in |
| `verify.lint` | Command `/sw-verify` runs for linting |
| `verify.typecheck` | Command `/sw-verify` runs for type checking |
| `verify.test` | Command `/sw-verify` runs for tests (Shipwright dev repos chain fixture suites; user installs use real project tests) |
| `ci.prTestPlanManifest` | Shipwright-CI-only path to `pr-test-plan.manifest.json` (dev/plugin repos; not in shipped example) |
| `verifyE2e.enabled` | Opt-in smoke/E2E adapter — default **`false`** (web-specific) |
| `worktree.scaffold` | Opt-in local port/DB scaffold for web apps — omit for generic repos |
| `review.local.ui.enrich` | Opt-in external UI enrichment — default **`off`** |
| `coderabbit.reviewGraceMinutes` | Gate grace window before absent review = settled |
| `checks.treatNeutralAsPass` | NEUTRAL CI checks count as pass unless allowlisted |
| `checks.neutralAllowlist` | Check names that stay blocking even if neutral |
| `guardrails.enforceBeforeSubmit` | Memory guardrails run before prompts submit |
| `guardrails.requireRuleClass` | Require allowlisted rules before prompts proceed |
| `planning.autonomy` | `maintenance-only` (default) \| `full-conductor` — planning posture (PRD 035) |
| `planning.fullConductor.*` | confidence/mutation/undo knobs under `full-conductor` opt-in |
| `orchestration.planPolicy` | `canonical` (default) \| `proposed` — agent plan proposals vs hardcoded chains; kill-switch |
| `intraPhase.parallelBudget` | Max concurrent intra-phase Task workers per phase (default **2**) |
| `intraPhase.harnessLimit` | Harness-wide cap combined with `worktree.parallelCeiling` (default **8**) |

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

`/sw-init` seeds the full command map from `core/sw-reference/communication-routing.defaults.json`. Override
for the current chat with `/sw-caveman <normal|lite|full|ultra>` until the next command dispatch.

Wenyan variants are not supported in Shipwright — attach the external user skill manually if needed.

## Model tier routing

`/sw-init` seeds `models.tiers` from the detected platform catalog and the full command/skill map from
`core/sw-reference/model-routing.defaults.json`. Each `sw-*` command documents its tier in
`**Model tier:**` prose; resolve at runtime:

```bash
python3 scripts/resolve-model-tier.py --command sw-prd
python3 scripts/resolve-model-tier.py --command sw-doc --delegate sw-prd
```

Orchestrators (`sw-doc`, `sw-ship`, `sw-deliver`, `sw-retrospective`) route at `inherit` — always resolve the
delegated child command. Full policy: `.sw/models-tiering.md`.

## Capability selection (manifest + selector)

Signal-driven eligibility for skills, personas, providers, rules, and hooks is declared in per-artifact
`capability` frontmatter, aggregated into `core/sw-reference/capability-index.json`, and resolved by
`scripts/capability-select.py` over a versioned `signal_context`. Contract:
`core/sw-reference/capability-manifest.md`.

| Concept | Meaning |
| --- | --- |
| **Eligibility** | Selector output — which capabilities match the snapshotted `signal_context` |
| **Authorization** | Named trust/config gate for executables only — `check-gate.py`, `memory-preflight`, hook slots (R27) |
| **Model tier** | Orthogonal — `models.routing` + `resolve-model-tier.py`; not chosen by the selector |

**No new `workflow.config.json` keys** — existing keys (`review.provider`, `review.local.provider`,
`memory.provider`, `verify.provider`, etc.) are read into `signal_context.config` at selection time via
manifest `config_flag` triggers. Provider configuredness (absent / `none` / unconfigured) matches
`check-gate.py` / `wave_preflight` verdicts.

**Freshness:** regenerate dist after manifest edits (`python3 -m sw generate --all`); stale index fails
`scripts/test/run_emitter_fixtures.py` and pre-selection preflight.

Fixture suites: `scripts/test/run_capability_select_fixtures.py`,
`scripts/test/run_capability_lint_fixtures.py`, `scripts/test/run_migration_parity_fixtures.py`.

## Retrospective compounding (`compound.autonomy`)

`/sw-retrospective` is the consolidated post-delivery chain (`retro → compound write → memory-sync → status`).
Deprecated aliases `/sw-compound-ship` and `/sw-compound` route to it for one release.

| Mode | `compound.autonomy` | Behavior |
|------|---------------------|----------|
| **supervised** (default) | `supervised` | Preserve retro/compound approval and merge-ack prompts |
| hands-off pre-merge | `auto` | Run the pre-merge chain when the terminal PR is green without re-prompting; merge detection still gates INDEX → `complete` |

Inspect at runtime: `python3 scripts/wave.py retrospective autonomy`. Autonomy never bypasses fail-closed
memory writes or rule-class human gates.

## Zero-config fast path

A repo can work without `workflow.config.json` if you commit:

```text
.cursor/sw-memory.provider    # file containing: in-repo
.cursor/sw-memory/memories/   # empty
.cursor/sw-memory/rules/      # empty
```

The fail-closed hook engages via the marker. Run `/sw-init` when you want full config.

## Base branch

Workflow entry resolves and **persists** your trunk base (branch name + SHA) before any feature worktree
is created. Precedence: explicit `--base` → user-set `defaultBaseBranch` → captured HEAD at entry.

- **Trunk base** — terminal PR target; secret-scan and frozen checks diff against this OID.
- **Integration base** — `<type>/<slug>` parent for phase-mode deliver; distinct from trunk base.

One-line disclosure at entry names the source, e.g. `base: dev (captured from HEAD)`.
Detached HEAD or Shipwright feature-branch HEAD is refused with recovery copy — re-enter from trunk or pass `--base`.

## Dev vs product boundary

The **shipped example** config (`core/sw-reference/workflow.config.example.json`) is neutral: no dev-harness
fixture paths, no `ci.*` keys. The **Shipwright source repo** carries a `.shipwright-dev` sentinel — it gates
CI generator tooling and template selection only; **never** weakens secret-scan, frozen guard, or push hooks.

User installs receive a closed `core/sw-reference/` emit set (schema, layout, example, routing defaults,
verify presets) via the plugin bundle — not the full dev `.sw/` tree.

## GitHub / CI ceiling

The merge-readiness gate (`/sw-watch-ci`, `/sw-stabilize`) observes **GitHub Actions** via the GitHub host
adapter (`scripts/host.py` over REST). Set `host.tokenEnv` (default `GITHUB_TOKEN`) — no host CLI is required.
Repos without a token or Actions can still use local `/sw-verify`, but cannot pass the CI-readiness gate until
GitHub CI is available — `/sw-init` host doctor warns about this honestly.

## Web-specific opt-in knobs (R15)

| Knob | Default | Enable when |
|------|---------|-------------|
| `worktree.scaffold` | omitted | Local web app needs port/DB isolation per worktree |
| `verifyE2e` | `enabled: false` | Smoke/E2E routes after static verify |
| `review.local.ui.enrich` | `off` | External design enrichment beyond native WCAG checklist |

Neutral shipped example omits scaffold; dogfood repos may set scaffold explicitly.

## Optional integrations

| Integration | Config | When to enable |
|-------------|--------|----------------|
| **CodeRabbit** | `review.provider: "coderabbit"` | AI review on PRs |
| **Recallium** | `memory.provider: "recallium"` | External memory store instead of in-repo markdown |
| **Sentry** | Production signals via `/sw-feedback` or `/sw-debug` | Route production errors into the debug workstream |

Provider **credentials** come from the environment or your secret store — never commit secrets.

## PR test-plan CI enforcement (FEAT PRs)

Shipwright repos single-source the standard FEAT test-plan fixture set in
`core/sw-reference/pr-test-plan.manifest.json` (`ci.prTestPlanManifest` in config — not under `verify.*`).
Local `verify.test` runs the same set via `scripts/test/run_pr_test_plan_manifest.py`; CI runs it via
`.github/workflows/pr-test-plan-ci.yml` (regenerate with `python3 scripts/generate-pr-test-plan-ci-workflow.py`).

Each manifest entry carries **`required`** (merge-blocking) or **`advisory`** (visible in the all-checks
readiness verdict but non-blocking). `scripts/check-gate.py` loads the manifest and exposes
`requiredFailingChecks` / `advisoryFailingChecks` in gate JSON; `/sw-stabilize` remediates through the
existing gate path. The PR template references CI **job names** as the authoritative gate — not a manual
script checklist.

Fixture suite: `python3 scripts/test/run_pr_test_plan_fixtures.py` (registered in `verify.test`).


## Deliver plan-policy pilot (PRD 023)

`/sw-deliver` is the live pilot for `orchestration.planPolicy: proposed`. Default stays `canonical`.

| Guard | Meaning |
| --- | --- |
| TR0 dependency gate | `proposed` refused until PRD-022 exec-fidelity + resume fixtures pass |
| Pilot acknowledgement | Real repos require explicit per-run opt-in + integration/non-`main` target |
| Driver budgets | `runStartedAt`, `driverIterationCount`, `noProgressStreak` on shared run-state |
| Benefit metric | Numeric/enumerated `benefitMetric`; soak via `wave.py plan benefit-report` |

Fixture suite: `python3 scripts/test/run_pilot_fixtures.py` (pilot-e2e, intra-phase-*, budget-*, benefit-*).
After `core/` pilot prose changes: `python3 -m sw generate --all` + `run_emitter_fixtures.py`.

## PRD 022 fixture suites (kernel / gate / plan policy)

After editing `core/sw-reference/kernel-classification.*`, `guidelines.*`, or orchestration prose under
`core/`, regenerate dist trees before opening a PR:

```bash
python3 -m sw generate --all
python3 scripts/test/run_emitter_fixtures.py
```

| Suite | Scope |
| --- | --- |
| `run_kernel_classification_fixtures.py` | Kernel membership, ordering, completeness lint |
| `run_guidelines_floor_fixtures.py` | Guideline harness reuse + floor matrix |
| `run_plan_validate_fixtures.py` | `wave.py plan validate` gate |
| `run_plan_persist_fixtures.py` | Two-tier persist + single-writer guard |
| `run_plan_killswitch_fixtures.py` | `orchestration.planPolicy` kill-switch + resume |
| `run_plan_proposed_parity_fixtures.py` | Kernel chokepoint parity under `proposed` |

All registered in `verify.test` for Shipwright dev repos.

