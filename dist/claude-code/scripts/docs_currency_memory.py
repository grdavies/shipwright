#!/usr/bin/env python3
"""PRD 082 R29 — memory envelope and redaction documentation currency bindings."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from memory_envelope_v2 import REQUIRED_FIELDS

CANONICAL_ENVELOPE_FIELDS: frozenset[str] = REQUIRED_FIELDS

MEMORY_SKILL_MARKERS: tuple[str, ...] = (
    "schemaVersion",
    "appliedRedaction",
    "--destination",
    "migration gate",
    "memory-authoritative",
    "/sw-memory-export",
    "/sw-memory-import",
    "/sw-memory-sync",
    "/sw-memory-audit",
    *sorted(CANONICAL_ENVELOPE_FIELDS),
)

MEMORY_COMMAND_DOCS: tuple[dict[str, str], ...] = (
    {"id": "sw-memory-export", "doc": "core/commands/sw-memory-export.md"},
    {"id": "sw-memory-import", "doc": "core/commands/sw-memory-import.md"},
    {"id": "sw-memory-sync", "doc": "core/commands/sw-memory-sync.md"},
    {"id": "sw-memory-audit", "doc": "core/commands/sw-memory-audit.md"},
)

MEMORY_DOC_BINDINGS: tuple[dict[str, Any], ...] = (
    {
        "id": "memory-skill",
        "doc": "core/skills/memory/SKILL.md",
        "sources": (
            "scripts/memory_envelope_v2.py",
            "scripts/memory_redact.py",
            "scripts/memory_sot.py",
        ),
        "markers": MEMORY_SKILL_MARKERS,
    },
    {
        "id": "memory-provider-catalog",
        "doc": "core/sw-reference/memory-provider-catalog.json",
        "sources": ("scripts/memory_envelope_v2.py",),
        "markers": ("envelopeFields",),
    },
    {
        "id": "contributing-ci-topology",
        "doc": "CONTRIBUTING.md",
        "sources": ("core/sw-reference/suite-registry.json", "scripts/ci_plan_gen.py"),
        "markers": (
            "pull-request-core",
            "changed-domain",
            "main-full",
            "scheduled-full-plus-integration",
            "minimum-python",
            "planning-doctor.py",
            "credentials-doctor.py",
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


def _catalog_envelope_coverage(root: Path) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    catalog_path = root / "core/sw-reference/memory-provider-catalog.json"
    if not catalog_path.is_file():
        drift.append({"kind": "catalog-missing", "artifact": str(catalog_path)})
        return drift
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        drift.append({"kind": "catalog-invalid-json", "artifact": str(catalog_path)})
        return drift
    providers = catalog.get("providers")
    if not isinstance(providers, dict):
        drift.append({"kind": "catalog-missing-providers", "artifact": str(catalog_path)})
        return drift
    for provider_id, row in providers.items():
        if not isinstance(row, dict):
            continue
        fields = row.get("envelopeFields")
        if not isinstance(fields, dict):
            drift.append(
                {
                    "kind": "catalog-envelope-fields-missing",
                    "provider": provider_id,
                    "artifact": str(catalog_path),
                }
            )
            continue
        covered: set[str] = set()
        for bucket in ("native", "sideChannel", "lossy"):
            values = fields.get(bucket)
            if not isinstance(values, list):
                drift.append(
                    {
                        "kind": "catalog-envelope-bucket-invalid",
                        "provider": provider_id,
                        "bucket": bucket,
                    }
                )
                continue
            covered.update(str(v) for v in values)
        missing = sorted(CANONICAL_ENVELOPE_FIELDS - covered)
        extra = sorted(covered - CANONICAL_ENVELOPE_FIELDS)
        if missing:
            drift.append(
                {
                    "kind": "catalog-envelope-field-missing",
                    "provider": provider_id,
                    "missingFields": missing,
                }
            )
        if extra:
            drift.append(
                {
                    "kind": "catalog-envelope-field-unknown",
                    "provider": provider_id,
                    "unknownFields": extra,
                }
            )
    return drift


def _command_doc_destination_markers(root: Path) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    envelope_enum_markers = ("memory_envelope_v2", "Envelope v2 fields")
    for entry in MEMORY_COMMAND_DOCS:
        doc_path = root / str(entry["doc"])
        if not doc_path.is_file():
            drift.append(
                {
                    "kind": "memory-command-doc-missing",
                    "id": entry["id"],
                    "doc": entry["doc"],
                }
            )
            continue
        text = doc_path.read_text(encoding="utf-8")
        if entry["id"] == "sw-memory-sync" and "--destination" not in text:
            drift.append(
                {
                    "kind": "memory-command-destination-missing",
                    "id": entry["id"],
                    "doc": entry["doc"],
                }
            )
        if entry["id"] in {"sw-memory-sync", "sw-memory-import"}:
            if not any(marker in text for marker in envelope_enum_markers):
                drift.append(
                    {
                        "kind": "memory-command-envelope-enum-missing",
                        "id": entry["id"],
                        "doc": entry["doc"],
                    }
                )
            missing_fields = sorted(f for f in CANONICAL_ENVELOPE_FIELDS if f not in text)
            if missing_fields:
                drift.append(
                    {
                        "kind": "memory-command-envelope-field-missing",
                        "id": entry["id"],
                        "missingFields": missing_fields,
                        "doc": entry["doc"],
                    }
                )
    return drift


def check_memory_doc_currency(root: Path) -> list[dict[str, Any]]:
    """Return drift rows when memory docs are missing, marker-incomplete, stale, or codec-mismatched."""
    drift: list[dict[str, Any]] = []
    drift.extend(_catalog_envelope_coverage(root))
    drift.extend(_command_doc_destination_markers(root))

    for binding in MEMORY_DOC_BINDINGS:
        doc_rel = str(binding["doc"])
        doc_path = root / doc_rel
        if not doc_path.is_file():
            drift.append({"kind": "memory-doc-missing", "artifact": doc_rel, "id": binding["id"]})
            continue

        if doc_path.suffix == ".json":
            # JSON bindings validated via catalog coverage above; still check staleness below.
            text = doc_path.read_text(encoding="utf-8")
            missing_markers = [m for m in binding.get("markers", ()) if m not in text]
            if missing_markers:
                drift.append(
                    {
                        "kind": "memory-doc-marker-missing",
                        "artifact": doc_rel,
                        "id": binding["id"],
                        "missingMarkers": missing_markers,
                    }
                )
        else:
            text = doc_path.read_text(encoding="utf-8")
            missing_markers = [m for m in binding.get("markers", ()) if m not in text]
            if missing_markers:
                drift.append(
                    {
                        "kind": "memory-doc-marker-missing",
                        "artifact": doc_rel,
                        "id": binding["id"],
                        "missingMarkers": missing_markers,
                    }
                )

        source_paths = [root / rel for rel in binding.get("sources", ()) if (root / rel).is_file()]
        if not source_paths:
            drift.append(
                {
                    "kind": "memory-doc-sources-missing",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "sources": list(binding.get("sources", ())),
                }
            )
            continue

        doc_mtime = _content_age(root, doc_path)
        newest_source = max(source_paths, key=lambda p: _content_age(root, p))
        newest_mtime = _content_age(root, newest_source)
        if doc_mtime + 1e-6 < newest_mtime:
            drift.append(
                {
                    "kind": "memory-doc-stale",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "docMtime": doc_mtime,
                    "newestSource": newest_source.relative_to(root).as_posix(),
                    "sourceMtime": newest_mtime,
                }
            )

    return drift
