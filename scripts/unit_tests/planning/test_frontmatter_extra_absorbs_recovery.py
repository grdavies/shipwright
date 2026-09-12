"""Recovery of mis-serialized absorbs from sw-frontmatter-extra for closeout."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from planning_store_facade import (
    _recover_absorbs_from_frontmatter_extra,
    _resolve_prd_absorption_context,
    gap_has_absorb_provenance,
)


def test_recover_absorbs_from_frontmatter_extra_when_edges_missing() -> None:
    gap = "gap-441-cursor-golden-manifest-still-lags-dist-cursor-af"
    body = (
        "<!-- sw-hybrid-frontmatter -->\n"
        f"<!-- sw-frontmatter-extra: {json.dumps({'absorbs': [gap], 'planningIssues': [951]})} -->\n"
        "# PRD\n"
    )
    fm, edges = _recover_absorbs_from_frontmatter_extra(body, {}, {})
    assert fm["absorbs"] == gap
    assert edges["edges"] == [{"rel": "absorbs", "target": gap}]


def test_recover_absorbs_does_not_override_existing_projection() -> None:
    body = (
        "<!-- sw-hybrid-frontmatter -->\n"
        '<!-- sw-frontmatter-extra: {"absorbs": ["gap-other"]} -->\n'
        "# PRD\n"
    )
    fm, edges = _recover_absorbs_from_frontmatter_extra(
        body,
        {"absorbs": "gap-kept"},
        {"edges": [{"rel": "absorbs", "target": "gap-kept"}]},
    )
    assert fm["absorbs"] == "gap-kept"
    assert edges["edges"] == [{"rel": "absorbs", "target": "gap-kept"}]


def test_resolve_prd_absorption_context_hybrid_extra_absorbs(tmp_path: Path) -> None:
    gap = "gap-443-readme-adopter-install-path-still-requires-a-sou"
    prd_unit = "345-prd-shipwright-distribution-onboarding"
    body = (
        "<!-- sw-hybrid-frontmatter -->\n"
        f"<!-- sw-frontmatter-extra: {json.dumps({'absorbs': [gap], 'planningIssues': [955]})} -->\n"
        "# PRD 345\n"
    )
    record = SimpleNamespace(labels=["sw:prd", "sw:status:complete"], unit_id=prd_unit)
    fm, edges = _resolve_prd_absorption_context(record, prd_unit, body)
    assert gap in fm.get("absorbs", "")
    assert gap_has_absorb_provenance(
        tmp_path,
        {},
        gap,
        prd_unit,
        fm,
        prd_num="345",
        edges=edges,
    )
