---
description: Scaffold and validate repo-local Shipwright config — providers, guardrails, memory store, and environment doctor. Does not scaffold CI or migrate existing memories.
alwaysApply: false
---

# `/sw-setup`

Take a repo from **installed** to **configured and working**. Re-runs as a **doctor** against an existing
config — validate, report, and offer targeted repair without a full rescaffold.

## Scope

**Does:** memory-provider selection, review-provider selection, guardrail knobs, store init/validate,
environment detection, write schema-valid `.cursor/workflow.config.json`.

**Does NOT:** scaffold CI workflows, migrate Recallium memories into in-repo, auto-seed rule files, or write
global (user-level) config — repo-local only.

## Procedure

### 1. Detect mode

```bash
CONFIG=".cursor/workflow.config.json"
if [ -f "$CONFIG" ]; then
  MODE=doctor
else
  MODE=scaffold
fi
```

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

### 4. Guardrail knobs

Defaults (greenfield-friendly):

```json
"guardrails": {
  "enforceBeforeSubmit": true,
  "requireRuleClass": false
}
```

Explain `requireRuleClass:true` for mature repos that must have allowlisted rules before prompts proceed.

### 4b. Model tier defaults

Detect platform and seed `models` block (four-tier catalog + routing registry):

```bash
bash scripts/detect-platform.sh
bash scripts/seed-model-config.sh --platform "$(bash scripts/detect-platform.sh)" --repair all
```

| Signal | Platform |
| --- | --- |
| `CURSOR_AGENT` or `CURSOR_PLUGIN_ROOT` | `cursor` |
| `CLAUDE_CODE`, `CLAUDE_CODE_SSE_PORT`, or `CLAUDE_PLUGIN_ROOT` | `claude-code` |
| Ambiguous | prompt user; default `cursor` in Cursor |

**Scaffold:** always write complete `models` (tiers, aliases, roles, routing) from detected platform catalog
and `core/sw-reference/model-routing.defaults.json`.

**Doctor:** when `models` is missing → offer add. When present → offer `--repair routing` (routing only, requires
tiers keys) or confirmed `--repair tiers|all` (overwrites `models.tiers` for detected platform). Never
auto-overwrite user-edited tiers without explicit confirm.

Report tier map (`cheap` → ID, …) and note re-run on another platform overwrites `models.tiers`.

### 5. Environment doctor

Detect and recommend (never hard-fail scaffold):

- CodeRabbit CLI on `PATH` when `review.provider` is `coderabbit`.
- CodeRabbit CLI present but `review.provider` unset → surface migration notice (implicit default flipped to
  `none`; set `review.provider` explicitly if review gating is desired).
- `review.enabled: false` in existing config → warn deprecated; suggest `review.provider: "none"`.
- Recallium reachable when `memory.provider` is `recallium`.
- `verify.*` commands still placeholders → recommend configuring them.
- Missing in-repo store dir → offer `mkdir -p` repair.
- Config drift vs `.sw/config.schema.json` → list validation errors.

**Doctor repair examples:**

- Missing `.cursor/sw-memory/memories` → create dirs.
- Stale `memory.provider` with unreachable Recallium → suggest switch to in-repo or fix URL.
- Invalid unknown keys → strip or fix per schema.

### 6. Write config

Assemble and validate against `.sw/config.schema.json` before write:

```bash
# Validate (python example)
python3 -c "
import json, jsonschema, pathlib
schema = json.loads(pathlib.Path('.sw/config.schema.json').read_text())
cfg = json.loads(pathlib.Path('/tmp/sw-setup-draft.json').read_text())
jsonschema.validate(cfg, schema)
print('schema ok')
"
```

Write `.cursor/workflow.config.json` (repo-local). Include `memory.inRepo` block when provider is in-repo.
Merge `models` from `scripts/seed-model-config.sh` unless user opts out.

Seed `communication` from `core/sw-reference/communication-routing.defaults.json` (`defaultIntensity` +
full `routing.commands` map) unless the user opts out during scaffold.

### 7. Report

Print summary: providers chosen, store path, guardrail mode, model tier map, communication routing seeded,
environment warnings, config path.

Print tip: "Tip: add docs/ to .gitignore to keep workflow artifacts local (brainstorms, PRDs, decisions)."

**Communication intensity:** ultra

## Guardrails

- Never auto-seed `category: rule` files (R42).
- Rule-class promotion remains human-gated via `/sw-memory-audit` + allowlist.
- Redaction chokepoint (`scripts/memory-redact.sh`) applies to all in-repo writes — setup does not bypass it.
- Per-repo marker (`.cursor/sw-memory.provider`) is committed; global installs on unrelated workspaces without
  marker still pass through guardrails unchanged.

## Fresh-install zero-config path

A repo can commit only:

```
.cursor/sw-memory.provider   # contains: in-repo
.cursor/sw-memory/memories/  # empty
.cursor/sw-memory/rules/     # empty
```

…without `workflow.config.json`. The fail-closed hook engages via the marker; run `/sw-setup` to customize.
