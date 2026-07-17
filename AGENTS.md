# Agent guidance (Shipwright)

Standing agent guidance is **rule-class memory** — not duplicated in this file (PRD 072 R7). Hooks load
allowlisted rules at session start; promote or edit rules only through `/sw-memory-audit` (human-gated).

## Retrieval

- **In-repo provider:** `.cursor/sw-memory/rules/` with allowlist `.cursor/sw-memory-rule-allowlist.json`
- **Recallium / other providers:** run memory-preflight, then adapter rules-load for category rule
- Dual-home standing guidance (policy copied here and in memory) is rejected — pointers only.

## Rule pointers

| Topic | Rule id | Path |
| --- | --- | --- |
| Mock realism (PRD 039 R10) | `mock-realism` | `.cursor/sw-memory/rules/mock-realism.md` |
