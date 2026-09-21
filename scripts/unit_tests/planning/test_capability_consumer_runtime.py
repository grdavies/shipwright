"""Consumer capability selection keeps bundle freshness and repo policy separate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capability_index import build_index, check_freshness, default_capability_index_path
from capability_migration_parity import dual_run, select_family


DIFF = {"files": [{"path": "app/plugin.ts", "added_lines": ["// retry after failure"]}]}
CONTEXT = {"version": 1, "phase_type": "sw-review", "change_digest": DIFF}


def _bundle(root: Path, *, installed: bool = False) -> Path:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for marker in ("check-gate.py", "resolve-model-tier.py"):
        (scripts / marker).write_text("# trusted runtime fixture\n", encoding="utf-8")
    scan = root if installed else root / "core"
    skill = scan / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: demo\ncapability:\n  version: 1\n  triggers:\n"
        "    - type: always_on\n      selectionFamily: code-review\n---\n",
        encoding="utf-8",
    )
    index = root / "core/sw-reference/capability-index.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps(build_index(scan)), encoding="utf-8")
    return index


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    root = tmp_path / "consumer"
    root.mkdir()
    return root


@pytest.mark.parametrize("installed", [False, True])
def test_trusted_runtime_freshness_uses_its_own_layout(
    tmp_path: Path, consumer: Path, monkeypatch: pytest.MonkeyPatch, installed: bool
) -> None:
    runtime = tmp_path / "runtime"
    _bundle(runtime, installed=installed)
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(runtime / "scripts"))
    assert check_freshness(runtime) == (True, "fresh")
    result = select_family("code-review", CONTEXT, repo_root=consumer)
    assert set(result["core"]) == {
        "correctness", "maintainability", "scope-fidelity", "testing", "security"
    }
    assert not (consumer / "core").exists()


@pytest.mark.parametrize("authority", ["local", "runtime"])
@pytest.mark.parametrize("damage", ["missing", "malformed", "stale", "frontmatter"])
def test_bad_selected_bundle_never_falls_back(
    tmp_path: Path, consumer: Path, monkeypatch: pytest.MonkeyPatch,
    authority: str, damage: str,
) -> None:
    runtime = tmp_path / "runtime"
    runtime_index = _bundle(runtime)
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(runtime / "scripts"))
    owner = consumer if authority == "local" else runtime
    index = _bundle(consumer) if authority == "local" else runtime_index
    if damage == "missing":
        index.unlink()
        message = "missing committed index"
    elif damage == "malformed":
        index.write_text("{invalid", encoding="utf-8")
        message = "invalid index JSON"
    elif damage == "stale":
        index.write_text('{"version": 1, "capabilities": []}', encoding="utf-8")
        message = "does not match"
    else:
        skill = owner / "core/skills/demo/SKILL.md"
        skill.write_text(skill.read_text().replace("always_on", "phase_default"))
        message = "does not match"
    with pytest.raises(RuntimeError, match=message):
        select_family("code-review", CONTEXT, repo_root=consumer)


@pytest.mark.parametrize("invalid", ["missing", "untrusted", "relative"])
def test_invalid_runtime_binding_fails_closed(
    tmp_path: Path, consumer: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    path = tmp_path / invalid
    if invalid == "untrusted":
        path.mkdir()
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", "relative/path" if invalid == "relative" else str(path))
    with pytest.raises(RuntimeError, match="absolute|does not exist|not a trusted"):
        select_family("code-review", CONTEXT, repo_root=consumer)


def test_explicit_index_remains_bound_to_consumer(
    tmp_path: Path, consumer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    index = _bundle(runtime)
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(runtime / "scripts"))
    with pytest.raises(RuntimeError, match="does not match"):
        select_family("code-review", CONTEXT, repo_root=consumer, index_path=index)


def test_source_roster_and_existing_family_parity() -> None:
    root = SCRIPTS.parent
    assert check_freshness(root) == (True, "fresh")
    for family in ("code-review", "doc-review", "dispatch", "providers"):
        assert dual_run(family, CONTEXT, repo_root=root)["match"], family


def test_provider_projection_keeps_consumer_policy(
    consumer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(SCRIPTS))
    ctx = {**CONTEXT, "config": {"review": {"provider": "coderabbit"}}}
    absent = select_family("providers", ctx, repo_root=consumer)
    assert absent["families"]["review"]["coderabbitConfigPresent"] is False
    (consumer / ".coderabbit.yaml").write_text("reviews:\n  profile: chill\n")
    present = select_family("providers", ctx, repo_root=consumer)
    assert present["families"]["review"]["coderabbitConfigPresent"] is True


def test_real_consumer_cli_keeps_config_and_harvest_in_consumer(consumer: Path) -> None:
    config_path = consumer / ".shipwright/workflow.config.json"
    config_path.parent.mkdir()
    diff_path = consumer / "diff.json"
    diff_path.write_text(json.dumps(DIFF))
    harvest_path = consumer / ".cursor/sw-learning-store/harvest-records.jsonl"
    harvest_path.parent.mkdir(parents=True)
    harvest_path.write_text(json.dumps({"harvest": {
        "schemaVersion": 1, "harvestedAt": "2026-09-20T00:00:00Z",
        "reviewers": [
            {"reviewerId": "comment-accuracy", "rating": 1800, "calibrationError": 0.1},
            {"reviewerId": "reliability", "rating": 1200, "calibrationError": 0.2},
        ],
    }}) + "\n")
    env = {**os.environ, "SHIPWRIGHT_SCRIPTS": str(SCRIPTS)}
    argv = [sys.executable, str(SCRIPTS / "code-review-select.py"),
            "--repo-root", str(consumer), "--diff", str(diff_path)]
    for ceiling, expected in ((1, ["comment-accuracy"]), (2, ["comment-accuracy", "reliability"])):
        config_path.write_text(json.dumps({"review": {"selection": {"maxPersonas": ceiling}}}))
        # Deliberately run outside the consumer; the explicit repo root must own policy.
        proc = subprocess.run(argv, cwd=SCRIPTS.parent, env=env, capture_output=True,
                              text=True, timeout=30, check=False)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["specialists"] == expected
    assert not (consumer / "core").exists()
