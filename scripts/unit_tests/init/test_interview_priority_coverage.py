"""Priority-zero interview coverage (PRD 342 R24/R25/R26/R27)."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from init_profile_report import (  # noqa: E402
    derive_interview_priorities,
    interview_priority_for_key,
    interview_reuse_bundle,
    load_config_schema,
)
from init_scripts_facade import (  # noqa: E402
    DECLINE_CONSEQUENCES,
    PRIORITY_ZERO_SURFACES,
    record_priority_zero_surface,
    validate_priority_zero_coverage,
)


def _load_sw_configure():
    path = SCRIPT_DIR / "sw-configure.py"
    spec = importlib.util.spec_from_file_location("sw_configure_interview", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sw_configure():
    return _load_sw_configure()


def test_five_of_five_priority_zero_surfaces_recorded(repo_root: Path, sw_configure) -> None:
    """R24 — one interview run records all five priority-zero surfaces."""
    payload = sw_configure.run_priority_zero_interview(
        repo_root,
        accept_defaults=True,
        plan_confirmed=True,
        apply_confirmed=True,
    )
    assert payload["verdict"] == "pass"
    assert payload["coverage"]["recorded"] == 5
    assert payload["coverage"]["expected"] == 5
    surfaces = {row["surface"]: row for row in payload["priorityZero"]}
    assert set(surfaces) == set(PRIORITY_ZERO_SURFACES)
    for name in PRIORITY_ZERO_SURFACES:
        assert surfaces[name]["state"] in {"detected", "confirmed", "declined"}


def test_declined_surfaces_carry_nonempty_consequence(repo_root: Path, sw_configure) -> None:
    """R25 — every declined surface carries a non-empty consequence."""
    decline = frozenset({"verify", "models.tiers", "ci-stub"})
    payload = sw_configure.run_priority_zero_interview(
        repo_root,
        decline_surfaces=decline,
        accept_defaults=True,
    )
    assert payload["verdict"] == "pass"
    declined = [row for row in payload["priorityZero"] if row["state"] == "declined"]
    assert {row["surface"] for row in declined} == set(decline)
    for row in declined:
        consequence = row.get("consequence")
        assert isinstance(consequence, str)
        assert consequence.strip()
        assert consequence == DECLINE_CONSEQUENCES[row["surface"]]


def test_record_declined_requires_consequence() -> None:
    """R25 — façade refuses declined records without a consequence."""
    with pytest.raises(ValueError, match="consequence"):
        record_priority_zero_surface("verify", "declined", consequence="   ")
    ok = record_priority_zero_surface("verify", "declined")
    assert ok["state"] == "declined"
    assert ok["consequence"].strip()


def test_new_schema_key_defaults_to_priority_two(repo_root: Path) -> None:
    """R26 — a key added after this unit defaults to priority two."""
    schema = load_config_schema(repo_root)
    mutated = copy.deepcopy(schema)
    props = mutated.setdefault("properties", {})
    assert isinstance(props, dict)
    new_key = "brandNewInterviewKey342"
    assert new_key not in props
    props[new_key] = {"type": "object", "additionalProperties": False}
    assert interview_priority_for_key(mutated, new_key) == 2
    priorities = derive_interview_priorities(mutated)
    assert new_key in priorities["priorityTwo"]
    assert new_key not in priorities["priorityOne"]
    assert priorities["defaultPriority"] == 2


def test_priority_one_keys_resolve_inline(repo_root: Path, sw_configure) -> None:
    """R26 — five priority-one keys resolve inline; remaining stay behind disclosure."""
    payload = sw_configure.run_priority_zero_interview(repo_root, accept_defaults=True)
    priority_one = set(payload["priorityOne"]["keys"])
    assert priority_one == {"host", "planning", "memory", "worktree", "review"}
    assert payload["priorityOne"]["inline"] is True
    assert payload["priorityTwo"]["progressiveDisclosure"] is True
    assert payload["priorityTwo"]["included"] is False
    assert "deliver" in payload["priorityTwo"]["keys"]
    assert "orchestration" in payload["priorityTwo"]["keys"]
    assert len(payload["priorityTwo"]["keys"]) > 10


def test_interview_reuses_existing_infrastructure(repo_root: Path, sw_configure) -> None:
    """R27 — findings, curated-profile classification, and consent gates are reused."""
    payload = sw_configure.run_priority_zero_interview(
        repo_root,
        accept_defaults=True,
        plan_confirmed=True,
        apply_confirmed=False,
    )
    assert payload["secondInterviewEngine"] is False
    infra = payload["infrastructure"]
    assert infra["engine"] == "existing-init-infrastructure"
    assert "profileClassification" in infra
    assert infra["planConsent"]["consented"] is True
    assert infra["applyConsent"]["consented"] is False
    assert "findings" in payload
    reuse = interview_reuse_bundle(repo_root, plan_confirmed=False, apply_confirmed=False)
    assert reuse["planConsent"]["verdict"] == "confirm-required"
    coverage = validate_priority_zero_coverage(payload["priorityZero"])
    assert coverage["verdict"] == "pass"


def test_empty_repo_records_five_surfaces_without_silent_unset(
    tmp_path: Path, sw_configure, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R24 — greenfield with no config still records five surfaces (decline or confirm)."""
    (tmp_path / ".git").mkdir()
    repo_schema = Path(__file__).resolve().parents[3] / "core/sw-reference/config.schema.json"
    schema_dest = tmp_path / "core/sw-reference"
    schema_dest.mkdir(parents=True)
    schema_dest.joinpath("config.schema.json").write_text(
        repo_schema.read_text(encoding="utf-8"), encoding="utf-8"
    )

    monkeypatch.setattr(sw_configure, "load_workflow_config", lambda _root: {})
    monkeypatch.setattr(sw_configure, "_detect_project_type", lambda _root: {})
    monkeypatch.setattr(
        sw_configure,
        "scan_ci_workflows",
        lambda _root, _branch: {"presence": "no-workflows", "ok": False},
    )
    monkeypatch.setattr(sw_configure, "default_base_branch", lambda _root: "main")
    monkeypatch.setattr(
        sw_configure,
        "build_findings_report",
        lambda _root, **_kwargs: {"verdict": "pass", "warnings": []},
    )
    monkeypatch.setattr(
        sw_configure,
        "interview_reuse_bundle",
        lambda _root, **_kwargs: {
            "engine": "existing-init-infrastructure",
            "profileClassification": {"verdict": "pass", "rows": []},
            "planConsent": {"gate": "plan", "verdict": "pass", "consented": True},
            "applyConsent": {"gate": "apply", "verdict": "pass", "consented": True},
        },
    )

    declined = sw_configure.run_priority_zero_interview(tmp_path)
    assert declined["coverage"]["recorded"] == 5
    by_surface = {row["surface"]: row for row in declined["priorityZero"]}
    # defaultBaseBranch can still be detected from the host default even with an empty config.
    assert by_surface["defaultBaseBranch"]["state"] in {"detected", "declined"}
    for name, row in by_surface.items():
        if name == "defaultBaseBranch" and row["state"] == "detected":
            continue
        assert row["state"] == "declined"
        assert str(row.get("consequence") or "").strip()

    confirmed = sw_configure.run_priority_zero_interview(tmp_path, accept_defaults=True)
    assert confirmed["coverage"]["recorded"] == 5
    assert all(row["state"] in {"confirmed", "detected"} for row in confirmed["priorityZero"])
    states = {row["surface"]: row["state"] for row in confirmed["priorityZero"]}
    assert states["defaultBaseBranch"] in {"detected", "confirmed"}
