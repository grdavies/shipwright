"""Linear issues provider adapter (PRD 082 phase 13 / R27)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

PROVIDER_ID = "linear"
BROKER_ID = "linear"
MIN_SCOPES = ("read", "write")
GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"


def live_client_wired() -> bool:
    try:
        import planning_linear_client as _plc  # noqa: WPS433 — optional provider probe
    except ImportError:
        return False
    return bool(getattr(_plc, "LIVE_CLIENT", False)) and callable(getattr(_plc, "graphql", None))


def operator_projection_linear_answerable() -> bool:
    """PRD 085 R18 — live-probe producer for matrix ``linearAnswerable`` (no network)."""
    return live_client_wired()


def populate_operator_projection_capability(payload: dict[str, Any]) -> None:
    """PRD 085 R18 — attach ``linearAnswerable`` from the Linear live-probe."""
    payload["linearAnswerable"] = operator_projection_linear_answerable()


def destination_endpoint(_cfg: dict[str, Any]) -> str:
    return GRAPHQL_ENDPOINT


def doctor_stub_result(
    root: Path,
    *,
    provider: str,
    issues_providers: frozenset[str],
    shipped_providers: frozenset[str],
) -> dict[str, Any] | None:
    """Linear-specific doctor-issues-provider-stub branches; None when not applicable."""
    if provider != PROVIDER_ID:
        return None
    if provider not in issues_providers:
        return {
            "verdict": "fail",
            "action": "doctor-issues-provider-stub",
            "error": "linear-stub-refused",
            "provider": provider,
            "message": (
                "linear is configured but no live client is wired — enum-only stub refused; "
                "install planning_linear_client.py with LIVE_CLIENT before recognition"
            ),
        }
    if provider not in shipped_providers:
        oauth: dict[str, Any]
        try:
            from planning_linear_client import doctor_oauth_ci_secret_check

            oauth = doctor_oauth_ci_secret_check(root)
        except ImportError:
            oauth = {"verdict": "fail", "error": "linear-client-missing"}
        if oauth.get("verdict") == "fail" and oauth.get("error") == "oauth-shared-ci-secret-refused":
            return {
                "verdict": "fail",
                "action": "doctor-issues-provider-stub",
                "error": "linear-oauth-stub-refused",
                "provider": provider,
                "oauth": oauth,
            }
        return {
            "verdict": "pass",
            "action": "doctor-issues-provider-stub",
            "provider": provider,
            "notice": "linear-recognized-not-shipped",
            "message": (
                "linear is recognized (live client wired) but not yet in SHIPPED_ISSUES_PROVIDERS; "
                "issue-store falls back to file-store until conformance + OAuth docs gate pass"
            ),
            "oauth": oauth,
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
        "promotionGatedBy": ["conformance", "oauth-docs-gate"],
        "adapterModule": "scripts/planning_linear_client.py",
        "doctorHooks": ["doctor-issues-provider-stub", "planning_linear_client.doctor-oauth"],
    }


def wire_client(root: Path, credential: Any) -> Any:
    from planning_linear_client import LinearIssuesClient

    return LinearIssuesClient(root, credential=credential)
