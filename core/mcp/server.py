"""Bounded local MCP server with connection isolation (PRD 349 R39–R42, R52).

Transport options:
  - ``stdio`` (default) — real MCP JSON-RPC for ``initialize``, ``protocolVersion``,
    ``notifications/initialized``, ``tools/list``, ``tools/call`` (PRD 352 R19/R20)
  - Unix domain socket with mode 0600, owned by the process user
  - Loopback TCP with a per-session random token (≥128 bits) stored at mode 0600

Unauthenticated TCP localhost binding is rejected at bind time.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Any, Mapping

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from core.mcp.operations import ALLOWED_OPERATIONS, dispatch  # noqa: E402
    from core.mcp import jsonrpc as _jsonrpc  # noqa: E402
except ImportError:  # script / path bootstrap
    from operations import ALLOWED_OPERATIONS, dispatch  # type: ignore # noqa: E402
    import jsonrpc as _jsonrpc  # type: ignore # noqa: E402

try:
    from memory_redact import redact as _redact
except Exception:  # pragma: no cover - soft fallback

    def _redact(text: str, *, destination: str = "mcp") -> str:  # type: ignore[misc]
        del destination
        return text


SERVER_NAME = "shipwright-bounded"
SERVER_VERSION = "1.0.0"


class BindError(RuntimeError):
    """Raised when the server would bind without required isolation (R52)."""


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, mode)


def redact_payload(payload: Mapping[str, Any] | list[Any] | str | None) -> Any:
    """SC7 — secret-pattern redaction before MCP response serialization."""
    raw = json.dumps(payload, sort_keys=True, default=str)
    redacted = _redact(raw, destination="logs")
    try:
        return json.loads(redacted)
    except json.JSONDecodeError:
        return {"redacted": True, "body": redacted}


def generate_session_token() -> str:
    """≥128 bits of entropy."""
    return secrets.token_urlsafe(24)  # 192 bits


def write_run_state(
    run_dir: Path,
    *,
    transport: str,
    endpoint: str,
    token_path: Path | None = None,
    socket_path: Path | None = None,
) -> Path:
    state = {
        "transport": transport,
        "endpoint": endpoint,
        "tokenPath": str(token_path) if token_path else None,
        "socketPath": str(socket_path) if socket_path else None,
        "allowedOperations": sorted(ALLOWED_OPERATIONS),
    }
    path = Path(run_dir) / "mcp-server.json"
    _atomic_write_text(path, json.dumps(state, indent=2) + "\n")
    return path


def handle_request(
    request: Mapping[str, Any],
    *,
    expected_token: str | None,
    allow_unauthed_unix: bool = False,
) -> dict[str, Any]:
    """Handle one legacy JSON-RPC-ish request after auth + allowlist checks."""
    if expected_token is not None:
        provided = str(request.get("token") or request.get("auth") or "")
        if not secrets.compare_digest(provided, expected_token):
            return {"ok": False, "error": "auth_failed"}
    elif not allow_unauthed_unix:
        return {"ok": False, "error": "auth_required"}

    # SC6 — allowedEndpoints / operation allowlist enforced per call before app logic
    operation = str(request.get("operation") or request.get("method") or "").strip()
    if operation not in ALLOWED_OPERATIONS:
        return {
            "ok": False,
            "error": "permission_denied",
            "operation": operation,
            "allowed": sorted(ALLOWED_OPERATIONS),
        }

    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    result = dispatch(operation, params)
    return {"ok": True, "result": redact_payload(result)}


def _tool_descriptors() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for name in sorted(ALLOWED_OPERATIONS):
        tools.append(
            {
                "name": name,
                "description": f"Shipwright bounded operation: {name}",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "root": {"type": "string", "description": "Workspace root path"},
                    },
                    "additionalProperties": True,
                },
            }
        )
    return tools


def handle_jsonrpc(message: Mapping[str, Any]) -> dict[str, Any] | None:
    """Handle one MCP JSON-RPC request/notification (PRD 352 R19).

    Returns a response object, or ``None`` for notifications (no response).
    """
    method = _jsonrpc.method_name(message)
    req_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if method == "initialize":
        client_version = str(
            params.get("protocolVersion") or _jsonrpc.DEFAULT_PROTOCOL_VERSION
        )
        return _jsonrpc.make_result(
            req_id,
            {
                "protocolVersion": client_version or _jsonrpc.DEFAULT_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method == "protocolVersion":
        return _jsonrpc.make_result(
            req_id,
            {"protocolVersion": _jsonrpc.DEFAULT_PROTOCOL_VERSION},
        )

    if method in {"notifications/initialized", "initialized"}:
        return None

    if method == "tools/list":
        return _jsonrpc.make_result(req_id, {"tools": _tool_descriptors()})

    if method == "tools/call":
        tool_name = str(params.get("name") or "").strip()
        arguments = (
            params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        )
        if tool_name not in ALLOWED_OPERATIONS:
            return _jsonrpc.make_error(
                req_id,
                -32601,
                f"Unknown tool: {tool_name}",
                data={"allowed": sorted(ALLOWED_OPERATIONS)},
            )
        try:
            result = dispatch(tool_name, arguments)
            redacted = redact_payload(result)
            return _jsonrpc.make_result(
                req_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(redacted, sort_keys=True, default=str),
                        }
                    ],
                    "isError": (
                        not bool(redacted.get("ok", True))
                        if isinstance(redacted, dict)
                        else False
                    ),
                    "structuredContent": (
                        redacted if isinstance(redacted, dict) else {"result": redacted}
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001 — surface as tool error payload
            return _jsonrpc.make_result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"tool error: {exc}"}],
                    "isError": True,
                },
            )

    if method == "ping":
        return _jsonrpc.make_result(req_id, {})

    if not method:
        return _jsonrpc.make_error(req_id, -32600, "Invalid Request: missing method")
    return _jsonrpc.make_error(req_id, -32601, f"Method not found: {method}")


def _read_stdio_message(stdin_buffer: Any) -> dict[str, Any] | None:
    """Read one MCP stdio message (Content-Length framing or newline-delimited JSON)."""
    first = stdin_buffer.readline()
    if not first:
        return None
    first_text = first.decode("utf-8") if isinstance(first, bytes) else first

    if first_text.lower().startswith("content-length:"):
        headers = first_text
        while True:
            line = stdin_buffer.readline()
            if not line:
                return None
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            if text in ("\r\n", "\n", ""):
                break
            headers += text
        length = 0
        for header_line in headers.splitlines():
            if header_line.lower().startswith("content-length:"):
                length = int(header_line.split(":", 1)[1].strip())
                break
        body = stdin_buffer.read(length)
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        return _jsonrpc.parse_message(body)

    return _jsonrpc.parse_message(first_text)


def _write_stdio_message(
    stdout_buffer: Any, message: Mapping[str, Any], *, framed: bool
) -> None:
    payload = json.dumps(message, sort_keys=True, default=str)
    if framed:
        encoded = payload.encode("utf-8")
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        stdout_buffer.write(header + encoded)
    else:
        data = (payload + "\n").encode("utf-8")
        stdout_buffer.write(data)
    stdout_buffer.flush()


def serve_stdio(*, max_requests: int | None = None, framed: bool = False) -> None:
    """Serve MCP JSON-RPC over stdin/stdout (PRD 352 R20 / TR5)."""
    stdin = sys.stdin.buffer if hasattr(sys.stdin, "buffer") else sys.stdin
    stdout = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
    handled = 0
    while max_requests is None or handled < max_requests:
        try:
            message = _read_stdio_message(stdin)
        except (ValueError, json.JSONDecodeError) as exc:
            err = _jsonrpc.make_error(None, -32700, f"Parse error: {exc}")
            _write_stdio_message(stdout, err, framed=framed)
            handled += 1
            continue
        if message is None:
            break
        response = handle_jsonrpc(message)
        if response is not None:
            _write_stdio_message(stdout, response, framed=framed)
        handled += 1


def bind_unix(socket_path: Path) -> socket.socket:
    if socket_path.exists():
        socket_path.unlink()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    sock.listen(8)
    return sock


def bind_tcp_loopback(*, port: int, token_path: Path) -> tuple[socket.socket, str]:
    """Bind 127.0.0.1 only; require token file (R52). Plain TCP without auth is forbidden."""
    if not token_path:
        raise BindError("TCP localhost binding requires a token path (R52)")
    token = generate_session_token()
    _atomic_write_text(token_path, token + "\n", mode=0o600)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(8)
    return sock, token


def _serve_once(conn: socket.socket, *, expected_token: str | None, unix: bool) -> None:
    with conn:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 1_000_000:
                break
        if not data:
            return
        try:
            request = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = {"ok": False, "error": "invalid_json"}
        else:
            if not isinstance(request, dict):
                response = {"ok": False, "error": "invalid_request"}
            else:
                response = handle_request(
                    request,
                    expected_token=expected_token,
                    allow_unauthed_unix=unix and expected_token is None,
                )
        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))


def serve(
    *,
    transport: str,
    run_dir: Path,
    socket_path: Path | None = None,
    token_path: Path | None = None,
    port: int = 0,
    max_requests: int | None = None,
) -> None:
    transport = transport.strip().lower()
    if transport == "tcp":
        if token_path is None:
            raise BindError("TCP transport requires --token-path (R52)")
        sock, token = bind_tcp_loopback(port=port, token_path=token_path)
        host, bound_port = sock.getsockname()[:2]
        endpoint = f"tcp://{host}:{bound_port}"
        write_run_state(
            run_dir,
            transport="tcp",
            endpoint=endpoint,
            token_path=token_path,
        )
        expected_token: str | None = token
        unix = False
    elif transport == "unix":
        if socket_path is None:
            raise BindError("unix transport requires --socket-path")
        sock = bind_unix(socket_path)
        endpoint = f"unix://{socket_path}"
        write_run_state(
            run_dir,
            transport="unix",
            endpoint=endpoint,
            socket_path=socket_path,
        )
        expected_token = None  # socket mode 0600 is the auth boundary
        unix = True
    else:
        raise BindError(f"unsupported transport: {transport}")

    handled = 0
    try:
        while max_requests is None or handled < max_requests:
            conn, _addr = sock.accept()
            _serve_once(conn, expected_token=expected_token, unix=unix)
            handled += 1
    finally:
        sock.close()
        if transport == "unix" and socket_path and socket_path.exists():
            try:
                socket_path.unlink()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shipwright bounded MCP server (PRD 349 + PRD 352 R19/R20)"
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "unix", "tcp"),
        default="stdio",
        help="Transport (default: stdio — required by platforms/*/mcpServers launch)",
    )
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--socket-path", type=Path, default=None)
    parser.add_argument("--token-path", type=Path, default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--max-requests", type=int, default=None)
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        serve_stdio(max_requests=args.max_requests)
        return 0

    if args.run_dir is None:
        print(
            json.dumps({"ok": False, "error": "run_dir_required_for_socket_transport"}),
            file=sys.stderr,
        )
        return 20

    if args.transport == "tcp" and not args.token_path:
        print(json.dumps({"ok": False, "error": "tcp_requires_token"}), file=sys.stderr)
        return 20

    try:
        serve(
            transport=args.transport,
            run_dir=args.run_dir,
            socket_path=args.socket_path,
            token_path=args.token_path,
            port=args.port,
            max_requests=args.max_requests,
        )
    except BindError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 20
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
