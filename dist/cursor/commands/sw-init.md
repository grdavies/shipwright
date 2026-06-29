---
description: Initialize and validate repo-local Shipwright config — providers, verify, guardrails, and environment doctor. Does not scaffold CI or migrate existing memories.
alwaysApply: false
---

# `/sw-init`

Take a repo from **installed** to **configured and working**. Re-runs as a **doctor** against an existing
config — validate, report, and offer targeted repair without a full rescaffold.

All configuration logic runs through **`scripts/sw-configure.sh`** (single configurator — R29). The command
orchestrates interactive choices; the script holds detection, drift checks, and draft assembly.

## Scope

**Does:** memory-provider selection, review-provider selection, project-type detection + verify configuration,
guardrail knobs, store init/validate, portability self-check, version-drift notice, write schema-valid
`.cursor/workflow.config.json`.

**Does NOT:** scaffold CI workflows, migrate Recallium memories into in-repo, auto-seed rule files, or write
global (user-level) config — repo-local only.

## Flags

- `--accept-defaults` — non-interactive: records detection + `verifyGaps[]` without writing derived verify
  (R4). Use `--write-verify` with explicit confirm to write verify commands.
- `--write-verify` — with interactive confirm (or scripted `--accept-defaults --write-verify`), writes real
  `verify.*` from fixed presets.

## Procedure

### 1. Detect mode

```bash
CONFIG=".cursor/workflow.config.json"
if [ -f "$CONFIG" ]; then
  MODE=doctor
else
  MODE=scaffold
fi
bash scripts/sw-configure.sh drift-check --config "$CONFIG"
```

When drift-check reports `stale: true`, surface: **"config may be stale; run `/sw-init` to refresh"** and offer
additive, consent-gated refresh (never auto-merge `verify.*`, user-set `defaultBaseBranch`, memory/review, or
model tiers).

### 2. Memory provider (interactive)

Offer:

| Choice | `memory.provider` | Notes |
| --- | --- | --- |
| **in-repo** (default) | `in-repo` | Zero-dependency; committed markdown store |
| recallium | `recallium` | Requires local Recallium at `memory.connection.restBaseUrl` |

For **in-repo**:

- Write `.cursor/sw-memory.provider` containing `in-repo` (per-repo marker for zero-config guardrails).
- Ensure store layout exists (empty — no auto-seed):

  ```bash
  mkdir -p .cursor/sw-memory/memories .cursor/sw-memory/rules
  ```

- Ask **commit mode**: `committed` (default, PR-reviewable) or `local` (gitignore `.cursor/sw-memory-local/`).

For **recallium**: verify reachability (`curl -fsS --max-time 3 <restBaseUrl>/health` or equivalent); warn if
unreachable but still allow save.

### 3. Review provider

Offer: `coderabbit` | `none` (default **`none`**). Canonical opt-out is `review.provider: "none"`.

Do **not** offer a separate `disabled` choice — `review.enabled: false` is deprecated (honored with a warning;
point users to `review.provider: "none"`).

### 3b. Doc→implementation boundary

Write `doc.afterTasks` (default **`confirm`**): `stop` | `confirm` | `auto`. Explain: `confirm` shows the frozen
task list and requires `proceed`/`yes` before dispatch; `auto` dispatches the implementation loop on a
worktree without a second prompt.

### 3c. Deliver autonomy (conductor)

Seed `deliver.autonomy` (default **`autonomous`** hands-off to terminal-PR gate; `supervised` adds
acknowledgement halts). Include run-level budgets:

```json
"deliver": {
  "autonomy": {
    "mode": "autonomous",
    "maxRunMinutes": 1440,
    "maxIterations": 500
  }
}
```

### 3d. Retrospective autonomy (`compound.autonomy`)

Seed `compound.autonomy` (default **`supervised`**).

### 3e. Delegation mode (Phase 1 default)

Seed:

```json
"delegation": { "mode": "bind-only" }
```

`default` mode remains gated until Phase-2 live acceptance (DL-9).

### 3f. Orchestration plan policy (PRD 022 R29)

Seed `orchestration.planPolicy` (default **`canonical`** — byte-identical to today; `proposed` is
live on `/sw-deliver` pilot when TR0 gate and opt-in guards pass). Orthogonal to `deliver.autonomy.mode` and
`deliver.phaseAckCadence`.

```json
"orchestration": { "planPolicy": "canonical" }
```

**Doctor:** surface current `orchestration.planPolicy` vs schema default (`canonical`). On re-run,
never overwrite an explicit `proposed` without user confirm — same consent gate as `verify.*` and model
tiers.

### 4. Guardrail knobs

Defaults (greenfield-friendly):

```json
"guardrails": {
  "enforceBeforeSubmit": true,
  "requireRuleClass": false
}
```

### 4b. Model tier defaults

```bash
bash scripts/detect-platform.sh
bash scripts/seed-model-config.sh --platform "$(bash scripts/detect-platform.sh)" --repair all
```

### 4c. Project-type detection + verify proposals (R1/R20/R23)

After platform/models:

```bash
bash scripts/detect-project-type.sh --propose
bash scripts/sw-configure.sh detect --propose
```

Present a **verify proposal table** (lint / typecheck / test / build). For each key: **edit** | **keep** |
**skip**. Multiple project types → disambiguation menu. Flag unsafe proposals (shell metacharacters,
destructive patterns) — never auto-write.

Show diff of proposed `verify.*` vs current config. Require explicit **`write`** or **`cancel`**. Re-running
`/sw-init` is the documented edit path (doctor shows current vs proposed; overwrites only on confirm).

Non-interactive:

```bash
bash scripts/sw-configure.sh write-draft --accept-defaults          # gaps only, no verify write
bash scripts/sw-configure.sh write-draft --accept-defaults --write-verify  # explicit verify write
```

### 5. Environment doctor

Detect and recommend (never hard-fail scaffold):

- CodeRabbit CLI on `PATH` when `review.provider` is `coderabbit`.
- CodeRabbit CLI present but `review.provider` unset → surface **migration notice** (implicit default flipped to
  `none`; set `review.provider` explicitly if review gating is desired).
- `review.enabled: false` in existing config → warn deprecated; suggest `review.provider: "none"`.
- Recallium reachable when `memory.provider` is `recallium`.
- **`orchestration.planPolicy`:** surface current value vs default (`canonical`); warn when set to
  `proposed` (fixture/adoption path — kernel envelope unchanged).
- **`verify-unconfigured`** via `bash scripts/verify-unconfigured.sh` — CTA: run `/sw-init`.
- Config drift vs schema → `bash scripts/sw-configure.sh drift-check`.
- Missing in-repo store dir → offer `mkdir -p` repair.

- **Host provider doctor** via `bash scripts/host-doctor.sh` — validates `host.provider`, configured remote, token env presence (never prints token), and rate-limit config. Warns when capability is degraded (missing token, missing remote) without blocking scaffold.
- Seed `host` config on greenfield: `provider` auto-detected, `remote: origin`, `tokenEnv` per provider (`GITHUB_TOKEN` default for GitHub). Existing GitHub repos need only `GITHUB_TOKEN` set (R33).
- **Planning store doctor** via `bash scripts/planning-doctor.sh` — validates `planning.store` backend reachability (degrade-open when `memory` is configured but no memory provider is present), sweeps orphaned `.cursor/planning-materialized/` trees, and never prints provider tokens (R27).

### 5b. Portability self-check (R24/R25)

Before first `/sw-ship`:

```bash
bash scripts/sw-configure.sh portability-check
```

Summarize: verify configured (real vs gaps), base resolvable, `gh`/Actions availability, `sw-reference` paths
present, no dev-harness refs, web knobs off. Warn when `gh` or GitHub Actions unavailable (CI-readiness gate
requires them — DL-7).

### 6. Write config

Assemble draft via configurator; validate against `.sw/config.schema.json`; stamp `configuredWith`:

```json
"configuredWith": {
  "shipwrightVersion": "<from scripts/sw-configure.sh shipwright-version>",
  "schemaVersion": "<from scripts/sw-configure.sh schema-version>"
}
```

Write `.cursor/workflow.config.json`. Merge `models` from `scripts/seed-model-config.sh` unless user opts out.
Seed `communication` from `core/sw-reference/communication-routing.defaults.json` (commands + skills + agents maps).

### 6b. Planning profile + store seeding (PRD 034 R21)

After the config file exists, seed the public-repo-aware visibility profile, default store backend, and
first-run privacy notice:

```bash
bash scripts/planning-init-seed.sh --config "$CONFIG"
```

This:

- Sets `planning.store.backend` to `in-repo-public` when unset (draft also seeds this key).
- Probes `origin` via `scripts/planning_visibility.py resolve-default-profile --write` — a **public**
  remote selects `all-private` and sets `planning.privacyAck.required: true`; private/absent remotes
  select `specs-public`.
- Copies `core/sw-reference/planning-privacy-notice.md` to
  `.cursor/hooks/state/planning-privacy-notice.md` and mirrors profile + ack into
  `.cursor/hooks/state/planning-visibility.json`.

**Doctor re-run:** `bash scripts/planning-doctor.sh` validates store reachability, degrade-opens when the
memory backend has no provider (actionable remediation, no hard-fail), sweeps orphaned materialized trees,
and references env-var names only — never token values (R27).

### 7. Report

Print summary: providers, verify status, portability self-check, drift notice, config path.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --command sw-init`.

## Guardrails

- Never auto-seed `category: rule` files (R42).
- Never write vacuous verify placeholders — real commands or explicit gaps only.
- Redaction chokepoint applies to all in-repo writes.

## Fresh-install zero-config path

A repo can commit only `.cursor/sw-memory.provider` + empty store dirs without `workflow.config.json`. Run
`/sw-init` to customize.
