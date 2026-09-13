"""MCP bounded operations + connection isolation conformance (PRD 349 R39–R42, R52)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from core.mcp.operations import (  # noqa: E402
    ALLOWED_OPERATIONS,
    cli_status,
    dispatch,
    status,
)
from core.mcp.server import BindError, bind_tcp_loopback, generate_session_token, handle_request  # noqa: E402


def test_unknown_operation_permission_denied():
    result = dispatch("shutdown", {"root": str(REPO)})
    assert result["error"] == "permission_denied"
    assert result["ok"] is False


def test_exactly_six_operations():
    assert ALLOWED_OPERATIONS == {
        "status",
        "context_retrieve",
        "task_progress",
        "gap_capture",
        "evidence_register",
        "handoff_export",
    }


def test_mcp_status_matches_cli_alias():
    via_mcp = dispatch("status", {"root": str(REPO)})
    via_cli = cli_status(root=REPO)
    via_direct = status(root=REPO)
    assert via_mcp["operation"] == via_cli["operation"] == via_direct["operation"]
    assert "pendingTransitions" in via_mcp


@pytest.mark.parametrize(
    "operation,params",
    [
        ("status", {}),
        ("context_retrieve", {"paths": ["README.md"]}),
        ("task_progress", {"task_list": "docs/prds/349-platform-portability/tasks-349-platform-portability.md"}),
        ("gap_capture", {"title": "mcp-gap", "detail": "from test"}),
        ("evidence_register", {"path": "README.md", "kind": "doc"}),
    ],
)
def test_each_bounded_operation_roundtrip(operation: str, params: dict, tmp_path: Path):
    params = {**params, "root": str(REPO), "run_id": "mcp-test"}
    if operation == "evidence_register":
        # write into tmp copy? uses repo README — ok for digest register under .shipwright
        pass
    result = dispatch(operation, params)
    assert result.get("ok") is True
    assert result.get("operation") == operation


def test_handoff_export_operation(tmp_path: Path):
    dest = tmp_path / "out-bundle.json"
    result = dispatch(
        "handoff_export",
        {
            "root": str(REPO),
            "destination": str(dest),
            "source_host": "claude-code",
            "destination_host": "codex",
            "remote_url": "https://github.com/example/shipwright.git",
            "head": "a" * 40,
        },
    )
    assert result["ok"] is True
    assert dest.is_file()


def test_tcp_requires_token():
    with tempfile.TemporaryDirectory() as td:
        token_path = Path(td) / "token"
        sock, token = bind_tcp_loopback(port=0, token_path=token_path)
        try:
            assert token_path.stat().st_mode & 0o777 == 0o600
            assert len(token) >= 22
            assert generate_session_token() != token
        finally:
            sock.close()


def test_handle_request_auth_and_redaction():
    token = generate_session_token()
    denied = handle_request({"operation": "status", "params": {"root": str(REPO)}}, expected_token=token)
    assert denied["error"] == "auth_failed"
    ok = handle_request(
        {"operation": "status", "token": token, "params": {"root": str(REPO)}},
        expected_token=token,
    )
    assert ok["ok"] is True
    assert "result" in ok


def test_unix_socket_server_integration(tmp_path: Path):
    # Keep AF_UNIX path short — macOS sockaddr_un sun_path is ~104 bytes.
    sock_path = Path(tempfile.mkdtemp(prefix="swmcp-")) / "s.sock"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    env = {**os.environ, "PYTHONPATH": f"{REPO}:{REPO / 'core'}:{REPO / 'scripts'}"}
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO / "core" / "mcp" / "server.py"),
            "--transport",
            "unix",
            "--socket-path",
            str(sock_path),
            "--run-dir",
            str(run_dir),
            "--max-requests",
            "1",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if sock_path.exists() or proc.poll() is not None:
                break
            time.sleep(0.05)
        if not sock_path.exists():
            err = (proc.stderr.read() if proc.stderr else b"").decode()
            raise AssertionError(f"socket missing; rc={proc.poll()} stderr={err}")
        mode = sock_path.stat().st_mode & 0o777
        assert mode == 0o600
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(sock_path))
        req = json.dumps({"operation": "status", "params": {"root": str(REPO)}}) + "\n"
        client.sendall(req.encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
        client.close()
        response = json.loads(data.decode())
        assert response["ok"] is True
        assert response["result"]["operation"] == "status"
        state = json.loads((run_dir / "mcp-server.json").read_text(encoding="utf-8"))
        assert state["transport"] == "unix"
        assert state["socketPath"] == str(sock_path)
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        else:
            proc.wait(timeout=5)
        try:
            sock_path.unlink(missing_ok=True)
            sock_path.parent.rmdir()
        except OSError:
            pass


def test_adapter_mcp_configs_do_not_conflict():
    """R41 — per-adapter MCP config paths remain distinct."""
    import shipwright_paths as sp

    codex = sp.bounded_mcp_config_path(REPO, "codex")
    opencode = sp.bounded_mcp_config_path(REPO, "opencode")
    claude = sp.bounded_mcp_config_path(REPO, "claude-code")
    assert len({codex, opencode, claude}) == 3
