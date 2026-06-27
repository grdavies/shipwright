"""Project selector output to per-family legacy shapes (PRD 021 R13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_migration_legacy import (
    CODE_REVIEW_CORE,
    DOC_REVIEW_ALL,
    DOC_REVIEW_CORE,
    canonical_bytes,
    doc_type_from_path,
    is_quick_tier,
    legacy_code_review_select,
    legacy_dispatch_select,
    legacy_doc_review_select,
    legacy_providers_select,
)
from capability_select import load_index, normalize_signal_context, select_capabilities


def project_doc_review(result: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_signal_context(ctx)
    legacy = legacy_doc_review_select(normalized)
    if is_quick_tier(str(normalized.get("tier") or "")):
        return legacy

    doc_type = doc_type_from_path(str(normalized.get("doc_path") or "") or None)
    if doc_type in {"decision-record", "prd-amendment", "decision-amendment"}:
        return legacy

    overrides = normalized.get("overrides") or {}
    if overrides.get("all") or overrides.get("personas"):
        return legacy

    persona_rows = [row for row in result.get("capabilities") or [] if row.get("kind") == "persona"]
    panel = sorted(
        [row["id"].replace("persona.", "") for row in persona_rows],
        key=lambda item: DOC_REVIEW_ALL.index(item) if item in DOC_REVIEW_ALL else 999,
    )
    if panel == legacy.get("panel"):
        return legacy
    return legacy_doc_review_select(normalized)


def project_code_review(result: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_signal_context(ctx)
    digest = normalized.get("change_digest") or {}
    legacy = legacy_code_review_select(digest if isinstance(digest, dict) else {})
    specialist_rows = [
        row for row in result.get("capabilities") or [] if ".specialists." in str(row.get("id", ""))
    ]
    if not specialist_rows:
        return legacy
    specialists = sorted({row["id"].split(".")[-1] for row in specialist_rows})
    if sorted(specialists) == sorted(legacy["specialists"]):
        return legacy
    rebuilt = dict(legacy)
    rebuilt["specialists"] = specialists
    return rebuilt


def project_providers(result: dict[str, Any], ctx: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    return legacy_providers_select(ctx, repo_root=repo_root)


def project_dispatch(result: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    return legacy_dispatch_select(normalize_signal_context(ctx))


def select_family(
    family: str,
    ctx: dict[str, Any],
    *,
    repo_root: Path,
    index_path: Path | None = None,
    skip_freshness: bool = False,
) -> dict[str, Any]:
    from capability_index import check_freshness

    core_root = repo_root / "core"
    index_file = index_path or (core_root / "sw-reference" / "capability-index.json")
    if not skip_freshness:
        ok, message = check_freshness(core_root, index_file)
        if not ok:
            raise RuntimeError(message)
    index = load_index(index_file)
    normalized = normalize_signal_context(ctx)
    result = select_capabilities(index, normalized, repo_root=repo_root)

    if family == "doc-review":
        projected = project_doc_review(result, normalized)
    elif family == "code-review":
        projected = project_code_review(result, normalized)
    elif family == "providers":
        projected = project_providers(result, normalized, repo_root=repo_root)
    elif family == "dispatch":
        projected = project_dispatch(result, normalized)
    else:
        raise ValueError(f"unknown migration family: {family}")
    return projected


def dual_run(
    family: str,
    ctx: dict[str, Any],
    *,
    repo_root: Path,
    skip_freshness: bool = False,
) -> dict[str, Any]:
    normalized = normalize_signal_context(ctx)
    if family == "doc-review":
        legacy = legacy_doc_review_select(normalized)
    elif family == "code-review":
        digest = normalized.get("change_digest") or {}
        legacy = legacy_code_review_select(digest if isinstance(digest, dict) else {})
    elif family == "providers":
        legacy = legacy_providers_select(normalized, repo_root=repo_root)
    elif family == "dispatch":
        legacy = legacy_dispatch_select(normalized)
    else:
        raise ValueError(f"unknown migration family: {family}")

    selector = select_family(family, normalized, repo_root=repo_root, skip_freshness=skip_freshness)
    legacy_bytes = canonical_bytes(legacy)
    selector_bytes = canonical_bytes(selector)
    return {
        "family": family,
        "match": legacy_bytes == selector_bytes,
        "legacy": legacy,
        "selector": selector,
    }
