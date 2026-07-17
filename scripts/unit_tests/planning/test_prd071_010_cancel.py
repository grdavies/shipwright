"""PRD 071 phase 10 — cancel PRD 010 planning lifecycle (R8/R9)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_lifecycle as plc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_migrate_issue_store import parse_frontmatter_fields
from planning_store import get_backend


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "cancel-071-010") -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "hierarchy": {"epicSubIssues": True},
            }
        },
        "host": {"provider": "github"},
    }


def _fixture_cancel_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prd_status: str = "planned",
    tasks_status: str = "open",
) -> tuple[Path, dict]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "cancel-071-010"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_body = compose_issue_body(
        project_key,
        "prd",
        plc.PRD_010_PRD_UNIT_ID,
        (
            f"---\n"
            f"id: {plc.PRD_010_PRD_UNIT_ID}\n"
            f"type: prd\n"
            f"status: {prd_status}\n"
            f"visibility: public\n"
            f"---\n"
            f"# PRD 010 MemPalace\n"
        ),
    )
    tasks_body = compose_issue_body(
        project_key,
        "tasks",
        plc.PRD_010_TASKS_UNIT_ID,
        (
            f"---\n"
            f"id: {plc.PRD_010_TASKS_UNIT_ID}\n"
            f"type: tasks\n"
            f"status: {tasks_status}\n"
            f"visibility: public\n"
            f"---\n"
            f"# Tasks 010\n"
        ),
    )
    foundation_body = compose_issue_body(
        project_key,
        "prd",
        plc.PRD_071_UNIT_ID,
        (
            f"---\n"
            f"id: {plc.PRD_071_UNIT_ID}\n"
            f"type: prd\n"
            f"status: open\n"
            f"visibility: public\n"
            f"---\n"
            f"# PRD 071 foundation\n"
        ),
    )

    prd_rec = store.create(
        title="PRD 010",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{plc.PRD_010_PRD_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=plc.PRD_010_PRD_UNIT_ID,
    )
    tasks_rec = store.create(
        title="Tasks 010",
        body=tasks_body,
        labels=["sw:tasks", f"sw:unit:{plc.PRD_010_TASKS_UNIT_ID}"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id=plc.PRD_010_TASKS_UNIT_ID,
    )
    foundation_rec = store.create(
        title="PRD 071",
        body=foundation_body,
        labels=["sw:prd", f"sw:unit:{plc.PRD_071_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=plc.PRD_071_UNIT_ID,
    )
    prd_rec.number = plc.PRD_010_PLANNING_ISSUE_NUMBERS[0]
    tasks_rec.number = plc.PRD_010_PLANNING_ISSUE_NUMBERS[1]
    store._issues[prd_rec.id] = prd_rec
    store._issues[tasks_rec.id] = tasks_rec
    store._issues[foundation_rec.id] = foundation_rec
    store._persist()

    index_units = {
        f"{project_key}:{plc.PRD_010_PRD_UNIT_ID}": prd_rec.id,
        f"{project_key}:{plc.PRD_010_TASKS_UNIT_ID}": tasks_rec.id,
        f"{project_key}:{plc.PRD_071_UNIT_ID}": foundation_rec.id,
    }
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": index_units}),
        encoding="utf-8",
    )
    return root, cfg


def test_next_free_prd_number_skips_reserved_010() -> None:
    """R9 — display number 010 stays retired; next free is above max occupied."""
    occupied = {1, 2, 9, 11, 71}
    assert plc.next_free_prd_number(occupied) == 72
    assert plc.next_free_prd_number(occupied | {72}) == 73
    assert 10 not in {plc.next_free_prd_number(set())}


def test_cancel_prd_010_writes_cancelled_and_depends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8 — PRD 010 + tasks become cancelled with depends-on 071 (not superseded)."""
    root, cfg = _fixture_cancel_repo(tmp_path, monkeypatch)
    out = plc.cancel_prd_010_for_071_foundation(root, cfg, dry_run=False)
    assert out["verdict"] == "ok", out

    backend = get_backend(root, cfg, override="issue-store")
    for unit_id, artifact_type in (
        (plc.PRD_010_PRD_UNIT_ID, "prd"),
        (plc.PRD_010_TASKS_UNIT_ID, "tasks"),
    ):
        import planning_store as ps

        body_path = ps._default_body_path(unit_id, artifact_type)
        fetched = backend.get(unit_id, body_path)
        assert fetched.verdict == "ok" and fetched.content
        fm = parse_frontmatter_fields(fetched.content)
        assert fm.get("status") == "cancelled"
        assert plc.depends_includes_foundation(fm.get("depends", ""), plc.PRD_071_UNIT_ID, plc.PRD_071_NUMBER)
        assert not plc._supersedes_points_at_foundation(
            fm.get("supersedes", ""),
            plc.PRD_071_UNIT_ID,
            plc.PRD_071_NUMBER,
        )


def test_cancel_prd_010_idempotent_when_already_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S — second cancel pass is a no-op when depends-on 071 already present."""
    root, cfg = _fixture_cancel_repo(tmp_path, monkeypatch, prd_status="cancelled", tasks_status="cancelled")
    backend = get_backend(root, cfg, override="issue-store")
    import planning_store as ps

    for unit_id, artifact_type in (
        (plc.PRD_010_PRD_UNIT_ID, "prd"),
        (plc.PRD_010_TASKS_UNIT_ID, "tasks"),
    ):
        body_path = ps._default_body_path(unit_id, artifact_type)
        fetched = backend.get(unit_id, body_path)
        assert fetched.content
        updated, _ = plc.apply_cancel_with_depends(
            fetched.content,
            depends_target=plc.PRD_071_UNIT_ID,
            rationale=plc.PRD_010_CANCEL_RATIONALE,
        )
        backend.put(unit_id, body_path, updated)

    first = plc.cancel_prd_010_for_071_foundation(root, cfg, dry_run=False)
    second = plc.cancel_prd_010_for_071_foundation(root, cfg, dry_run=False)
    assert first["verdict"] == "ok"
    assert second["verdict"] == "ok"
    assert second["updates"][plc.PRD_010_PRD_UNIT_ID]["changed"] is False
    assert second["updates"][plc.PRD_010_TASKS_UNIT_ID]["changed"] is False


def test_verify_prd_010_cancel_for_071_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O — verify helper passes after cancel with issues 139/140 retained."""
    root, cfg = _fixture_cancel_repo(tmp_path, monkeypatch)
    cancel = plc.cancel_prd_010_for_071_foundation(root, cfg, dry_run=False)
    assert cancel["verdict"] == "ok", cancel
    verify = plc.verify_prd_010_cancel_for_071(root, cfg)
    assert verify["verdict"] == "ok", verify
    assert verify["nextFreePrdNumber"] != int(plc.PRD_010_NUMBER)


def test_later_mempalace_supersedes_cancelled_010_not_071() -> None:
    """I — future MemPalace PRD supersedes cancelled 010; foundation link stays depends-on."""
    content = (
        "---\n"
        "id: 073-prd-mempalace-memory-provider\n"
        "type: prd\n"
        "status: proposed\n"
        f"supersedes: [{plc.mempalace_reauth_supersedes_target()}]\n"
        f"depends: [{plc.PRD_071_UNIT_ID}]\n"
        "---\n"
        "# MemPalace re-auth\n"
    )
    fm = parse_frontmatter_fields(content)
    assert plc.mempalace_reauth_supersedes_target() in plc._parse_depends_list(fm.get("supersedes", ""))
    assert plc.depends_includes_foundation(fm.get("depends", ""), plc.PRD_071_UNIT_ID, plc.PRD_071_NUMBER)
    assert not plc._supersedes_points_at_foundation(
        fm.get("supersedes", ""),
        plc.PRD_071_UNIT_ID,
        plc.PRD_071_NUMBER,
    )
