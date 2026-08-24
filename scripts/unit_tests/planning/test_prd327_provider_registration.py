"""PRD 327 phase 2 — Notion provider registration, issues_lib gating, schema/rate-limit (hermetic)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import host_lib
import issues_http
import issues_lib
from issues_lib import FixtureIssuesStore
import planning_notion_client as pnc
import planning_gap_capture as pgc
import planning_store as ps
import planning_store_facade as ps_facade
from planning.providers import notion as notion_provider
from planning_canonical import compose_issue_body
from planning_store import (
    audit_closure_completeness,
    discover_absorbed_units_anchored,
    resolve_delivery_linked_units,
)
from planning_notion_projection import (
    NOTION_ENTITY_MAP,
    apply_dual_property_capability,
    encode_planning_edge,
    map_artifact_to_notion_entity,
    project_graph_to_notion_layout,
    rebuild_projection_for_unit,
    resolve_canonical_freeze_body,
)
from planning_request_budget import RequestBudgetLedger


def _notion_cfg(*, with_database: bool = True) -> dict[str, Any]:
    issues: dict[str, Any] = {"tokenEnv": "ISSUES_NOTION_TOKEN"}
    if with_database:
        issues["notionDatabaseId"] = "db-fixture-00000000000000000000000000000001"
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "notion",
                "projectKey": "planning",
                "issues": issues,
            }
        }
    }


def test_notion_live_client_wired() -> None:
    assert pnc.LIVE_CLIENT is True
    assert notion_provider.live_client_wired() is True


def test_notion_recognized_and_shipped() -> None:
    assert "notion" in ps.ISSUES_PROVIDERS
    assert "notion" in ps.SHIPPED_ISSUES_PROVIDERS


def test_registration_footprint_notion_surface() -> None:
    footprint = ps.issues_provider_registration_footprint()
    assert footprint["notion"]["liveClientWired"] is True
    assert footprint["notion"]["promotionGatedBy"] == ["conformance", "docs-gate"]
    assert footprint["rateLimitMap"]["notion"] == "notion"
    assert footprint["capabilityIndexIds"]["notion"] == "provider.providers.issues.notion"
    assert footprint["recognitionVsShipped"]["notion"] == {
        "recognized": True,
        "shipped": True,
        "deferred": False,
    }


def test_doctor_notion_shipped_passes(tmp_path: Path) -> None:
    result = ps.doctor_issues_provider_stub(tmp_path, _notion_cfg())
    assert result["verdict"] == "pass"
    assert result["provider"] == "notion"
    assert "notice" not in result


def test_doctor_notion_stub_refused_when_client_unwired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notion_provider, "live_client_wired", lambda: False)
    result = notion_provider.doctor_stub_result(
        tmp_path,
        provider="notion",
        issues_providers=frozenset({"github-issues"}),
        shipped_providers=ps.SHIPPED_ISSUES_PROVIDERS,
    )
    assert result is not None
    assert result["verdict"] == "fail"
    assert result["error"] == "notion-stub-refused"


def test_issues_lib_notion_shipped_fixture_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    client = issues_lib.IssuesClient(tmp_path, "notion")
    backend = client._live_backend()
    assert backend is not None


def test_issues_http_notion_ratelimit_profile() -> None:
    cfg = _notion_cfg()
    resolved = issues_http.resolve_issues_rate_limit(cfg, issues_provider="notion")
    assert resolved["mutatingMinDelayMs"] == 334
    assert issues_http.issues_ratelimit_provider("notion") == "notion"


def test_notion_retryable_errors() -> None:
    assert issues_http._notion_retryable_error(
        409,
        json.dumps({"code": "conflict_error"}),
    )
    assert issues_http._notion_retryable_error(
        502,
        json.dumps({"code": "gateway_timeout"}),
    )
    assert not issues_http._notion_retryable_error(
        400,
        json.dumps({"code": "validation_error"}),
    )
    assert issues_http._notion_validation_error(
        400,
        json.dumps({"code": "validation_error"}),
    )


def test_request_budget_notion_defaults(tmp_git_repo: Path) -> None:
    from planning_request_budget import RequestBudgetLedger

    (tmp_git_repo / "workflow.config.json").write_text(
        json.dumps(_notion_cfg()) + "\n",
        encoding="utf-8",
    )
    ledger = RequestBudgetLedger.from_config(tmp_git_repo, "notion")
    assert ledger.max_calls == 300
    assert ledger.max_pagination_depth == 5

# --- PRD 327 phase 3 operator projection (R5) ---


def _fixture_graph() -> dict:
    return {
        "units": [
            {"unitId": "prd-1", "artifactType": "prd"},
            {"unitId": "bs-1", "artifactType": "brainstorm", "prdUnitId": "prd-1"},
            {"unitId": "gap-1", "artifactType": "gap", "prdUnitId": "prd-1"},
            {"unitId": "phase-1", "artifactType": "phase", "prdUnitId": "prd-1"},
            {"unitId": "task-1", "artifactType": "task"},
            {"unitId": "task-2", "artifactType": "task"},
            {"unitId": "prog-1", "artifactType": "program"},
            {"unitId": "prog-status", "artifactType": "progress"},
        ],
        "edges": [
            {
                "edgeType": "absorbs",
                "source": {"unitId": "gap-1", "kind": "gap"},
                "target": {"unitId": "prd-1", "kind": "prd"},
            },
            {
                "edgeType": "feeds",
                "source": {"unitId": "bs-1", "kind": "brainstorm"},
                "target": {"unitId": "prd-1", "kind": "prd"},
            },
            {
                "edgeType": "depends",
                "source": {"unitId": "task-2", "kind": "task"},
                "target": {"unitId": "task-1", "kind": "task"},
            },
        ],
    }


def test_notion_entity_map_covers_required_artifact_types() -> None:
    required = {"prd", "brainstorm", "gap", "phase", "task", "program", "progress"}
    assert required <= set(NOTION_ENTITY_MAP)
    assert NOTION_ENTITY_MAP["prd"]["notionEntity"] == "DatabasePage"
    assert NOTION_ENTITY_MAP["progress"]["property"] == "Status"
    assert NOTION_ENTITY_MAP["program"]["property"] == "select"
    assert NOTION_ENTITY_MAP["phase"]["windowProperty"] == "date"


def test_map_artifact_refuses_unknown_type() -> None:
    bad = map_artifact_to_notion_entity("wiki")
    assert bad["verdict"] == "fail"
    assert bad["error"] == "unsupported-artifact-type"


def test_project_graph_to_notion_layout_portable_graph_authority() -> None:
    layout = project_graph_to_notion_layout(_fixture_graph())
    assert layout["verdict"] == "pass"
    assert layout["freezeAuthority"] == "portable-graph"
    assert layout["isSourceOfTruth"] is False
    assert layout["properties"]["completion"] == "Status"
    roles = set(layout["byDatabaseRole"])
    assert {"prd", "brainstorm", "gap", "phase", "task", "program", "progress"} <= roles
    encodings = {e["edgeType"]: e["encoding"] for e in layout["edges"]}
    assert encodings["absorbs"] == "dual_property"
    assert encodings["feeds"] == "dual_property"
    assert encodings["depends"] == "task-task-relation"


def test_dual_property_degrades_with_operator_notice() -> None:
    layout = project_graph_to_notion_layout(
        _fixture_graph(),
        workspace={"dualPropertyEnabled": False},
    )
    assert layout["verdict"] == "pass"
    absorbs = next(e for e in layout["edges"] if e["edgeType"] == "absorbs")
    assert absorbs["encoding"] == "single_property+back-reference-view"
    assert absorbs["degradationNotices"]
    assert absorbs["degradationNotices"][0]["silentSkip"] is False
    cap = apply_dual_property_capability(
        probe={"available": False},
        substitute_configured=True,
    )
    assert cap["verdict"] == "ok"
    assert cap["dualPropertyAvailable"] is False
    assert cap["substituteViews"]["requiredViews"]


def test_stub_page_endpoints_prohibited() -> None:
    edge = encode_planning_edge(
        {
            "edgeType": "absorbs",
            "source": {"unitId": "gap-1", "kind": "gap", "stub": True},
            "target": {"unitId": "prd-1", "kind": "prd"},
        }
    )
    assert edge["verdict"] == "fail"
    assert edge["error"] == "stub-page-endpoints-prohibited"


def test_projection_prefer_split_brain_and_drift() -> None:
    prefer = resolve_canonical_freeze_body(
        unit_id="prd-1",
        body="# body",
        prefer="projection",
    )
    assert prefer["verdict"] == "fail"
    assert prefer["error"] == "projection-prefer-split-brain"

    drift = resolve_canonical_freeze_body(
        unit_id="prd-1",
        body="# canonical",
        projection_mirrors=[
            {
                "entityKind": "DatabasePage",
                "entityId": "page-1",
                "body": "# other",
                "derived": False,
                "bodyParityRequired": True,
                "isFreezeAuthority": False,
            }
        ],
    )
    assert drift["verdict"] == "fail"
    assert drift["error"] == "canonical-projection-body-drift"


def test_rebuild_projection_idempotent_no_duplicates() -> None:
    graph = _fixture_graph()
    first = rebuild_projection_for_unit(graph, unit_id="prd-1")
    second = rebuild_projection_for_unit(graph, unit_id="prd-1")
    assert first["verdict"] == "pass"
    assert second["verdict"] == "pass"
    assert first["idempotent"] is True
    assert second["duplicatePages"] is False


def test_facade_notion_projection_schema_contract() -> None:
    contract = ps.notion_projection_schema_contract()
    assert contract["verdict"] == "ok"
    assert contract["action"] == "notion-projection-schema-contract"
    assert "prd" in contract["entityMapping"]["byArtifactType"]
    assert contract["parityMatrixRow"]["edges"] == "dual_property relations"
    matrix = ps.operator_projection_capability_matrix()
    assert "notion" in matrix["backends"]
    notion_prd = next(r for r in matrix["rows"] if r["row"] == "prd")
    assert notion_prd["notion"] == "prd-database-page"


def test_facade_project_graph_to_notion_layout() -> None:
    layout = ps.project_graph_to_notion_layout(_fixture_graph())
    assert layout["verdict"] == "pass"
    assert layout["provider"] == "notion"


# --- PRD 327 phase 6 registration non-regression (R14) ---


def _github_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "planning",
                "issues": {"tokenEnv": "ISSUES_GITHUB_TOKEN"},
            }
        },
        "host": {"provider": "github"},
    }


def _gitlab_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "gitlab-issues",
                "projectKey": "planning",
                "issues": {"tokenEnv": "ISSUES_GITLAB_TOKEN", "endpoint": "https://gitlab.example"},
            }
        },
        "host": {"provider": "gitlab"},
    }


def _jira_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "jira",
                "projectKey": "planning",
                "issues": {
                    "tokenEnv": "ISSUES_JIRA_TOKEN",
                    "endpoint": "https://example.atlassian.net",
                },
            }
        },
        "host": {"provider": "none"},
    }


def _linear_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": "planning",
                "issues": {
                    "tokenEnv": "ISSUES_LINEAR_TOKEN",
                    "teamKey": "ENG",
                    "teamId": "team_ENG",
                    "authMode": "api-key",
                },
            }
        }
    }


def _none_provider_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "none",
                "projectKey": "planning",
            }
        }
    }


def test_registration_nonregression_other_providers_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R14 — notion addition does not change resolution/budget/doctor for peers."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    fake_host = lambda _root: {
        "verdict": "ok",
        "provider": "github",
        "remoteUrl": "https://github.com/acme/planning.git",
    }
    monkeypatch.setattr(host_lib, "resolve_provider", fake_host)
    monkeypatch.setattr(ps_facade, "resolve_provider", fake_host)

    cases = (
        ("github-issues", _github_cfg(), True, "github"),
        ("jira", _jira_cfg(), True, "jira"),
        ("linear", _linear_cfg(), True, "linear"),
    )
    for provider, cfg, shipped, rate_key in cases:
        issues = ps.resolve_issues_provider(cfg)
        assert issues["provider"] == provider
        assert issues["shipped"] is shipped
        assert issues_http.issues_ratelimit_provider(provider) == rate_key
        assert ps.issue_store_fallback_reason(tmp_path, cfg) != "issues-provider-not-shipped"
        resolved = ps.resolve_effective_backend(tmp_path, cfg)
        assert resolved["configured"] == "issue-store"
        assert resolved["effective"] == "issue-store"
        assert resolved.get("fallbackReason") != "issues-provider-not-shipped"
        doctor = ps.doctor_issues_provider_stub(tmp_path, cfg)
        assert doctor["verdict"] == "pass"
        assert doctor.get("error") != "notion-stub-refused"
        (tmp_path / "workflow.config.json").write_text(json.dumps(cfg) + "\n", encoding="utf-8")
        ledger = RequestBudgetLedger.from_config(tmp_path, provider)
        assert ledger.max_calls > 0

    gitlab = ps.resolve_issues_provider(_gitlab_cfg())
    assert gitlab["provider"] == "gitlab-issues"
    assert gitlab["shipped"] is False
    gitlab_doctor = ps.doctor_issues_provider_stub(tmp_path, _gitlab_cfg())
    assert gitlab_doctor["verdict"] == "fail"
    assert gitlab_doctor["error"] == "deferred-provider-stub-refused"

    none_issues = ps.resolve_issues_provider(_none_provider_cfg())
    assert none_issues["provider"] == "none"
    none_doctor = ps.doctor_issues_provider_stub(tmp_path, _none_provider_cfg())
    assert none_doctor["verdict"] in {"pass", "fail"}
    assert none_doctor.get("error") != "notion-stub-refused"
    assert issues_http.ISSUES_PROVIDER_TO_RATELIMIT["github-issues"] == "github"
    assert issues_http.ISSUES_PROVIDER_TO_RATELIMIT["linear"] == "linear"
    assert issues_http.ISSUES_PROVIDER_TO_RATELIMIT["notion"] == "notion"


# --- PRD 327 phase 5 docs, conformance, shipped gate (R12/R13) ---


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_notion_docs_gate_passes() -> None:
    root = _repo_root()
    result = pnc.docs_gate(root)
    assert result["verdict"] == "ok"
    assert result["gate"] == "docs-gate"


def test_notion_docs_gate_missing_doc_fail_closed(tmp_path: Path) -> None:
    """Harness FIX_ROOT copies scripts/ only — docs_gate must not raise (living-doc set-index-status-cli)."""
    result = pnc.docs_gate(tmp_path)
    assert result["verdict"] == "fail"
    assert result["error"] == "missing-provider-doc"


def test_shipped_resolution_survives_scripts_only_root(tmp_path: Path) -> None:
    """Import-time shipped resolution must tolerate missing core/providers when conformance fixtures exist."""
    from _planning_pkg_loader import load_submodule

    pc = load_submodule("provider_conformance")
    fixtures = (
        _repo_root()
        / "scripts/test/fixtures/planning-provider-conformance/notion.ok.json"
    )
    dest = tmp_path / "scripts/test/fixtures/planning-provider-conformance"
    dest.mkdir(parents=True)
    dest.joinpath("notion.ok.json").write_text(fixtures.read_text(encoding="utf-8"), encoding="utf-8")
    shipped = pc.providers_with_green_conformance(tmp_path)
    assert "notion" not in shipped


def test_notion_promotion_gate_evidence_green() -> None:
    root = _repo_root()
    evidence = pnc.notion_promotion_gate_evidence(root)
    assert evidence["verdict"] == "ok", evidence.get("failures")


def test_notion_conformance_record_matches_live(monkeypatch: pytest.MonkeyPatch) -> None:
    from _planning_pkg_loader import load_submodule

    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    pc = load_submodule("provider_conformance")
    root = _repo_root()
    evidence = pc.conformance_evidence(root, "notion")
    assert evidence["verdict"] == "ok", evidence.get("failures")

# --- PRD 327 R15 absorb closeout (folded here: CI shard lists this file; workflow PAT lacks scope to regen pr-test-plan-ci.yml) ---

def _absorb_init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _absorb_issue_store_cfg(project_key: str = "closure-327") -> dict:
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


def _prd_327_frontmatter(*, with_absorbs: bool = True) -> str:
    absorbs_line = (
        f"absorbs: [{pgc.GAP_078_UNIT_ID}]\n" if with_absorbs else ""
    )
    return (
        f"---\n"
        f"id: {pgc.PRD_327_UNIT_ID}\n"
        f"type: prd\n"
        f"status: complete\n"
        f"visibility: public\n"
        f"{absorbs_line}"
        f"---\n"
        f"# PRD 327\n"
    )


def _prd_327_edges(*, with_absorbs: bool = True) -> list[dict[str, str]]:
    if not with_absorbs:
        return []
    return [{"rel": "absorbs", "target": pgc.GAP_078_UNIT_ID}]


def _fixture_prd327_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_absorbs: bool = True,
) -> tuple[Path, dict, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _absorb_init_repo(root)
    project_key = "closure-327"
    cfg = _absorb_issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    gap_id = pgc.GAP_078_UNIT_ID
    prd_body = compose_issue_body(
        project_key,
        "prd",
        pgc.PRD_327_UNIT_ID,
        _prd_327_frontmatter(with_absorbs=with_absorbs),
        edges=_prd_327_edges(with_absorbs=with_absorbs),
    )
    prd_rec = store.create(
        title="PRD 327",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{pgc.PRD_327_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=pgc.PRD_327_UNIT_ID,
    )
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
            f"---\n"
            f"# Gap 078\n"
        ),
    )
    gap_rec = store.create(
        title="Gap 078",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_id}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_id,
    )
    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{pgc.PRD_327_UNIT_ID}": prd_rec.id,
                    f"{project_key}:{gap_id}": gap_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )
    return root, cfg, store


def test_discover_gap_078_from_anchored_markers() -> None:
    fm = {"absorbs": f"[{pgc.GAP_078_UNIT_ID}]"}
    edges = {"edges": _prd_327_edges()}
    discovered, skipped = discover_absorbed_units_anchored(fm, edges)
    assert any(pgc.gap_absorb_target_match(item, pgc.GAP_078_UNIT_ID) for item in discovered)
    assert not skipped


def test_resolve_delivery_linked_units_discovers_gap_078(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    snap = resolve_delivery_linked_units(root, cfg, pgc.PRD_327_UNIT_ID)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert any(pgc.gap_absorb_target_match(got, pgc.GAP_078_UNIT_ID) for got in gap_ids)


def test_verify_absorb_closeout_327_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    out = pgc.verify_absorb_closeout_327(root, cfg)
    assert out["verdict"] == "ok", out
    assert out["discoveredCount"] == 1
    assert not out.get("missing")


def test_verify_absorb_closeout_327_fails_when_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    out = pgc.verify_absorb_closeout_327(root, cfg)
    assert out["verdict"] == "fail", out
    assert any(
        pgc.gap_absorb_target_match(item, pgc.GAP_078_UNIT_ID)
        for item in (out.get("missing") or [])
    )


def test_record_and_verify_absorb_linkage_327(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    record = pgc.record_absorb_linkage_327(root, dry_run=False)
    assert record["verdict"] == "ok", record
    assert record["gapUnitId"] == pgc.GAP_078_UNIT_ID
    assert record["action"] == "record-absorb-linkage-327"

    verify = pgc.verify_absorb_closeout_327(root, cfg)
    assert verify["verdict"] == "ok", verify
    assert not verify.get("missing")


def test_record_absorb_linkage_327_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    first = pgc.record_absorb_linkage_327(root, dry_run=False)
    second = pgc.record_absorb_linkage_327(root, dry_run=False)
    assert first["verdict"] == "ok", first
    assert second["verdict"] == "ok", second
    assert pgc.verify_absorb_closeout_327(root, cfg)["verdict"] == "ok"


def test_record_absorb_linkage_327_no_local_docs_prds_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    docs_prds = root / "docs" / "prds" / "327-notion-planning-store-provider"
    docs_prds.mkdir(parents=True)
    marker = docs_prds / "marker.txt"
    marker.write_text("untouched\n", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")
    out = pgc.record_absorb_linkage_327(root, dry_run=False)
    assert out["verdict"] == "ok", out
    assert marker.read_text(encoding="utf-8") == before
    assert not any(docs_prds.glob("**/*.md"))


def test_audit_closure_not_ready_with_open_absorbed_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    audit = audit_closure_completeness(root, cfg, pgc.PRD_327_UNIT_ID)
    assert audit["verdict"] == "not-ready"
    assert len(audit.get("openRemaining") or []) == 1


def test_record_absorb_linkage_327_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "planning_gap_capture.py"),
            str(root),
            "record-absorb-linkage-327",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SW_ISSUES_FIXTURE": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "ok", payload
    assert payload["action"] == "record-absorb-linkage-327"


def test_verify_absorb_closeout_327_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "planning_gap_capture.py"),
            str(root),
            "verify-absorb-closeout-327",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SW_ISSUES_FIXTURE": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "ok", payload
    assert payload["action"] == "verify-absorb-closeout-327"

