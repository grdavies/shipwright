"""Fresh-install smoke for the Shipwright zipapp + thin shim (PRD 091 R3)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _scripts_tree_is_shim_only(scripts_dir: Path) -> bool:
    if not scripts_dir.is_dir():
        return True
    files = [p for p in scripts_dir.rglob("*") if p.is_file()]
    return files == [scripts_dir / "sw-run.py"]


def _generate_platform_dist(repo_root: Path, out_root: Path, platform: str) -> Path:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sw",
            "generate",
            platform,
            "--dest",
            str(out_root),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return out_root / platform


@pytest.mark.parametrize("platform", ["cursor", "claude-code"])
def test_zipapp_fresh_install_smoke(repo_root: Path, tmp_path: Path, platform: str) -> None:
    dist_root = tmp_path / "dist"
    plugin_root = _generate_platform_dist(repo_root, dist_root, platform)

    scripts_dir = plugin_root / "scripts"
    assert _scripts_tree_is_shim_only(scripts_dir), (
        f"expected only scripts/sw-run.py under {scripts_dir}, found: "
        f"{list(scripts_dir.rglob('*')) if scripts_dir.is_dir() else 'missing'}"
    )

    pyz = plugin_root / "shipwright.pyz"
    assert pyz.is_file(), f"missing stable zipapp symlink at {pyz}"
    versioned = sorted(plugin_root.glob("shipwright-*.pyz"))
    assert versioned, f"missing versioned zipapp under {plugin_root}"

    env_name = "CURSOR_PLUGIN_ROOT" if platform == "cursor" else "CLAUDE_PLUGIN_ROOT"
    env = os.environ.copy()
    env[env_name] = str(plugin_root)

    shim = scripts_dir / "sw-run.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(shim),
            "resolve-model-tier.py",
            "--command",
            "sw-ship",
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "tier" in proc.stdout.lower() or "model" in proc.stdout.lower()

    direct = subprocess.run(
        [sys.executable, str(pyz), "resolve-model-tier.py", "--command", "sw-ship"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert direct.returncode == 0, direct.stderr or direct.stdout
