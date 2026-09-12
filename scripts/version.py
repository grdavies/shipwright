"""Version metadata — semver from release-please-owned version.txt (PRD 345 R12–R14)."""

from __future__ import annotations

from pathlib import Path

# Explicit floor — not release-please managed; keep aligned with pyproject/README via parity tests.
PYTHON_FLOOR = "3.10"


def _candidate_version_txt_paths() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        here.parent / "version.txt",  # repo root (dev / source tree)
        here.parent / "sw" / "version.txt",  # bundled package data (wheel)
        here / "version.txt",  # adjacent to mirrored scripts/
    ]


def _read_version_txt() -> str:
    for path in _candidate_version_txt_paths():
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    tried = ", ".join(p.as_posix() for p in _candidate_version_txt_paths())
    raise RuntimeError(f"version.txt not found or empty; tried: {tried}")


__version__ = _read_version_txt()
