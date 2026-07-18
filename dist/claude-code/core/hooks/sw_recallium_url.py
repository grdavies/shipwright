"""Validate Recallium REST base URLs — localhost-only to block SSRF via repo config."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sw_recallium_url import (  # noqa: E402
    RestFetchPolicyError,
    fetch_json,
    guarded_urlopen,
    is_allowed_recallium_base,
    is_rest_url_allowed,
    load_catalog_rest_policy,
    rest_fetch_policy_from_catalog_entry,
    rest_fetch_policy_from_transport,
    validate_rest_url,
)

__all__ = [
    "RestFetchPolicyError",
    "fetch_json",
    "guarded_urlopen",
    "is_allowed_recallium_base",
    "is_rest_url_allowed",
    "load_catalog_rest_policy",
    "rest_fetch_policy_from_catalog_entry",
    "rest_fetch_policy_from_transport",
    "validate_rest_url",
]
