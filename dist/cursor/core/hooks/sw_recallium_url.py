"""Validate Recallium REST base URLs — localhost-only to block SSRF via repo config."""

from __future__ import annotations

import ipaddress
import urllib.parse

_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_allowed_recallium_base(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname
    if not host:
        return False
    if host in _ALLOWED_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_loopback
    except ValueError:
        return False
