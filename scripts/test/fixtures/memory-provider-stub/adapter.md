---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: memory.provider
        equals: memory-stub
    metadata:
      providerFamily: memory
      adapterId: memory-stub
      selectionFamily: providers
      gateRef: check-gate.py
---

# Provider adapter: memory-stub

Hermetic third-provider fixture for PRD 071 phase 12 (R7, R11). Exercises catalog registration,
adapter integrity, and consumer paths without implementing a real external memory backend.

## Purpose

- Proves third providers register via catalog row + adapter doc + rules script only.
- No command-body edits or closed `memory.provider` enum changes required.
- Not shipped as a seeded production provider — test fixture surface only.

## Capability flags

```json
{
  "typedMemories": true,
  "filePathSearch": true,
  "categoryFilter": true,
  "recencyControl": true,
  "rulesAtStartup": true,
  "tasks": false,
  "export": false,
  "import": false,
  "softDelete": true,
  "semanticSearch": false
}
```

## Hook transport

Agent session: `mcp` with out-of-band rule fetch via `stub-rules.py`. Reachability is registration-gated
(validate_registration pass) — no live MCP session required for hermetic tests.

## Interchange

Both `jsonl` and `okf` are `unsupported`. Provider-switch flows must use the skip-ack path when migrating
to or from this fixture provider.
