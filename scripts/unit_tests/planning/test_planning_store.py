"""Pytest port of run_planning_store_fixtures.py (PRD 054 W4 behavioral)."""
from __future__ import annotations

import json
import subprocess

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/planning"
_HARNESS = "harness_planning_store.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_planning_store", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_planning_store_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_planning_store_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()


# --- PRD 094 R1/R13 absorbs put edge projection (folded to avoid workflow regen) ---
from planning_canonical import (
    build_edges_block,
    canonical_content_from_operator,
    operator_body_from_canonical,
    parse_absorbs_from_canonical_content,
    parse_edges_block,
    reconcile_edges,
    resolve_put_edge_projection,
    type_label,
    unit_id_label,
    edge_labels_for,
)
from planning_gap_capture import _merge_prd_absorbs_frontmatter
from issues_lib import FixtureIssuesStore
from planning_store import IssueStoreBackend, _default_body_path

def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "absorbs-put-094") -> dict:
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


def test_resolve_put_emits_absorbs_sw_edges() -> None:
    """R1 — canonical absorbs frontmatter becomes durable sw-edges on put projection."""
    canonical = (
        "---\n"
        "id: 094-prd-test\n"
        "type: prd\n"
        "status: open\n"
        "visibility: public\n"
        "absorbs: [gap-261, gap-263]\n"
        "---\n"
        "# PRD with absorbs\n"
    )
    store_content = operator_body_from_canonical(canonical)
    stripped, edges, native = resolve_put_edge_projection(
        store_content=store_content,
        canonical_content=canonical,
    )
    assert "```sw-edges" not in store_content
    assert edges is not None
    absorbs = [e for e in edges if e.get("rel") == "absorbs"]
    assert {e["target"] for e in absorbs} == {"gap-261", "gap-263"}
    assert native is None
    assert stripped.startswith("<!-- sw-hybrid-frontmatter -->")


def test_put_merges_absorbs_with_existing_edges_and_native(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R13 — absorbs union preserves depends edges and provider native links."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "absorbs-merge-094"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    parent_unit = "gap-parent-absorbs-merge"
    prd_unit = "094-prd-absorbs-merge"
    backend = IssueStoreBackend(root, cfg)

    parent_path = _default_body_path(parent_unit, "gap")
    assert (
        backend.put(
            parent_unit,
            parent_path,
            f"---\nid: {parent_unit}\ntype: gap\nvisibility: public\n---\n# parent\n",
        ).verdict
        == "ok"
    )

    from issues_lib import FixtureIssuesStore

    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    parent_rec = store.find_by_unit(project_key, parent_unit)
    assert parent_rec is not None

    edge_list = [{"rel": "depends", "target": parent_unit}]
    native_links = [{"type": "depends-on", "target": parent_rec.id}]
    prd_path = _default_body_path(prd_unit, "prd")
    seed_body = (
        f"---\nid: {prd_unit}\ntype: prd\nstatus: open\nvisibility: public\n---\n# seed\n"
        + build_edges_block(edge_list, native_links)
    )
    assert backend.put(prd_unit, prd_path, seed_body).verdict == "ok"

    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [gap-261]\n"
        f"depends: [{parent_unit}]\n"
        f"---\n"
        f"# PRD absorbs merge\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"

    got = backend.get(prd_unit, prd_path)
    assert got.verdict == "ok" and got.content

    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    record = store.find_by_unit(project_key, prd_unit)
    assert record is not None
    body_edges = parse_edges_block(record.body)
    assert body_edges is not None
    rels = {(e.get("rel"), e.get("target")) for e in body_edges.get("edges") or []}
    assert ("depends", parent_unit) in rels
    assert ("absorbs", "gap-261") in rels
    assert body_edges.get("native") == native_links
    reconciled = reconcile_edges(body_edges, record.native_links)
    assert reconciled.get("native") == native_links


def test_read_edges_authoritative_over_labels_and_extra_filter() -> None:
    """R2/R14 — sw-edges wins over stale labels; structural keys stripped from extra."""
    prd_unit = "094-prd-read-edges-auth"
    gap_sw = "gap-from-sw-edges"
    gap_label = "gap-from-label-only"
    labels = [
        type_label("prd"),
        unit_id_label(prd_unit),
        "sw:status:open",
        "sw:visibility:public",
    ]
    labels.extend(edge_labels_for("absorbs", [gap_label]))
    sw_edges = build_edges_block([{"rel": "absorbs", "target": gap_sw}], [])
    operator = (
        "<!-- sw-hybrid-frontmatter -->\n"
        + (
            "<!-- sw-frontmatter-extra: "
            + '{"absorbs": ["gap-from-extra"], "customNote": "keep-me", "status": "draft"}'
            + " -->\n"
        )
        + "# PRD read edges authoritative\n"
        + sw_edges
    )
    canonical = canonical_content_from_operator(labels, operator, unit_id=prd_unit)
    absorbs = parse_absorbs_from_canonical_content(canonical)
    assert gap_sw in absorbs
    assert gap_label not in absorbs
    assert "gap-from-extra" not in absorbs
    assert "customNote: keep-me" in canonical
    assert "status: draft" not in canonical


def test_absorbs_put_get_roundtrip_above_label_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 — >20 absorbs round-trip via sw-edges (label projection capped at 20)."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "absorbs-cap-094"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    prd_unit = "094-prd-absorbs-cap"
    backend = IssueStoreBackend(root, cfg)
    prd_path = _default_body_path(prd_unit, "prd")
    gap_targets = [f"gap-cap-{i:02d}" for i in range(25)]
    absorbs_yaml = ", ".join(gap_targets)
    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [{absorbs_yaml}]\n"
        f"---\n"
        f"# PRD above cap absorbs\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"

    got = backend.get(prd_unit, prd_path)
    assert got.verdict == "ok" and got.content
    roundtrip_absorbs = parse_absorbs_from_canonical_content(got.content)
    assert set(roundtrip_absorbs) == set(gap_targets)


# --- PRD 094 R12 absorbs regression fixtures (folded to avoid workflow regen) ---


def _assert_no_edge_divergence(
    backend: IssueStoreBackend,
    *,
    project_key: str,
    unit_id: str,
    body_path: str,
) -> None:
    record = FixtureIssuesStore(
        backend.root / ".cursor/hooks/state/issue-store-fixture.json"
    ).find_by_unit(project_key, unit_id)
    assert record is not None
    body_edges = parse_edges_block(record.body)
    reconciled = reconcile_edges(body_edges, record.native_links)
    assert reconciled.get("edges") == (body_edges or {}).get("edges")
    got = backend.get(unit_id, body_path)
    assert got.verdict == "ok" and got.content


def test_put_get_preserves_absorbs_on_hybrid_body_r12(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R12a — put→get round-trip preserves absorbs on hybrid-operator bodies."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "absorbs-r12-basic"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    backend = IssueStoreBackend(root, cfg)
    prd_unit = "094-prd-absorbs-r12-basic"
    prd_path = _default_body_path(prd_unit, "prd")
    gap_targets = ["gap-261", "gap-263"]
    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [{', '.join(gap_targets)}]\n"
        f"---\n"
        f"# PRD absorbs basic roundtrip\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"
    got = backend.get(prd_unit, prd_path)
    assert got.verdict == "ok" and got.content
    assert set(parse_absorbs_from_canonical_content(got.content)) == set(gap_targets)
    _assert_no_edge_divergence(
        backend, project_key=project_key, unit_id=prd_unit, body_path=prd_path
    )


def test_merge_prd_absorbs_semantic_noop_on_alias_rerun() -> None:
    """R12b — alias-normalized absorb merge reports changed=False on re-run."""
    gap_unit = "gap-261-planning-store-absorb"
    prd_body = (
        "---\n"
        "id: 094-prd-semantic-noop\n"
        "type: prd\n"
        "status: open\n"
        "visibility: public\n"
        "absorbs: [gap-261]\n"
        "---\n"
        "# PRD with absorbs\n"
        + build_edges_block([{"rel": "absorbs", "target": "gap-261"}], [])
    )
    merged, changed = _merge_prd_absorbs_frontmatter(prd_body, gap_unit)
    assert changed is False
    assert merged == prd_body


def test_merge_prd_absorbs_semantic_noop_on_set_equivalent_rewrite() -> None:
    """R12b — set-equivalent reorder does not report changed=True."""
    prd_body = (
        "---\n"
        "id: 094-prd-semantic-set\n"
        "type: prd\n"
        "status: open\n"
        "visibility: public\n"
        "absorbs: [gap-261, gap-263]\n"
        "---\n"
        "# PRD\n"
        + build_edges_block(
            [
                {"rel": "absorbs", "target": "gap-261"},
                {"rel": "absorbs", "target": "gap-263"},
            ],
            [],
        )
    )
    merged, changed = _merge_prd_absorbs_frontmatter(prd_body, "gap-263")
    assert changed is False
    assert merged == prd_body


def test_put_get_second_roundtrip_preserves_edge_union_r12(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R12e — metadata-only re-put does not drop absorbs or trigger edge-divergence."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "absorbs-r12-reput"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    backend = IssueStoreBackend(root, cfg)
    prd_unit = "094-prd-absorbs-r12-reput"
    prd_path = _default_body_path(prd_unit, "prd")
    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [gap-261, gap-263]\n"
        f"---\n"
        f"# PRD re-put\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"
    metadata_only = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: draft\n"
        f"visibility: public\n"
        f"absorbs: [gap-261, gap-263]\n"
        f"---\n"
        f"# PRD re-put status change\n"
    )
    assert backend.put(prd_unit, prd_path, metadata_only).verdict == "ok"
    second = backend.get(prd_unit, prd_path)
    assert second.verdict == "ok" and second.content
    assert set(parse_absorbs_from_canonical_content(second.content)) == {"gap-261", "gap-263"}
    _assert_no_edge_divergence(
        backend, project_key=project_key, unit_id=prd_unit, body_path=prd_path
    )
