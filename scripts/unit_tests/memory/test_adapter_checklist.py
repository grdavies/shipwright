"""PRD 071 R5 — adapter registration checklist + SSRF policy conformance."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "sw_recallium_url_scripts",
    SCRIPTS / "sw_recallium_url.py",
)
assert _SPEC and _SPEC.loader
sw_recallium_url = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sw_recallium_url)

from memory_adapter_checklist import (
    ChecklistError,
    capabilities_doc_contains_checklist,
    validate_provider_checklist,
    validate_seeded_catalog_checklist,
)
from memory_provider_catalog import get_provider, load_catalog

RestFetchPolicyError = sw_recallium_url.RestFetchPolicyError
is_allowed_recallium_base = sw_recallium_url.is_allowed_recallium_base
is_rest_url_allowed = sw_recallium_url.is_rest_url_allowed
rest_fetch_policy_from_catalog_entry = sw_recallium_url.rest_fetch_policy_from_catalog_entry
validate_rest_url = sw_recallium_url.validate_rest_url

CAPABILITIES_PATH = (
    Path(__file__).resolve().parents[3] / "core" / "skills" / "memory" / "CAPABILITIES.md"
)


def test_capabilities_doc_documents_registration_checklist() -> None:
    text = CAPABILITIES_PATH.read_text(encoding="utf-8")
    assert capabilities_doc_contains_checklist(text)


def test_seeded_catalog_entries_satisfy_checklist(repo_root: Path) -> None:
    """O — recallium and in-repo satisfy the registration checklist including credentials."""
    provider_ids = validate_seeded_catalog_checklist(repo_root)
    assert provider_ids == ["in-repo", "recallium"]


def test_missing_credentials_clause_fails_checklist(repo_root: Path, tmp_path: Path) -> None:
    """M — credentials clause is mandatory for every catalog row."""
    catalog = json.loads(json.dumps(load_catalog(repo_root)))
    del catalog["providers"]["recallium"]["credentials"]
    row = catalog["providers"]["recallium"]
    with pytest.raises(ChecklistError) as exc:
        validate_provider_checklist("recallium", row)
    assert "credentials" in str(exc.value)


def test_recallium_rest_policy_allows_localhost_only(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    policy = rest_fetch_policy_from_catalog_entry(get_provider(catalog, "recallium"))
    assert is_rest_url_allowed("http://localhost:8001/health", policy)
    assert is_rest_url_allowed("http://127.0.0.1:8001/health", policy)
    assert not is_rest_url_allowed("http://169.254.169.254/latest/meta-data/", policy)
    assert not is_rest_url_allowed("http://10.0.0.1/", policy)


def test_in_repo_has_no_rest_policy_requirement(repo_root: Path) -> None:
    catalog = load_catalog(repo_root)
    policy = rest_fetch_policy_from_catalog_entry(get_provider(catalog, "in-repo"))
    assert policy["allowLoopback"] is True
    assert policy["allowPrivate"] is False


def test_shared_rest_fetch_blocks_metadata_and_private() -> None:
    strict = {
        "allowedHosts": [],
        "allowLoopback": False,
        "allowPrivate": False,
        "allowLinkLocal": False,
        "allowMetadata": False,
    }
    with pytest.raises(RestFetchPolicyError):
        validate_rest_url("http://169.254.169.254/", strict)
    with pytest.raises(RestFetchPolicyError):
        validate_rest_url("http://10.1.2.3/", strict)
    with pytest.raises(RestFetchPolicyError):
        validate_rest_url("file:///etc/passwd", strict)


def test_recallium_base_guard_matches_legacy_behavior() -> None:
    assert is_allowed_recallium_base("http://localhost:8001")
    assert is_allowed_recallium_base("http://127.0.0.1:8001")
    assert not is_allowed_recallium_base("http://169.254.169.254/")
    assert not is_allowed_recallium_base("file:///etc/passwd")
