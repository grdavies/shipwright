"""PRD 345 R1–R3 — distribution channel packaging and namespace."""

from __future__ import annotations

import importlib.util
import json
import re
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from unit_tests._harness_runtime import isolated_source_fixture, isolated_git_environment


@pytest.fixture(autouse=True)
def _isolate_git_environment(monkeypatch):
    # Imported helpers also spawn Git, so isolate the whole test process.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    for key, value in isolated_git_environment({}).items():
        monkeypatch.setenv(key, value)


@pytest.fixture(scope="session")
def repo_root():
    """Own all source, generation, and index mutations used by distribution tests."""
    source = Path(__file__).resolve().parents[2]
    with isolated_source_fixture(source, extra_inputs=("sw", "platforms", "dist")) as root:
        yield root

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime_requirements import HANDOFF_RUNTIME_MODULES, bundle_targets, sync_runtime_bundle  # noqa: E402


def _pyproject_text() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_pyproject_uses_non_colliding_package_name() -> None:
    """The release contract reverted the distribution name to shipwright (#1144)."""
    text = _pyproject_text()
    match = re.search(r'^name\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert match is not None
    assert match.group(1) == "shipwright"


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

    for rel in HANDOFF_RUNTIME_MODULES:
        dependency = root / rel
        dependency.parent.mkdir(parents=True, exist_ok=True)
        dependency.write_text(f"# synthetic runtime dependency: {rel}\\n", encoding="utf-8")

    result = sync_runtime_bundle(root)
    assert result["verdict"] == "pass", result
    assert result["handoff"]["verdict"] == "pass"
    for rel in HANDOFF_RUNTIME_MODULES:
        assert (root / "sw" / rel).read_bytes() == (root / rel).read_bytes()
    targets = bundle_targets(root)
    assert (targets["scripts"] / "version.py").is_file()
    assert (targets["scripts"] / "install.py").is_file()
    assert not (targets["scripts"] / "unit_tests" / "skip.py").exists()
    assert (targets["dist"] / "cursor" / "version.txt").is_file()
    assert (targets["version.txt"]).read_text(encoding="utf-8").strip() == "9.9.9"


def _built_wheels(wheel_dir: Path) -> list[Path]:
    return sorted(wheel_dir.glob("shipwright*.whl"))


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
    wheels = _built_wheels(wheel_dir)
    assert wheels, "expected shipwright*.whl"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    assert any(name.startswith("sw/scripts/version.py") for name in names)
    assert any(name.startswith("sw/dist/") for name in names)


def test_wheel_bundles_version_without_manual_presync(repo_root: Path, tmp_path: Path) -> None:
    """R2 — plain PEP 517 build (no manual sync) still packs sw/scripts/version.py."""
    if not (repo_root / "scripts" / "version.py").is_file():
        pytest.skip("scripts/version.py missing")
    if not (repo_root / "version.txt").is_file():
        pytest.skip("version.txt missing")

    # Simulate a clean git checkout where sw/scripts has not been synced yet.
    mirrored = repo_root / "sw" / "scripts"
    if mirrored.exists():
        import shutil

        shutil.rmtree(mirrored)

    wheel_dir = tmp_path / "wheels-no-presync"
    wheel_dir.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheel_dir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    wheels = _built_wheels(wheel_dir)
    assert wheels, "expected shipwright*.whl from plain PEP 517 build"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
    assert any(name.startswith("sw/scripts/version.py") for name in names)
    assert any(name == "sw/version.txt" or name.endswith("/sw/version.txt") for name in names)


def test_getting_started_documents_shipwright_workflow_package() -> None:
    """Adopter docs use the current isolated release installation commands."""
    docs = (REPO_ROOT / "core/documentation/getting-started.md").read_text(encoding="utf-8")
    assert "uv tool install shipwright --from git+https://github.com/grdavies/shipwright.git@vX.Y.Z" in docs
    assert "pipx install git+https://github.com/grdavies/shipwright.git@vX.Y.Z" in docs


def test_release_workflow_has_clean_wheel_install(repo_root: Path) -> None:
    """R3 — release workflow validates wheel install in a clean environment."""
    workflow = (repo_root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "wheel-clean-install" in workflow or "wheel clean" in workflow.lower()
    assert "build_dist.py" in workflow
