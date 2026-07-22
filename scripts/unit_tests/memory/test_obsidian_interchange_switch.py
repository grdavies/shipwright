"""PRD 076 R27–R28 — obsidian synthesized interchange + memory_switch target import."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_switch as ms
import obsidian_interchange as oi
from memory_provider_catalog import load_catalog

FIXTURE = SCRIPTS / "test/fixtures/in-repo-memory"


def _seed_workspace(
    tmp_path: Path,
    repo_root: Path,
    *,
    provider: str = "in-repo",
    vault_path: Path | None = None,
) -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURE / "store", workspace / ".cursor/sw-memory")
    (workspace / ".cursor").mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / ".sw", workspace / ".sw")
    config = json.loads((FIXTURE / "config-in-repo.json").read_text(encoding="utf-8"))
    config["memory"]["provider"] = provider
    if provider == "obsidian":
        vault = vault_path or (workspace / "obsidian-vault")
        vault.mkdir(parents=True, exist_ok=True)
        config["memory"]["obsidian"] = {
            "vaultPath": str(vault.resolve()),
            "memoriesDirectory": "memories",
            "rulesDirectory": "rules",
        }
    (workspace / ".cursor/workflow.config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return workspace


def test_capabilities_in_repo_to_obsidian_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "in-repo", "obsidian")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    assert caps["formats"]["okf"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "in-repo", "obsidian")
    assert plan["path"] == "migrate"
    assert plan["migration"] == "lossy"


def test_capabilities_recallium_to_obsidian_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "recallium", "obsidian")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "recallium", "obsidian")
    assert plan["path"] == "migrate"
    assert plan["migration"] == "lossy"


def test_capabilities_obsidian_to_in_repo_is_lossy(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    caps = ms.display_capabilities(catalog, "obsidian", "in-repo")
    assert caps["formats"]["jsonl"]["migration"] == "lossy"
    plan = ms.plan_switch(catalog, "obsidian", "in-repo")
    assert plan["path"] == "migrate"


def test_in_repo_export_to_obsidian_import_preserves_links(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="obsidian")
    vault = Path(ms.load_config(workspace)["memory"]["obsidian"]["vaultPath"])
    project = ms._memory_project(ms.load_config(workspace))
    export_path = workspace / "export.jsonl"
    ms.migrate_export_step(
        workspace,
        source_id="in-repo",
        target_id="obsidian",
        fmt="jsonl",
        export_path=export_path,
        store_path=workspace / ".cursor/sw-memory",
    )
    ms.migrate_switch_step(workspace, "obsidian", dry_run=False)
    dry = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=vault,
        dry_run=True,
        confirm=False,
    )
    assert dry["target"] == "obsidian"
    assert dry["preview"]["plannedImport"] > 0
    confirmed = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=vault,
        dry_run=False,
        confirm=True,
    )
    assert confirmed["fidelity"]["verdict"] in {"pass", "lossy_warning"}
    links = oi.load_links(vault)
    ids = set(oi.list_path_ids(vault, project=project))
    path_a = f"memories/{project}/learning/20260701-link-a.md"
    path_b = f"memories/{project}/learning/20260701-link-b.md"
    assert path_a in ids
    assert path_b in ids
    assert any(link["source"] == path_a and link["target"] == path_b for link in links)
    assert (vault / "memories" / project / "learning" / "20260701-link-a.md").is_file()


def test_obsidian_merge_remaps_conflicting_path_ids_and_resolves_links(
    repo_root: Path, tmp_path: Path
) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="obsidian")
    vault = Path(ms.load_config(workspace)["memory"]["obsidian"]["vaultPath"])
    project = ms._memory_project(ms.load_config(workspace))
    oi.ensure_vault(vault, project=project)
    existing_path = f"memories/{project}/learning/20260701-link-a.md"
    oi.write_note(
        vault,
        {
            "pathId": existing_path,
            "category": "learning",
            "frontmatter": {
                "title": "existing occupant",
                "type": "learning",
                "permalink": "20260701-link-a",
                "category": "learning",
            },
            "body": "existing occupant",
            "links": None,
        },
    )
    export_path = workspace / "export.jsonl"
    ms.export_in_repo_store(workspace / ".cursor/sw-memory", "jsonl", export_path)
    result = oi.import_vault(vault, "jsonl", export_path, project=project, dry_run=False)
    remapped = {entry["from"]: entry["to"] for entry in result["idRemaps"]}
    assert existing_path in remapped
    new_a = remapped[existing_path]
    links = oi.load_links(vault)
    path_b = f"memories/{project}/learning/20260701-link-b.md"
    assert any(link["source"] == new_a and link["target"] == path_b for link in links)
    assert result["imported"] > 0


def test_obsidian_export_round_trip_jsonl(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="obsidian")
    vault = Path(ms.load_config(workspace)["memory"]["obsidian"]["vaultPath"])
    project = ms._memory_project(ms.load_config(workspace))
    source_export = workspace / "source.jsonl"
    ms.export_in_repo_store(workspace / ".cursor/sw-memory", "jsonl", source_export)
    oi.import_vault(vault, "jsonl", source_export, project=project, dry_run=False)
    out_export = workspace / "obs-export.jsonl"
    meta = oi.export_vault(vault, "jsonl", out_export, project=project)
    assert meta["count"] >= 3
    text = out_export.read_text(encoding="utf-8")
    assert "20260701-link-a" in text
    assert "20260701-link-b" in text


def test_rules_excluded_from_ordinary_export(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root, provider="obsidian")
    vault = Path(ms.load_config(workspace)["memory"]["obsidian"]["vaultPath"])
    project = ms._memory_project(ms.load_config(workspace))
    oi.ensure_vault(vault, project=project)
    oi.write_note(
        vault,
        {
            "pathId": f"memories/{project}/learning/ordinary-learning.md",
            "category": "learning",
            "frontmatter": {
                "title": "Ordinary",
                "type": "learning",
                "permalink": "ordinary-learning",
                "category": "learning",
            },
            "body": "ordinary",
            "links": None,
        },
    )
    oi.write_note(
        vault,
        {
            "pathId": "rules/secret-rule.md",
            "category": "rule",
            "frontmatter": {
                "title": "Rule",
                "type": "rule",
                "permalink": "secret-rule",
                "category": "rule",
            },
            "body": "do not export me by default",
            "links": None,
        },
    )
    out = workspace / "no-rules.jsonl"
    meta = oi.export_vault(vault, "jsonl", out, project=project, include_rules=False)
    text = out.read_text(encoding="utf-8")
    assert "ordinary-learning" in text
    assert "secret-rule" not in text
    assert meta["count"] == 1
    with_rules = workspace / "with-rules.jsonl"
    meta_rules = oi.export_vault(vault, "jsonl", with_rules, project=project, include_rules=True)
    assert "secret-rule" in with_rules.read_text(encoding="utf-8")
    assert meta_rules["count"] == 2


def test_recallium_synthesized_export_imports_into_obsidian(repo_root: Path, tmp_path: Path) -> None:
    """recallium↔obsidian: pre-built synthesized JSONL (no live Recallium) → obsidian import."""
    workspace = _seed_workspace(tmp_path, repo_root, provider="obsidian")
    vault = Path(ms.load_config(workspace)["memory"]["obsidian"]["vaultPath"])
    project = ms._memory_project(ms.load_config(workspace))
    export_path = workspace / "recallium-export.jsonl"
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
            "target": "obsidian",
            "format": "jsonl",
            "exportPath": str(export_path),
            "exportHash": export_meta["sha256"],
            "exportCount": export_meta["count"],
            "snapshotPreserved": True,
            "migration": "lossy",
        },
    )
    ms.migrate_switch_step(workspace, "obsidian", dry_run=False)
    confirmed = ms.migrate_import_step(
        workspace,
        fmt="jsonl",
        source_path=export_path,
        store_path=vault,
        dry_run=False,
        confirm=True,
    )
    assert confirmed["fidelity"]["verdict"] in {"pass", "lossy_warning"}
    ids = set(oi.list_path_ids(vault, project=project))
    assert f"memories/{project}/learning/rec-a.md" in ids
    assert f"memories/{project}/decision/rec-b.md" in ids
    links = oi.load_links(vault)
    path_a = f"memories/{project}/learning/rec-a.md"
    path_b = f"memories/{project}/decision/rec-b.md"
    assert any(link["source"] == path_a and link["target"] == path_b for link in links)


def test_skip_ack_obsidian_blocked_pair_halts_until_ack(repo_root: Path, tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path, repo_root)
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
    plan = ms.plan_switch(catalog, "obsidian", "blocked-dst")
    assert plan["path"] == "skip"
    halted = ms.skip_ack_step(workspace, "obsidian", "in-repo", acknowledged=False)
    assert halted["verdict"] == "halt"
    assert halted["requiresAcknowledgement"] is True
    done = ms.skip_ack_step(workspace, "obsidian", "in-repo", acknowledged=True)
    assert done["verdict"] == "pass"
    assert done["switch"]["next"] == "in-repo"
