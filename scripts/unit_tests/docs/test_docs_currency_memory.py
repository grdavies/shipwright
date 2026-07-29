"""PRD 082 R29 — memory envelope and redaction documentation currency fixtures."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from docs_currency_memory import (
    CANONICAL_ENVELOPE_FIELDS,
    MEMORY_DOC_BINDINGS,
    check_memory_doc_currency,
)
from memory_envelope_v2 import REQUIRED_FIELDS


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "core/skills/memory").mkdir(parents=True)
    (root / "core/sw-reference").mkdir(parents=True)
    (root / "core/commands").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    for binding in MEMORY_DOC_BINDINGS:
        for rel in binding["sources"]:
            src = root / rel
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(f"# source for {binding['id']}\n", encoding="utf-8")
    time.sleep(0.02)
    catalog = {
        "version": 1,
        "providers": {
            "in-repo": {
                "envelopeFields": {
                    "native": sorted(CANONICAL_ENVELOPE_FIELDS),
                    "sideChannel": [],
                    "lossy": [],
                }
            }
        },
    }
    (root / "core/sw-reference/memory-provider-catalog.json").write_text(
        __import__("json").dumps(catalog),
        encoding="utf-8",
    )
    for binding in MEMORY_DOC_BINDINGS:
        doc = root / str(binding["doc"])
        doc.parent.mkdir(parents=True, exist_ok=True)
        if doc.suffix == ".json":
            doc.write_text(__import__("json").dumps(catalog), encoding="utf-8")
        else:
            doc.write_text("\n".join(binding["markers"]) + "\n", encoding="utf-8")
    for cmd in (
        "sw-memory-export.md",
        "sw-memory-import.md",
        "sw-memory-sync.md",
        "sw-memory-audit.md",
    ):
        (root / "core/commands" / cmd).write_text(
            "memory_envelope_v2\nEnvelope v2 fields\n"
            + "\n".join(sorted(CANONICAL_ENVELOPE_FIELDS))
            + "\n--destination committed\n",
            encoding="utf-8",
        )
    return root


def test_canonical_fields_match_codec() -> None:
    assert CANONICAL_ENVELOPE_FIELDS == REQUIRED_FIELDS


def test_memory_doc_currency_passes_when_current(repo: Path) -> None:
    assert check_memory_doc_currency(repo) == []


def test_memory_doc_currency_fails_when_doc_stale(repo: Path) -> None:
    binding = MEMORY_DOC_BINDINGS[0]
    source = repo / str(binding["sources"][0])
    time.sleep(0.02)
    source.write_text("# touched\n", encoding="utf-8")
    drift = check_memory_doc_currency(repo)
    assert any(row.get("kind") == "memory-doc-stale" and row.get("id") == binding["id"] for row in drift)


def test_memory_doc_currency_fails_when_marker_missing(repo: Path) -> None:
    doc = repo / "core/skills/memory/SKILL.md"
    doc.write_text("# incomplete\n", encoding="utf-8")
    drift = check_memory_doc_currency(repo)
    assert any(row.get("kind") == "memory-doc-marker-missing" for row in drift)


def test_memory_doc_currency_fails_when_catalog_field_missing(repo: Path) -> None:
    catalog_path = repo / "core/sw-reference/memory-provider-catalog.json"
    catalog = __import__("json").loads(catalog_path.read_text(encoding="utf-8"))
    catalog["providers"]["in-repo"]["envelopeFields"]["native"] = ["stableId"]
    catalog_path.write_text(__import__("json").dumps(catalog), encoding="utf-8")
    drift = check_memory_doc_currency(repo)
    assert any(row.get("kind") == "catalog-envelope-field-missing" for row in drift)


def test_docs_currency_gate_imports_memory_check() -> None:
    text = (SCRIPT_DIR / "docs-currency-gate.py").read_text(encoding="utf-8")
    assert "from docs_currency_memory import check_memory_doc_currency" in text
    assert "check_memory_doc_currency(root)" in text
