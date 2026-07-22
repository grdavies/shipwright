---
description: Initialize and validate repo-local Shipwright config through a guided interview — scan, confirm, ask only unresolved choices — plus doctor/repair. Does not scaffold CI or migrate existing memories.
alwaysApply: false
---

# `/sw-init`

Take a repo from **installed** to **configured and working** via a guided interview, not a wall of
prompts. Re-runs as a **doctor** against an existing config — validate, report, and offer targeted repair
without a full rescaffold.

All configuration logic runs through **`scripts/sw-configure.py`** (single configurator — R29). The command
orchestrates interactive choices; the script holds detection, drift checks, and draft assembly.

## Scope

**Does:** guided scan → confirm → unresolved-choices-only interview; memory-provider selection,
review-provider selection, project-type detection + verify configuration, guardrail knobs, store
init/validate, portability self-check, version-drift notice, write schema-valid
`.cursor/workflow.config.json`; retains doctor and repair modes on re-run.

**Does NOT:** scaffold CI workflows, migrate Recallium memories into in-repo, auto-install MemPalace (or any
memory provider package), auto-install Obsidian or the Local REST API community plugin, auto-seed rule files,
or write global (user-level) config — repo-local only.

## Flags

- `--accept-defaults` — non-interactive: records detection + `verifyGaps[]` without writing derived verify
  (R4). Use `--write-verify` with explicit confirm to write verify commands.
- `--write-verify` — with interactive confirm (or scripted `--accept-defaults --write-verify`), writes real
  `verify.*` from fixed presets.

## Procedure

### 0. Guided interview (scan → confirm → unresolved only)

Before any per-key prompting, run the interview shape that keeps `/sw-init` fast on a well-detected repo and
verbose only where the operator's input actually changes the outcome:

1. **Scan** — run a read-only reconnaissance pass over the repo (language/framework signals, existing
   `.cursor/workflow.config.json`, `AGENTS.md`, CI files, remote visibility) via
   `python3 scripts/detect-project-type.py --propose` and `python3 scripts/sw-configure.py detect --propose`.
   A subagent MAY perform the scan when the repo is large; the scan is always read-only (no writes).
2. **Present findings** — summarize detected project type(s), proposed verify commands, memory/review
   provider defaults, and any existing config drift as one consolidated findings report — not a sequence of
   yes/no prompts.
3. **Confirm/correct** — the operator confirms the findings wholesale or corrects individual fields; corrected
   fields are recorded and never re-asked in the same run.
4. **Ask only unresolved choices** — every field the scan resolved with a documented default and no drift
   signal is **not** re-prompted; only genuinely unresolved choices (ambiguous project-type, no detected
   memory/review preference, first-run repo) surface as an explicit question, each with a **recommended
   default** stated up front so the operator can accept with one word.
5. **Optional project-intent and working-style capture** — after the resolved-choice interview, offer (never
   force) one short optional capture: a one-paragraph project intent (what this repo is for, who it serves)
   and a working-style note (e.g. preferred ceremony level, review posture). Skip silently on decline.
   When provided, redact via `python3 scripts/memory-redact.py` and persist to
   `.cursor/sw-context/project-intent.md` (repo-local, not the planning store) for later `/sw-brainstorm` and
   `/sw-prd` consumption — those skills read this file opportunistically when present; its absence changes
   nothing.
6. **Doctor/repair retained** — steps 1–6 below (memory, review, doc boundary, guardrails, verify, drift
   repair) are unchanged; the guided interview only changes *how* they are surfaced (findings-first,
   unresolved-only) — never what they configure.

### 1. Detect mode

```bash
CONFIG=".cursor/workflow.config.json"
if [ -f "$CONFIG" ]; then
  MODE=doctor
else
  MODE=scaffold
fi
python3 scripts/sw-configure.py drift-check --config "$CONFIG"
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
| mempalace | `mempalace` | Local palace directory + MemPalace MCP; see `docs/guides/configuration.md` **MemPalace memory provider** |
| basic-memory | `basic-memory` | Dual-mode local MCP or Basic Memory Cloud; see `docs/guides/configuration.md` **Basic Memory provider** |
| obsidian | `obsidian` | Obsidian vault + Local REST API on loopback; see `docs/guides/configuration.md` **Obsidian memory provider** |

For **in-repo**:

- Write `.cursor/sw-memory.provider` containing `in-repo` (per-repo marker for zero-config guardrails).
- Ensure store layout exists (empty — no auto-seed):

  ```bash
  mkdir -p .cursor/sw-memory/memories .cursor/sw-memory/rules
  ```

- Ask **commit mode**: `committed` (default, PR-reviewable) or `local` (gitignore `.cursor/sw-memory-local/`).

For **recallium**: verify reachability (`host HTTP transport -fsS --max-time 3 <restBaseUrl>/health` or equivalent); warn if
unreachable but still allow save.

For **mempalace**:

- **Catalog-detect only** — offer when `mempalace` is registered in `.sw/memory-provider-catalog.json`; **never
  auto-install** the package (`uv tool install 'mempalace>=3.6.0,<4.0.0'` is documented in
  `docs/guides/configuration.md`; operator runs it manually).
- Collect `memory.mempalace.palacePath` (local filesystem path; reject remote URLs) and `memory.project` (wing name).
- Seed schema defaults: `rulesRoom: "rules"`, `searchExcludeRooms: ["transcripts"]`, `failClosed: true`,
  `redactOnWrite: true`, `supportedPackage: "mempalace>=3.6.0,<4.0.0"`.
- **Doctor / validate when configured:** probe `python -c "import mempalace"` (warn with install recipe on failure);
  verify `palacePath` exists and is a directory; optional hook smoke:
  `python3 providers/mempalace-rules.py` with `SW_WORKSPACE_ROOT` set — warn on failure, do not block scaffold
  unless the operator opts into hard-fail. Link remediation to `docs/guides/configuration.md` **MemPalace memory
  provider** (hook recipes, break-glass, live-smoke checklist).

For **basic-memory**:

- **Catalog-detect only** — offer when `basic-memory` is registered in `.sw/memory-provider-catalog.json`; **never
  auto-install** the package and **never create** a Basic Memory Cloud account or workspace (`uv tool install
  'basic-memory>=0.22.0,<1.0.0'` and cloud signup are documented in `docs/guides/configuration.md`; operator
  runs them manually).
- Require explicit `memory.basicMemory.mode` (`local` | `cloud`) — no silent cross-mode defaulting beyond the
  schema default of `local` when the operator confirms local.
- **Local:** collect `memory.basicMemory.projectPath` (local filesystem path; reject remote URLs) and
  `memory.project`. Seed defaults: `memoriesDirectory: "memories"`, `rulesDirectory: "rules"`,
  `failClosed: true`, `redactOnWrite: true`, `supportedPackage: "basic-memory>=0.22.0,<1.0.0"`.
- **Cloud:** collect optional `apiBase` (default `https://cloud.basicmemory.com`), `tokenEnv` (default
  `BASIC_MEMORY_API_KEY`), and optional `workspace` / `projectId`. Confirm the token is present in the
  environment or secret store — never write the token into config.
- **Doctor / validate when configured:** for local, probe package import (warn with install recipe on failure)
  and verify `projectPath` is a directory; for cloud, verify `tokenEnv` is set (never print the value) and
  `apiBase` host is allowlisted. Optional hook smoke: `python3 providers/basic-memory-rules.py` with
  `SW_WORKSPACE_ROOT` set — warn on failure, do not block scaffold unless the operator opts into hard-fail.
  Link remediation to `docs/guides/configuration.md` **Basic Memory provider** (mode selection, SSRF,
  break-glass, live-smoke checklist).

For **obsidian**:

- **Catalog-detect only** — offer when `obsidian` is registered in `.sw/memory-provider-catalog.json`; **never
  auto-install** Obsidian, the Local REST API community plugin, or an API key (enablement + `OBSIDIAN_API_KEY`
  are documented in `docs/guides/configuration.md`; operator completes them manually).
- Collect `memory.obsidian.vaultPath` (absolute local filesystem path; reject remote URLs) and `memory.project`
  (folder name under `memoriesDirectory`).
- Seed schema defaults: `mcpBaseUrl: "http://127.0.0.1:27123"`, `tokenEnv: "OBSIDIAN_API_KEY"`,
  `memoriesDirectory: "memories"`, `rulesDirectory: "rules"`, `failClosed: true`, `redactOnWrite: true`.
- **Doctor / validate when configured:** verify `vaultPath` exists and is a directory; confirm `tokenEnv` is set
  in the environment or secret store (never print the value); optional loopback reachability probe against
  `memory.obsidian.mcpBaseUrl` (HTTP on loopback by default — warn when Obsidian is closed or the plugin is
  disabled); optional hook smoke: `python3 providers/obsidian-rules.py` with `SW_WORKSPACE_ROOT` set — warn on
  failure, do not block scaffold unless the operator opts into hard-fail. Link remediation to
  `docs/guides/configuration.md` **Obsidian memory provider** (HTTP vs HTTPS, unreachable degrade, rules folder,
  live-smoke checklist).

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
python3 scripts/detect-platform.py
python3 scripts/seed-model-config.py --platform "$(python3 scripts/detect-platform.py)" --repair all
```

### 4c. Project-type detection + verify proposals (R1/R20/R23)

After platform/models:

```bash
python3 scripts/detect-project-type.py --propose
python3 scripts/sw-configure.py detect --propose
```

Present a **verify proposal table** (lint / typecheck / test / build). For each key: **edit** | **keep** |
**skip**. Multiple project types → disambiguation menu. Flag unsafe proposals (shell metacharacters,
destructive patterns) — never auto-write.

Show diff of proposed `verify.*` vs current config. Require explicit **`write`** or **`cancel`**. Re-running
`/sw-init` is the documented edit path (doctor shows current vs proposed; overwrites only on confirm).

Non-interactive:

```bash
python3 scripts/sw-configure.py write-draft --accept-defaults          # gaps only, no verify write
python3 scripts/sw-configure.py write-draft --accept-defaults --write-verify  # explicit verify write
```

### 5. Environment doctor

Detect and recommend (never hard-fail scaffold):

- CodeRabbit CLI on `PATH` when `review.provider` is `coderabbit`.
- CodeRabbit CLI present but `review.provider` unset → surface **migration notice** (implicit default flipped to
  `none`; set `review.provider` explicitly if review gating is desired).
- `review.enabled: false` in existing config → warn deprecated; suggest `review.provider: "none"`.
- Recallium reachable when `memory.provider` is `recallium`.
- MemPalace package import + `memory.mempalace.palacePath` directory probe when `memory.provider` is `mempalace`
  (install recipe + live-smoke checklist: `docs/guides/configuration.md` **MemPalace memory provider**; no
  auto-install).
- Basic Memory mode + local package/`projectPath` or cloud `tokenEnv` presence (+ allowlisted `apiBase`) when
  `memory.provider` is `basic-memory` (install recipe + live-smoke checklist: `docs/guides/configuration.md`
  **Basic Memory provider**; no auto-install / no cloud account create).
- Obsidian vault path + `tokenEnv` presence + loopback reachability when `memory.provider` is `obsidian`
  (install/enable recipe + live-smoke checklist: `docs/guides/configuration.md` **Obsidian memory provider**;
  no auto-install of Obsidian or the Local REST API plugin).
- **`orchestration.planPolicy`:** surface current value vs default (`canonical`); warn when set to
  `proposed` (fixture/adoption path — kernel envelope unchanged).
- **`verify-unconfigured`** via `python3 scripts/verify-unconfigured.py` — CTA: run `/sw-init`.
- Config drift vs schema → `python3 scripts/sw-configure.py drift-check`.
- Missing in-repo store dir → offer `mkdir -p` repair.

- **Host provider doctor** via `python3 scripts/host-doctor.py` — validates `host.provider`, configured remote, token env presence (never prints token), and rate-limit config. Warns when capability is degraded (missing token, missing remote) without blocking scaffold.
- Seed `host` config on greenfield: `provider` auto-detected, `remote: origin`, `tokenEnv` per provider (`GITHUB_TOKEN` default for GitHub). Existing GitHub repos need only `GITHUB_TOKEN` set (R33).
- **Jira issue-store init probes (PRD 047 R101/R105/R108/R109):** when `planning.store.issuesProvider` is `jira`, run `python3 scripts/planning_store.py probe-jira-init` — auth (Cloud email+token / DC PAT), per-issue privacy classification, createmeta required fields, and label-write permission (fail-closed).
- **Planning store doctor** via `python3 scripts/planning-doctor.py` — validates `planning.store` backend reachability (degrade-open when `memory` is configured but no memory provider is present), sweeps orphaned `.cursor/planning-materialized/` trees, and never prints provider tokens (R27).

### 5b. Portability self-check (R24/R25)

Before first `/sw-ship`:

```bash
python3 scripts/sw-configure.py portability-check
```

Summarize: verify configured (real vs gaps), base resolvable, `gh`/Actions availability, `sw-reference` paths
present, no dev-harness refs, web knobs off. Warn when `gh` or GitHub Actions unavailable (CI-readiness gate
requires them — DL-7).

### 6. Write config

Assemble draft via configurator; validate against `.sw/config.schema.json`; stamp `configuredWith`:

```json
"configuredWith": {
  "shipwrightVersion": "<from scripts/sw-configure.py shipwright-version>",
  "schemaVersion": "<from scripts/sw-configure.py schema-version>"
}
```

Write `.cursor/workflow.config.json`. Merge `models` from `scripts/seed-model-config.py` unless user opts out.
Seed `communication` from `core/sw-reference/communication-routing.defaults.json` (commands + skills + agents maps).

### 6b. Planning profile + store seeding (PRD 034 R21)

After the config file exists, seed the public-repo-aware visibility profile, default store backend, and
first-run privacy notice:

```bash
python3 scripts/planning-init-seed.py --config "$CONFIG"
```

This:

- Sets `planning.store.backend` to `in-repo-public` when unset (draft also seeds this key).
- Probes `origin` via `scripts/planning_visibility.py resolve-default-profile --write` — a **public**
  remote selects `all-private` and sets `planning.privacyAck.required: true`; private/absent remotes
  select `specs-public`.
- Copies `core/sw-reference/planning-privacy-notice.md` to
  `.cursor/hooks/state/planning-privacy-notice.md` and mirrors profile + ack into
  `.cursor/hooks/state/planning-visibility.json`.

Then auto-configure `.gitignore` for planning-store paths from the resolved visibility profile:

```bash
python3 scripts/gitignore-generate.py generate --write
```

This regenerates the `# BEGIN visibility-generated … # END visibility-generated` block (private/memory unit
bodies) plus the static `.cursor/hooks/state/` local-hook-state exclusion — the same directory that holds
`.cursor/hooks/state/planning-cutover-gate.json` (PRD 057 R5). That gate file is a **local override only**;
the CI-authoritative cutover signal is derived at read time from committed `workflow.config.json`
(`planning.store.backend`) + structural markers (see `docs/guides/configuration.md`), so its absence in a
fresh, gitignored checkout never causes a false "file mode" default.

**Doctor re-run:** `python3 scripts/planning-doctor.py` validates store reachability, degrade-opens when the
memory backend has no provider (actionable remediation, no hard-fail), sweeps orphaned materialized trees,
and references env-var names only — never token values (R27).


### 6c. Scripts façade (consumer repos — PRD 073 R1/R3/R16)

After config + planning seed, emit the repo-local deliver scripts façade. **Skip** when the target is the
Shipwright plugin source repo itself (full `scripts/` tree already present).

```bash
python3 scripts/init_scripts_facade.py "$ROOT" emit
python3 scripts/init_scripts_facade.py "$ROOT" probe   # optional doctor: deliver entrypoints resolvable
```

**Ownership:** `/sw-init` is the sole writer of `scripts/sw`, `.cursor/sw-scripts-facade.json`, and the
documented deliver forwarders under `scripts/` (`wave.py`, `wave_deliver.py`, … plus trust markers
`check-gate.py`, `resolve-model-tier.py`). Forwarders are **real files** (never symlinks) that delegate to
the plugin install path recorded in the manifest — durable without `SHIPWRIGHT_SCRIPTS` or other transient env.

**Precedence:** resolver order remains self-repo working-tree → validated `SHIPWRIGHT_SCRIPTS` → plugin install
→ consumer `scripts/` façade (`sw_scripts_resolve.py`). Re-run `/sw-init` to refresh after plugin upgrades.

**Agent guardrail:** do **not** hand-author or patch forwarders mid-deliver; halt and re-run `/sw-init` emit
(or `init_scripts_facade.py emit`) when entrypoints are missing.

### 7. Report

Print summary: providers, verify status, portability self-check, drift notice, config path.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-init`.

## Guardrails

- Never auto-seed `category: rule` files (R42).
- Never write vacuous verify placeholders — real commands or explicit gaps only.
- Redaction chokepoint applies to all in-repo writes.

## Fresh-install zero-config path

A repo can commit only `.cursor/sw-memory.provider` + empty store dirs without `workflow.config.json`. Run
`/sw-init` to customize.
