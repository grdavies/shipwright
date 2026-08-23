"""PRD 326 phase 1 / R1 — core/ mirror parity for verified PRD 323 surfaces.

``merge_provenance.py`` and ``merge_intent_resolve.py`` must be byte-identical under
``scripts/`` vs ``core/scripts/``. ``debug_repro_gate.py`` is intentionally unmirrored.
"""
from __future__ import annotations

import filecmp
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


MIRRORED = (
    "merge_provenance.py",
    "merge_intent_resolve.py",
)
INTENTIONALLY_UNMIRRORED = "debug_repro_gate.py"


def test_prd323_mirror_parity(repo_root: Path) -> None:
    """Mirrored 323 surfaces stay byte-identical; debug_repro_gate stays unmirrored."""
    for name in MIRRORED:
        src = repo_root / "scripts" / name
        dst = repo_root / "core" / "scripts" / name
        assert src.is_file(), f"missing scripts/{name}"
        assert dst.is_file(), f"missing core/scripts/{name}"
        assert filecmp.cmp(src, dst, shallow=False), f"mirror drift: {name}"

    unmirrored_core = repo_root / "core" / "scripts" / INTENTIONALLY_UNMIRRORED
    assert (repo_root / "scripts" / INTENTIONALLY_UNMIRRORED).is_file()
    assert not unmirrored_core.exists(), (
        "debug_repro_gate.py must remain intentionally unmirrored in core/scripts "
        "(do not invent a mirror in later phases)"
    )
