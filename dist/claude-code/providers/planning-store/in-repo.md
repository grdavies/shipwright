---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: planning.store.backend
        equals: in-repo-public
    metadata:
      providerFamily: planning-store
      adapterId: in-repo-public
      selectionFamily: providers
---

# Planning store adapter: in-repo public

Default backend. Unit bodies are read and written at their canonical repo-relative paths with
no behavior change from pre-034 public units.

## Operations

| Op | Implementation |
| --- | --- |
| `put` | Write `body_path` under repo root |
| `get` | Read `body_path` |
| `exists` | `is_file(body_path)` |
| `materialize` | `copy2(body_path, dest)` |
