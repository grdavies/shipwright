---
description: "[DEPRECATED] Use /sw-retrospective instead. Thin alias routing to the consolidated retrospective orchestrator with phase auto-detect."
alwaysApply: false
deprecated: true
replacedBy: sw-retrospective
---

# `/sw-compound-ship` (deprecated)

> **Deprecation notice (one release):** `/sw-compound-ship` is deprecated. Use **`/sw-retrospective`**
> instead. Behavior is preserved via this alias for one release.

## Procedure

1. Print this deprecation notice once at the start of the run.
2. **Route to `/sw-retrospective`** with the same flags:
   - No flags → `/sw-retrospective` (phase auto-detect via `bash scripts/wave.sh retrospective detect-phase`)
   - `--pre-merge` → `/sw-retrospective --pre-merge`
   - `--post-merge` → `/sw-retrospective --post-merge`
   - Pass through `--from`, `--skip-memory-sync`, and `--dry-run` unchanged.
3. Do not reimplement the chain — delegate entirely to `/sw-retrospective`.

**Communication intensity:** full

**Model tier:** inherit — resolve via `python3 scripts/resolve-model-tier.py --command sw-retrospective`.
