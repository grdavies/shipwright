"""Host HTTP transport on urllib with TLS and SSRF hardening (PRD 042 R8, R44)."""

from __future__ import annotations

import argparse
import ipaddress
import os
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from _sw import jsonio, logging_setup

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from host_lib import host_section, load_workflow_config, resolve_rate_limit  # noqa: E402
from host_ratelimit import RequestResult, SerialGate, execute_with_retry  # noqa: E402

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.goog",
    }
)
_METADATA_IPS = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)
_REDACT_PATTERNS = ("authorization", "bearer", "token", "ghp_", "glpat-")


def _host_allowlist(root: Path) -> set[str]:
    cfg = host_section(load_workflow_config(root))
    raw = cfg.get("ssrfAllowlist")
    if not isinstance(raw, list):
        return set()
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def _is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if addr.is_loopback or addr.is_link_local or addr.is_private:
        return True
    for net in _METADATA_IPS:
        if addr in net:
            return True
    return False


def validate_url(url: str, *, root: Path | None = None) -> tuple[str, str]:
    """Return (scheme, hostname) when URL passes SSRF policy; else raise ValueError."""
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError("only https URLs are permitted")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("missing hostname")
    allowlist = _host_allowlist(root or Path.cwd())
    if host in allowlist:
        return parsed.scheme.lower(), host
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"blocked host: {host}")
    try:
        addr = ipaddress.ip_address(host)
        if _is_blocked_ip(addr):
            raise ValueError(f"blocked address: {host}")
    except ValueError as exc:
        if "blocked" in str(exc):
            raise
        if host.endswith(".localhost"):
            raise ValueError(f"blocked host: {host}") from exc
    return parsed.scheme.lower(), host


class _SameHostRedirectHandler(HTTPRedirectHandler):
    """Follow redirects only when scheme is https and host is unchanged."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        orig = urlparse(req.full_url)
        dest = urlparse(newurl)
        if dest.scheme.lower() != "https":
            return None
        if (dest.hostname or "").lower() != (orig.hostname or "").lower():
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _redact_for_log(text: str) -> str:
    lower = text.lower()
    for needle in _REDACT_PATTERNS:
        if needle in lower:
            return "[REDACTED]"
    return text


def _read_token(token_env: str) -> str | None:
    if not token_env:
        return None
    return os.environ.get(token_env) or None


def _build_headers(token_env: str, extra_header_file: Path | None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    token = _read_token(token_env)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif extra_header_file and extra_header_file.is_file():
        for line in extra_header_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            headers[key.strip()] = val.strip()
    return headers


def urllib_request(
    *,
    method: str,
    url: str,
    root: Path,
    provider: str,
    token_env: str = "",
    body: bytes | None = None,
    header_file: Path | None = None,
    lock_file: Path | None = None,
) -> dict[str, Any]:
    """Perform one host HTTP request with rate-limit retry; emit transport JSON payload."""
    try:
        validate_url(url, root=root)
    except ValueError as exc:
        payload = {
            "verdict": "fail",
            "reason": "ssrf-policy",
            "message": str(exc),
            "retryable": False,
        }
        print(jsonio.dumps(payload, indent=2))
        return payload

    if token_env and not _read_token(token_env):
        payload = {"verdict": "degraded", "reason": "missing-token", "retryable": False}
        print(jsonio.dumps(payload, indent=2))
        return payload

    cfg = resolve_rate_limit(host_section(load_workflow_config(root)))
    headers = _build_headers(token_env, header_file)
    opener = build_opener(HTTPSHandler(context=_ssl_context()), _SameHostRedirectHandler())

    def request_fn() -> RequestResult:
        req = Request(url, data=body, method=method.upper(), headers=headers)
        try:
            with opener.open(req, timeout=120) as resp:
                raw = resp.read()
                text = raw.decode("utf-8", errors="replace")
                resp_headers = {k: v for k, v in resp.headers.items()}
                return RequestResult(status_code=int(resp.status), headers=resp_headers, body=text)
        except HTTPError as exc:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace") if raw else ""
            resp_headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
            return RequestResult(status_code=int(exc.code), headers=resp_headers, body=text)
        except URLError as exc:
            logging_setup.warning(_redact_for_log(f"host-transport url error: {exc.reason}"))
            return RequestResult(status_code=0, headers={}, body=str(exc.reason))

    gate = SerialGate(lock_file) if lock_file else SerialGate()
    outcome = execute_with_retry(
        provider=provider,
        config=cfg,
        method=method,
        request_fn=request_fn,
        serial_gate=gate,
    )
    payload = outcome.to_json()
    if outcome.result is not None:
        payload["body"] = outcome.result.body
        payload["bodyBytes"] = len(outcome.result.body or "")
        payload["headers"] = outcome.result.headers
    print(jsonio.dumps(payload, indent=2))
    return payload


def transport_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host HTTP transport (urllib, SSRF-hardened)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider", required=True)
    parser.add_argument("--method", default="GET")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-env", default="")
    parser.add_argument("--header-file", type=Path, default=None)
    parser.add_argument("--body-file", type=Path, default=None)
    args = parser.parse_args(argv)

    body_bytes: bytes | None = None
    if args.body_file and args.body_file.is_file():
        body_bytes = args.body_file.read_bytes()

    lock_dir = Path(tempfile.mkdtemp(prefix="sw-host-transport-"))
    lock_file = lock_dir / "serial.lock"
    try:
        payload = urllib_request(
            method=args.method,
            url=args.url,
            root=args.root.resolve(),
            provider=args.provider,
            token_env=args.token_env,
            body=body_bytes,
            header_file=args.header_file,
            lock_file=lock_file,
        )
    finally:
        lock_file.unlink(missing_ok=True)
        lock_dir.rmdir()

    verdict = payload.get("verdict")
    if verdict == "ok":
        return 0
    if verdict == "rate-limited":
        return 37
    if verdict == "degraded":
        return 0
    return 1


def main() -> int:
    return transport_cli()


if __name__ == "__main__":
    raise SystemExit(main())
