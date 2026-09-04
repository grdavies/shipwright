# Agent guidance (Shipwright)

Standing agent guidance is **rule-class memory** — not duplicated in this file (PRD 072 R7). Hooks load
allowlisted rules at session start; promote or edit rules only through `/sw-memory-audit` (human-gated).
`memory.provider` selects the adapter at `providers/<id>.md`; configuration is in
`docs/guides/configuration.md`.

## Retrieval

- **In-repo provider:** local bodies under `.shipwright/memory/rules/` (legacy `.cursor/sw-memory/rules/` during redirect) plus allowlist `.shipwright/memory/rule-allowlist.json` (legacy `.cursor/sw-memory-rule-allowlist.json`)
- **Recallium / other providers:** `memory-preflight` `rules-load` via the adapter — thin pointers only
- **Layout contract:** `.shipwright/layout.md` (legacy stub `.sw/layout.md`)
- Dual-home standing guidance (policy copied here and in the provider) is rejected except for `in-repo` local bodies

## Rule pointers

| Topic | Rule id | Path |
| --- | --- | --- |
| Mock realism (PRD 039 R10) | `mock-realism` | adapter `rules-load` (`providers/<memory.provider>.md`) |
| Orphan worktree cleanup (PRD 095) | — | `scripts/cleanup_lib.py` (`enumerate_orphan_worktrees`, `_classify_orphan`; ghost → park → husk) |
