# Guardrail matrix fixtures

Shared scenarios exercised against both Cursor and Claude Code hook adapters through
`guardrail_core.py`. Each scenario stubs the memory rules provider via `PF_RULES_SCRIPT`.

| Scenario | Cursor expect | Claude expect |
|----------|---------------|---------------|
| provider-unreachable | `continue: false` | `decision: block`, exit 2 |
| greenfield-empty-rules | `continue: true` | allow, exit 0 |
| rules-present | `continue: true` | allow, exit 0 |
| catch-all-exception | `continue: false` | block, exit 2 |
| session-start | n/a | `additionalContext` non-empty |

Driver: `scripts/test/run-guardrail-matrix-fixtures.sh` (delegates to `run-hook-fixtures.sh`).
