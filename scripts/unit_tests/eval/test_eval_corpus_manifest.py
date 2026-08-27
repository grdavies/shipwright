"""PRD 333 R1, R13, R14 — external consumer evaluation corpus manifest."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from eval_corpus_manifest import (  # noqa: E402
    EvalCorpusManifest,
    EvalCorpusManifestError,
    corpus_composition_report,
    default_corpus_path,
    default_schema_path,
    detect_holdout_leakage,
    load_manifest,
    scan_forbidden_secrets,
    validate_manifest,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_schema() -> dict[str, Any]:
    return json.loads(default_schema_path(_repo_root()).read_text(encoding="utf-8"))


def _validate_with_jsonschema(document: dict[str, Any], schema: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)


def _fixture_corpus() -> dict[str, Any]:
    return json.loads(default_corpus_path(_repo_root()).read_text(encoding="utf-8"))


def test_minimum_external_mix_and_holdout() -> None:
    manifest = load_manifest(default_corpus_path(_repo_root()))
    report = corpus_composition_report(manifest)
    assert report["complete"] is True
    assert report["repositoryCount"] >= 3
    assert report["holdoutCount"] >= 1
    assert report["evalCount"] < report["repositoryCount"]
    assert manifest.holdout_repositories()
    assert {"greenfield", "brownfield", "mixed-planning-store"} <= manifest.classifications_present()


def test_stance_b_external_fixture_boundary() -> None:
    manifest = load_manifest(default_corpus_path(_repo_root()))
    for repo in manifest.repositories:
        assert repo.remote_url.startswith("https://github.com/shipwright-fixtures/")
        assert "shipwright" not in repo.repository_id or repo.repository_id.startswith("ext-")


def test_schema_accepts_canonical_fixture() -> None:
    schema = _load_schema()
    document = _fixture_corpus()
    _validate_with_jsonschema(document, schema)


def test_missing_repository_classes_rejected() -> None:
    raw = _fixture_corpus()
    raw["repositories"] = [
        repo
        for repo in raw["repositories"]
        if repo["classification"] != "mixed-planning-store"
    ]
    manifest = EvalCorpusManifest.from_dict(raw)
    with pytest.raises(EvalCorpusManifestError, match="missing repository classifications"):
        validate_manifest(manifest)


def test_undersized_corpus_rejected() -> None:
    raw = _fixture_corpus()
    raw["repositories"] = raw["repositories"][:2]
    manifest = EvalCorpusManifest.from_dict(raw)
    with pytest.raises(EvalCorpusManifestError, match="undersized corpus"):
        validate_manifest(manifest)


def test_holdout_leakage_detected() -> None:
    manifest = load_manifest(default_corpus_path(_repo_root()))
    holdout_id = manifest.holdout_repositories()[0].repository_id
    eval_ids = [repo.repository_id for repo in manifest.eval_repositories()]
    leaked = detect_holdout_leakage(manifest, eval_set=[*eval_ids, holdout_id])
    assert leaked == [holdout_id]


def test_stale_fixture_version_rejected() -> None:
    raw = _fixture_corpus()
    raw["repositories"][0]["fixtureVersion"] = "not-semver"
    manifest = EvalCorpusManifest.from_dict(raw)
    with pytest.raises(EvalCorpusManifestError, match="invalid fixtureVersion"):
        validate_manifest(manifest)


def test_malformed_revision_rejected() -> None:
    raw = _fixture_corpus()
    raw["repositories"][0]["sourceRevision"] = "short-sha"
    manifest = EvalCorpusManifest.from_dict(raw)
    with pytest.raises(EvalCorpusManifestError, match="malformed sourceRevision"):
        validate_manifest(manifest)


def test_secret_like_values_rejected() -> None:
    raw = _fixture_corpus()
    raw["repositories"][0]["remoteUrl"] = "https://example.com/?token=ghp_abcdefghijklmnopqrstuvwxyz123456"
    manifest = EvalCorpusManifest.from_dict(raw)
    with pytest.raises(EvalCorpusManifestError, match="secret-like material"):
        validate_manifest(manifest)


def test_forbidden_secret_keys_scan() -> None:
    errors = scan_forbidden_secrets({"apiKey": "value"})
    assert errors == ["forbidden-secret-key:apiKey"]


def test_no_holdout_designation_rejected() -> None:
    raw = _fixture_corpus()
    for repo in raw["repositories"]:
        repo["holdout"] = False
    manifest = EvalCorpusManifest.from_dict(raw)
    with pytest.raises(EvalCorpusManifestError, match="at least one holdout"):
        validate_manifest(manifest)


def test_corpus_version_must_be_semver() -> None:
    raw = _fixture_corpus()
    raw["corpusVersion"] = "v1"
    manifest = EvalCorpusManifest.from_dict(raw)
    with pytest.raises(EvalCorpusManifestError, match="invalid corpusVersion"):
        validate_manifest(manifest)


def test_manifest_round_trip() -> None:
    manifest = load_manifest(default_corpus_path(_repo_root()))
    clone = copy.deepcopy(manifest.to_dict())
    round_trip = EvalCorpusManifest.from_dict(clone)
    validate_manifest(round_trip)
