# Sentry MCP — debug context recipe

Read-only issue/event retrieval for `/pf-debug` (R23). **No Sentry mutations** from this workflow.

## Prerequisites

- Sentry MCP server enabled in Cursor (`user-Sentry` or `plugin-sentry-sentry`)
- Authenticated (`mcp_auth` if the server reports auth required)
- Read scope: issues, events, stack traces, breadcrumbs, tags

## Tool discovery (mandatory)

Before hard-coding calls, list and read MCP tool schemas:

```
# Cursor MCP descriptors: mcps/<server>/tools/*.json
```

Common patterns (names vary by server version):

| Intent | Typical tool |
|--------|----------------|
| Issue summary | `get_issue`, `fetch_issue`, `sentry_get_issue` |
| Event detail | `get_event`, `fetch_event` |
| Stack / breadcrumbs | fields on event payload |

If no tool matches, degrade gracefully (see below).

## Query recipe

1. Parse signal: `organization`, `project`, `issueId`, optional `eventId` / `url`.
2. Call issue fetch → latest event if `eventId` absent.
3. Normalize into debug input enrichment:

```json
{
  "title": "",
  "level": "",
  "firstSeen": "",
  "lastSeen": "",
  "count": 0,
  "stackTrace": "",
  "breadcrumbs": [],
  "tags": {},
  "traceId": ""
}
```

4. **Redact** the entire normalized JSON (stringify → `bash scripts/memory-redact.sh` → parse) before:
   - RCA prompts
   - `memory-preflight` writes
   - Any distilled memory

5. Attach `relatedFiles` from stack frame paths when present.

## Graceful degradation

| Condition | Behavior |
|-----------|----------|
| MCP unavailable / auth failed | Note in report; proceed with raw `issueId` + user context |
| Tool schema mismatch | Use URL/issue ref only; do not fail the workflow |
| Empty event | Issue metadata only |

Never store raw Sentry payloads without redaction.

## Test assertion (fixtures)

A payload containing `ghp_` or email in a breadcrumb must be scrubbed before RCA prompt assembly.
