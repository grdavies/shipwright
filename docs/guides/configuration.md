# Configuration

> **Redirect:** This public path is a durable stub. The canonical adopter guide lives at
> [`core/documentation/configuration.md`](../../core/documentation/configuration.md) and ships to
> `<install-root>/documentation/configuration.md` in packaged installs.

**Canonical guide:** [Configuration](../../core/documentation/configuration.md)

## Layout dual-home sync (`.sw/layout.md`)

Shipwright keeps a dual-home pair for the artifact layout contract:

| Path | Role |
| --- | --- |
| `.sw/layout.md` | Legacy / operator-facing layout contract |
| `core/sw-reference/layout.md` | Packaged reference mirror shipped with the plugin |

These two files **must stay byte-identical**. Commit hooks and CI refuse divergence.

### Sync procedure

1. Edit the authoritative content in one home (usually `.sw/layout.md` while iterating, or
   `core/sw-reference/layout.md` when packaging).
2. Copy the file bytes to the other home so both paths contain the exact same content:

   ```bash
   cp .sw/layout.md core/sw-reference/layout.md
   # or the reverse, depending on which side you edited
   ```

3. Verify before committing:

   ```bash
   python3 scripts/layout_sync_check.py --root .
   ```

4. Stage **both** paths together and commit. A one-sided stage still fails the pre-commit check
   if the working tree pair is divergent.

### Skip behavior

When **neither** file is present (consumer checkouts without the layout contract), the check
passes and is skipped. When only one side exists, the check fails closed.
