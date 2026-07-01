#!/usr/bin/env python3
"""verify.test bundle executed via Python runner (R27)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root


def suites_for_verify(root: Path | None = None) -> list[str]:
    root = root or repo_root(__file__)
    import suite_registry

    return suite_registry.verify_bundle_entries(root)


def _run(path: Path) -> int:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return int(mod.main()) if hasattr(mod, "main") else 1


def main() -> int:
    root = repo_root(__file__)
    failures = 0
    for name in suites_for_verify(root):
        path = SCRIPT_DIR / name
        if not path.is_file():
            print(f"FAIL missing suite {name}")
            failures += 1
            continue
        print(f"==> verify/{name}")
        if _run(path) != 0:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
