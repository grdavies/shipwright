"""PRD 074 R26/R27 — MemPalace synthesized interchange + memory_switch target import."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mempalace_interchange as mpi
import memory_switch as ms
from memory_provider_catalog import load_catalog

FIXTURE = SCRIPTS / "test/fixtures/in-repo-memory"


def _seed_workspace(tmp_path: Path, repo_root: Path, *, provider: str = "in-repo", palace_path: Path | None = None) -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURE / "store", workspace / ".cursor/sw-memory")
    (workspace / ".cursor").mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / ".sw", workspace / ".sw")
    config = json.loads((FIXTURE / "config-in-repo.json").read_text(encoding="utf-8"))
    config["memory"]["provider"] = provider
    if provider == "mempalace":
        palace = palace_path or (workspace / "palace")
        palace.mkdir(parents=True, exist_ok=True)
        config["memory"]["mempalace"] = {"palacePath": str(palace)}
    (workspace / ".cursor/workflow.config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return workspace


def test_capabilities_mempalace_to_in_repo_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "mempalace", "in-repo")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "mempalace", "in-repo")
    assert plan["path"] == "migrate"
    assert plan["migration"] == "lossy"


def test_capabilities_recallium_to_mempalace_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "recallium", "mempalace")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "recallium", "mempalace")
    assert plan["path"] == "migrate"


def test_in_repo_export_to_mempalace_import_preserves_links(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="mempalace")
    palace = workspace / "palace"
    export_path = workspace / "export.jsonl"
    ms.migrate_export_step(
        workspace,
        source_id="in-repo",
        target_id="mempalace",
        fmt="jsonl",
        export_path=export_path,
        store_path=workspace / ".cursor/sw-memory",
    )
    ms.migrate_switch_step(workspace, "mempalace", dry_run=False)
    dry = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=palace,
        dry_run=True,
        confirm=False,
    )
    assert dry["target"] == "mempalace"
    assert dry["preview"]["plannedImport"] > 0
    confirmed = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=palace,
        dry_run=False,
        confirm=True,
    )
    assert confirmed["fidelity"]["verdict"] in {"pass", "lossy_warning"}
    links = mpi.load_kg_links(palace)
    ids = set(mpi.list_drawer_ids(palace))
    assert "20260701-link-a" in ids
    assert "20260701-link-b" in ids
    assert any(link["source"] == "20260701-link-a" and link["target"] == "20260701-link-b" for link in links)


def test_mempalace_merge_remaps_conflicting_ids_and_resolves_links(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="mempalace")
    palace = workspace / "palace"
    mpi.ensure_palace(palace)
    mpi.write_drawer(
        palace,
        {
            "id": "20260701-link-a",
            "wing": "fixture-repo",
            "room": "learning",
            "content": "existing occupant",
            "fields": {},
        },
    )
    export_path = workspace / "export.jsonl"
    ms.export_in_repo_store(workspace / ".cursor/sw-memory", "jsonl", export_path)
    result = mpi.import_palace(palace, "jsonl", export_path, dry_run=False, wing="fixture-repo")
    remapped = {entry["from"]: entry["to"] for entry in result["idRemaps"]}
    assert "20260701-link-a" in remapped
    new_a = remapped["20260701-link-a"]
    links = mpi.load_kg_links(palace)
    assert any(link["source"] == new_a and link["target"] == "20260701-link-b" for link in links)


def test_mempalace_export_round_trip_jsonl(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="mempalace")
    palace = workspace / "palace"
    source_export = workspace / "source.jsonl"
    ms.export_in_repo_store(workspace / ".cursor/sw-memory", "jsonl", source_export)
    mpi.import_palace(palace, "jsonl", source_export, dry_run=False, wing="fixture-repo")
    out_export = workspace / "palace-export.jsonl"
    meta = mpi.export_palace(palace, "jsonl", out_export, wing="fixture-repo")
    assert meta["count"] >= 3
    text = out_export.read_text(encoding="utf-8")
    assert "20260701-link-a" in text
    assert "20260701-link-b" in text


def test_skip_ack_mempalace_to_recallium_halts_until_ack(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root)
    halted = ms.skip_ack_step(workspace, "mempalace", "recallium", acknowledged=False)
    assert halted["verdict"] == "halt"
    assert halted["requiresAcknowledgement"] is True
    done = ms.skip_ack_step(workspace, "mempalace", "recallium", acknowledged=True)
    assert done["verdict"] == "pass"
    assert done["switch"]["next"] == "recallium"


def test_import_by_target_rejects_unsupported_provider(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root)
    with pytest.raises(ms.SwitchError) as exc:
        ms.import_by_target(
            workspace,
            target_id="recallium",
            fmt="jsonl",
            source_path=workspace / "missing.jsonl",
            store_path=workspace / "store",
            dry_run=True,
            config=ms.load_config(workspace),
        )
    assert exc.value.cause == "unsupported"
