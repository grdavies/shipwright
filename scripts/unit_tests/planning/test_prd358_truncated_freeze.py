"""PRD 358 R9 / D8 / AS8 — freeze and frozen-hash refuse truncated Linear reconstruct."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import check_frozen_lib as cfl
import doc_format as df
import planning_canonical as pc
import planning_store as ps
from planning.backends.issues import IssueStoreBackend
from planning_canonical import BODY_SIZE_LIMIT, compose_issue_body

_ORACLE_FIXTURE = Path(__file__).parent / "fixtures" / "prd358_reconstruct_oracle.json"

ORACLE_TRUNCATED_BYTES = 57_881

_STUMP_RID_TAIL = (
    "* **R1** Stump requirement remains parseable.\n"
    "* **R9** Freeze refuse truncated reconstruct.\n"
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)


def _linear_issue_store_cfg(project_key: str) -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": project_key,
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }


def _chunked_prd_content(project_key: str, unit_id: str) -> str:
    prefix = "# Title\n\n"
    composed_probe = compose_issue_body(project_key, "prd", unit_id, "X")
    marker_len = composed_probe.index("X")
    target = BODY_SIZE_LIMIT - marker_len - len(prefix) - 2
    head = prefix + ("A" * target) + "\n\n"
    tail = "Paragraph tail for truncated freeze.\n\n" + _STUMP_RID_TAIL + "END\n"
    operator = head + tail
    return (
        f"---\n"
        f"id: {unit_id}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"---\n"
        f"{operator}"
    )


def _backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_key: str) -> IssueStoreBackend:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.chdir(tmp_path)
    cfg = _linear_issue_store_cfg(project_key)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return IssueStoreBackend(tmp_path, cfg)


def _fail_payload(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    captured = capsys.readouterr()
    start = captured.out.find("{")
    if start < 0:
        raise AssertionError(f"no fail json in stdout: {captured.out!r}")
    return json.loads(captured.out[start:])


def _put_chunked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_key: str, unit_id: str
) -> tuple[IssueStoreBackend, str, str]:
    backend = _backend(tmp_path, monkeypatch, project_key)
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    content = _chunked_prd_content(project_key, unit_id)
    result = backend.put(unit_id, body_path, content)
    assert result.verdict == "ok"
    return backend, body_path, content


def test_empty_reconstruct_refuses_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Z — empty reconstruct cannot freeze."""
    _init_repo(tmp_path)
    backend, body_path, content = _put_chunked(
        tmp_path, monkeypatch, "freeze-empty-reconstruct", "358-prd-freeze-empty"
    )
    orig_reassemble = ps.reassemble_body

    def empty_reconstruct(body_text: str, comments: list, **kwargs: Any) -> str:
        if pc.load_chunk_manifest(body_text):
            return ""
        return orig_reassemble(body_text, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", empty_reconstruct)
    with pytest.raises(SystemExit) as exc:
        backend.freeze(unit_id="358-prd-freeze-empty", body_path=body_path, distill=False, pre_chunk_body=content)
    assert exc.value.code == 2
    payload = _fail_payload(capsys)
    assert payload["code"] in {"reconstruct-mismatch", "reconstruct-incomplete-comments"}


def test_matching_hash_freeze_and_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O — complete reconstruct freezes and frozen-hash matches."""
    _init_repo(tmp_path)
    backend, body_path, content = _put_chunked(
        tmp_path, monkeypatch, "freeze-matching-hash", "358-prd-freeze-match"
    )
    frozen = backend.freeze(
        unit_id="358-prd-freeze-match", body_path=body_path, distill=False, pre_chunk_body=content
    )
    assert frozen["verdict"] == "ok"
    assert frozen.get("hash")
    verified = backend.verify_frozen_hash(
        "358-prd-freeze-match", body_path, pre_chunk_body=content
    )
    assert verified["verdict"] == "ok"
    assert verified["hash"] == frozen["hash"]


def test_truncated_linear_body_refuses_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """M — truncated Linear reconstruct (194480 vs 57881 oracle size) cannot freeze."""
    oracle = json.loads(_ORACLE_FIXTURE.read_text(encoding="utf-8"))
    assert oracle["truncatedReassemblyBytes"] == ORACLE_TRUNCATED_BYTES
    _init_repo(tmp_path)
    backend, body_path, content = _put_chunked(
        tmp_path, monkeypatch, "freeze-truncated-body", "358-prd-freeze-trunc"
    )
    orig_reassemble = ps.reassemble_body

    def truncated_oracle(body_text: str, comments: list, **kwargs: Any) -> str:
        if pc.load_chunk_manifest(body_text):
            return "z" * ORACLE_TRUNCATED_BYTES
        return orig_reassemble(body_text, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", truncated_oracle)
    with pytest.raises(SystemExit):
        backend.freeze(unit_id="358-prd-freeze-trunc", body_path=body_path, distill=False, pre_chunk_body=content)
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-mismatch"
    assert int(payload.get("actualBytes") or 0) == ORACLE_TRUNCATED_BYTES
    assert int(payload.get("expectedBytes") or 0) > payload["actualBytes"]


def test_parser_green_stump_still_refuses_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B/I — spec-rigor `*` R-IDs parse on the stump, but freeze is still refused (AS8)."""
    _init_repo(tmp_path)
    backend, body_path, content = _put_chunked(
        tmp_path, monkeypatch, "freeze-parser-stump", "358-prd-freeze-stump"
    )
    ids = {rid for rid, _ in df.extract_rd_bullets(_STUMP_RID_TAIL)}
    assert ids == {"R1", "R9"}
    orig_reassemble = ps.reassemble_body

    def parser_green_stump(body_text: str, comments: list, **kwargs: Any) -> str:
        if pc.load_chunk_manifest(body_text):
            return _STUMP_RID_TAIL
        return orig_reassemble(body_text, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", parser_green_stump)
    stump_ids = {rid for rid, _ in df.extract_rd_bullets(_STUMP_RID_TAIL)}
    assert stump_ids == {"R1", "R9"}
    with pytest.raises(SystemExit):
        backend.freeze(unit_id="358-prd-freeze-stump", body_path=body_path, distill=False, pre_chunk_body=content)
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-mismatch"


def test_normalized_temp_copy_is_never_freeze_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """E — hyphen-normalized temp copy cannot be freeze evidence (R9)."""
    _init_repo(tmp_path)
    backend, body_path, content = _put_chunked(
        tmp_path, monkeypatch, "freeze-temp-copy", "358-prd-freeze-temp"
    )
    hyphen_temp = cfl.hyphen_normalize_rid_list_markers(content)
    assert hyphen_temp != content
    assert "* **R1**" in content
    assert "- **R1**" in hyphen_temp
    with pytest.raises(SystemExit):
        backend.freeze(
            unit_id="358-prd-freeze-temp",
            body_path=body_path,
            distill=False,
            pre_chunk_body=content,
            freeze_evidence_body=hyphen_temp,
        )
    payload = _fail_payload(capsys)
    assert payload["code"] == "normalized-temp-freeze-evidence"


def test_truncated_reconstruct_refuses_frozen_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S — frozen-hash refuses truncated Linear reconstruction."""
    _init_repo(tmp_path)
    backend, body_path, content = _put_chunked(
        tmp_path, monkeypatch, "freeze-hash-trunc", "358-prd-freeze-hash"
    )
    orig_reassemble = ps.reassemble_body

    def truncated_oracle(body_text: str, comments: list, **kwargs: Any) -> str:
        if pc.load_chunk_manifest(body_text):
            return "z" * ORACLE_TRUNCATED_BYTES
        return orig_reassemble(body_text, comments, **kwargs)

    monkeypatch.setattr(ps, "reassemble_body", truncated_oracle)
    with pytest.raises(SystemExit):
        backend.verify_frozen_hash(
            "358-prd-freeze-hash", body_path, pre_chunk_body=content
        )
    payload = _fail_payload(capsys)
    assert payload["code"] == "reconstruct-mismatch"


def test_github_provider_freeze_is_linear_gated_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shared IssueStoreBackend freeze stays a no-op gate for GitHub (non-goal)."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.chdir(tmp_path)
    _init_repo(tmp_path)
    project_key = "freeze-github-noop"
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "host": {"provider": "github"},
    }
    (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    backend = IssueStoreBackend(tmp_path, cfg)
    unit_id = "358-prd-freeze-github"
    body_path = f"docs/prds/{unit_id}/{unit_id}.md"
    content = (
        f"---\nid: {unit_id}\ntype: prd\nstatus: open\nvisibility: public\n---\n"
        f"# GitHub freeze\n\nSmall body.\n"
    )
    assert backend.put(unit_id, body_path, content).verdict == "ok"
    frozen = backend.freeze(unit_id, body_path, distill=False, pre_chunk_body=content)
    assert frozen["verdict"] == "ok"
    verified = backend.verify_frozen_hash(unit_id, body_path, pre_chunk_body=content)
    assert verified["verdict"] == "ok"
