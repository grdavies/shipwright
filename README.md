# Shipwright

Self-contained multi-platform agentic dev-lifecycle plugin (Cursor + Claude Code). Commands use the
`sw-` prefix. Infrastructure seams (CI gate, memory, AI review, stabilize loop, hooks) are vendored in-tree
from phase-flow v1 and compound-engineering patterns — no runtime dependency on sibling plugins.

> **Install migration:** remove `~/.cursor/plugins/local/phase-flow-v2` before installing Shipwright, or a
> zombie plugin may duplicate commands alongside `~/.cursor/plugins/local/shipwright`.

## Install (local development)

Authoring lives under `core/`; installable trees are **generated** and committed under `dist/`.

```bash
python3 -m pf generate --all   # after editing core/
./scripts/sync-local-install.sh   # rsync dist/cursor/ → ~/.cursor/plugins/local/shipwright
```

Then **Developer: Reload Window** in Cursor.

Default install path: `~/.cursor/plugins/local/shipwright`

For Claude Code, point your plugin path at `dist/claude-code/` (or copy it to your Claude plugins directory).

## Configuration

Copy the example config into your target repo, or run `/sw-setup` for guided scaffolding:

```bash
mkdir -p .cursor
cp core/sw-reference/workflow.config.example.json .cursor/workflow.config.json
# edit memory.project, verify.*, and provider selection
```

Fresh installs can use **zero-config in-repo memory**: commit `.cursor/pf-memory.provider` (containing
`in-repo`) plus empty `.cursor/pf-memory/{memories,rules}/` — no `workflow.config.json` required until you
run `/sw-setup`.

Provider **selection** lives in config; API credentials are sourced from the environment / secret store at
runtime — never commit secrets.

| Key | Purpose |
|-----|---------|
| `memory.provider` | Active memory adapter (`in-repo` default in example; `recallium` also supported) |
| `review.provider` | Active AI review adapter (`coderabbit` default) |
| `coderabbit.reviewGraceMinutes` | Gate grace window before absent review = settled |
| `checks.treatNeutralAsPass` | NEUTRAL checks count as pass unless allowlisted |
| `checks.neutralAllowlist` | Check names that stay blocking |
| `memory.autoSync` | Stop-hook thresholds for `/sw-memory-sync` scheduling |

See `core/sw-reference/config.schema.json` for the full schema.

## Components (foundation)

| Area | Path | Status |
|------|------|--------|
| Authoring | `core/` | portability M1+ |
| Cursor install tree | `dist/cursor/` (generated) | portability U6 |
| Claude install tree | `dist/claude-code/` (generated) | portability U7 |
| Generate entrypoint | `python3 -m pf generate` | portability U5 |
| CI gate | `core/scripts/check-gate.sh`, `core/skills/checks-gate/` | U2–U3 |
| Memory seam | `core/skills/memory/`, `core/providers/` | U4–U5 |
| Review seam | `core/providers/review/` | U3 |
| Stabilize / RCA | `core/skills/stabilize-loop/`, `core/skills/rca-core/` | U6 |
| Hooks | `core/hooks/` + platform adapters | U4/U7 |
| Provenance | `PROVENANCE.md` | U1+ |

Workstreams (documentation, implementation, debugging, feedback) are planned separately.

## Provenance

Vendored components are tracked in [`PROVENANCE.md`](PROVENANCE.md) with source repo and commit.

## License

MIT
