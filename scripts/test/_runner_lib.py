"""Runner-only helpers for scripts/test/_runner.py (PRD 054 phase 7)."""
from __future__ import annotations

import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path


def invoke_suite_main(module: object) -> int:
    """Run a fixture module's main() without inheriting parent sys.argv."""
    main_fn = getattr(module, "main", None)
    if not callable(main_fn):
        return 1
    params = list(inspect.signature(main_fn).parameters)
    if not params:
        return int(main_fn())
    return int(main_fn([]))


def deliver_verify_active() -> bool:
    return os.environ.get("SW_DELIVER_VERIFY", "").strip().lower() in ("1", "true", "yes")


def fixtures_base(root: Path) -> Path:
    """Resolve writable fixtures root (ephemeral during deliver verify — PRD 050 R51)."""
    ep = os.environ.get("SW_FIXTURES_EPHEMERAL_ROOT", "").strip()
    if ep:
        return Path(ep)
    return root / "scripts" / "test" / "fixtures"


def prepare_ephemeral_fixtures(root: Path) -> Path:
    """Copy tracked fixtures tree to a temp root for deliver verify (R51)."""
    td = Path(tempfile.mkdtemp(prefix="sw-fixtures-ephemeral-"))
    src = root / "scripts" / "test" / "fixtures"
    if src.is_dir():
        shutil.copytree(src, td / "fixtures")
    return td
