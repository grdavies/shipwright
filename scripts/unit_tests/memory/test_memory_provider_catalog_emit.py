"""PRD 071 R2 — memory provider catalog build-chain emit golden."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("core_content_sync", Path(__file__).resolve().parents[2] / "core_content_sync.py")
assert _SPEC and _SPEC.loader
core_content_sync = importlib.util.module_from_spec(_SPEC)
sys.modules["core_content_sync_emit_test"] = core_content_sync
_SPEC.loader.exec_module(core_content_sync)


def _golden_path(repo_root: Path) -> Path:
    return repo_root / "scripts/test/fixtures/memory-provider-catalog/golden.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_golden(repo_root: Path) -> dict:
    return json.loads(_golden_path(repo_root).read_text(encoding="utf-8"))


@pytest.mark.parametrize("artifact", ["memory-provider-catalog.json"])
def test_catalog_emit_matches_golden(repo_root: Path, artifact: str) -> None:
    golden = _load_golden(repo_root)
    row = next(a for a in golden["artifacts"] if a["rel"] == artifact)
    source = repo_root / row["source"]
    emit = repo_root / row["emit"]
    assert source.is_file(), f"missing source authority: {row['source']}"
    assert emit.is_file(), f"missing emit mirror: {row['emit']}"
    assert row["sync"] == "core-content-sync"
    assert source.read_bytes() == emit.read_bytes()
    assert _sha256(source) == row["sha256"]


def test_core_content_sync_preserves_catalog_emit(repo_root: Path) -> None:
    artifact = _load_golden(repo_root)["artifacts"][0]
    source = repo_root / artifact["source"]
    emit = repo_root / artifact["emit"]
    before = emit.read_bytes()
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/core_content_sync.py")],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert source.read_bytes() == emit.read_bytes()
    assert emit.read_bytes() == before


def test_mempalace_catalog_lineage_supersedes_010_not_071(repo_root: Path) -> None:
    """PRD 074 phase 12 — mempalace in emitted catalog; re-auth supersedes cancelled 010, not 071."""
    import planning_lifecycle as plc

    catalog = json.loads((repo_root / ".sw/memory-provider-catalog.json").read_text(encoding="utf-8"))
    assert "mempalace" in catalog.get("providers", {})
    target = plc.mempalace_reauth_supersedes_target()
    assert target == plc.PRD_010_PRD_UNIT_ID
    assert target != plc.PRD_071_UNIT_ID
    for rel in (
        "core/sw-reference/memory-provider-catalog.json",
        "dist/cursor/core/sw-reference/memory-provider-catalog.json",
        "dist/claude-code/core/sw-reference/memory-provider-catalog.json",
    ):
        emit = json.loads((repo_root / rel).read_text(encoding="utf-8"))
        assert "mempalace" in emit.get("providers", {}), f"missing mempalace in {rel}"


def test_catalog_emit_preserves_support_status(repo_root: Path) -> None:
    """PRD 086 R3 — supportStatus survives copy-to-core emit for all five providers."""
    expected = {
        "recallium": "ga",
        "in-repo": "ga",
        "mempalace": "community-triage",
        "basic-memory": "community-triage",
        "obsidian": "community-triage",
    }
    source = json.loads((repo_root / ".sw/memory-provider-catalog.json").read_text(encoding="utf-8"))
    emit = json.loads(
        (repo_root / "core/sw-reference/memory-provider-catalog.json").read_text(encoding="utf-8")
    )
    for provider_id, want in expected.items():
        assert source["providers"][provider_id]["supportStatus"] == want
        assert emit["providers"][provider_id]["supportStatus"] == want


def test_core_only_catalog_orphan_refused(repo_root: Path, tmp_path: Path) -> None:
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
    orphan = tmp_path / "core" / "sw-reference" / "memory-provider-catalog.json"
    orphan.write_text('{"version":1,"providers":{}}\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        core_content_sync.check_sw_reference_orphans(
            tmp_path / "core", tmp_path / ".sw", manifest, force=False
        )
    assert exc.value.code == 1
