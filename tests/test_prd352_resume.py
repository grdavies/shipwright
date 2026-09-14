"""PRD 352 Slice 1 — connect import to executable resume (R1–R4, R15, TR6)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from handoff.bundle import BundleBuildError, neutralize_checkpoint_paths  # noqa: E402
from handoff.importer import ImportValidationError, validate_import_record  # noqa: E402
from handoff_bundle import (  # noqa: E402
    REQUIRED_HANDOFF_MODULES,
    cmd_resume,
    handoff_module_hashes,
    verify_dependencies,
    verify_handoff_manifest,
)
from shipwright_paths import run_dir  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_import_record(root: Path, run_id: str, transition_id: str, **overrides: object) -> Path:
    record = {
        "transition_id": transition_id,
        "run_id": run_id,
        "bundleDigest": "sha256:" + ("a" * 64),
        "taskRows": {"completed": [], "remaining": [{"id": "1.1"}]},
        "evidence": [],
        "continuation_payload": {
            "repo": {"worktree": ".", "head": "b" * 40},
            "currentWorkflowNodeId": "sw-execute",
        },
    }
    record.update(overrides)
    path = run_dir(root, run_id) / "imports" / f"{transition_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


def test_validate_import_record_absent(tmp_path: Path) -> None:
    with pytest.raises(ImportValidationError) as exc:
        validate_import_record(tmp_path, "run-missing")
    assert exc.value.code == "import_record_absent"
    assert exc.value.remediation


def test_validate_import_record_incomplete(tmp_path: Path) -> None:
    path = _seed_import_record(tmp_path, "run-1", "tid-1")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("bundleDigest")
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ImportValidationError) as exc:
        validate_import_record(tmp_path, "run-1", "tid-1")
    assert exc.value.code == "import_record_incomplete"


def test_validate_import_record_invalid(tmp_path: Path) -> None:
    path = run_dir(tmp_path, "run-1") / "imports" / "tid-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ImportValidationError) as exc:
        validate_import_record(tmp_path, "run-1", "tid-1")
    assert exc.value.code == "import_record_invalid"


def test_validate_import_record_ok(tmp_path: Path) -> None:
    _seed_import_record(tmp_path, "run-1", "tid-1")
    record = validate_import_record(tmp_path, "run-1", "tid-1")
    assert record["transition_id"] == "tid-1"


def test_verify_dependencies_missing_module(tmp_path: Path) -> None:
    result = verify_dependencies(tmp_path)
    assert result["verdict"] == "fail"
    assert result["error"] == "handoff:missing-dependency"
    assert "installer" in str(result.get("remediation") or "").lower()
    assert result["missing"]


def test_verify_dependencies_pass_on_repo() -> None:
    result = verify_dependencies(REPO)
    assert result["verdict"] == "pass"
    assert result["modules"] == list(REQUIRED_HANDOFF_MODULES)


def test_resume_cli_dispatches_scheduler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_import_record(tmp_path, "run-resume", "tid-9")
    captured: list[list[str]] = []

    def _runner(argv: list[str], *, cwd) -> dict:
        captured.append({"argv": argv, "cwd": Path(cwd)})
        return {"verdict": "pass", "dispatched": True, "argv": argv}

    monkeypatch.setattr("handoff_bundle.dispatch_deliver_scheduler", _runner)
    ns = type(
        "NS",
        (),
        {
            "root": str(tmp_path),
            "path": "",
            "run_id": "run-resume",
            "transition_id": "tid-9",
        },
    )()
    # Copy required modules into tmp root so verify_dependencies passes.
    for rel in REQUIRED_HANDOFF_MODULES:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")

    code = cmd_resume(ns)
    assert code == 0
    assert captured
    argv = captured[0]["argv"]
    assert captured[0]["cwd"] == tmp_path
    assert "deliver-loop" in argv
    assert "--run-id" in argv
    assert "run-resume" in argv


def test_resume_cli_exits_20_on_validation_failure(tmp_path: Path) -> None:
    ns = type(
        "NS",
        (),
        {"root": str(tmp_path), "path": "", "run_id": "absent", "transition_id": ""},
    )()
    assert cmd_resume(ns) == 20


def test_resume_fresh_process_fixture(tmp_path: Path) -> None:
    fixture = REPO / "scripts" / "test" / "fixtures" / "host-switching" / "resume-fixture.bundle"
    assert fixture.is_file()
    for rel in REQUIRED_HANDOFF_MODULES:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
    schema_rel = Path("core/sw-reference/handoff-bundle.schema.json")
    schema_dest = tmp_path / schema_rel
    schema_dest.parent.mkdir(parents=True, exist_ok=True)
    schema_dest.write_text((REPO / schema_rel).read_text(encoding="utf-8"), encoding="utf-8")
    stub = tmp_path / "scripts" / "wave.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "print(json.dumps({'verdict': 'pass', 'action': 'deliver-loop'}))\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "handoff_bundle.py"),
            "--root",
            str(tmp_path),
            "resume",
            str(fixture),
            "--run-id",
            "run-fixture",
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    ticket = run_dir(tmp_path, "run-fixture") / "imports" / "imported.json"
    assert ticket.is_file()


def test_neutral_checkpoint_rejects_relative_escape(tmp_path: Path) -> None:
    with pytest.raises(BundleBuildError):
        neutralize_checkpoint_paths(
            {"repo": {"worktree": "../outside"}},
            root=tmp_path,
        )


def test_validate_import_record_rejects_unsafe_transition_id(tmp_path: Path) -> None:
    _seed_import_record(tmp_path, "run-1", "tid-1")
    with pytest.raises(ImportValidationError) as exc:
        validate_import_record(tmp_path, "run-1", "../acks/tid-1")
    assert exc.value.code == "import_record_invalid"


def test_validate_import_record_multiple_requires_transition_id(tmp_path: Path) -> None:
    _seed_import_record(tmp_path, "run-1", "tid-1")
    _seed_import_record(tmp_path, "run-1", "tid-2")
    with pytest.raises(ImportValidationError) as exc:
        validate_import_record(tmp_path, "run-1")
    assert exc.value.code == "import_record_incomplete"
    record = validate_import_record(tmp_path, "run-1", "tid-2")
    assert record["transition_id"] == "tid-2"


def test_resume_cli_exits_20_on_missing_dependencies(tmp_path: Path) -> None:
    _seed_import_record(tmp_path, "run-dep", "tid-dep")
    ns = type(
        "NS",
        (),
        {"root": str(tmp_path), "path": "", "run_id": "run-dep", "transition_id": "tid-dep"},
    )()
    assert cmd_resume(ns) == 20


def test_neutral_checkpoint_paths_are_repo_relative(tmp_path: Path) -> None:
    nested = tmp_path / "wt" / "inner"
    nested.mkdir(parents=True)
    payload = {
        "repo": {"worktree": str(nested), "head": "c" * 40},
        "evidenceReferences": [{"path": str(tmp_path / "notes.md"), "digest": "sha256:x"}],
    }
    out = neutralize_checkpoint_paths(payload, root=tmp_path)
    assert out["repo"]["worktree"] == "wt/inner"
    assert out["evidenceReferences"][0]["path"] == "notes.md"


def test_neutral_checkpoint_rejects_host_absolute_outside_repo(tmp_path: Path) -> None:
    with pytest.raises(BundleBuildError):
        neutralize_checkpoint_paths(
            {"repo": {"worktree": "/tmp/not-this-repo"}},
            root=tmp_path,
        )


def test_dist_manifest_includes_handoff_hashes() -> None:
    manifest_path = REPO / "dist" / "manifest.json"
    assert manifest_path.is_file()
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    modules = {row["path"]: row["sha256"] for row in doc["handoff"]["modules"]}
    for rel in REQUIRED_HANDOFF_MODULES:
        assert modules[rel] == _sha256(REPO / rel)
    assert verify_handoff_manifest(REPO)["verdict"] == "pass"
    hashes = handoff_module_hashes(REPO)
    assert set(hashes) == set(REQUIRED_HANDOFF_MODULES)
