"""PRD 338 R27 — pure-install version metadata and drift-check resolution."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sw.generate import generate_platform  # noqa: E402


def _manifest_version(install_root: Path, manifest_dir: str) -> str:
    manifest_path = install_root / manifest_dir / "plugin.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest: {manifest_path}")
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(doc.get("version") or "").strip()
    if not version:
        raise ValueError(f"malformed manifest version in {manifest_path}")
    return version


def _version_txt(install_root: Path) -> str:
    path = install_root / "version.txt"
    if not path.is_file():
        raise FileNotFoundError(f"missing version.txt under {install_root}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"empty version.txt under {install_root}")
    return text


def _load_sw_configure():
    path = SCRIPT_DIR / "sw-configure.py"
    spec = importlib.util.spec_from_file_location("sw_configure_prd338", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolve_drift_version(consumer_root: Path, plugin_root: Path, env_name: str) -> str:
    """Mirror sw-configure shipwright_version for pure-install consumers."""
    shipwright_version = _load_sw_configure().shipwright_version
    prev = os.environ.get(env_name)
    os.environ[env_name] = str(plugin_root)
    try:
        return shipwright_version(consumer_root)
    finally:
        if prev is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = prev


@pytest.fixture
def pure_install_targets(repo_root: Path, tmp_path: Path) -> dict[str, Path]:
    out = tmp_path / "dist"
    cursor = generate_platform("cursor", dest_root=out)
    claude = generate_platform("claude-code", dest_root=out)
    return {"cursor": cursor, "claude-code": claude, "repo": repo_root}


def test_pure_install_drift_version_both_targets(pure_install_targets: dict[str, Path]) -> None:
    """M — both Cursor and Claude installs expose matching canonical version metadata."""
    repo = pure_install_targets["repo"]
    expected = (repo / "version.txt").read_text(encoding="utf-8").strip()
    for platform, manifest_dir in (("cursor", ".cursor-plugin"), ("claude-code", ".claude-plugin")):
        root = pure_install_targets[platform]
        assert _version_txt(root) == expected
        assert _manifest_version(root, manifest_dir) == expected


def test_pure_install_drift_version_cursor_drift_check(pure_install_targets: dict[str, Path], tmp_path: Path) -> None:
    """I — drift-check resolves shipwrightVersion from CURSOR_PLUGIN_ROOT/version.txt."""
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    plugin = pure_install_targets["cursor"]
    resolved = _resolve_drift_version(consumer, plugin, "CURSOR_PLUGIN_ROOT")
    assert resolved == _version_txt(plugin)


def test_pure_install_drift_version_claude_drift_check(pure_install_targets: dict[str, Path], tmp_path: Path) -> None:
    """I — drift-check resolves shipwrightVersion from install-root version.txt."""
    consumer = tmp_path / "consumer-claude"
    consumer.mkdir()
    plugin = pure_install_targets["claude-code"]
    resolved = _resolve_drift_version(consumer, plugin, "CURSOR_PLUGIN_ROOT")
    assert resolved == _version_txt(plugin)


def test_pure_install_drift_version_absent_manifest(tmp_path: Path) -> None:
    """E — absent manifest fails clearly."""
    install = tmp_path / "cursor-bare"
    install.mkdir()
    (install / "version.txt").write_text("1.0.0\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing manifest"):
        _manifest_version(install, ".cursor-plugin")


def test_pure_install_drift_version_malformed_manifest(tmp_path: Path) -> None:
    """B — malformed manifest version fails clearly."""
    install = tmp_path / "cursor-bad"
    manifest_dir = install / ".cursor-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text('{"name":"shipwright","version":""}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="malformed manifest version"):
        _manifest_version(install, ".cursor-plugin")


def test_pure_install_drift_version_missing_version_txt(tmp_path: Path) -> None:
    """Z — missing version.txt fails clearly."""
    install = tmp_path / "cursor-no-version"
    install.mkdir()
    with pytest.raises(FileNotFoundError, match="missing version.txt"):
        _version_txt(install)


def test_pure_install_drift_version_one_target_cursor_only(pure_install_targets: dict[str, Path]) -> None:
    """O — single target (Cursor) still emits version.txt aligned to manifest."""
    root = pure_install_targets["cursor"]
    assert _version_txt(root) == _manifest_version(root, ".cursor-plugin")
