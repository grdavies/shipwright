"""PRD 091 R4 — zipapp build-manifest completeness regression guard."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_build_zipapp():
    spec = importlib.util.spec_from_file_location("build_zipapp", SCRIPT_DIR / "build_zipapp.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_emits_manifest_and_passes_completeness(repo_root: Path, tmp_path: Path) -> None:
    mod = _load_build_zipapp()
    dest = tmp_path / "plugin"
    payload = mod.build_archive(repo_root, dest)
    assert payload["verdict"] == "pass"
    manifest_path = Path(str(payload["manifestPath"]))
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["moduleCount"] == payload["moduleCount"]
    assert data["modules"] == payload["modules"]
    pyz = Path(str(payload["versionedPath"]))
    assert mod.verify_zipapp_completeness(pyz, data["modules"]) == []


def test_completeness_fails_when_module_missing(repo_root: Path, tmp_path: Path) -> None:
    mod = _load_build_zipapp()
    dest = tmp_path / "plugin"
    with pytest.raises(mod.ZipappCompletenessError, match="missing modules"):
        mod.build_archive(repo_root, dest, skip_modules={"resolve-model-tier.py"})


def test_completeness_passes_when_module_included(repo_root: Path, tmp_path: Path) -> None:
    mod = _load_build_zipapp()
    dest = tmp_path / "plugin"
    payload = mod.build_archive(repo_root, dest)
    pyz = Path(str(payload["versionedPath"]))
    assert "resolve-model-tier.py" in payload["modules"]
    assert mod.verify_zipapp_completeness(pyz, payload["modules"]) == []
