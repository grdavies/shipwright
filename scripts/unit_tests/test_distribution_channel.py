"""PRD 345 R1–R3 — distribution channel packaging and namespace."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime_requirements import bundle_targets, sync_runtime_bundle  # noqa: E402


def _pyproject_text() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_pyproject_uses_non_colliding_package_name() -> None:
    """R1 — PyPI distribution name avoids generic shipwright namespace collision."""
    text = _pyproject_text()
    match = re.search(r'^name\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert match is not None
    assert match.group(1) == "shipwright-workflow"


def test_console_entry_keeps_shipwright_command() -> None:
    """R1 — console script name stays ``shipwright`` after package rename."""
    assert 'shipwright = "sw.console:main"' in _pyproject_text()


def test_sync_runtime_bundle_mirrors_scripts_and_dist(tmp_path: Path) -> None:
    """R2 — runtime bundle lands under sw/ for wheel installs."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "version.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (root / "scripts" / "install.py").write_text("# stub\n", encoding="utf-8")
    (root / "scripts" / "unit_tests").mkdir()
    (root / "scripts" / "unit_tests" / "skip.py").write_text("# skip\n", encoding="utf-8")
    (root / "dist" / "cursor").mkdir(parents=True)
    (root / "dist" / "cursor" / "version.txt").write_text("9.9.9\n", encoding="utf-8")
    (root / "version.txt").write_text("9.9.9\n", encoding="utf-8")

    result = sync_runtime_bundle(root)
    assert result["verdict"] == "pass"
    targets = bundle_targets(root)
    assert (targets["scripts"] / "version.py").is_file()
    assert (targets["scripts"] / "install.py").is_file()
    assert not (targets["scripts"] / "unit_tests" / "skip.py").exists()
    assert (targets["dist"] / "cursor" / "version.txt").is_file()
    assert (targets["version.txt"]).read_text(encoding="utf-8").strip() == "9.9.9"


def test_wheel_is_self_contained(repo_root: Path, tmp_path: Path) -> None:
    """R2/R3 — wheel built after bundle sync includes scripts + dist payloads."""
    missing = []
    for rel in ("scripts/version.py", "dist/cursor/version.txt", "version.txt"):
        if not (repo_root / rel).is_file() and not (repo_root / rel).parent.is_dir():
            missing.append(rel)
    if missing:
        pytest.skip(f"runtime sources not present in checkout: {missing}")

    sync_runtime_bundle(repo_root)
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheel_dir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    wheels = sorted(wheel_dir.glob("shipwright_workflow-*.whl"))
    assert wheels, "expected shipwright_workflow wheel"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    assert any(name.startswith("sw/scripts/version.py") for name in names)
    assert any(name.startswith("sw/dist/") for name in names)


def test_getting_started_documents_shipwright_workflow_package() -> None:
    """R4 — adopter docs reference the non-colliding PyPI package name."""
    docs = (REPO_ROOT / "core/documentation/getting-started.md").read_text(encoding="utf-8")
    assert "pip install shipwright-workflow" in docs
    assert "pip install shipwright\n" not in docs


def test_release_workflow_has_clean_wheel_install(repo_root: Path) -> None:
    """R3 — release workflow validates wheel install in a clean environment."""
    workflow = (repo_root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "wheel-clean-install" in workflow or "wheel clean" in workflow.lower()
    assert "build_dist.py" in workflow
