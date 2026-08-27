#!/usr/bin/env python3
"""External-consumer evaluation corpus manifest loader and validator (PRD 333 R1, R13, R14)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

MANIFEST_SCHEMA_VERSION = "EvalCorpus@v1"

REQUIRED_CLASSIFICATIONS = frozenset(
    {
        "greenfield",
        "brownfield",
        "mixed-planning-store",
    }
)

PLANNING_STORE_MODES = frozenset(
    {
        "same-repo",
        "separate-project",
        "mixed",
    }
)

SECRET_FORBIDDEN_KEYS = frozenset(
    {
        "apiKey",
        "token",
        "password",
        "secret",
        "credential",
        "privateKey",
        "accessToken",
    }
)

SECRET_VALUE_PATTERN = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|password\s*=|BEGIN (RSA |OPENSSH )?PRIVATE KEY)"
)

REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FIXTURE_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class EvalCorpusManifestError(ValueError):
    """Raised when corpus manifest structure or composition fails validation."""


@dataclass(frozen=True)
class ExpectedOutcome:
    scenario: str
    status: str
    detail: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ExpectedOutcome:
        return cls(
            scenario=str(raw["scenario"]),
            status=str(raw["status"]),
            detail=str(raw["detail"]) if raw.get("detail") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scenario": self.scenario,
            "status": self.status,
        }
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class RepositoryFixture:
    repository_id: str
    classification: str
    planning_store_mode: str
    fixture_version: str
    holdout: bool
    source_revision: str
    remote_url: str
    expected_outcomes: tuple[ExpectedOutcome, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RepositoryFixture:
        outcomes_raw = raw.get("expectedOutcomes")
        if not isinstance(outcomes_raw, list) or not outcomes_raw:
            raise EvalCorpusManifestError("expectedOutcomes must be a non-empty list")
        return cls(
            repository_id=str(raw["repositoryId"]),
            classification=str(raw["classification"]),
            planning_store_mode=str(raw["planningStoreMode"]),
            fixture_version=str(raw["fixtureVersion"]),
            holdout=bool(raw["holdout"]),
            source_revision=str(raw["sourceRevision"]),
            remote_url=str(raw["remoteUrl"]),
            expected_outcomes=tuple(
                ExpectedOutcome.from_dict(item) for item in outcomes_raw
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repositoryId": self.repository_id,
            "classification": self.classification,
            "planningStoreMode": self.planning_store_mode,
            "fixtureVersion": self.fixture_version,
            "holdout": self.holdout,
            "sourceRevision": self.source_revision,
            "remoteUrl": self.remote_url,
            "expectedOutcomes": [item.to_dict() for item in self.expected_outcomes],
        }


@dataclass(frozen=True)
class CompositionRules:
    minimum_repositories: int
    required_classifications: frozenset[str]
    holdout_isolation: bool
    secret_free: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CompositionRules:
        required = raw.get("requiredClassifications")
        if not isinstance(required, list):
            raise EvalCorpusManifestError("requiredClassifications must be a list")
        return cls(
            minimum_repositories=int(raw["minimumRepositories"]),
            required_classifications=frozenset(str(item) for item in required),
            holdout_isolation=bool(raw["holdoutIsolation"]),
            secret_free=bool(raw["secretFree"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimumRepositories": self.minimum_repositories,
            "requiredClassifications": sorted(self.required_classifications),
            "holdoutIsolation": self.holdout_isolation,
            "secretFree": self.secret_free,
        }


@dataclass(frozen=True)
class EvalCorpusManifest:
    schema_version: str
    corpus_version: str
    manifest_id: str
    composition_rules: CompositionRules
    repositories: tuple[RepositoryFixture, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> EvalCorpusManifest:
        repos_raw = raw.get("repositories")
        if not isinstance(repos_raw, list) or not repos_raw:
            raise EvalCorpusManifestError("repositories must be a non-empty list")
        rules_raw = raw.get("compositionRules")
        if not isinstance(rules_raw, dict):
            raise EvalCorpusManifestError("compositionRules must be an object")
        return cls(
            schema_version=str(raw["schemaVersion"]),
            corpus_version=str(raw["corpusVersion"]),
            manifest_id=str(raw["manifestId"]),
            composition_rules=CompositionRules.from_dict(rules_raw),
            repositories=tuple(RepositoryFixture.from_dict(item) for item in repos_raw),
        )

    def classifications_present(self) -> frozenset[str]:
        return frozenset(repo.classification for repo in self.repositories)

    def holdout_repositories(self) -> tuple[RepositoryFixture, ...]:
        return tuple(repo for repo in self.repositories if repo.holdout)

    def eval_repositories(self, *, include_holdout: bool = False) -> tuple[RepositoryFixture, ...]:
        if include_holdout:
            return self.repositories
        return tuple(repo for repo in self.repositories if not repo.holdout)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "corpusVersion": self.corpus_version,
            "manifestId": self.manifest_id,
            "compositionRules": self.composition_rules.to_dict(),
            "repositories": [repo.to_dict() for repo in self.repositories],
        }


def default_corpus_path(repo_root: str | Path) -> Path:
    return (
        Path(repo_root)
        / "scripts"
        / "test"
        / "fixtures"
        / "external-consumer-eval"
        / "corpus.json"
    )


def default_schema_path(repo_root: str | Path) -> Path:
    return Path(repo_root) / "core" / "sw-reference" / "eval-corpus.schema.json"


def scan_forbidden_secrets(document: Mapping[str, Any], prefix: str = "") -> list[str]:
    errors: list[str] = []
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else key
        if key in SECRET_FORBIDDEN_KEYS:
            errors.append(f"forbidden-secret-key:{path}")
        if isinstance(value, dict):
            errors.extend(scan_forbidden_secrets(value, path))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    errors.extend(scan_forbidden_secrets(item, f"{path}[{idx}]"))
                elif isinstance(item, str) and SECRET_VALUE_PATTERN.search(item):
                    errors.append(f"forbidden-secret-value:{path}[{idx}]")
        elif isinstance(value, str) and SECRET_VALUE_PATTERN.search(value):
            errors.append(f"forbidden-secret-value:{path}")
    return errors


def validate_manifest(manifest: EvalCorpusManifest) -> None:
    """Fail closed on schema drift, composition gaps, holdout leakage, or secret material."""
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
        raise EvalCorpusManifestError(
            f"unsupported schemaVersion {manifest.schema_version!r}"
        )
    if not FIXTURE_VERSION_PATTERN.match(manifest.corpus_version):
        raise EvalCorpusManifestError(
            f"invalid corpusVersion {manifest.corpus_version!r}"
        )
    rules = manifest.composition_rules
    if not rules.holdout_isolation:
        raise EvalCorpusManifestError("compositionRules.holdoutIsolation must be true")
    if not rules.secret_free:
        raise EvalCorpusManifestError("compositionRules.secretFree must be true")
    if len(manifest.repositories) < rules.minimum_repositories:
        raise EvalCorpusManifestError(
            f"undersized corpus: {len(manifest.repositories)} < {rules.minimum_repositories}"
        )
    present = manifest.classifications_present()
    missing = REQUIRED_CLASSIFICATIONS - present
    if missing:
        raise EvalCorpusManifestError(
            f"missing repository classifications: {sorted(missing)}"
        )
    declared = rules.required_classifications
    if declared != REQUIRED_CLASSIFICATIONS:
        raise EvalCorpusManifestError(
            "compositionRules.requiredClassifications must declare the full classification set"
        )
    holdouts = manifest.holdout_repositories()
    if not holdouts:
        raise EvalCorpusManifestError("corpus must designate at least one holdout repository")
    seen_ids: set[str] = set()
    for repo in manifest.repositories:
        if repo.repository_id in seen_ids:
            raise EvalCorpusManifestError(
                f"duplicate repositoryId {repo.repository_id!r}"
            )
        seen_ids.add(repo.repository_id)
        if repo.classification not in REQUIRED_CLASSIFICATIONS:
            raise EvalCorpusManifestError(
                f"invalid classification on {repo.repository_id}: {repo.classification}"
            )
        if repo.planning_store_mode not in PLANNING_STORE_MODES:
            raise EvalCorpusManifestError(
                f"invalid planningStoreMode on {repo.repository_id}: {repo.planning_store_mode}"
            )
        if not FIXTURE_VERSION_PATTERN.match(repo.fixture_version):
            raise EvalCorpusManifestError(
                f"invalid fixtureVersion on {repo.repository_id}: {repo.fixture_version}"
            )
        if not REVISION_PATTERN.match(repo.source_revision):
            raise EvalCorpusManifestError(
                f"malformed sourceRevision on {repo.repository_id}: {repo.source_revision}"
            )
        if not repo.remote_url.startswith("https://"):
            raise EvalCorpusManifestError(
                f"remoteUrl must be https on {repo.repository_id}"
            )
    secret_errors = scan_forbidden_secrets(manifest.to_dict())
    if secret_errors:
        raise EvalCorpusManifestError(
            f"secret-like material detected: {secret_errors[0]}"
        )


def detect_holdout_leakage(
    manifest: EvalCorpusManifest,
    *,
    eval_set: Sequence[str],
) -> list[str]:
    """Return holdout repository ids present in a non-holdout eval set."""
    holdout_ids = {repo.repository_id for repo in manifest.holdout_repositories()}
    return sorted(repo_id for repo_id in eval_set if repo_id in holdout_ids)


def load_manifest(path: str | Path) -> EvalCorpusManifest:
    manifest_path = Path(path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvalCorpusManifestError("manifest root must be an object")
    manifest = EvalCorpusManifest.from_dict(raw)
    validate_manifest(manifest)
    return manifest


def corpus_composition_report(manifest: EvalCorpusManifest) -> dict[str, Any]:
    return {
        "manifestId": manifest.manifest_id,
        "corpusVersion": manifest.corpus_version,
        "repositoryCount": len(manifest.repositories),
        "classifications": sorted(manifest.classifications_present()),
        "holdoutCount": len(manifest.holdout_repositories()),
        "evalCount": len(manifest.eval_repositories()),
        "complete": manifest.classifications_present() >= REQUIRED_CLASSIFICATIONS,
    }
