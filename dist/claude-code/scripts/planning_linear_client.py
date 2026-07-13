#!/usr/bin/env python3
"""Thin Linear GraphQL-over-HTTP client (PRD 066 R9, R11–R14, R23)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import issues_http
from host_lib import load_workflow_config

LIVE_CLIENT = True
GRAPHQL_URL = "https://api.linear.app/graphql"
DEFAULT_TOKEN_ENV = "ISSUES_LINEAR_TOKEN"
DEFAULT_COMPLEXITY_ESTIMATE = 100
ADAPTER_VERBS = (
    "create",
    "get",
    "update",
    "add_comment",
    "set_labels",
    "lock",
    "search",
)

BATCH_CREATE_MUTATION = """
mutation IssueBatchCreate($input: IssueBatchCreateInput!) {
  issueBatchCreate(input: $input) {
    success
    issues { id identifier }
  }
}
""".strip()

TEAM_PROBE_QUERY = """
query TeamProbe($filter: TeamFilter) {
  teams(filter: $filter) {
    nodes { id key name }
  }
  viewer { id }
}
""".strip()


class LinearClientError(Exception):
    def __init__(self, message: str, *, code: str = "linear-client-error") -> None:
        super().__init__(message)
        self.code = code


class LinearTeamConfigError(LinearClientError):
    pass


class LinearBatchInputError(LinearClientError):
    pass


class LinearRateLimited(LinearClientError):
    def __init__(
        self,
        message: str = "Linear GraphQL RATELIMITED",
        *,
        code: str = "RATELIMITED",
        retryable: bool = True,
    ) -> None:
        super().__init__(message, code=code)
        self.retryable = retryable


def _issues_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    issues = store.get("issues")
    return issues if isinstance(issues, dict) else {}


def resolve_auth_mode(cfg: dict[str, Any]) -> str:
    raw = _issues_section(cfg).get("authMode")
    if isinstance(raw, str) and raw.strip().lower() == "oauth":
        return "oauth"
    return "api-key"


def resolve_token_env(cfg: dict[str, Any]) -> str:
    raw = _issues_section(cfg).get("tokenEnv")
    return raw.strip() if isinstance(raw, str) and raw.strip() else DEFAULT_TOKEN_ENV


def resolve_team_scope(cfg: dict[str, Any]) -> dict[str, str]:
    issues = _issues_section(cfg)
    team_key = issues.get("teamKey")
    team_id = issues.get("teamId")
    key = team_key.strip() if isinstance(team_key, str) and team_key.strip() else ""
    tid = team_id.strip() if isinstance(team_id, str) and team_id.strip() else ""
    if not key and not tid:
        raise LinearTeamConfigError(
            "planning.store.issues requires teamKey and/or teamId",
            code="missing-team-scope",
        )
    return {"teamKey": key, "teamId": tid}


def auth_headers(token: str, *, auth_mode: str = "api-key") -> dict[str, str]:
    """Build Authorization header — api-key has no Bearer; oauth uses Bearer (R23)."""
    value = token.strip()
    if auth_mode == "oauth":
        auth = value if value.lower().startswith("bearer ") else f"Bearer {value}"
    else:
        auth = value
    return {
        "Authorization": auth,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "shipwright-linear-client",
    }


def adapter_verbs(*, auth_mode: str = "api-key") -> tuple[str, ...]:
    del auth_mode  # header/token only — verb set unchanged (R23)
    return ADAPTER_VERBS


def oauth_token_storage_guidance() -> dict[str, Any]:
    """Operator-local token storage docs hooks (R23 / M20)."""
    return {
        "operatorLocalOnly": True,
        "mustNotCommitToPlanningRepo": True,
        "sharedCiSecretRefused": True,
        "exceptionConfigKey": "planning.store.issues.oauthSharedCiException",
        "docHints": [
            "Store OAuth access/refresh tokens in an operator-local secret store or machine keychain.",
            "Do not commit tokens to the planning repo or wire authMode:oauth through shared CI secrets by default.",
            "Set oauthSharedCiException: true only for an explicit documented exception path.",
        ],
    }


def _redact(text: str, token: str) -> str:
    if not token:
        return text
    return text.replace(token, "[REDACTED]")


def _graphql_errors_ratelimited(payload: dict[str, Any]) -> bool:
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    for err in errors:
        if not isinstance(err, dict):
            continue
        ext = err.get("extensions")
        if isinstance(ext, dict) and str(ext.get("code") or "").upper() == "RATELIMITED":
            return True
        if str(err.get("message") or "").upper().find("RATELIMIT") >= 0:
            return True
    return False


def _complexity_from_headers(headers: dict[str, str]) -> int:
    for key in (
        "x-ratelimit-complexity-cost",
        "x-complexity",
        "x-ratelimit-complexity-used",
    ):
        raw = headers.get(key) or headers.get(key.title())
        if raw and str(raw).isdigit():
            return int(raw)
    return DEFAULT_COMPLEXITY_ESTIMATE


def graphql(
    root: Path,
    cfg: dict[str, Any],
    *,
    query: str,
    variables: dict[str, Any] | None = None,
    token: str | None = None,
    charge_budget: bool = True,
) -> dict[str, Any]:
    """POST a GraphQL operation to Linear; detect RATELIMITED extensions (R13)."""
    auth_mode = resolve_auth_mode(cfg)
    token_env = resolve_token_env(cfg)
    auth_token = (token if token is not None else os.environ.get(token_env, "")).strip()
    if not auth_token:
        raise LinearClientError(f"missing token in {token_env}", code="missing-token")

    headers = auth_headers(auth_token, auth_mode=auth_mode)
    payload: dict[str, Any] = {"query": query}
    if variables is not None:
        payload["variables"] = variables

    try:
        status, resp_headers, body = issues_http.http_request(
            "POST",
            GRAPHQL_URL,
            headers,
            payload,
            root=root,
            issues_provider="linear",
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 — never echo token material
        raise LinearClientError(_redact(str(exc), auth_token), code="transport-error") from None

    try:
        data = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise LinearClientError(
            _redact(f"invalid JSON response (HTTP {status})", auth_token),
            code="invalid-json",
        ) from exc

    if not isinstance(data, dict):
        raise LinearClientError("unexpected GraphQL payload", code="invalid-payload")

    if status == 429 or _graphql_errors_ratelimited(data):
        raise LinearRateLimited(
            _redact("Linear GraphQL RATELIMITED", auth_token),
            code="RATELIMITED",
        )

    if status >= 400:
        raise LinearClientError(
            _redact(f"HTTP {status}", auth_token),
            code="http-error",
        )

    if charge_budget:
        try:
            import planning_request_budget as prb

            complexity = _complexity_from_headers(
                {str(k).lower(): str(v) for k, v in (resp_headers or {}).items()}
            )
            ledger = prb.RequestBudgetLedger.from_config(root, "linear")
            ledger.charge("graphql", count=1, complexity=complexity)
        except Exception:  # noqa: BLE001 — budget charge must not leak tokens
            pass

    return data


def detect_overscoped_key(
    payload: dict[str, Any],
    *,
    expected_team_id: str = "",
    expected_team_key: str = "",
) -> bool:
    """Return True when credential can see teams beyond the configured Team (R11)."""
    teams = (((payload.get("data") or {}).get("teams") or {}).get("nodes")) or []
    if not isinstance(teams, list) or len(teams) <= 1:
        return False
    matched = 0
    for node in teams:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or "")
        nkey = str(node.get("key") or "")
        if expected_team_id and nid == expected_team_id:
            matched += 1
        elif expected_team_key and nkey == expected_team_key:
            matched += 1
    # More than one team visible beyond a single configured team ⇒ over-scoped.
    return len(teams) > 1 and matched <= 1


def probe_team_scope(root: Path, cfg: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    """Fail-closed Team scope probe (R11)."""
    try:
        scope = resolve_team_scope(cfg)
    except LinearTeamConfigError as exc:
        return {"verdict": "fail", "error": exc.code, "message": str(exc)}

    team_filter: dict[str, Any] = {}
    if scope["teamKey"]:
        team_filter["key"] = {"eq": scope["teamKey"]}
    elif scope["teamId"]:
        team_filter["id"] = {"eq": scope["teamId"]}

    try:
        payload = graphql(
            root,
            cfg,
            query=TEAM_PROBE_QUERY,
            variables={"filter": team_filter or None},
            token=token,
        )
    except LinearRateLimited as exc:
        return {"verdict": "fail", "error": exc.code, "retryable": True}
    except LinearClientError as exc:
        return {"verdict": "fail", "error": exc.code, "message": str(exc)}

    nodes = (((payload.get("data") or {}).get("teams") or {}).get("nodes")) or []
    if not isinstance(nodes, list) or not nodes:
        return {"verdict": "fail", "error": "team-not-found"}

    node = nodes[0] if isinstance(nodes[0], dict) else {}
    resolved_id = str(node.get("id") or "")
    resolved_key = str(node.get("key") or "")

    if scope["teamId"] and scope["teamKey"]:
        if resolved_id != scope["teamId"] or (
            resolved_key and resolved_key != scope["teamKey"]
        ):
            return {
                "verdict": "fail",
                "error": "team-scope-mismatch",
                "resolvedTeamId": resolved_id,
                "resolvedTeamKey": resolved_key,
            }
        # Also catch when configured id does not match key-resolved team.
        if scope["teamId"] != resolved_id:
            return {"verdict": "fail", "error": "team-scope-mismatch"}

    if detect_overscoped_key(
        payload,
        expected_team_id=scope["teamId"] or resolved_id,
        expected_team_key=scope["teamKey"] or resolved_key,
    ):
        return {
            "verdict": "fail",
            "error": "overscoped-key",
            "message": "API key can access multiple teams; use a Team-restricted key",
        }

    return {
        "verdict": "ok",
        "teamId": resolved_id or scope["teamId"],
        "teamKey": resolved_key or scope["teamKey"],
        "authMode": resolve_auth_mode(cfg),
    }


def validate_batch_create_input(raw: Any) -> dict[str, Any]:
    """Require IssueBatchCreateInput wrapper — bare issues array is a silent no-op (R14)."""
    if isinstance(raw, list):
        raise LinearBatchInputError(
            "bare issues array is invalid for Linear batch create; "
            "wrap as {\"issues\": [...]}",
            code="bare-issues-array",
        )
    if not isinstance(raw, dict):
        raise LinearBatchInputError("batch input must be an object", code="invalid-batch-input")
    issues = raw.get("issues")
    if not isinstance(issues, list):
        raise LinearBatchInputError(
            "batch input requires issues: [...] wrapper",
            code="missing-issues-wrapper",
        )
    return {"issues": issues}


def create_issue_batch_payload(raw: Any) -> dict[str, Any]:
    """Build GraphQL mutation payload with required wrapper shape (R14)."""
    wrapped = validate_batch_create_input(raw)
    return {
        "query": BATCH_CREATE_MUTATION,
        "variables": {"input": wrapped},
    }


def create_issue_batch(
    root: Path,
    cfg: dict[str, Any],
    raw: Any,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Execute issueBatchCreate with foot-gun guard (R14)."""
    payload = create_issue_batch_payload(raw)
    return graphql(
        root,
        cfg,
        query=str(payload["query"]),
        variables=payload["variables"],
        token=token,
    )


def doctor_oauth_ci_secret_check(root: Path) -> dict[str, Any]:
    """Refuse authMode:oauth wired via shared CI secret without exception (R23)."""
    cfg = load_workflow_config(root)
    if resolve_auth_mode(cfg) != "oauth":
        return {"verdict": "ok", "skipped": True, "reason": "auth-mode-not-oauth"}

    ci = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}
    gha = os.environ.get("GITHUB_ACTIONS", "").strip().lower() in {"1", "true", "yes"}
    if not (ci or gha):
        return {"verdict": "ok", "skipped": True, "reason": "not-ci-context"}

    issues = _issues_section(cfg)
    if issues.get("oauthSharedCiException") is True:
        return {
            "verdict": "ok",
            "exceptionPath": True,
            "note": "oauthSharedCiException explicitly enabled",
        }

    return {
        "verdict": "fail",
        "error": "oauth-shared-ci-secret-refused",
        "check": "linear-oauth-ci-secret",
        "remediation": (
            "Use operator-local OAuth tokens, or set "
            "planning.store.issues.oauthSharedCiException: true for a documented exception"
        ),
        "guidance": oauth_token_storage_guidance(),
    }


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print(json.dumps({"verdict": "fail", "error": "usage: planning_linear_client.py <root> <probe-team|doctor-oauth>"}))
        raise SystemExit(2)
    root = Path(args[0]).resolve()
    cfg = load_workflow_config(root)
    cmd = args[1]
    if cmd == "probe-team":
        print(json.dumps(probe_team_scope(root, cfg), indent=2))
    elif cmd == "doctor-oauth":
        print(json.dumps(doctor_oauth_ci_secret_check(root), indent=2))
    else:
        print(json.dumps({"verdict": "fail", "error": f"unknown command: {cmd}"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
