"""PRD 082 R30 — doctor classifies memory.sourceOfTruth knob states."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_sot as ms
from memory_provider_catalog import load_catalog

THIRD_PROVIDER_ID = "fixture-third-classification"
CAPABILITY_FLAGS = {
    "typedMemories": True,
    "filePathSearch": True,
    "categoryFilter": True,
    "recencyControl": True,
    "rulesAtStartup": True,
    "tasks": False,
    "export": False,
    "import": False,
    "softDelete": True,
    "semanticSearch": False,
}


def _load_planning_doctor():
    path = SCRIPTS / "planning-doctor.py"
    spec = importlib.util.spec_from_file_location("planning_doctor_classification", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _init_git(workspace: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(workspace), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(workspace), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(workspace), check=True)


def _install_workspace(
    workspace: Path,
    repo_root: Path,
    *,
    source_class: str,
    source_of_truth: str | None,
) -> dict:
    catalog = json.loads(json.dumps(load_catalog(repo_root)))
    catalog["providers"][THIRD_PROVIDER_ID] = {
        "adapterDoc": f"core/providers/{THIRD_PROVIDER_ID}.md",
        "rulesScript": f"providers/{THIRD_PROVIDER_ID}-rules.py",
        "capabilities": dict(CAPABILITY_FLAGS),
        "hookTransport": {
            "agentSession": "mcp",
            "ruleFetch": "out-of-band-script",
            "notes": "Classification fixture provider.",
        },
        "interchange": {"jsonl": "unsupported", "okf": "unsupported"},
        "sourceOfTruthClass": source_class,
        "supportStatus": "ga",
        "credentials": {"location": "env-only", "notes": "fixture"},
    }

    catalog_path = workspace / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    for rel in (
        "scripts/memory_provider_catalog.py",
        "scripts/memory_provider_register.py",
        "scripts/capability_index.py",
        "scripts/sw_resolve_plugin_root.py",
        "scripts/memory_sot.py",
        "scripts/planning-doctor.py",
    ):
        src = repo_root / rel
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    memory_cfg: dict = {"provider": THIRD_PROVIDER_ID, "project": "classification-test"}
    if source_of_truth is not None:
        memory_cfg["sourceOfTruth"] = source_of_truth
    config = {"memory": memory_cfg}
    (cursor / "workflow.config.json").write_text(json.dumps(config), encoding="utf-8")
    _init_git(workspace)
    return config


def test_explicit_auto_classified_ok(repo_root: Path, tmp_path: Path) -> None:
    """Z — explicit auto is distinct from omitted key and needs no migration action."""
    workspace = tmp_path / "explicit-auto"
    config = _install_workspace(
        workspace, repo_root, source_class="memory-authoritative", source_of_truth="auto"
    )

    finding = ms.classify_source_of_truth(workspace, config)
    assert finding["classification"] == "explicit-auto"
    assert finding["status"] == "ok"


def test_explicit_repo_classified_ok(repo_root: Path, tmp_path: Path) -> None:
    """O — explicit repo is operator-bound and needs no migration action."""
    workspace = tmp_path / "explicit-repo"
    config = _install_workspace(
        workspace, repo_root, source_class="memory-authoritative", source_of_truth="repo"
    )

    finding = ms.classify_source_of_truth(workspace, config)
    assert finding["classification"] == "explicit-bound"
    assert finding["sourceOfTruth"] == "repo"
    assert finding["status"] == "ok"


def test_omitted_key_memory_authoritative_requires_action(repo_root: Path, tmp_path: Path) -> None:
    """M — omitted key on memory-authoritative provider is the only class demanding action."""
    workspace = tmp_path / "migration-required"
    config = _install_workspace(
        workspace, repo_root, source_class="memory-authoritative", source_of_truth=None
    )

    finding = ms.classify_source_of_truth(workspace, config)
    assert finding["classification"] == "migration-required"
    assert finding["status"] == "action-required"
    assert ms.MIGRATION_EXPORT_COMMAND in finding["exportCommand"]


def test_omitted_key_repo_authoritative_implicit_default(repo_root: Path, tmp_path: Path) -> None:
    """I — omitted key on repo-authoritative provider resolves without migration."""
    workspace = tmp_path / "implicit-repo"
    config = _install_workspace(
        workspace, repo_root, source_class="repo-authoritative", source_of_truth=None
    )

    finding = ms.classify_source_of_truth(workspace, config)
    assert finding["classification"] == "implicit-repo-default"
    assert finding["status"] == "ok"


def test_planning_doctor_surfaces_migration_required(repo_root: Path, tmp_path: Path) -> None:
    """E — planning-doctor fails closed only for migration-required classification."""
    workspace = tmp_path / "doctor-migration"
    _install_workspace(workspace, repo_root, source_class="memory-authoritative", source_of_truth=None)

    doctor = _load_planning_doctor()
    report = doctor.doctor(workspace, sweep=False)
    sot_checks = [c for c in report.get("checks", []) if c.get("check") == "memory-source-of-truth"]
    assert len(sot_checks) == 1
    assert sot_checks[0]["classification"] == "migration-required"
    assert report["verdict"] == "fail"
    assert "memory-source-of-truth-migration-required" in report.get("warnings", [])


def test_planning_doctor_explicit_auto_passes(repo_root: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "doctor-auto"
    _install_workspace(workspace, repo_root, source_class="memory-authoritative", source_of_truth="auto")

    doctor = _load_planning_doctor()
    report = doctor.doctor(workspace, sweep=False)
    sot_checks = [c for c in report.get("checks", []) if c.get("check") == "memory-source-of-truth"]
    assert sot_checks[0]["classification"] == "explicit-auto"
    assert report["verdict"] != "fail"
