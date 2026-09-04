#!/usr/bin/env python3
"""PRD 082 R26 — planning authority, ledger, and facade documentation currency bindings."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

PLANNING_DOC_BINDINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "layout-planning-authority",
        "doc": ".shipwright/layout.md",
        "sources": (
            "scripts/planning_store_facade.py",
            "scripts/planning_authority.py",
            "scripts/planning_ledger_store.py",
        ),
        "markers": (
            "Planning backend and authority",
            "planning_store_facade",
            "facade boundary",
            "sw-refusal-ledger",
            "refusal-ledger",
        ),
    },
    {
        "id": "layout-reference-mirror",
        "doc": "core/sw-reference/layout.md",
        "sources": (".shipwright/layout.md",),
        "markers": (
            "Planning backend and authority",
            "planning_store_facade",
            "facade boundary",
            "sw-refusal-ledger",
        ),
    },
    {
        "id": "commands-refusal-ledger",
        "doc": "docs/guides/commands.md",
        "sources": (
            "scripts/planning_refusal_ledger_cli.py",
            "scripts/planning_refusal_ledger.py",
        ),
        "markers": (
            "refusal ledger",
            "planning_refusal_ledger_cli.py",
            "list",
            "show",
            "export",
            "purge",
            "human decision",
        ),
    },
    {
        "id": "planning-store-capabilities",
        "doc": "core/providers/planning-store/CAPABILITIES.md",
        "sources": (
            "scripts/planning_authority.py",
            "scripts/planning_authority_reasons.py",
        ),
        "markers": (
            "Authority states",
            "online",
            "read-only",
            "blocked",
            "writeDisposition",
            "no silent fallback",
        ),
    },
    {
        "id": "memory-guardrails-redaction",
        "doc": "core/rules/memory-guardrails.mdc",
        "sources": (
            "scripts/memory_redact.py",
        ),
        "markers": (
            "--destination",
            "fail-closed",
            "emission point",
            "resolve_emission_destination",
        ),
    },
    {
        "id": "configuration-workflow-extensions",
        "doc": "docs/guides/configuration.md",
        "sources": (
            "scripts/workflow_extensions.py",
            "scripts/handoff_bundle.py",
            "scripts/workflow_pack_sdk.py",
            "scripts/planning_external_intake.py",
        ),
        "markers": (
            "workflow.extensions",
            "externalIntake",
            "handoffBundle",
            "packageSdk",
            "HandoffBundle",
            "workflow-pack-sdk",
            "External intake",
        ),
    },
)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _git_last_commit_epoch(root: Path, rel_path: str) -> float | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%ct", "--", rel_path],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    line = proc.stdout.strip()
    return float(line) if line.isdigit() else None


def _content_age(root: Path, path: Path) -> float:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return _mtime(path)
    git_age = _git_last_commit_epoch(root, rel)
    if git_age is not None:
        return git_age
    return _mtime(path)


def check_planning_doc_currency(root: Path) -> list[dict[str, Any]]:
    """Return drift rows when planning authority docs are missing, marker-incomplete, or stale."""
    drift: list[dict[str, Any]] = []
    for binding in PLANNING_DOC_BINDINGS:
        doc_rel = str(binding["doc"])
        doc_path = root / doc_rel
        if not doc_path.is_file():
            drift.append({"kind": "planning-doc-missing", "artifact": doc_rel, "id": binding["id"]})
            continue

        text = doc_path.read_text(encoding="utf-8")
        missing_markers = [m for m in binding["markers"] if m not in text]
        if missing_markers:
            drift.append(
                {
                    "kind": "planning-doc-marker-missing",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "missingMarkers": missing_markers,
                }
            )

        source_paths = [root / rel for rel in binding["sources"] if (root / rel).is_file()]
        if not source_paths:
            drift.append(
                {
                    "kind": "planning-doc-sources-missing",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "sources": list(binding["sources"]),
                }
            )
            continue

        doc_mtime = _content_age(root, doc_path)
        newest_source = max(source_paths, key=lambda p: _content_age(root, p))
        newest_mtime = _content_age(root, newest_source)
        if doc_mtime + 1e-6 < newest_mtime:
            drift.append(
                {
                    "kind": "planning-doc-stale",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "docMtime": doc_mtime,
                    "newestSource": newest_source.relative_to(root).as_posix(),
                    "sourceMtime": newest_mtime,
                }
            )
    return drift
