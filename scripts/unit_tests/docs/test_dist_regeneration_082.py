"""PRD 082 R27 — distribution regeneration and build-chain freshness fixtures."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dist_regeneration_082 import (
    PRD_082_SOURCE_MODULES,
    check_distribution_freshness,
    check_source_modules_registered,
    find_stale_distribution_mirrors,
)


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "core" / "sw-reference").mkdir(parents=True)
    manifest = {
        "version": 1,
        "pathPrefixes": ["scripts/"],
        "sourceModules": {key: list(value) for key, value in PRD_082_SOURCE_MODULES.items()},
    }
    (root / "core" / "sw-reference" / "build-chain-paths.json").write_text(
        __import__("json").dumps(manifest, indent=2),
        encoding="utf-8",
    )
    for paths in PRD_082_SOURCE_MODULES.values():
        for rel in paths:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                (target / "__init__.py").write_text("# pkg\n", encoding="utf-8")
            else:
                target.write_text(f"# source for {rel}\n", encoding="utf-8")
    for dist in ("dist/cursor", "dist/claude-code"):
        for paths in PRD_082_SOURCE_MODULES.values():
            for rel in paths:
                src = root / rel
                dst = root / dist / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
    return root


def test_source_modules_registered_in_manifest(repo_root: Path) -> None:
    manifest = repo_root / "core/sw-reference/build-chain-paths.json"
    assert check_source_modules_registered(manifest) == []


def test_distribution_freshness_passes_on_synced_repo(repo_root: Path) -> None:
    assert check_distribution_freshness(repo_root) == []


def test_stale_mirror_fails_freshness_check(mini_root: Path) -> None:
    source = mini_root / "scripts/planning_refusal_ledger.py"
    source.write_text("# touched\n", encoding="utf-8")
    drift = find_stale_distribution_mirrors(mini_root)
    assert any(row.get("kind") == "mirror-stale" for row in drift)


def test_missing_module_group_fails_registration_check(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "core" / "sw-reference").mkdir(parents=True)
    manifest = root / "core/sw-reference/build-chain-paths.json"
    manifest.write_text('{"sourceModules": {}}', encoding="utf-8")
    drift = check_source_modules_registered(manifest)
    assert any(row.get("kind") == "module-group-missing" for row in drift)


def test_build_chain_sync_is_idempotent(repo_root: Path) -> None:
    before = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    first = subprocess.run(
        ["python3", "scripts/build-chain-sync.py"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    mid = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    second = subprocess.run(
        ["python3", "scripts/build-chain-sync.py"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    after = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert mid == after
