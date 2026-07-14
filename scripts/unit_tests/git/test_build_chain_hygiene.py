"""PRD 060 gap-096/100 — build-chain sync hygiene (R11–R13)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("copy_to_core", _ROOT / "copy-to-core.py")
assert _SPEC and _SPEC.loader
copy_to_core = importlib.util.module_from_spec(_SPEC)
sys.modules["copy_to_core"] = copy_to_core
_SPEC.loader.exec_module(copy_to_core)


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "core" / "sw-reference").mkdir(parents=True)
    manifest = {
        "coreAuthoredAllowlist": [],
        "deprecatedAllowlist": [],
        "roles": {"coreScripts": {"excludes": ["test/"]}},
    }
    (tmp_path / "core" / "sw-reference" / "build-chain-sot.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (tmp_path / ".sw").mkdir()
    (tmp_path / ".sw" / "layout.md").write_text("# layout\n", encoding="utf-8")
    (tmp_path / "core" / "sw-reference" / "layout.md").write_text("# layout\n", encoding="utf-8")
    for d in ("commands", "skills", "rules", "agents", "providers", "scripts"):
        (tmp_path / d).mkdir()
    return tmp_path


def test_force_escape_fixture_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("SW_BUILD_CHAIN_FORCE", raising=False)
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
    monkeypatch.delenv("SW_HARNESS", raising=False)
    assert copy_to_core._force_escape_allowed() is False
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    assert copy_to_core._force_escape_allowed() is True


def test_refuse_core_only_divergence(mini_root: Path) -> None:
    sw = mini_root / ".sw"
    core_ref = mini_root / "core" / "sw-reference"
    manifest = json.loads((core_ref / "build-chain-sot.json").read_text(encoding="utf-8"))
    copy_to_core._write_provenance(mini_root, copy_to_core._sw_reference_tree_hashes(core_ref))
    (core_ref / "layout.md").write_text("# manual core edit\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        copy_to_core.check_core_sw_reference_divergence(mini_root, sw, manifest, force=False)
    assert exc.value.code == 1


def test_build_chain_sync_check_emits_remediation(repo_root: Path) -> None:
    proc = subprocess.run(
        ["python3", "scripts/build-chain-sync.py", "--check"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        assert "python3 scripts/build-chain-sync.py" in proc.stderr
