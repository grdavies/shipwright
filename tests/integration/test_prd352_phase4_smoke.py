"""PRD 352 R27 — phase-4 hook conformance + MCP launchability smoke."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "core" / "hooks")]

from adapters.pre_tool_evaluator import (  # noqa: E402
    PreToolVerdict,
    _emit_submit_result,
    _session_start_payload,
    fail_closed_pretool_deny,
)
from core.mcp.server import handle_jsonrpc  # noqa: E402


def test_prd352_phase4_hook_conformance_shapes() -> None:
    session = _session_start_payload("phase4-context")
    assert session["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "event_name" not in session

    allow = PreToolVerdict(verdict="pass").to_claude_hook_output()
    assert "decision" not in allow
    assert allow["hookSpecificOutput"]["permissionDecision"] == "allow"

    deny = PreToolVerdict(verdict="fail", cause="x").to_claude_hook_output()
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"

    submit_allow = _emit_submit_result(type("R", (), {"allow": True, "message": ""})())
    assert "decision" not in submit_allow

    submit_block = _emit_submit_result(
        type("R", (), {"allow": False, "message": "blocked"})()
    )
    assert submit_block["decision"] == "block"

    crash = fail_closed_pretool_deny("crash")
    assert crash["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_prd352_phase4_mcp_jsonrpc_methods() -> None:
    init = handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "phase4", "version": "0"},
            },
        }
    )
    assert init is not None
    assert init["result"]["protocolVersion"] == "2024-11-05"

    proto = handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "protocolVersion"})
    assert proto is not None
    assert "protocolVersion" in proto["result"]

    assert handle_jsonrpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    tools = handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert tools is not None
    names = {t["name"] for t in tools["result"]["tools"]}
    assert "status" in names

    call = handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "status", "arguments": {"root": str(REPO)}},
        }
    )
    assert call is not None
    assert call["result"]["isError"] is False


def test_prd352_phase4_mcp_stdio_launchable() -> None:
    """Spawn server.py with stdio default and complete initialize handshake."""
    server = REPO / "core" / "mcp" / "server.py"
    assert server.is_file()
    payload = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "phase4-stdio", "version": "0"},
                },
            }
        )
        + "\n"
    )
    proc = subprocess.run(
        [sys.executable, str(server), "--max-requests", "1"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"stdio MCP failed: rc={proc.returncode} stderr={proc.stderr!r} stdout={proc.stdout!r}"
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"no stdout from MCP server: stderr={proc.stderr!r}"
    msg = json.loads(lines[0])
    assert msg["result"]["protocolVersion"] == "2024-11-05"
    assert msg["result"]["serverInfo"]["name"]


def test_prd352_phase4_depmanifest_declares_mcp() -> None:
    manifest = json.loads(
        (REPO / "scripts" / "_sw" / "depmanifest.json").read_text(encoding="utf-8")
    )
    allowed = set(manifest.get("allowed") or [])
    declared = manifest.get("declared") or {}
    assert "mcp" in allowed or "mcp" in declared, f"mcp not declared: {manifest}"


def test_prd352_phase4_claude_mcp_servers_stdio() -> None:
    sys.path.insert(0, str(REPO / "platforms" / "claude-code"))
    import hook_adapter

    cfg = hook_adapter.build_mcp_config(REPO)
    assert cfg is not None
    server = cfg["mcpServers"]["shipwright-bounded"]
    assert server["transport"] == "stdio"
    assert server["args"] and Path(server["args"][0]).name == "server.py"
