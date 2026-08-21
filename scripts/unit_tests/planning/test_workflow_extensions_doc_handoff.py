#!/usr/bin/env python3
"""PRD 280 phase 4 — workflow extensions rollout + issue-store doc/deliver handoff (R20–R22)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from handoff_bundle import validate_bundle  # noqa: E402
from issues_lib import get_fixture_store  # noqa: E402
from planning_gap_capture import capture_external_intake  # noqa: E402
from planning_materialize import ensure_run_entry_materialized  # noqa: E402
from planning_store import get_backend  # noqa: E402
from planning_store_facade import load_workflow_config  # noqa: E402
from workflow_extensions import (  # noqa: E402
    EXTENSION_FLAGS,
    extension_enabled,
    extension_flags,
    require_extension,
)
from workflow_pack_sdk import main as pack_sdk_main  # noqa: E402


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_cfg(root: Path, *, extensions: dict[str, bool] | None = None) -> dict:
    cfg = {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "workflow-ext-fixture",
                "storeLocation": {
                    "mode": "separate-project",
                    "owner": "fixture-owner",
                    "repo": "planning",
                },
            }
        },
        "host": {"provider": "github"},
        "workflow": {
            "extensions": extensions
            or {
                "externalIntake": False,
                "handoffBundle": False,
                "packageSdk": False,
            }
        },
    }
    path = root / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg


@pytest.fixture
def ext_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.delenv("SW_WORKFLOW_EXTENSIONS", raising=False)
    for flag in EXTENSION_FLAGS:
        monkeypatch.delenv(f"SW_WORKFLOW_EXTENSION_{flag.upper()}", raising=False)
    root = _init_repo(tmp_path)
    _write_cfg(root)
    get_fixture_store(root).clear()
    return root


def test_extension_flags_default_false(ext_repo: Path) -> None:
    flags = extension_flags(root=ext_repo)
    assert set(flags) == set(EXTENSION_FLAGS)
    assert flags == {k: False for k in EXTENSION_FLAGS}
    for flag in EXTENSION_FLAGS:
        assert extension_enabled(flag, root=ext_repo) is False
        halt = require_extension(flag, root=ext_repo)
        assert halt is not None
        assert halt["error"] == "workflow-extensions:disabled"
        assert halt["flag"] == f"workflow.extensions.{flag}"


def test_operator_surfaces_fail_closed_when_disabled(ext_repo: Path) -> None:
    halted = capture_external_intake(
        ext_repo,
        signal_id="sig-disabled",
        title="Should halt",
        outcome="brief",
    )
    assert halted["verdict"] == "halt"
    assert halted["error"] == "workflow-extensions:disabled"

    from wave_status import collect_export_handoff

    handoff = collect_export_handoff(ext_repo)
    assert handoff["verdict"] == "halt"
    assert handoff["error"] == "workflow-extensions:disabled"

    rc = pack_sdk_main(["validate", str(ext_repo / "missing-pack.json"), "--root", str(ext_repo)])
    assert rc == 20


def test_issue_store_put_no_code_repo_authoritative_write(ext_repo: Path) -> None:
    task_rel = "docs/prds/280-workflow-extensions/tasks-280-workflow-extensions.md"
    body = (
        "---\n"
        "type: tasks\n"
        "id: tasks-280-workflow-extensions\n"
        "frozen: true\n"
        "visibility: public\n"
        "---\n"
        "# Tasks — Workflow Extensions fixture\n\n"
        "### 4. Cross-cutting\n"
        "- [ ] **4.1** flags\n"
        "  - **File:** .cursor/workflow.config.json\n"
    )
    cfg = load_workflow_config(ext_repo)
    backend = get_backend(ext_repo, cfg, override="issue-store")
    put = backend.put("tasks-280-workflow-extensions", task_rel, body)
    assert put.verdict == "ok"
    # Authoritative body must not land as a tracked code-repo path.
    assert not (ext_repo / task_rel).exists()
    assert not (ext_repo / "docs" / "prds" / "280-workflow-extensions").exists()


def test_deliver_entry_materialize_only(ext_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_FORCE_MATERIALIZE", "1")
    task_rel = "docs/prds/280-workflow-extensions/tasks-280-workflow-extensions.md"
    body = (
        "---\n"
        "type: tasks\n"
        "id: tasks-280-workflow-extensions\n"
        "frozen: true\n"
        "visibility: public\n"
        "---\n"
        "# Tasks — Workflow Extensions fixture\n"
    )
    cfg = load_workflow_config(ext_repo)
    backend = get_backend(ext_repo, cfg, override="issue-store")
    assert backend.put("tasks-280-workflow-extensions", task_rel, body).verdict == "ok"
    freeze = backend.freeze("tasks-280-workflow-extensions", task_rel, distill=False)
    assert freeze["verdict"] == "ok", freeze
    assert not (ext_repo / task_rel).exists()

    out = ensure_run_entry_materialized(ext_repo, task_rel)
    assert out.get("action") == "run-entry-materialize" or out.get("verdict") in {"ok", "pass"}, out
    dest = ext_repo / ".cursor" / "planning-materialized" / task_rel
    assert dest.is_file(), out
    # Still no authoritative write under docs/prds in the code repo.
    assert not (ext_repo / task_rel).exists()


def test_enabled_flags_open_surfaces(ext_repo: Path) -> None:
    _write_cfg(
        ext_repo,
        extensions={"externalIntake": True, "handoffBundle": True, "packageSdk": True},
    )
    for flag in EXTENSION_FLAGS:
        assert extension_enabled(flag, root=ext_repo) is True
        assert require_extension(flag, root=ext_repo) is None

    # Library validation remains available (schema fail-closed) regardless of CLI gate.
    schema_src = _SCRIPTS.parent / "core" / "sw-reference" / "handoff-bundle.schema.json"
    (ext_repo / "core" / "sw-reference").mkdir(parents=True, exist_ok=True)
    (ext_repo / "core" / "sw-reference" / "handoff-bundle.schema.json").write_text(
        schema_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert validate_bundle({"schemaVersion": "HandoffBundle@v1"}, root=ext_repo)["verdict"] == "fail"
