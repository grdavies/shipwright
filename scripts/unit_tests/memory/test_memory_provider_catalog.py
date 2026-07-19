"""PRD 071 R2 — memory provider catalog fail-closed loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_provider_catalog import (
    SEEDED_PROVIDER_IDS,
    CatalogError,
    get_provider,
    load_catalog,
    provider_ids,
    resolve_catalog_path,
    validate_catalog,
)


def test_seeded_catalog_loads(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    assert catalog["version"] == 1
    assert provider_ids(catalog) == SEEDED_PROVIDER_IDS


def test_recallium_entry_matches_adapter_flags(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    recallium = get_provider(catalog, "recallium")
    assert recallium["capabilities"]["semanticSearch"] is True
    assert recallium["capabilities"]["export"] is False
    assert recallium["interchange"]["jsonl"] == "synthesized"
    assert recallium["interchange"]["okf"] == "synthesized"
    assert recallium["sourceOfTruthClass"] == "memory-authoritative"
    assert recallium["hookTransport"]["agentSession"] == "mcp"


def test_in_repo_entry_is_first_class(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    in_repo = get_provider(catalog, "in-repo")
    assert in_repo["capabilities"]["export"] is True
    assert in_repo["capabilities"]["import"] is True
    assert in_repo["interchange"]["jsonl"] == "native"
    assert in_repo["interchange"]["okf"] == "native"
    assert in_repo["sourceOfTruthClass"] == "repo-authoritative"
    assert in_repo["hookTransport"]["agentSession"] == "filesystem"


def test_missing_catalog_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(CatalogError) as exc:
        load_catalog(tmp_path)
    assert exc.value.cause == "missing"


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    catalog_path = tmp_path / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError) as exc:
        load_catalog(tmp_path)
    assert exc.value.cause == "malformed"


def test_partial_write_missing_provider_fails_closed(repo_root: Path, tmp_path: Path) -> None:
    source = load_catalog(repo_root)
    partial = json.loads(json.dumps(source))
    del partial["providers"]["in-repo"]
    catalog_path = tmp_path / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(partial), encoding="utf-8")
    with pytest.raises(CatalogError) as exc:
        load_catalog(tmp_path)
    assert exc.value.cause == "partial"


def test_partial_write_missing_capability_flag_fails_closed(repo_root: Path, tmp_path: Path) -> None:
    source = load_catalog(repo_root)
    partial = json.loads(json.dumps(source))
    del partial["providers"]["recallium"]["capabilities"]["semanticSearch"]
    catalog_path = tmp_path / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(partial), encoding="utf-8")
    with pytest.raises(CatalogError) as exc:
        load_catalog(tmp_path)
    assert exc.value.cause == "partial"


def test_no_legacy_allowlist_fallback_on_missing(tmp_path: Path) -> None:
    """Z — missing catalog must not fall back to hard-coded recallium/in-repo allowlist."""
    with pytest.raises(CatalogError):
        load_catalog(tmp_path)
    assert not resolve_catalog_path(tmp_path).is_file()


def test_resolve_catalog_path_falls_back_to_emit_when_sw_missing(
    repo_root: Path, tmp_path: Path
) -> None:
    """Plugin install layout: no .sw/, but core/sw-reference emit is present."""
    from memory_provider_catalog import CATALOG_EMIT_REL, CATALOG_REL

    plugin = tmp_path / "plugin"
    emit = plugin / CATALOG_EMIT_REL
    emit.parent.mkdir(parents=True)
    emit.write_text(
        (repo_root / CATALOG_REL).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert not (plugin / CATALOG_REL).is_file()
    assert resolve_catalog_path(plugin) == emit.resolve()
    catalog = load_catalog(plugin)
    assert provider_ids(catalog) == SEEDED_PROVIDER_IDS


def test_validate_rejects_unknown_interchange_mode(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    drifted = json.loads(json.dumps(catalog))
    drifted["providers"]["recallium"]["interchange"]["jsonl"] = "maybe"
    with pytest.raises(CatalogError) as exc:
        validate_catalog(drifted)
    assert exc.value.cause == "partial"
