"""Pin-validity checker library for GitHub workflow action refs (PRD 083 R10).

Validates third-party action pins in .github/workflows/*.yml against the GitHub
API or a maintained allowlist.

Fail-closed behaviour:
  - Confirmed-invalid pin   → non-zero exit, {"verdict": "fail", "invalid_pins": [...]}
  - Transient lookup error  → exit 0,        {"verdict": "warn", "warnings": [...]}
  - All pins valid          → exit 0,        {"verdict": "pass"}
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

# Actions under these owners are treated as first-party and skipped.
_FIRST_PARTY_OWNERS: frozenset[str] = frozenset({"grdavies"})

# SHA pattern: exactly 40 hex characters.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

# Matches `uses:` lines in YAML (with optional leading spaces/dash).
_USES_RE = re.compile(
    r"^\s*-?\s*uses:\s+(?P<ref>[^\s#]+)",
    re.MULTILINE,
)

# GitHub API base URL (module-level so tests can monkeypatch via patch.object).
_GH_API_BASE = "https://api.github.com"

# Statically maintained allowlist of known-valid tag pins by action slug.
# Consult this before calling the API to avoid unnecessary requests for common
# well-known tags, and as a fallback when the API is unreachable.
_KNOWN_VALID_TAGS: dict[str, frozenset[str]] = {
    "actions/checkout": frozenset({"v1", "v2", "v3", "v4", "v5"}),
    "actions/setup-python": frozenset({"v1", "v2", "v3", "v4", "v5"}),
    "actions/setup-node": frozenset({"v1", "v2", "v3", "v4", "v5"}),
    "actions/upload-artifact": frozenset({"v1", "v2", "v3", "v4", "v5"}),
    "actions/download-artifact": frozenset({"v1", "v2", "v3", "v4", "v5"}),
    "actions/cache": frozenset({"v1", "v2", "v3", "v4"}),
    "actions/github-script": frozenset({"v1", "v2", "v3", "v4", "v5", "v6", "v7"}),
    "google-github-actions/release-please-action": frozenset({"v4"}),
    "release-drafter/release-drafter": frozenset({"v5", "v6"}),
}

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_action_ref(raw: str) -> tuple[str, str, str] | None:
    """Parse 'owner/repo@ref' or 'owner/repo/path@ref'. Returns (owner, slug, ref) or None."""
    raw = raw.split("#")[0].strip()
    if "@" not in raw:
        return None
    path_part, ref = raw.rsplit("@", 1)
    segments = path_part.split("/")
    if len(segments) < 2:
        return None
    owner = segments[0]
    repo = segments[1]
    slug = f"{owner}/{repo}"
    return owner, slug, ref


def _is_first_party(owner: str) -> bool:
    return owner.lower() in _FIRST_PARTY_OWNERS


def _github_api_request(url: str, token: str | None = None) -> dict | list | None:
    """Make a GitHub API GET request.

    Returns parsed JSON dict/list on success, None on HTTP 404/error.
    Raises urllib.error.URLError / OSError on transient network failure.
    """
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    # URLError, OSError, TimeoutError → caller treats as transient; re-raise.


def _validate_sha_pin(slug: str, sha: str, token: str | None) -> str:
    """Validate a SHA pin against the GitHub API.

    Returns:
        "valid"     — SHA confirmed to exist
        "invalid"   — SHA confirmed to not exist (404)
        "transient" — network/API error; treat as fail-open
    """
    url = f"{_GH_API_BASE}/repos/{slug}/commits/{sha}"
    try:
        data = _github_api_request(url, token)
    except Exception:
        return "transient"
    if data is None:
        return "invalid"
    if isinstance(data, dict) and data.get("sha"):
        return "valid"
    return "invalid"


def _validate_tag_pin(slug: str, tag: str, token: str | None) -> str:
    """Validate a tag pin via allowlist then GitHub API.

    Returns:
        "valid"     — tag confirmed valid
        "invalid"   — tag confirmed not found
        "transient" — network error; cannot confirm
    """
    known = _KNOWN_VALID_TAGS.get(slug)
    if known is not None and tag in known:
        return "valid"
    url = f"{_GH_API_BASE}/repos/{slug}/git/ref/tags/{tag}"
    try:
        data = _github_api_request(url, token)
    except Exception:
        return "transient"
    if data is None:
        return "invalid"
    if isinstance(data, dict) and "ref" in data:
        return "valid"
    return "invalid"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_workflow_files(root: Path) -> list[dict]:
    """Return list of pin records from all workflow YAML files under root."""
    pins: list[dict] = []
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return pins
    for wf_file in sorted(workflow_dir.glob("*.yml")):
        text = wf_file.read_text(encoding="utf-8")
        for match in _USES_RE.finditer(text):
            raw = match.group("ref")
            parsed = _parse_action_ref(raw)
            if parsed is None:
                continue
            owner, slug, ref = parsed
            if _is_first_party(owner):
                continue
            is_sha = bool(_SHA_RE.match(ref))
            pins.append(
                {
                    "file": str(wf_file.relative_to(root)),
                    "slug": slug,
                    "ref": ref,
                    "is_sha": is_sha,
                }
            )
    return pins


def validate_pins(
    pins: list[dict],
    token: str | None = None,
    skip_api: bool = False,
) -> tuple[list[dict], list[str]]:
    """Validate each pin record. Returns (invalid_pins, warnings).

    invalid_pins: confirmed-invalid entries → fail closed.
    warnings:     transient errors → fail open (logged, exit 0).
    """
    invalid: list[dict] = []
    warnings: list[str] = []

    for pin in pins:
        slug, ref, is_sha = pin["slug"], pin["ref"], pin["is_sha"]
        file_path = pin["file"]

        if skip_api:
            if not is_sha:
                known = _KNOWN_VALID_TAGS.get(slug)
                if known is not None and ref not in known:
                    invalid.append(
                        {"file": file_path, "slug": slug, "ref": ref, "reason": "not-in-allowlist"}
                    )
            continue

        result = _validate_sha_pin(slug, ref, token) if is_sha else _validate_tag_pin(slug, ref, token)

        if result == "invalid":
            invalid.append(
                {"file": file_path, "slug": slug, "ref": ref, "reason": "api-not-found"}
            )
        elif result == "transient":
            msg = f"{file_path}: {slug}@{ref} — upstream lookup failed (transient); skipped"
            warnings.append(msg)
            log.warning(msg)

    return invalid, warnings


def run_check(
    root: Path,
    *,
    token: str | None = None,
    skip_api: bool = False,
) -> tuple[int, dict]:
    """Entry point for gate and tests. Returns (exit_code, result_dict)."""
    pins = scan_workflow_files(root)
    if not pins:
        return 0, {"verdict": "pass", "reason": "no-third-party-pins-found", "pins": []}

    invalid, warnings = validate_pins(pins, token=token, skip_api=skip_api)

    if invalid:
        return 20, {
            "verdict": "fail",
            "reason": "invalid-pins-detected",
            "invalid_pins": invalid,
            "warnings": warnings,
            "total_pins_checked": len(pins),
        }

    verdict = "pass" if not warnings else "warn"
    reason = "all-pins-valid" if not warnings else "transient-lookup-failures"
    return 0, {
        "verdict": verdict,
        "reason": reason,
        "warnings": warnings,
        "total_pins_checked": len(pins),
    }
