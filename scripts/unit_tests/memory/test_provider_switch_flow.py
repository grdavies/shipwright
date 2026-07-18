"""PRD 071 R6 — provider-switch operator flow."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_switch as ms
from memory_provider_catalog import load_catalog

FIXTURE = SCRIPTS / "test/fixtures/in-repo-memory"


def _seed_workspace(tmp_path: Path, repo_root: Path) -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURE / "store", workspace / ".cursor/sw-memory")
    (workspace / ".cursor").mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / ".sw", workspace / ".sw")
    config = json.loads((FIXTURE / "config-in-repo.json").read_text(encoding="utf-8"))
    (workspace / ".cursor/workflow.config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return workspace


def test_capabilities_recallium_to_in_repo_is_lossy(repo_root: Path) -> None:
    """O — synthesized recallium export to native in-repo import is lossy but migratable."""
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "recallium", "in-repo")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "recallium", "in-repo")
    assert plan["path"] == "migrate"
    assert plan["migration"] == "lossy"


def test_capability_mismatch_blocks_migrate(repo_root: Path, tmp_path: Path) -> None:
    """E — unsupported interchange blocks migrate path."""
    catalog = json.loads(json.dumps(load_catalog(repo_root)))
    catalog["providers"]["blocked-src"] = json.loads(json.dumps(catalog["providers"]["recallium"]))
    catalog["providers"]["blocked-src"]["interchange"] = {"jsonl": "unsupported", "okf": "unsupported"}
    cat_path = tmp_path / ".sw/memory-provider-catalog.json"
    cat_path.parent.mkdir(parents=True)
    cat_path.write_text(json.dumps(catalog), encoding="utf-8")
    plan = ms.plan_switch(load_catalog(tmp_path), "blocked-src", "in-repo", fmt="jsonl")
    assert plan["path"] == "skip"
    assert plan["migration"] == "blocked"


def test_migrate_jsonl_round_trip_fidelity(repo_root: Path, tmp_path: Path) -> None:
    """One — in-repo migrate path preserves count/hash through export and import."""
    workspace = _seed_workspace(tmp_path, repo_root)
    export_path = workspace / "export.jsonl"
    target_store = workspace / "target-store"
    result = ms.migrate_export_step(
        workspace,
        source_id="in-repo",
        target_id="in-repo",
        fmt="jsonl",
        export_path=export_path,
        store_path=workspace / ".cursor/sw-memory",
    )
    assert result["verdict"] == "pass"
    state = ms.read_switch_state(workspace)
    assert state and state["snapshotPreserved"] is True
    ms.migrate_switch_step(workspace, "in-repo", dry_run=True)
    dry = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=target_store,
        dry_run=True,
        confirm=False,
    )
    assert dry["preview"]["plannedImport"] == state["exportCount"]
    confirmed = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=target_store,
        dry_run=False,
        confirm=True,
    )
    assert confirmed["fidelity"]["verdict"] == "pass"
    assert confirmed["snapshotPreserved"] is False


def test_skip_ack_requires_acknowledgement(repo_root: Path, tmp_path: Path) -> None:
    """S — no-migration path halts until acknowledged."""
    workspace = _seed_workspace(tmp_path, repo_root)
    halted = ms.skip_ack_step(workspace, "recallium", "in-repo", acknowledged=False)
    assert halted["verdict"] == "halt"
    assert halted["requiresAcknowledgement"] is True
    done = ms.skip_ack_step(workspace, "recallium", "in-repo", acknowledged=True)
    assert done["verdict"] == "pass"
    assert done["switch"]["next"] == "in-repo"


def test_partial_failure_preserves_snapshot(repo_root: Path, tmp_path: Path) -> None:
    """E — partial import failure keeps snapshot preserved."""
    workspace = _seed_workspace(tmp_path, repo_root)
    export_path = workspace / "export.jsonl"
    ms.migrate_export_step(
        workspace,
        source_id="in-repo",
        target_id="in-repo",
        fmt="jsonl",
        export_path=export_path,
        store_path=workspace / ".cursor/sw-memory",
    )
    state = ms.read_switch_state(workspace)
    fidelity = ms.check_fidelity(state, {"imported": int(state["exportCount"]) - 1})
    assert fidelity["verdict"] == "fail"
    state["phase"] = "partial-fail"
    ms.write_switch_state(workspace, state)
    preserved = ms.read_switch_state(workspace)
    assert preserved["snapshotPreserved"] is True
    assert preserved["phase"] == "partial-fail"


def test_zero_empty_export_fidelity(repo_root: Path, tmp_path: Path) -> None:
    """Z — empty export/import passes fidelity."""
    state = {"exportCount": 0, "exportHash": "abc", "migration": "supported"}
    result = ms.check_fidelity(state, {"imported": 0})
    assert result["verdict"] == "pass"
