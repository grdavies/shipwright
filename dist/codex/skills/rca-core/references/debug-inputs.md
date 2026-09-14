# Debug entry — input shapes

Normalized signals for the RCA core `debug` entry (R22). All text fields must pass through
`python3 scripts/sw_bootstrap.py memory-redact.py` before prompts or memory.

## Signal types

### `sentry`

```json
{
  "type": "sentry",
  "issueId": "PROJECT-123",
  "organization": "my-org",
  "project": "my-project",
  "eventId": "optional-event-uuid",
  "url": "https://sentry.io/..."
}
```

Enrichment via `skills/debug/references/sentry.md`. When MCP unavailable, proceed with the ref + user context.

### `deploy_log`

```json
{
  "type": "deploy_log",
  "source": "vercel|github-actions|fly|other",
  "excerpt": "redacted log text",
  "deployRef": "optional-sha-or-url"
}
```

### `user_report`

```json
{
  "type": "user_report",
  "description": "what the user saw",
  "environment": "production|staging|optional",
  "reproSteps": "optional"
}
```

## Optional repo context

- `relatedFiles[]` — paths implicated by stack trace or user report
- `prdRef` — frozen PRD path when known (for spec-union check on proposed fix)
- `priorDebugMemoryIds[]` — from `memory-preflight` search

## Reproduction posture

Attempt reproduction **from signal context** (Sentry stack, log line, user steps). A local repro strengthens
evidence but is **not required** to continue the loop — unlike stabilize's in-loop test failures.
