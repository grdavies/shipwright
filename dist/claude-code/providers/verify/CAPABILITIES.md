---
capability:
  version: 1
  triggers:
    - type: phase_default
      selectionFamily: providers
      scope: verify-contract
  metadata:
    providerFamily: verify
    selectionFamily: providers
    notes: neutral capability contract doc
---

# Verify E2E / smoke adapter capabilities (IM9 / U10)

Provider-style smoke/E2E verification. Selected by `verifyE2e.provider` in `workflow.config.json`.
Invoked by `scripts/verify-e2e.sh` during `/sw-verify` — runs **only when enabled**.

## Config

```json
"verifyE2e": {
  "enabled": true,
  "provider": "stub",
  "routes": ["/", "/api/health"]
}
```

| Field | Meaning |
| --- | --- |
| `enabled` | When `false` or `provider: "none"`, adapter is skipped (non-blocking). |
| `provider` | Executable id under `providers/verify/<id>.sh` + `<id>.md`. |
| `routes` | Optional affected routes hint for smoke scoping (adapter-specific). |

## Executable adapter contract (stdout JSON)

```json
{
  "status": "complete | skipped | failed",
  "exitCode": 0,
  "name": "e2e",
  "provider": "stub",
  "logPath": "/tmp/sw-verify.e2e.log",
  "skipped": false,
  "reason": ""
}
```

| `status` | `exitCode` | Meaning |
| --- | --- | --- |
| `complete` | `0` | Smoke/E2E passed |
| `skipped` | `0` | Not configured / stack absent — non-blocking |
| `failed` | non-zero | Actionable failure |

## Environment (set by selector)

| Var | Content |
| --- | --- |
| `SW_VERIFY_ROOT` | Repo root |
| `SW_CHANGED_FILES` | Newline-separated changed paths |
| `SW_E2E_ROUTES` | JSON array from config |
| `SW_E2E_CONFIG` | Path to workflow.config.json |

## Providers

| Id | Role |
| --- | --- |
| `none` | Explicit skip |
| `stub` | Fixture-friendly no-op pass |
| `playwright` | Runs `npx playwright test` when project has Playwright config; else skips |

Agent-mediated adapters document runner setup in `providers/verify/<id>.md`.
