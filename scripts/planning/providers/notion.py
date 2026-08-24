"""Notion issues provider adapter (PRD 327 phase 2)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

PROVIDER_ID = "notion"
BROKER_ID = "notion"
MIN_SCOPES: tuple[str, ...] = ()
NOTION_API_BASE = "https://api.notion.com/v1"


def live_client_wired() -> bool:
    try:
        import planning_notion_client as _pnc  # noqa: WPS433 — optional provider probe
    except ImportError:
        return False
    return bool(getattr(_pnc, "LIVE_CLIENT", False)) and callable(getattr(_pnc, "notion_request", None))


def destination_endpoint(_cfg: dict[str, Any]) -> str:
    return NOTION_API_BASE


def scope_probe(token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    from planning_notion_client import probe_database

    result = probe_database(root, cfg, token=token)
    if result.get("verdict") == "ok":
        out: dict[str, Any] = {"verdict": "ok"}
        for key in (
            "provider",
            "tokenEnv",
            "fixtureProbe",
            "databases",
            "titleProperty",
            "statusProperty",
            "projectProperty",
        ):
            if key in result:
                out[key] = result[key]
        return out
    out = {
        "verdict": "fail",
        "error": result.get("error", "probe-failed"),
        "provider": PROVIDER_ID,
    }
    for key in ("message", "tokenEnv", "httpStatus", "failures"):
        if key in result:
            out[key] = result[key]
    return out


def doctor_stub_result(
    root: Path,
    *,
    provider: str,
    issues_providers: frozenset[str],
    shipped_providers: frozenset[str],
) -> dict[str, Any] | None:
    """Notion-specific doctor-issues-provider-stub branches; None when not applicable."""
    if provider != PROVIDER_ID:
        return None
    if provider not in issues_providers:
        return {
            "verdict": "fail",
            "action": "doctor-issues-provider-stub",
            "error": "notion-stub-refused",
            "provider": provider,
            "message": (
                "notion is configured but no live client is wired — enum-only stub refused; "
                "install planning_notion_client.py with LIVE_CLIENT before recognition"
            ),
        }
    if provider not in shipped_providers:
        return {
            "verdict": "pass",
            "action": "doctor-issues-provider-stub",
            "provider": provider,
            "notice": "notion-recognized-not-shipped",
            "message": (
                "notion is recognized (live client wired) but not yet in SHIPPED_ISSUES_PROVIDERS; "
                "issue-store falls back to file-store until conformance + docs gate pass"
            ),
        }
    return None


def registration_footprint(
    *,
    recognized: bool,
    shipped: bool,
    live_client_wired: bool,
) -> dict[str, Any]:
    return {
        "recognized": recognized,
        "shipped": shipped,
        "liveClientWired": live_client_wired,
        "promotionGatedBy": ["conformance", "docs-gate"],
        "adapterModule": "scripts/planning_notion_client.py",
        "doctorHooks": ["doctor-issues-provider-stub", "planning_notion_client.probe-database"],
    }


def wire_client(root: Path, credential: Any) -> Any:
    from planning_notion_client import NotionIssuesClient

    return NotionIssuesClient(root, credential=credential)
