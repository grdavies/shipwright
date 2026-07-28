"""Context envelope forwarding tests (PRD 080 12.4 / R9)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repository_context import CONTEXT_ENVELOPE_ENV, from_root
from sw_bootstrap import resolve_workspace, parse_args


def _seed_trusted_scripts(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (path / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")


def _write_workflow_config(repo: Path) -> None:
    cursor = repo / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": {"provider": "github", "remote": "origin"},
        "memory": {"provider": "recallium", "project": "fixture-project"},
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
            }
        },
    }
    (cursor / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


def _seed_repo(repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/demo.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    _write_workflow_config(repo)


class TestEnvelopeRoundTrip:
    def test_factory_round_trips_without_secret_material(self, tmp_git_repo: Path) -> None:
        _seed_repo(tmp_git_repo)
        context = from_root(tmp_git_repo, run_id="run-envelope")
        envelope = context.to_envelope()
        serialized = json.dumps(envelope)
        assert "GITHUB_TOKEN" not in serialized
        assert "secret" not in serialized.lower()
        assert envelope["credentialRefs"] == list(context.credential_refs)
        assert envelope["root"] == str(tmp_git_repo.resolve())

    def test_bootstrap_forwards_envelope_to_child_env(self, tmp_git_repo: Path, tmp_path: Path) -> None:
        _seed_repo(tmp_git_repo)
        context = from_root(tmp_git_repo)
        plugin_scripts = tmp_path / "plugin" / "scripts"
        _seed_trusted_scripts(plugin_scripts)
        helper = plugin_scripts / "env_probe.py"
        helper.write_text(
            "import json, os\nprint(json.dumps(os.environ.get(%r)))\n" % CONTEXT_ENVELOPE_ENV,
            encoding="utf-8",
        )

        parent_env = {
            **os.environ,
            "SHIPWRIGHT_SCRIPTS": str(plugin_scripts),
            CONTEXT_ENVELOPE_ENV: context.serialize_envelope(),
        }
        args = parse_args(
            [
                "--root",
                str(tmp_path / "ignored"),
                "env_probe.py",
            ]
        )
        workspace, child_env = resolve_workspace(args, env=parent_env)
        assert workspace == tmp_git_repo.resolve()
        assert CONTEXT_ENVELOPE_ENV in child_env
        assert "GITHUB_TOKEN" not in child_env[CONTEXT_ENVELOPE_ENV]

        proc = subprocess.run(
            [sys.executable, str(helper)],
            env={**os.environ, **child_env},
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(proc.stdout) == context.serialize_envelope()


class TestRequireEnvelopeRefusal:
    def test_require_envelope_refuses_working_directory_fallback(self, tmp_path: Path) -> None:
        args = parse_args(["--require-envelope", "--print", "wave_deliver.py"])
        with pytest.raises(Exception, match="refusing working-directory fallback"):
            resolve_workspace(args, env={})

    def test_cli_require_envelope_fails_without_envelope(
        self, tmp_path: Path, sw_env: dict[str, str]
    ) -> None:
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        bootstrap = Path(__file__).resolve().parents[2] / "sw_bootstrap.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(bootstrap),
                "--require-envelope",
                "--print",
                "wave_deliver.py",
            ],
            cwd=consumer,
            capture_output=True,
            text=True,
            check=False,
            env=sw_env,
        )
        assert proc.returncode == 2
        assert "refusing working-directory fallback" in proc.stderr

    def test_cli_uses_envelope_root_over_cwd(
        self, tmp_git_repo: Path, tmp_path: Path, sw_env: dict[str, str]
    ) -> None:
        _seed_repo(tmp_git_repo)
        context = from_root(tmp_git_repo)
        plugin_scripts = tmp_path / "plugin" / "scripts"
        _seed_trusted_scripts(plugin_scripts)
        helper = plugin_scripts / "root_probe.py"
        helper.write_text(
            "import json, os\n"
            f"from pathlib import Path\n"
            f"from repository_context import envelope_from_env\n"
            "ctx = envelope_from_env()\n"
            "print(json.dumps({'root': ctx.root if ctx else None}))\n",
            encoding="utf-8",
        )
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        bootstrap = Path(__file__).resolve().parents[2] / "sw_bootstrap.py"
        env = {
            **sw_env,
            "SHIPWRIGHT_SCRIPTS": str(plugin_scripts),
            CONTEXT_ENVELOPE_ENV: context.serialize_envelope(),
        }
        proc = subprocess.run(
            [
                sys.executable,
                str(bootstrap),
                "--root",
                str(consumer),
                "root_probe.py",
            ],
            cwd=consumer,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["root"] == str(tmp_git_repo.resolve())
