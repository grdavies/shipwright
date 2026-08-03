"""tokenEnv alias deprecation notices in credential doctor JSON (PRD 087 R1)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from credentials.config_surface import ALIAS_NOTICE
from credentials.doctor import diagnose_repository

SCRIPTS = Path(__file__).resolve().parents[2]


def _write_config(root: Path, **overrides: object) -> None:
    cfg: dict[str, object] = {
        "projectId": "proj-1",
        "host": {
            "provider": "github",
            "credentialRef": "github-work",
        },
    }
    cfg.update(overrides)
    path = root / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def _init_git_remote(root: Path, slug: str = "owner/repo") -> None:
    remote = f"https://github.com/{slug}.git"
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)


class TestDoctorTokenenvNotices:
    def test_alias_surface_reports_non_empty_notices(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(
            root,
            host={"provider": "github", "tokenEnv": "GITHUB_TOKEN"},
        )

        report = diagnose_repository(root, skip_integrity=True, register_env_backend=False)
        host_surface = next(item for item in report["surfaces"] if item["surface"] == "host")

        assert host_surface["notices"]
        assert ALIAS_NOTICE in host_surface["notices"]

    def test_credential_ref_only_surface_reports_empty_notices(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(root)

        report = diagnose_repository(root, skip_integrity=True, register_env_backend=False)
        host_surface = next(item for item in report["surfaces"] if item["surface"] == "host")

        assert "notices" in host_surface
        assert host_surface["notices"] == []

    def test_diagnose_repository_json_includes_notices_per_surface(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(
            root,
            host={"provider": "github", "tokenEnv": "GITHUB_TOKEN"},
        )

        doctor_script = SCRIPTS / "credentials-doctor.py"
        proc = subprocess.run(
            [sys.executable, str(doctor_script), "--root", str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(proc.stdout)
        for surface in payload["surfaces"]:
            assert "notices" in surface
            assert isinstance(surface["notices"], list)
