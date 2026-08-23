"""PRD 325 R15 — absorb close-out for units #331–#338."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body, type_label
from planning_store import (
    audit_closure_completeness,
    discover_absorbed_units_anchored,
    gap_has_absorb_provenance,
    resolve_delivery_linked_units,
)
from planning_store_facade import (
    PlanningIssueRefResolutionError,
    _gap_closure_evidence,
    _iter_numeric_absorb_refs,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-325") -> dict:
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


def _prd_325_frontmatter() -> str:
    issues = ", ".join(str(n) for n in pgc.PRD_325_PLANNING_ISSUE_NUMBERS)
    absorbs = ", ".join(str(n) for n in pgc.PRD_325_PLANNING_ISSUE_NUMBERS)
    return (
        f"---\n"
        f"id: {pgc.PRD_325_UNIT_ID}\n"
        f"type: prd\n"
        f"status: complete\n"
        f"visibility: public\n"
        f"planningIssues: [{issues}]\n"
        f"absorbs: [{absorbs}]\n"
        f"---\n"
        f"# PRD 325\n"
    )


def _prd_325_edges() -> list[dict[str, str]]:
    return [
        {"rel": "absorbs", "target": str(num)}
        for num in pgc.PRD_325_PLANNING_ISSUE_NUMBERS
    ]


def _fixture_prd325_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-325"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_body = compose_issue_body(
        project_key,
        "prd",
        pgc.PRD_325_UNIT_ID,
        _prd_325_frontmatter(),
        edges=_prd_325_edges(),
    )
    prd_rec = store.create(
        title="PRD 325",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{pgc.PRD_325_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=pgc.PRD_325_UNIT_ID,
    )
    index_units = {f"{project_key}:{pgc.PRD_325_UNIT_ID}": prd_rec.id}

    for gap_id, issue_num in zip(pgc.PRD_325_ABSORB_GAP_UNITS, pgc.PRD_325_PLANNING_ISSUE_NUMBERS):
        gap_body = compose_issue_body(
            project_key,
            "gap",
            gap_id,
            (
                f"---\n"
                f"id: {gap_id}\n"
                f"type: gap\n"
                f"status: open\n"
                f"visibility: public\n"
                f"related: planning#{issue_num}\n"
                f"---\n"
                f"# {gap_id}\n"
            ),
        )
        gap_rec = store.create(
            title=gap_id,
            body=gap_body,
            labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_id}"],
            project_key=project_key,
            artifact_type="gap",
            unit_id=gap_id,
        )
        gap_rec.number = issue_num
        store._issues[gap_rec.id] = gap_rec
        index_units[f"{project_key}:{gap_id}"] = gap_rec.id

    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": index_units}),
        encoding="utf-8",
    )
    return root, cfg, store


def test_discover_all_eight_gaps_from_anchored_markers() -> None:
    fm = {
        "absorbs": "[" + ", ".join(str(n) for n in pgc.PRD_325_PLANNING_ISSUE_NUMBERS) + "]",
        "planningIssues": "[" + ", ".join(str(n) for n in pgc.PRD_325_PLANNING_ISSUE_NUMBERS) + "]",
    }
    edges = {"edges": _prd_325_edges()}
    discovered, skipped = discover_absorbed_units_anchored(fm, edges)
    assert not discovered
    assert _iter_numeric_absorb_refs(fm, edges) == [str(n) for n in pgc.PRD_325_PLANNING_ISSUE_NUMBERS]
    assert not skipped


def test_resolve_delivery_linked_units_discovers_eight_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd325_repo(tmp_path, monkeypatch)
    snap = resolve_delivery_linked_units(root, cfg, pgc.PRD_325_UNIT_ID)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert len(gap_ids) == 8
    for expected in pgc.PRD_325_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(got, expected) for got in gap_ids)


def test_gap_closure_evidence_resolves_all_numeric_absorbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd325_repo(tmp_path, monkeypatch)
    fm = {
        "planningIssues": "[" + ", ".join(str(n) for n in pgc.PRD_325_PLANNING_ISSUE_NUMBERS) + "]",
    }
    edges = {"edges": _prd_325_edges()}
    discovered, skipped = _gap_closure_evidence(fm, edges, "325", root, cfg)
    assert len(discovered) == 8
    for expected in pgc.PRD_325_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(item, expected) for item in discovered)
    assert not any(item.get("reason") == "planning-issue-no-provenance" for item in skipped)


def test_gap_has_absorb_provenance_via_numeric_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd325_repo(tmp_path, monkeypatch)
    gap_id = pgc.PRD_325_ABSORB_GAP_UNITS[0]
    issue_num = pgc.PRD_325_PLANNING_ISSUE_NUMBERS[0]
    fm = {"planningIssues": f'["{issue_num}"]'}
    edges = {"edges": [{"rel": "absorbs", "target": str(issue_num)}]}
    assert gap_has_absorb_provenance(
        root, cfg, gap_id, pgc.PRD_325_UNIT_ID, fm, prd_num="325", edges=edges
    )


def test_verify_absorb_closeout_325_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, cfg, _store = _fixture_prd325_repo(tmp_path, monkeypatch)
    out = pgc.verify_absorb_closeout_325(root, cfg)
    assert out["verdict"] == "ok", out
    assert out["discoveredCount"] == 8
    assert not out.get("missing")


def test_unresolvable_numeric_absorb_raises_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-325-missing"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    prd_body = compose_issue_body(
        project_key,
        "prd",
        pgc.PRD_325_UNIT_ID,
        f"---\nid: {pgc.PRD_325_UNIT_ID}\ntype: prd\nstatus: complete\n---\n# PRD\n",
        edges=[{"rel": "absorbs", "target": "999"}],
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{pgc.PRD_325_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=pgc.PRD_325_UNIT_ID,
    )
    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {f"{project_key}:{pgc.PRD_325_UNIT_ID}": prd_rec.id}}),
        encoding="utf-8",
    )
    snap = resolve_delivery_linked_units(root, cfg, pgc.PRD_325_UNIT_ID)
    assert snap["verdict"] == "not-ready", snap
    assert snap["error"] == "absorb-gap-unresolved"
    assert snap.get("planningIssueRef") == "999"


def test_record_absorb_linkage_325_no_local_docs_prds_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd325_repo(tmp_path, monkeypatch)
    docs_prds = root / "docs" / "prds" / "325-deliver-finalize-consumer-resilience"
    docs_prds.mkdir(parents=True)
    marker = docs_prds / "marker.txt"
    marker.write_text("untouched\n", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")
    out = pgc.record_absorb_linkage_325(root, dry_run=False)
    assert out["verdict"] == "ok", out
    assert marker.read_text(encoding="utf-8") == before
    assert not any(docs_prds.glob("**/*.md"))


def test_audit_closure_not_ready_with_open_absorbed_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd325_repo(tmp_path, monkeypatch)
    audit = audit_closure_completeness(root, cfg, pgc.PRD_325_UNIT_ID)
    assert audit["verdict"] == "not-ready"
    assert len(audit.get("openRemaining") or []) == 8
