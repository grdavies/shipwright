"""Byte-identical disabled-surface baseline (PRD 342 R1).

With every flag-gated surface disabled, template resolution and deliver-phase
composition stay byte-identical to the pre-change / core baseline.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import converge_phase as cp
import template_resolve as tr


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_core_templates(repo: Path) -> None:
    core = tr.core_templates_dir(repo)
    core.mkdir(parents=True, exist_ok=True)
    (core / "pr-body.md").write_text("CORE-PR-BODY\n", encoding="utf-8")
    (core / "merge-commit.md").write_text("CORE-MERGE\n", encoding="utf-8")


def _disabled_config() -> dict:
    """Every flag-gated surface introduced by this program, off."""
    return {
        "converge": {"enabled": False},
        "templates": {
            # Empty / default dirs — no overrides, no packs installed.
        },
    }


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    _git_init(root)
    _seed_core_templates(root)
    unit = root / "docs" / "prds" / "342-demo"
    unit.mkdir(parents=True)
    _write(
        unit / "tasks-342-demo.md",
        "---\nid: tasks-342-demo\ntype: tasks\nstatus: draft\ntitle: Tasks\n"
        "visibility: public\nfrozen: true\n---\n\n# Tasks\n\n### 1. Alpha\n\n"
        "- [ ] 1.1 Do thing\n  - **File:** `scripts/a.py`\n",
    )
    _write(root / "scripts" / "a.py", "print('a')\n")
    _write(root / "scripts" / "b.py", "print('b')\n")
    for rel in (
        ".shipwright/workflow.config.json",
        ".cursor/workflow.config.json",
        "workflow.config.json",
    ):
        _write(root / rel, json.dumps(_disabled_config(), indent=2) + "\n")
    return root


def test_template_granularity_byte_identical_when_surfaces_disabled(repo: Path) -> None:
    """R1/R38 — no overrides/packs ⇒ every resolved template equals core bytes."""
    resolved = tr.resolve_all(repo)
    assert resolved, "expected at least core templates"
    for item in resolved:
        core_file = tr.core_templates_dir(repo) / item.path
        assert core_file.is_file()
        assert item.layer == tr.LAYER_CORE
        assert item.bytes == core_file.read_bytes()


def test_deliver_phase_granularity_byte_identical_when_surfaces_disabled(
    repo: Path,
) -> None:
    """R1/R42 — converge off ⇒ deliver phase sequence and graph equal baseline."""
    items = [
        {
            "id": "1",
            "slug": "alpha",
            "title": "Alpha",
            "branch": "feat/demo-phase-alpha",
            "files": ["scripts/a.py"],
        },
        {
            "id": "2",
            "slug": "beta",
            "title": "Beta",
            "branch": "feat/demo-phase-beta",
            "files": ["scripts/b.py"],
        },
    ]
    task_list = "docs/prds/342-demo/tasks-342-demo.md"
    baseline_seq = [item["slug"] for item in items]
    disabled = _disabled_config()

    assert (
        cp.deliver_phase_sequence(repo, items, task_list=task_list, config={})
        == baseline_seq
    )
    assert (
        cp.deliver_phase_sequence(
            repo, items, task_list=task_list, config=disabled
        )
        == baseline_seq
    )
    # Serialize for byte-identical comparison at deliver-phase granularity.
    assert json.dumps(baseline_seq).encode() == json.dumps(
        cp.deliver_phase_sequence(repo, items, task_list=task_list, config=disabled)
    ).encode()

    from graph.legacy_adapters import compile_legacy_plan

    plan = {
        "phases": [
            {"id": "1", "slug": "alpha", "name": "Alpha"},
            {"id": "2", "slug": "beta", "name": "Beta"},
        ],
        "maxConcurrency": 1,
        "maxDurationSeconds": 3600,
        "safety": {
            "humanMergeGate": True,
            "lockOwner": "test",
            "resumeCursor": "start",
        },
    }
    baseline_graph = compile_legacy_plan(plan, plan_type="delivery").graph
    attached = cp.maybe_attach_converge_nodes(repo, baseline_graph, config=disabled)
    assert attached == baseline_graph
    assert json.dumps(attached, sort_keys=True).encode() == json.dumps(
        baseline_graph, sort_keys=True
    ).encode()
    assert cp.is_converge_enabled(repo, disabled) is False
