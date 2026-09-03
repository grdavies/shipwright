"""PRD 337 R21/R22 — phase HEAD provenance and shared-doc contention."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_gap_gate(repo_root: Path):
    path = repo_root / "scripts" / "gap-check-gate.py"
    spec = importlib.util.spec_from_file_location("gap_check_gate", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _load_wave_merge(repo_root: Path):
    path = repo_root / "scripts" / "wave_merge.py"
    spec = importlib.util.spec_from_file_location("wave_merge", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _load_wave_deliver(repo_root: Path):
    path = repo_root / "scripts" / "wave_deliver.py"
    spec = importlib.util.spec_from_file_location("wave_deliver", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _write_task_list(repo: Path, *, shared_doc: bool) -> str:
    rel = "docs/prds/337-demo/tasks-337-demo.md"
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    phase_b_file = (
        "docs/guides/workflows.md"
        if shared_doc
        else "docs/guides/phase-b-only.md"
    )
    path.write_text(
        f"""---
type: tasks
id: tasks-337-demo
frozen: true
---

# Tasks

### 1. Phase one

- [ ] 1.1 First
  - **File:** `docs/guides/workflows.md`

### 2. Phase two

- [ ] 2.1 Second
  - **File:** `{phase_b_file}`
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", rel], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "tasks"], check=True, capture_output=True)
    return rel


def test_phase_head_provenance_authority(tmp_git_repo: Path, repo_root: Path) -> None:
    """phase_head_provenance_authority — verified write binds phase worktree HEAD (R21)."""
    phase_slug = "phase-provenance"
    gap_gate = _load_gap_gate(repo_root)
    wt_root = tmp_git_repo / ".sw-worktrees" / "phase-wt"
    wt_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=wt_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=wt_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=wt_root, check=True)
    (wt_root / "phase.txt").write_text("phase\n", encoding="utf-8")
    subprocess.run(["git", "add", "phase.txt"], cwd=wt_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "phase"], cwd=wt_root, check=True, capture_output=True)
    phase_head = subprocess.run(
        ["git", "-C", str(wt_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    run_dir = wt_root / ".cursor" / "sw-deliver-runs" / phase_slug
    run_dir.mkdir(parents=True)
    (run_dir / "ship-steps.json").write_text(
        json.dumps(
            {
                "chain": ["gap-check"],
                "lastCompletedStep": "gap-check",
                "updatedAt": _utc_now(),
            }
        ),
        encoding="utf-8",
    )
    state_dir = tmp_git_repo / ".cursor"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sw-deliver-state.json").write_text(
        json.dumps(
            {
                "target": {"branch": "feat/demo"},
                "phases": {"1": {"id": "1", "slug": phase_slug, "status": "in-flight"}},
                "phaseWorktrees": {"1": {"path": str(wt_root), "name": "phase-wt"}},
            }
        ),
        encoding="utf-8",
    )
    from phase_ship_hygiene import try_auto_repair_gap_check_missing

    repair = try_auto_repair_gap_check_missing(tmp_git_repo, phase_slug)
    assert repair.get("verdict") == "pass", repair
    ok, cause = gap_gate.deliver_gap_check_ok(tmp_git_repo, phase_slug, require_status=True)
    assert ok, cause
    doc = json.loads((run_dir / "gap-check.status.json").read_text(encoding="utf-8"))
    assert doc.get("head") == phase_head
    assert doc.get("evaluationProvenance", {}).get("evaluationHead") == phase_head


def test_forged_gap_check_rejected(tmp_git_repo: Path, repo_root: Path) -> None:
    """phase_head_provenance_authority — forged pass without provenance rejected (R21)."""
    phase_slug = "forged-gap"
    gap_gate = _load_gap_gate(repo_root)
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status_dir = tmp_git_repo / ".cursor" / "sw-deliver-runs" / phase_slug
    status_dir.mkdir(parents=True)
    (status_dir / "gap-check.status.json").write_text(
        json.dumps({"verdict": "pass", "binding": True, "head": head, "updatedAt": _utc_now()}),
        encoding="utf-8",
    )
    ok, cause = gap_gate.deliver_gap_check_ok(tmp_git_repo, phase_slug, require_status=True)
    assert not ok
    assert cause == "gap-check-forged-pass"


def test_orchestrator_root_artifact_rejected(tmp_git_repo: Path, repo_root: Path) -> None:
    """phase_head_provenance_authority — orchestrator-root copy ignored when worktree registered."""
    phase_slug = "orch-root"
    gap_gate = _load_gap_gate(repo_root)
    wt_root = tmp_git_repo / ".sw-worktrees" / "phase-only"
    wt_root.mkdir(parents=True)
    orch_dir = tmp_git_repo / ".cursor" / "sw-deliver-runs" / phase_slug
    orch_dir.mkdir(parents=True)
    (orch_dir / "gap-check.status.json").write_text(
        json.dumps(
            {
                "verdict": "pass",
                "binding": True,
                "head": "f" * 40,
                "updatedAt": _utc_now(),
                "evaluationProvenance": {
                    "source": "ship-steps",
                    "evaluationHead": "f" * 40,
                    "evaluatedAt": _utc_now(),
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_git_repo / ".cursor" / "sw-deliver-state.json").write_text(
        json.dumps(
            {
                "target": {"branch": "feat/demo"},
                "phases": {"1": {"id": "1", "slug": phase_slug, "status": "in-flight"}},
                "phaseWorktrees": {"1": {"path": str(wt_root), "name": "phase-only"}},
            }
        ),
        encoding="utf-8",
    )
    path, data = gap_gate.discover_gap_check_status(tmp_git_repo, phase_slug)
    assert path is None
    assert data is None


def test_shared_doc_plan_serialization(tmp_git_repo: Path, repo_root: Path) -> None:
    """shared_doc_plan_serialization — colliding phases get serialization edges (R22)."""
    task_list = _write_task_list(tmp_git_repo, shared_doc=True)
    wave_deliver = _load_wave_deliver(repo_root)
    content = (tmp_git_repo / task_list).read_text(encoding="utf-8")
    phases = wave_deliver.parse_phases(content)
    dep_rows = wave_deliver.parse_phase_dependencies(content)
    phase_files = wave_deliver.parse_phase_files(content)
    edges, _ = wave_deliver.deps_to_edges(phases, dep_rows, phase_files, tmp_git_repo)
    contention = __import__("planning_paths").contention_default(tmp_git_repo)
    _waves, edges_out, injected, notices, _files = wave_deliver.apply_contention(
        content, phases, edges, contention, tmp_git_repo
    )
    serialized = any(
        e.get("kind") in ("shared-authored-doc", "contention", "file-set")
        and e.get("from") == "1"
        and e.get("to") == "2"
        for e in [*edges_out, *injected]
    )
    assert serialized, {"edges": edges_out, "injected": injected}
    pp = __import__("planning_paths")
    assert pp.shared_human_authored_paths(
        phase_files.get("1", []), phase_files.get("2", []), tmp_git_repo
    )


def test_disjoint_docs_allow_parallel(tmp_git_repo: Path, repo_root: Path) -> None:
    """shared_doc_plan_serialization — disjoint authored docs do not serialize (R22)."""
    task_list = _write_task_list(tmp_git_repo, shared_doc=False)
    wave_deliver = _load_wave_deliver(repo_root)
    content = (tmp_git_repo / task_list).read_text(encoding="utf-8")
    phases = wave_deliver.parse_phases(content)
    dep_rows = wave_deliver.parse_phase_dependencies(content)
    phase_files = wave_deliver.parse_phase_files(content)
    edges, _ = wave_deliver.deps_to_edges(phases, dep_rows, phase_files, tmp_git_repo)
    contention = __import__("planning_paths").contention_default(tmp_git_repo)
    _waves, _edges, injected, _notices, _files = wave_deliver.apply_contention(
        content, phases, edges, contention, tmp_git_repo
    )
    assert not any(e.get("kind") == "shared-authored-doc" for e in injected)


def test_merge_queue_contention_blocker_payload(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """shared_doc_plan_serialization — actionable merge-queue blocker payload (R22)."""
    wave_merge = _load_wave_merge(repo_root)
    state = {
        "target": {"branch": "feat/demo"},
        "source_task_list": "docs/prds/337-demo/tasks-337-demo.md",
        "mergeQueue": [
            {"phaseSlug": "phase-a"},
            {"phaseSlug": "phase-b"},
        ],
        "phases": {
            "1": {"id": "1", "slug": "phase-a", "status": "merge-ready-green"},
            "2": {"id": "2", "slug": "phase-b", "status": "merge-ready-green"},
        },
    }
    plan = {
        "items": [
            {"slug": "phase-a", "files": ["docs/guides/workflows.md"]},
            {"slug": "phase-b", "files": ["docs/guides/workflows.md"]},
        ]
    }
    root = Path("/tmp/unused")
    monkeypatch.setattr(wave_merge, "load_deliver_plan", lambda _root, _state: plan)
    blockers = wave_merge.merge_queue_contention_blockers(state, root)
    assert blockers
    blocker = blockers[0]
    assert blocker["phaseSlug"] == "phase-b"
    assert blocker["blockedByPhaseSlug"] == "phase-a"
    assert "docs/guides/workflows.md" in blocker["conflictingPaths"]
    assert blocker["cause"].startswith("merge-queue:")
    assert blocker["remediationCommand"]
