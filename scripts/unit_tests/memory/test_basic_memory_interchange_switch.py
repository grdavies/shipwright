"""PRD 075 R29–R31 — basic-memory synthesized interchange + memory_switch target import."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import basic_memory_interchange as bmi
import memory_switch as ms
from memory_provider_catalog import load_catalog

FIXTURE = SCRIPTS / "test/fixtures/in-repo-memory"


def _seed_workspace(
    tmp_path: Path,
    repo_root: Path,
    *,
    provider: str = "in-repo",
    project_path: Path | None = None,
) -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURE / "store", workspace / ".cursor/sw-memory")
    (workspace / ".cursor").mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / ".sw", workspace / ".sw")
    config = json.loads((FIXTURE / "config-in-repo.json").read_text(encoding="utf-8"))
    config["memory"]["provider"] = provider
    if provider == "basic-memory":
        project = project_path or (workspace / "bm-project")
        project.mkdir(parents=True, exist_ok=True)
        config["memory"]["basicMemory"] = {
            "mode": "local",
            "projectPath": str(project),
            "memoriesDirectory": "memories",
            "rulesDirectory": "rules",
        }
    (workspace / ".cursor/workflow.config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return workspace


def test_capabilities_in_repo_to_basic_memory_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "in-repo", "basic-memory")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    assert caps["formats"]["okf"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "in-repo", "basic-memory")
    assert plan["path"] == "migrate"
    assert plan["migration"] == "lossy"


def test_capabilities_recallium_to_basic_memory_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "recallium", "basic-memory")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "recallium", "basic-memory")
    assert plan["path"] == "migrate"
    assert plan["migration"] == "lossy"


def test_capabilities_basic_memory_to_in_repo_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "basic-memory", "in-repo")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "basic-memory", "in-repo")
    assert plan["path"] == "migrate"


def test_in_repo_export_to_basic_memory_import_preserves_links(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="basic-memory")
    project = workspace / "bm-project"
    export_path = workspace / "export.jsonl"
    ms.migrate_export_step(
        workspace,
        source_id="in-repo",
        target_id="basic-memory",
        fmt="jsonl",
        export_path=export_path,
        store_path=workspace / ".cursor/sw-memory",
    )
    ms.migrate_switch_step(workspace, "basic-memory", dry_run=False)
    dry = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=project,
        dry_run=True,
        confirm=False,
    )
    assert dry["target"] == "basic-memory"
    assert dry["preview"]["plannedImport"] > 0
    confirmed = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=project,
        dry_run=False,
        confirm=True,
    )
    assert confirmed["fidelity"]["verdict"] in {"pass", "lossy_warning"}
    links = bmi.load_links(project)
    ids = set(bmi.list_permalinks(project))
    assert "20260701-link-a" in ids
    assert "20260701-link-b" in ids
    assert any(link["source"] == "20260701-link-a" and link["target"] == "20260701-link-b" for link in links)
    # Category folders under memories/
    assert (project / "memories" / "learning" / "20260701-link-a.md").is_file()


def test_basic_memory_merge_remaps_conflicting_permalinks_and_resolves_links(
    repo_root: Path, tmp_path: Path
) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="basic-memory")
    project = workspace / "bm-project"
    bmi.ensure_project(project)
    bmi.write_note(
        project,
        {
            "permalink": "20260701-link-a",
            "category": "learning",
            "frontmatter": {
                "title": "existing occupant",
                "type": "learning",
                "permalink": "20260701-link-a",
            },
            "body": "existing occupant",
            "links": None,
        },
    )
    export_path = workspace / "export.jsonl"
    ms.export_in_repo_store(workspace / ".cursor/sw-memory", "jsonl", export_path)
    result = bmi.import_project(project, "jsonl", export_path, dry_run=False)
    remapped = {entry["from"]: entry["to"] for entry in result["idRemaps"]}
    assert "20260701-link-a" in remapped
    new_a = remapped["20260701-link-a"]
    links = bmi.load_links(project)
    assert any(link["source"] == new_a and link["target"] == "20260701-link-b" for link in links)
    assert result["imported"] > 0


def test_basic_memory_export_round_trip_jsonl(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="basic-memory")
    project = workspace / "bm-project"
    source_export = workspace / "source.jsonl"
    ms.export_in_repo_store(workspace / ".cursor/sw-memory", "jsonl", source_export)
    bmi.import_project(project, "jsonl", source_export, dry_run=False)
    out_export = workspace / "bm-export.jsonl"
    meta = bmi.export_project(project, "jsonl", out_export)
    assert meta["count"] >= 3
    text = out_export.read_text(encoding="utf-8")
    assert "20260701-link-a" in text
    assert "20260701-link-b" in text


def test_rules_excluded_from_ordinary_export(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="basic-memory")
    project = workspace / "bm-project"
    bmi.ensure_project(project)
    bmi.write_note(
        project,
        {
            "permalink": "ordinary-learning",
            "category": "learning",
            "frontmatter": {"title": "Ordinary", "type": "learning", "permalink": "ordinary-learning"},
            "body": "ordinary",
            "links": None,
        },
    )
    bmi.write_note(
        project,
        {
            "permalink": "secret-rule",
            "category": "rule",
            "frontmatter": {"title": "Rule", "type": "rule", "permalink": "secret-rule"},
            "body": "do not export me by default",
            "links": None,
        },
    )
    out = workspace / "no-rules.jsonl"
    meta = bmi.export_project(project, "jsonl", out, include_rules=False)
    text = out.read_text(encoding="utf-8")
    assert "ordinary-learning" in text
    assert "secret-rule" not in text
    assert meta["count"] == 1
    with_rules = workspace / "with-rules.jsonl"
    meta_rules = bmi.export_project(project, "jsonl", with_rules, include_rules=True)
    assert "secret-rule" in with_rules.read_text(encoding="utf-8")
    assert meta_rules["count"] == 2


def test_recallium_synthesized_export_imports_into_basic_memory(repo_root: Path, tmp_path: Path) -> None:
    """recallium↔basic-memory: pre-built synthesized JSONL (no live Recallium) → BM import."""
    workspace = _seed_workspace(tmp_path, repo_root, provider="basic-memory")
    project = workspace / "bm-project"
    export_path = workspace / "recallium-export.jsonl"
    # Hermetic stand-in for a Recallium synthesized export (lossy edges OK).
    records = [
        {
            "id": "rec-a",
            "content": "Recallium note A",
            "category": "learning",
            "title": "Rec A",
            "links": [{"to": "rec-b", "edge": "relates-to"}],
        },
        {
            "id": "rec-b",
            "content": "Recallium note B",
            "category": "decision",
            "title": "Rec B",
        },
    ]
    export_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in records) + "\n",
        encoding="utf-8",
    )
    # Export-by-source for recallium consumes a pre-existing artifact.
    export_meta = ms.export_by_source(
        workspace,
        source_id="recallium",
        fmt="jsonl",
        export_path=export_path,
        store_path=None,
        config=ms.load_config(workspace),
    )
    assert export_meta["provider"] == "recallium"
    assert export_meta["count"] == 2
    ms.write_switch_state(
        workspace,
        {
            "phase": "export",
            "source": "recallium",
            "target": "basic-memory",
            "format": "jsonl",
            "exportPath": str(export_path),
            "exportHash": export_meta["sha256"],
            "exportCount": export_meta["count"],
            "snapshotPreserved": True,
            "migration": "lossy",
        },
    )
    ms.migrate_switch_step(workspace, "basic-memory", dry_run=False)
    confirmed = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=project,
        dry_run=False,
        confirm=True,
    )
    assert confirmed["fidelity"]["verdict"] in {"pass", "lossy_warning"}
    ids = set(bmi.list_permalinks(project))
    assert "rec-a" in ids
    assert "rec-b" in ids
    links = bmi.load_links(project)
    assert any(link["source"] == "rec-a" and link["target"] == "rec-b" for link in links)


def test_skip_ack_basic_memory_blocked_pair_halts_until_ack(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root)
    # Inject a blocked target so skip-ack path is exercised for basic-memory source planning.
    catalog = load_catalog(repo_root)
    catalog["providers"]["blocked-dst"] = {
        "adapterDoc": "core/providers/in-repo.md",
        "rulesScript": "providers/in-repo-rules.py",
        "capabilities": dict(catalog["providers"]["in-repo"]["capabilities"]),
        "hookTransport": dict(catalog["providers"]["in-repo"]["hookTransport"]),
        "interchange": {"jsonl": "unsupported", "okf": "unsupported"},
        "sourceOfTruthClass": "repo-authoritative",
        "credentials": {"location": "none", "notes": "fixture"},
    }
    plan = ms.plan_switch(catalog, "basic-memory", "blocked-dst")
    assert plan["path"] == "skip"
    halted = ms.skip_ack_step(workspace, "basic-memory", "in-repo", acknowledged=False)
    assert halted["verdict"] == "halt"
    assert halted["requiresAcknowledgement"] is True
    done = ms.skip_ack_step(workspace, "basic-memory", "in-repo", acknowledged=True)
    assert done["verdict"] == "pass"
    assert done["switch"]["next"] == "in-repo"


def test_shared_local_cloud_interchange_semantics(repo_root: Path, tmp_path: Path) -> None:
    """R31: interchange is projectPath synthesis — mode does not fork the protocol."""
    workspace = _seed_workspace(tmp_path, repo_root, provider="basic-memory")
    project = workspace / "bm-project"
    config = ms.load_config(workspace)
    config["memory"]["basicMemory"]["mode"] = "cloud"
    (workspace / ".cursor/workflow.config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    export_path = workspace / "export.jsonl"
    ms.export_in_repo_store(workspace / ".cursor/sw-memory", "jsonl", export_path)
    # Import still uses hermetic projectPath (no live cloud).
    result = ms.import_by_target(
        workspace,
        target_id="basic-memory",
        fmt="jsonl",
        source_path=export_path,
        store_path=project,
        dry_run=False,
        config=ms.load_config(workspace),
    )
    assert result["imported"] > 0
    assert Path(result["projectPath"]) == project.resolve()
