"""Install seeds .sw/memory-provider-catalog.json from closed-emit mirror."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_install():
    path = Path(__file__).resolve().parents[2] / "install.py"
    spec = importlib.util.spec_from_file_location("sw_install_seed_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sw_install_seed_test"] = mod
    # install.py imports _sw from scripts/
    scripts = Path(__file__).resolve().parents[2]
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec.loader.exec_module(mod)
    return mod


def test_seed_memory_provider_catalog_copies_emit(repo_root: Path, tmp_path: Path) -> None:
    install = _load_install()
    dest = tmp_path / "plugin"
    emit = dest / "core" / "sw-reference" / "memory-provider-catalog.json"
    emit.parent.mkdir(parents=True)
    src = repo_root / ".sw" / "memory-provider-catalog.json"
    emit.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    assert install.seed_memory_provider_catalog(dest) is True
    seeded = dest / ".sw" / "memory-provider-catalog.json"
    assert seeded.is_file()
    assert seeded.read_bytes() == emit.read_bytes()


def test_seed_memory_provider_catalog_noop_without_emit(tmp_path: Path) -> None:
    install = _load_install()
    assert install.seed_memory_provider_catalog(tmp_path / "empty") is False
