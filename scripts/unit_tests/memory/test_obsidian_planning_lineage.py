"""PRD 076 R32–R33 — planning lineage for obsidian provider (item C only)."""
from __future__ import annotations

import json
from pathlib import Path

from memory_provider_catalog import get_provider, load_catalog, validate_catalog


def test_obsidian_catalog_row_present(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    row = get_provider(catalog, "obsidian")
    assert row["adapterDoc"] == "core/providers/obsidian.md"
    assert row["rulesScript"] == "providers/obsidian-rules.py"
    assert row["capabilities"]["semanticSearch"] is False
    assert row["capabilities"]["filePathSearch"] is True


def test_obsidian_lineage_depends_on_071_not_074_075(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    row = get_provider(catalog, "obsidian")
    lineage = row["planningLineage"]
    assert lineage["prd"] == "076-prd-obsidian-memory-provider"
    assert lineage["dependsOn"] == ["071-prd-pluggable-memory-adapter-framework"]
    assert "074-prd-mempalace-memory-provider" in lineage["doesNotSupersede"]
    assert "075-prd-basic-memory-provider" in lineage["doesNotSupersede"]
    assert "010" in lineage["doesNotSupersede"]
    # must not claim dependency edges that supersede peer providers
    for peer in lineage["doesNotSupersede"]:
        assert peer not in lineage["dependsOn"]


def test_obsidian_portfolio_item_c_only(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    row = get_provider(catalog, "obsidian")
    lineage = row["planningLineage"]
    assert lineage["portfolioItem"] == "C"
    assert lineage["portfolioDecision"] == "planning#491"


def test_emit_mirrors_include_obsidian_lineage(repo_root: Path) -> None:
    for rel in (
        ".sw/memory-provider-catalog.json",
        "core/sw-reference/memory-provider-catalog.json",
        "dist/cursor/core/sw-reference/memory-provider-catalog.json",
        "dist/claude-code/core/sw-reference/memory-provider-catalog.json",
    ):
        path = repo_root / rel
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        validate_catalog(data)
        lineage = data["providers"]["obsidian"]["planningLineage"]
        assert lineage["dependsOn"] == ["071-prd-pluggable-memory-adapter-framework"]
        assert lineage["portfolioItem"] == "C"


def test_peer_providers_remain_present(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    # item C must not remove or supersede peers
    assert get_provider(catalog, "mempalace")
    assert get_provider(catalog, "basic-memory")
    assert get_provider(catalog, "in-repo")
