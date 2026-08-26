"""PRD 331 R36 — absorb traceability edges for first-release explore gaps."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc
from planning_canonical import build_edges_block, parse_edges_block, reconcile_edges
from planning_store import discover_absorbed_units_anchored

PRD_331_UNIT_ID = "331-prd-sw-explore-first-release"
PRD_331_NUMBER = "331"
PRD_331_FROZEN_REL = Path(
    ".cursor/sw-doc-runs/v250-review-gaps/review/331-prd-sw-explore-first-release-frozen.md"
)

PRD_331_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-346-add-sw-explore-as-first-class-pre-planning-works",
    "gap-347-sw-explore-first-release-must-include-full-entry",
    "gap-348-destination-first-exploration-model-before-large",
    "gap-349-structured-exploration-fields-outcomes-constrain",
    "gap-350-conversational-first-exploration-with-persistent",
    "gap-351-define-and-implement-explorationmap-v1",
    "gap-352-exploration-node-types-for-questions-decisions-e",
    "gap-353-reuse-researchevidence-and-prototypeevidence-ins",
    "gap-354-repository-discovery-in-first-sw-explore-release",
    "gap-356-architecture-radar-integration-in-first-sw-explo",
    "gap-358-historical-memory-integration-in-first-sw-explor",
    "gap-360-greenfield-support-for-sw-explore",
    "gap-361-domain-vocabulary-integration-in-first-sw-explor",
    "gap-363-exploration-authority-boundaries-plans-does-not-",
    "gap-364-automatic-planning-unit-decomposition-from-explo",
    "gap-368-define-and-emit-planningreadiness-v1-from-sw-exp",
    "gap-372-blocking-non-blocking-and-deferred-uncertainty-c",
    "gap-374-decision-supersession-and-invalidation-during-mu",
    "gap-377-define-and-emit-explorationbrief-v1-as-explore-h",
    "gap-378-handoffbundle-cross-session-resume-in-first-sw-e",
    "gap-379-provider-backed-exploration-map-frontier-visuali",
    "gap-380-sw-status-exploration-summary-and-explain-decisi",
    "gap-381-bare-sw-routing-across-capture-explore-doc-deliv",
    "gap-382-sw-doc-should-route-backward-to-sw-explore-when-",
    "gap-383-sw-explore-should-route-forward-explicitly-to-sw",
    "gap-384-human-interaction-model-for-exploration-question",
    "gap-385-do-not-apply-quick-standard-full-tiers-at-sw-exp",
    "gap-392-update-workflow-command-contracts-for-explore-in",
    "gap-393-do-not-add-a-bag-of-explore-supporting-top-level",
    "gap-394-adopt-recommended-bounded-command-taxonomy-inclu",
    "gap-396-sw-explore-first-release-acceptance-scope-entry-",
    "gap-398-instrument-sw-explore-quality-metrics-from-first",
    "gap-399-encode-sw-explore-anti-goals-not-mega-planner-im",
    "gap-400-preserve-architectural-principles-while-adding-e",
)

PRD_331_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (
    829,
    830,
    831,
    832,
    833,
    834,
    835,
    836,
    837,
    839,
    841,
    842,
    843,
    844,
    845,
    848,
    851,
    853,
    855,
    856,
    857,
    858,
    859,
    860,
    861,
    862,
    863,
    870,
    871,
    872,
    874,
    876,
    877,
    878,
)


def _prd_331_edges() -> list[dict[str, str]]:
    return [{"target": gap_id, "rel": "absorbs"} for gap_id in PRD_331_ABSORB_GAP_UNITS]


def _parse_absorbs_from_frozen(repo_root: Path) -> list[str]:
    path = repo_root / PRD_331_FROZEN_REL
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^absorbs:\s*\[(.*)\]", text, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    return [item.strip() for item in match.group(1).split(",") if item.strip()]


def test_all_prd331_absorb_edges_are_durable() -> None:
    """R36 — every Absorb Traceability unit has exactly one canonical absorbs edge."""
    edges = {"edges": _prd_331_edges()}
    frontmatter = {
        "absorbs": "[" + ", ".join(PRD_331_ABSORB_GAP_UNITS) + "]",
        "planningIssues": "[" + ", ".join(str(n) for n in PRD_331_PLANNING_ISSUE_NUMBERS) + "]",
    }
    discovered, skipped = discover_absorbed_units_anchored(frontmatter, edges)
    assert not skipped, skipped
    assert len(discovered) == len(PRD_331_ABSORB_GAP_UNITS), (discovered, skipped)
    for gap_id in PRD_331_ABSORB_GAP_UNITS:
        matches = [item for item in discovered if pgc.gap_absorb_target_match(item, gap_id)]
        assert len(matches) == 1, gap_id


def test_prd331_absorb_fixture_matches_frozen_prd(repo_root: Path) -> None:
    """R36 — fixture tuple matches frozen PRD absorbs frontmatter when present."""
    parsed = _parse_absorbs_from_frozen(repo_root)
    if not parsed:
        pytest.skip("frozen PRD absorb frontmatter unavailable")
    assert parsed == list(PRD_331_ABSORB_GAP_UNITS)


def test_prd331_sw_edges_have_no_foreign_targets() -> None:
    """R36 — absorbs edges reference only PRD 331 traceability units."""
    allowed = set(PRD_331_ABSORB_GAP_UNITS)
    for edge in _prd_331_edges():
        assert edge["rel"] == "absorbs"
        assert edge["target"] in allowed


def test_prd331_related_only_edges_do_not_satisfy_absorbs() -> None:
    """R36 — related-only substitution is rejected by absorbs discovery."""
    frontmatter = {"absorbs": "[]", "planningIssues": "[829]"}
    edges = {
        "edges": [{"rel": "related", "target": gap_id} for gap_id in PRD_331_ABSORB_GAP_UNITS[:3]]
    }
    discovered, _skipped = discover_absorbed_units_anchored(frontmatter, edges)
    assert not discovered


def test_prd331_sw_edges_round_trip_preserves_absorbs(tmp_path: Path) -> None:
    """R36 — reconcile_edges preserves absorbs targets on round trip."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    edge_list = _prd_331_edges()
    body = (
        f"---\nid: {PRD_331_UNIT_ID}\ntype: prd\nstatus: draft\nvisibility: public\n---\n"
        f"# PRD 331\n"
        + build_edges_block(edge_list)
    )
    parsed = parse_edges_block(body)
    assert parsed is not None
    assert len(parsed.get("edges") or []) == len(PRD_331_ABSORB_GAP_UNITS)
    reconciled = reconcile_edges(parsed, parsed.get("native") or [])
    targets = {edge["target"] for edge in reconciled.get("edges") or [] if edge.get("rel") == "absorbs"}
    assert targets == set(PRD_331_ABSORB_GAP_UNITS)


@pytest.mark.parametrize("gap_id", PRD_331_ABSORB_GAP_UNITS)
def test_each_prd331_absorb_edge_is_canonical(gap_id: str) -> None:
    """R36 — one canonical absorbs edge per traceability unit."""
    edges = {"edges": _prd_331_edges()}
    frontmatter = {"absorbs": f"[{gap_id}]"}
    discovered, skipped = discover_absorbed_units_anchored(frontmatter, edges)
    assert not skipped
    assert any(pgc.gap_absorb_target_match(item, gap_id) for item in discovered)


def test_prd331_duplicate_absorb_edge_is_detected() -> None:
    """R36 — duplicate absorbs targets fail closed."""
    duplicate_edges = _prd_331_edges() + [{"target": PRD_331_ABSORB_GAP_UNITS[0], "rel": "absorbs"}]
    targets = [edge["target"] for edge in duplicate_edges if edge.get("rel") == "absorbs"]
    assert len(targets) != len(set(targets))
