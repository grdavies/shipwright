"""PRD 082 R30 — sourceOfTruth default flip behind fail-closed migration gate."""
from __future__ import annotations

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

THIRD_PROVIDER_ID = "fixture-third-migration"
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


def _init_git(workspace: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(workspace), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(workspace), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(workspace), check=True)


def _install_workspace(
    workspace: Path,
    repo_root: Path,
    *,
    source_class: str,
    source_of_truth: str | None,
) -> None:
    catalog = json.loads(json.dumps(load_catalog(repo_root)))
    catalog["providers"][THIRD_PROVIDER_ID] = {
        "adapterDoc": f"core/providers/{THIRD_PROVIDER_ID}.md",
        "rulesScript": f"providers/{THIRD_PROVIDER_ID}-rules.py",
        "capabilities": dict(CAPABILITY_FLAGS),
        "hookTransport": {
            "agentSession": "mcp",
            "ruleFetch": "out-of-band-script",
            "notes": "Migration gate fixture provider.",
        },
        "interchange": {"jsonl": "unsupported", "okf": "unsupported"},
        "sourceOfTruthClass": source_class,
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
    ):
        src = repo_root / rel
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    cursor = workspace / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    memory_cfg: dict = {"provider": THIRD_PROVIDER_ID, "project": "migration-test"}
    if source_of_truth is not None:
        memory_cfg["sourceOfTruth"] = source_of_truth
    (cursor / "workflow.config.json").write_text(
        json.dumps({"memory": memory_cfg}),
        encoding="utf-8",
    )
    _init_git(workspace)


def test_unset_knob_repo_authoritative_defaults_repo(repo_root: Path, tmp_path: Path) -> None:
    """Z — unset knob on repo-authoritative provider resolves to repo without gate."""
    workspace = tmp_path / "repo-auth"
    _install_workspace(workspace, repo_root, source_class="repo-authoritative", source_of_truth=None)

    knob, explicit = ms.source_of_truth_knob_state(json.loads((workspace / ".cursor/workflow.config.json").read_text()))
    assert knob is None and explicit is False
    provider = ms.resolve_memory_provider(workspace)
    assert ms.resolve_effective_sot(None, provider, "decision", root=workspace, knob_explicit=False) == "repo"
    assert ms.migration_gate_blocks(workspace, ms.load_config(workspace)) is None


def test_memory_authoritative_unset_knob_fails_closed(repo_root: Path, tmp_path: Path) -> None:
    """O — memory-authoritative provider with unset knob fails closed and names export."""
    workspace = tmp_path / "mem-auth"
    _install_workspace(workspace, repo_root, source_class="memory-authoritative", source_of_truth=None)

    blocked = ms.migration_gate_blocks(workspace, ms.load_config(workspace))
    assert blocked is not None
    assert blocked["exportCommand"] == ms.MIGRATION_EXPORT_COMMAND
    assert "memory-decision-snapshot.py export" in blocked["exportCommand"]

    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/memory-sot.py"), "resolve", "--class", "decision", "--json"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"
    assert payload["exportCommand"] == ms.MIGRATION_EXPORT_COMMAND


def test_explicit_auto_bypasses_migration_gate(repo_root: Path, tmp_path: Path) -> None:
    """E — explicit auto bypasses the migration gate on memory-authoritative providers."""
    workspace = tmp_path / "explicit-auto"
    _install_workspace(workspace, repo_root, source_class="memory-authoritative", source_of_truth="auto")

    assert ms.migration_gate_blocks(workspace, ms.load_config(workspace)) is None
    provider = ms.resolve_memory_provider(workspace)
    assert (
        ms.resolve_effective_sot("auto", provider, "decision", root=workspace, knob_explicit=True) == "memory"
    )


def test_export_materializes_decision_bodies(repo_root: Path, tmp_path: Path) -> None:
    """S — export writes provider decision memories into docs/decisions/."""
    workspace = tmp_path / "export"
    _install_workspace(workspace, repo_root, source_class="memory-authoritative", source_of_truth=None)

    mem_dir = workspace / ".cursor" / "sw-memory" / "memories"
    mem_dir.mkdir(parents=True)
    (mem_dir / "010-api-auth.md").write_text(
        """---
category: decision
relatedFiles: [docs/decisions/010-api-auth.md]
---
    Use JWT with short expiry for API auth tokens.
""",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/memory-decision-snapshot.py"), "export"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["count"] == 1
    assert payload["written"][0]["path"] == "docs/decisions/010-api-auth.md"
    target = workspace / "docs/decisions/010-api-auth.md"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "authoritative: repo" in text
    assert "JWT with short expiry" in text


def test_export_then_explicit_repo_resolves_green(repo_root: Path, tmp_path: Path) -> None:
    """I — export plus explicit repo knob clears the gate and resolves repo SoT."""
    workspace = tmp_path / "flip"
    _install_workspace(workspace, repo_root, source_class="memory-authoritative", source_of_truth=None)

    mem_dir = workspace / ".cursor" / "sw-memory" / "memories"
    mem_dir.mkdir(parents=True)
    (mem_dir / "011-flip.md").write_text(
        """---
category: decision
relatedFiles: [docs/decisions/011-flip.md]
---
Decision body to materialize before flip.
""",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(repo_root / "scripts/memory-decision-snapshot.py"), "export"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=True,
    )
    config_path = workspace / ".cursor/workflow.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["memory"]["sourceOfTruth"] = "repo"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/memory-sot.py"), "resolve", "--class", "decision", "--json"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert payload["effective"] == "repo"
    assert payload["sourceOfTruth"] == "repo"
    assert (workspace / "docs/decisions/011-flip.md").is_file()
