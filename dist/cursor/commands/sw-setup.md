---
description: Deprecated alias — delegates to /sw-init. Does not implement configuration logic.
alwaysApply: false
---

# `/sw-setup` (deprecated)

> **Deprecated:** use **`/sw-init`** instead. This alias will be removed after one release.

`/sw-setup` prints the deprecation notice above and delegates to **`/sw-init`** with identical behavior. All
configuration logic lives in `scripts/sw-configure.sh` — this file does not duplicate the `/sw-init` body.

## Procedure

1. Print: `sw-setup is deprecated — use /sw-init`.
2. Run the full **`/sw-init`** procedure from `core/commands/sw-init.md`.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `bash scripts/resolve-model-tier.sh --command sw-init`.
