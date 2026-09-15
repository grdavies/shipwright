# Packaged provider conformance consumer fixture (PRD 356 D4)

Hermetic staged wheel layout for packaged-consumer conformance tests.

## D4 layout (required)

Conformance evidence must live under a real host bundle:

```text
dist/<host>/core/sw-reference/provider-conformance/<provider>.ok.json
```

This fixture ships `dist/codex/` because `codex` is present in released wheels
(`PACKAGED_DIST_IDS` in `scripts/planning/packaged_conformance_roots.py`).

## Wrong-root-only layout (insufficient — negative assertion)

Staging only:

```text
core/sw-reference/provider-conformance/<provider>.ok.json
```

at the package root (without `dist/<host>/`) does **not** satisfy D4. Consumer
tests assert an empty shipped set for that layout.

See `wrong-root-only/` for the negative fixture subtree.
