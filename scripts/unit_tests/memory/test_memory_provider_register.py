"""PRD 071 R1 — memory provider registration validator."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_provider_catalog import load_catalog
from memory_provider_register import (
    RegistrationError,
    validate_provider_id,
    validate_registration,
)


@pytest.mark.parametrize("provider_id", ["recallium", "in-repo"])
def test_accepts_seeded_providers(repo_root: Path, provider_id: str) -> None:
    result = validate_registration(repo_root, provider_id)
    assert result["providerId"] == provider_id
    assert result["adapterDoc"]
    assert result["rulesScript"]


def test_rejects_unknown_provider(repo_root: Path) -> None:
    with pytest.raises(RegistrationError) as exc:
        validate_registration(repo_root, "not-a-real-provider")
    assert exc.value.cause == "unknown"


def test_rejects_empty_provider_id(repo_root: Path) -> None:
    with pytest.raises(RegistrationError) as exc:
        validate_provider_id("")
    assert exc.value.cause == "empty"


def test_rejects_traversal_provider_id(repo_root: Path) -> None:
    with pytest.raises(RegistrationError) as exc:
        validate_provider_id("../recallium")
    assert exc.value.cause in {"traversal", "invalid"}


def test_rejects_invalid_charset_provider_id(repo_root: Path) -> None:
    with pytest.raises(RegistrationError) as exc:
        validate_provider_id("Bad_Provider")
    assert exc.value.cause == "invalid"


def test_rejects_missing_rules_script(repo_root: Path, tmp_path: Path) -> None:
    catalog = load_catalog(repo_root)
    broken = json.loads(json.dumps(catalog))
    broken["providers"]["recallium"]["rulesScript"] = "providers/missing-recallium-rules.py"
    catalog_path = tmp_path / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(RegistrationError) as exc:
        validate_registration(tmp_path, "recallium", catalog=broken)
    assert exc.value.cause == "missing"


def test_rejects_adapter_integrity_mismatch(repo_root: Path, tmp_path: Path) -> None:
    catalog = load_catalog(repo_root)
    drifted = json.loads(json.dumps(catalog))
    drifted["providers"]["in-repo"]["adapterDoc"] = "core/providers/recallium.md"
    catalog_path = tmp_path / ".sw" / "memory-provider-catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(drifted), encoding="utf-8")

    core = tmp_path / "core"
    (core / "providers").mkdir(parents=True)
    for name in ("recallium.md", "in-repo.md", "recallium-rules.py", "in-repo-rules.py"):
        src = repo_root / "core" / "providers" / name
        if src.is_file():
            (core / "providers" / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RegistrationError) as exc:
        validate_registration(tmp_path, "in-repo", catalog=drifted)
    assert exc.value.cause == "integrity"
