# Shipwright


## sw-python-first

---
description: Python-first authoring policy for Shipwright workflow logic (R31).
alwaysApply: true
---

# sw-python-first

- New workflow logic MUST be authored in Python (stdlib-first per R11/R12).
- Introducing `.sh`, `.bash`, or `.ps1` files under enforced trees fails `zero-shell-guard.py`.
- Shelling out to `bash`/`sh`/`cmd` for plugin scripts is prohibited (R41).
- Third-party Python dependencies require `scripts/_sw/depmanifest.json` declaration and vendoring.

