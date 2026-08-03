"""tokenEnv deprecation issues in the default repo-wide doctor (PRD 087 R2)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
DOCTOR = SCRIPTS / "doctor.py"
MIGRATE_CMD = "python3 scripts/sw-configure.py credential migrate"


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


def _run_doctor(root: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SCRIPTS)
    proc = subprocess.run(
        [sys.executable, str(DOCTOR), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(SCRIPTS.parent),
        env=env,
    )
    assert proc.stdout.strip(), (
        f"doctor produced no stdout: stderr={proc.stderr!r} ec={proc.returncode}"
    )
    return json.loads(proc.stdout)


class TestDoctorTokenenvDeprecation:
    def test_host_tokenenv_alias_emits_deprecation_issue(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _write_config(
            root,
            host={"provider": "github", "tokenEnv": "GITHUB_TOKEN"},
        )

        payload = _run_doctor(root)
        issues = payload["issues"]
        remediation = payload["remediation"]

        assert "tokenenv-deprecation:host" in issues
        assert any(MIGRATE_CMD in line for line in remediation)
        # Operator does not need a separate credentials-doctor invocation for this signal.
        assert not any("credentials-doctor" in line for line in remediation)

    def test_no_tokenenv_alias_no_false_positive(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _write_config(root)

        payload = _run_doctor(root)
        issues = [
            item
            for item in payload["issues"]
            if str(item).startswith("tokenenv-deprecation:")
        ]

        assert issues == []
