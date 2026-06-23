# phase-flow v2 (`currsor-phase-flow-2`)

Self-contained Cursor plugin for the unified phase-flow v2 development workflow. All commands use the
`pf-` prefix. Infrastructure seams (CI gate, memory, AI review, stabilize loop, hooks) are vendored in-tree
from phase-flow v1 and compound-engineering patterns — no runtime dependency on sibling plugins.

## Install (local development)

```bash
./scripts/sync-local-install.sh
```

Then **Developer: Reload Window** in Cursor.

Default install path: `~/.cursor/plugins/local/phase-flow-v2`

## Configuration

Copy the example config into your target repo:

```bash
mkdir -p .cursor
cp config/workflow.config.example.json .cursor/workflow.config.json
# edit memory.project, verify.*, and provider selection
```

Provider **selection** lives in config; API credentials are sourced from the environment / secret store at
runtime — never commit secrets.

| Key | Purpose |
|-----|---------|
| `memory.provider` | Active memory adapter (`recallium` default) |
| `review.provider` | Active AI review adapter (`coderabbit` default) |
| `coderabbit.reviewGraceMinutes` | Gate grace window before absent review = settled |
| `checks.treatNeutralAsPass` | NEUTRAL checks count as pass unless allowlisted |
| `checks.neutralAllowlist` | Check names that stay blocking |
| `memory.autoSync` | Stop-hook thresholds for `/pf-memory-sync` scheduling |

See `docs/config.schema.json` for the full schema.

## Components (foundation)

| Area | Path | Status |
|------|------|--------|
| Manifest | `.cursor-plugin/plugin.json` | U1 |
| CI gate | `scripts/check-gate.sh`, `skills/checks-gate/` | U2–U3 |
| Memory seam | `skills/memory/`, `providers/recallium.md` | U4–U5 |
| Review seam | `providers/review/` | U3 |
| Stabilize / RCA | `skills/stabilize-loop/`, `skills/rca-core/` | U6 |
| Hooks | `hooks/` | U7 |
| Provenance | `PROVENANCE.md` | U1+ |

Workstreams (documentation, implementation, debugging, feedback) are planned separately.

## Provenance

Vendored components are tracked in [`PROVENANCE.md`](PROVENANCE.md) with source repo and commit.

## License

MIT
