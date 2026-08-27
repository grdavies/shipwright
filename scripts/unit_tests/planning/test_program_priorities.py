"""Program priority authority and projection tests (PRD 333 phase 3 — R5/R6/R18/R20)."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_priority_projection as ppp


def _authority_doc() -> dict:
    path = scripts.parent / ".sw" / "program-priorities.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_p0_p3_authority() -> None:
    """R5 — complete P0-P3 ranking; reject duplicate rank and second authority."""
    doc = _authority_doc()
    validated = ppp.validate_authority(doc)
    assert set(validated["priorityTiers"]) == set(ppp.TIER_ORDER)

    duplicate_rank = copy.deepcopy(doc)
    duplicate_rank["priorityTiers"]["P1"]["rank"] = 0
    with pytest.raises(ValueError, match="duplicate-priority-rank"):
        ppp.validate_authority(duplicate_rank)

    second_authority = copy.deepcopy(doc)
    second_authority["authorityPath"] = ".sw/program-priorities.alt.json"
    with pytest.raises(ValueError, match="second-authority-path"):
        ppp.validate_authority(second_authority)


def test_release_sequence_projection() -> None:
    """R6 — three release trains project deterministically; reject inversion and unknown train."""
    doc = _authority_doc()
    projection = ppp.project_index_fields(doc)
    trains = projection["releaseSequence"]
    assert [item["id"] for item in trains] == list(ppp.RELEASE_TRAIN_IDS)

    inverted = copy.deepcopy(doc)
    inverted["releaseSequence"][0]["order"] = 2
    inverted["releaseSequence"][1]["order"] = 2
    with pytest.raises(ValueError, match="duplicate-release-sequence"):
        ppp.validate_authority(inverted)

    unknown_train = copy.deepcopy(doc)
    unknown_train["releaseSequence"][1]["id"] = "v9.9"
    with pytest.raises(ValueError, match="unknown-release-train"):
        ppp.validate_authority(unknown_train)


def test_provider_follow_on_order() -> None:
    """R18 — GitLab first, marketplace last; reject order inversion."""
    doc = _authority_doc()
    follow_on = ppp.project_graph_metadata(doc)["providerFollowOn"]
    assert [item["id"] for item in follow_on] == list(ppp.PROVIDER_FOLLOW_ON_IDS)
    assert follow_on[0]["id"] == "gitlab-planning-store"
    assert follow_on[-1]["id"] == "workflow-package-marketplace"

    inverted = copy.deepcopy(doc)
    inverted["providerFollowOn"][0]["order"] = 2
    inverted["providerFollowOn"][1]["order"] = 2
    with pytest.raises(ValueError, match="duplicate-provider-follow-on"):
        ppp.validate_authority(inverted)


def test_projections_cannot_be_authority() -> None:
    """R20 — projection artifacts cannot be treated as authority."""
    doc = _authority_doc()
    projection = ppp.project_all(doc)
    assert projection["projection"] is True
    assert projection["authorityPath"] == ppp.AUTHORITY_REL_PATH

    with pytest.raises(ValueError, match="projection-cannot-be-authority"):
        ppp.reject_projection_as_authority(".sw/program-priorities.projection.json")

    with pytest.raises(ValueError, match="projection-cannot-be-authority"):
        ppp.validate_authority(doc, source=".sw/program-priorities.labels.json")


def test_gitlab_remote_provenance_marketplace_order() -> None:
    """D6 — four-stage provider follow-on order is stable in priority metadata."""
    doc = _authority_doc()
    metadata = ppp.project_graph_metadata(doc)
    ids = [item["id"] for item in metadata["providerFollowOn"]]
    assert ids == [
        "gitlab-planning-store",
        "remote-execution",
        "upstream-provenance",
        "workflow-package-marketplace",
    ]
    assert metadata["priorityTiers"]["P2"]["programs"][0] == "gitlab-planning-store"
    assert metadata["priorityTiers"]["P3"]["programs"][0] == "workflow-package-marketplace"


def test_planning_graph_priority_projection_command(tmp_path: Path) -> None:
    """Wiring — planning_graph exposes read-only priority projection."""
    import subprocess

    authority = tmp_path / ".sw"
    authority.mkdir(parents=True)
    shutil_copy = _authority_doc()
    (authority / "program-priorities.json").write_text(
        json.dumps(shutil_copy, indent=2),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "planning_graph.py"),
            str(tmp_path),
            "priority-projection",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "ok"
    assert payload["projection"] is True
    assert "sw:provider-follow-on:gitlab-planning-store" in payload["labels"]
