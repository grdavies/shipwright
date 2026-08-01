"""GitHub Projects operator-projection provider adapter (PRD 085 R18)."""
from __future__ import annotations

from typing import Any

PROVIDER_ID = "github-projects"


def live_client_wired() -> bool:
    try:
        import planning_github_projects_v2 as _pgp  # noqa: WPS433 — optional provider probe
    except ImportError:
        return False
    return bool(getattr(_pgp, "LIVE_CLIENT", False)) and callable(
        getattr(_pgp, "refresh_projection", None)
    )


def operator_projection_projects_answerable() -> bool:
    """PRD 085 R18 — live-probe producer for matrix ``projectsAnswerable`` (no network)."""
    return live_client_wired()


def populate_operator_projection_capability(payload: dict[str, Any]) -> None:
    """PRD 085 R18 — attach ``projectsAnswerable`` from the Projects live-probe."""
    payload["projectsAnswerable"] = operator_projection_projects_answerable()
