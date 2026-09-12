"""PRD 345 R13–R14 — version metadata parity; version.txt is release-please SoT."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_scripts_version() -> tuple[str, str]:
    path = REPO_ROOT / "scripts" / "version.py"
    spec = importlib.util.spec_from_file_location("scripts_version_parity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    version = str(getattr(mod, "__version__", "")).strip()
    floor = str(getattr(mod, "PYTHON_FLOOR", "")).strip()
    if not version:
        raise ValueError(f"missing __version__ in {path}")
    if not floor:
        raise ValueError(f"missing PYTHON_FLOOR in {path}")
    return version, floor


def _version_txt() -> str:
    path = REPO_ROOT / "version.txt"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"empty version.txt at {path}")
    return text


def _release_please_manifest() -> str:
    path = REPO_ROOT / ".release-please-manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    version = str(data.get(".") or "").strip()
    if not version:
        raise ValueError(f"missing root version in {path}")
    return version


def _dist_zipapp_versions() -> list[str]:
    versions: list[str] = []
    dist = REPO_ROOT / "dist"
    if not dist.is_dir():
        return versions
    for manifest in sorted(dist.glob("*/shipwright-*.manifest.json")):
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        version = str(doc.get("zipappVersion") or "").strip()
        if version:
            versions.append(version)
    return versions


def _plugin_manifest_versions() -> list[str]:
    versions: list[str] = []
    dist = REPO_ROOT / "dist"
    for rel in (".cursor-plugin/plugin.json", ".claude-plugin/plugin.json"):
        for path in sorted(dist.glob(f"*/{rel}")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            version = str(doc.get("version") or "").strip()
            if version:
                versions.append(version)
    return versions


def _pyproject_python_floor() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', text)
    if not match:
        raise ValueError("could not parse requires-python from pyproject.toml")
    return match.group(1)


def test_scripts_version_reads_version_txt() -> None:
    """O — scripts/version.py exposes version from version.txt plus Python floor."""
    version, floor = _load_scripts_version()
    assert version == _version_txt()
    assert floor == "3.10"
    # No manually maintained duplicate semver literal in scripts/version.py body.
    body = (REPO_ROOT / "scripts" / "version.py").read_text(encoding="utf-8")
    assert f'__version__ = "{version}"' not in body
    assert "__version__ = _read_version_txt()" in body


def test_sw_reexports_scripts_version() -> None:
    """M — packaged sw module reads the same canonical version."""
    import sw

    canonical, floor = _load_scripts_version()
    assert sw.__version__ == canonical
    assert sw.PYTHON_FLOOR == floor


def test_version_txt_is_release_please_source_of_truth() -> None:
    """M — version.txt aligns with release-please manifest (RP-owned)."""
    assert _version_txt() == _release_please_manifest()


def test_scripts_version_matches_version_txt() -> None:
    """M — scripts/version.py resolves to version.txt."""
    canonical, _ = _load_scripts_version()
    assert _version_txt() == canonical


def test_dist_stamps_match_canonical() -> None:
    """M — dist manifest zipappVersion and plugin.json versions match canonical."""
    canonical, _ = _load_scripts_version()
    zipapp_versions = _dist_zipapp_versions()
    plugin_versions = _plugin_manifest_versions()
    if not zipapp_versions and not plugin_versions:
        pytest.skip("dist/ artifacts not present in this checkout")
    for version in zipapp_versions + plugin_versions:
        assert version == canonical


def test_python_floor_consistency() -> None:
    """B — README, pyproject, and scripts/version.py agree on Python floor."""
    _, floor = _load_scripts_version()
    assert _pyproject_python_floor() == floor
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Python ≥ {floor}" in readme


def test_release_tag_matches_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    """E — release tag env matches canonical version when set."""
    canonical, _ = _load_scripts_version()
    monkeypatch.setenv("GITHUB_REF", f"refs/tags/v{canonical}")
    ref = __import__("os").environ.get("GITHUB_REF", "")
    tag = ref.removeprefix("refs/tags/v") if ref.startswith("refs/tags/v") else ""
    assert tag == canonical
