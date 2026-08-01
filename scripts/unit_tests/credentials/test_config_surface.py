"""Config surface tests (PRD 080 17.4 / R1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from credentials.config_surface import (
    PROJECT_ID_PATTERN_DOC,
    ConfigSurfaceError,
    resolve_config_surface,
    validate_project_id,
)
from credentials.pairing_store import approve_pairing, record_first_use


def _prepare_pairing(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


class TestAbsentProjectId:
    def test_absent_project_id_fails_closed(self) -> None:
        with pytest.raises(ConfigSurfaceError) as exc:
            resolve_config_surface({})
        assert exc.value.code == "project-id-absent"


class TestOneValidProjectId:
    def test_one_valid_id_resolves_credential_refs(self) -> None:
        result = resolve_config_surface(
            {
                "projectId": "acme-demo",
                "host": {"credentialRef": "github-work"},
                "planning": {"store": {"issues": {"credentialRef": "planning-work"}}},
                "memory": {"credentialRef": "memory-work"},
            }
        )
        assert result.project_id == "acme-demo"
        assert result.host.credential_ref == "github-work"
        assert result.host.source == "credentialRef"
        assert result.planning.credential_ref == "planning-work"
        assert result.memory.credential_ref == "memory-work"
        assert result.notices == ()


class TestManyRepositories:
    def test_many_repositories_resolve_independently(self) -> None:
        configs = [
            {
                "projectId": f"proj-{index}",
                "host": {"credentialRef": f"ref-{index}"},
            }
            for index in range(3)
        ]
        results = [resolve_config_surface(cfg) for cfg in configs]
        assert {item.project_id for item in results} == {"proj-0", "proj-1", "proj-2"}
        assert {item.host.credential_ref for item in results} == {"ref-0", "ref-1", "ref-2"}


class TestInheritedPairingConflict:
    def test_inherited_id_paired_to_different_remote_blocks(self, tmp_path: Path) -> None:
        pairing = tmp_path / "credential-pairings.json"
        _prepare_pairing(pairing)
        record_first_use(
            "github-work",
            "shared-proj",
            "https://github.com/acme/other.git",
            path=pairing,
            skip_integrity=True,
        )
        approve_pairing(
            "github-work",
            "shared-proj",
            "https://github.com/acme/other.git",
            path=pairing,
            skip_integrity=True,
        )
        with pytest.raises(ConfigSurfaceError) as exc:
            resolve_config_surface(
                {
                    "projectId": "shared-proj",
                    "host": {"credentialRef": "github-work"},
                },
                remote="https://github.com/acme/demo.git",
                pairing_path=pairing,
            )
        assert exc.value.code == "project-id-pairing-conflict"

    def test_matching_remote_allows_resolution(self, tmp_path: Path) -> None:
        pairing = tmp_path / "credential-pairings.json"
        _prepare_pairing(pairing)
        record_first_use(
            "github-work",
            "shared-proj",
            "https://github.com/acme/demo.git",
            path=pairing,
            skip_integrity=True,
        )
        approve_pairing(
            "github-work",
            "shared-proj",
            "https://github.com/acme/demo.git",
            path=pairing,
            skip_integrity=True,
        )
        result = resolve_config_surface(
            {
                "projectId": "shared-proj",
                "host": {"credentialRef": "github-work"},
            },
            remote="https://github.com/acme/demo.git",
            pairing_path=pairing,
        )
        assert result.project_id == "shared-proj"


class TestPatternViolatingId:
    def test_pattern_violating_id_fails_closed(self) -> None:
        with pytest.raises(ConfigSurfaceError) as exc:
            validate_project_id("ACME_Demo")
        assert exc.value.code == "project-id-pattern"
        assert PROJECT_ID_PATTERN_DOC in exc.value.message


class TestShipwrightWorkflowConfig:
    def test_repo_workflow_config_resolves_project_id(self) -> None:
        root = Path(__file__).resolve().parents[3]
        cfg_path = root / ".cursor" / "workflow.config.json"
        assert cfg_path.is_file(), "workflow.config.json must exist for R19"
        import json

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        result = resolve_config_surface(cfg)
        assert result.project_id == "shipwright"

    def test_planning_doctor_credential_probe_not_project_id_absent(self) -> None:
        import importlib

        root = Path(__file__).resolve().parents[3]
        doctor = importlib.import_module("planning-doctor")
        out = doctor.doctor(root, sweep=False)
        probe = next(
            (check for check in out.get("checks", []) if check.get("check") == "credential-probe"),
            None,
        )
        assert probe is not None
        assert probe.get("failureCode") != "project-id-absent"
        if out.get("verdict") == "degraded":
            assert probe.get("failureCode") != "project-id-absent"
