#!/usr/bin/env python3
"""Thin Linear GraphQL-over-HTTP client (PRD 066 R9–R14, R23) + LCD verbs (R10)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import issues_http
from host_lib import load_workflow_config
from planning_canonical import (
    BODY_SIZE_LIMIT,
    FROZEN_LABEL,
    MARKER_ARTIFACT_TYPE,
    MARKER_PROJECT_KEY,
    MARKER_UNIT_ID,
    SOURCE_REMOVED_LABEL,
    CommentRecord,
    artifact_type_from_labels,
    chunk_body_if_needed,
    compute_etag,
    parse_body_marker,
    project_label,
    type_label,
    unit_id_from_labels,
)

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
LIFECYCLE_HOOKS = (
    "mark_tombstone",
    "mark_transferred",
    "mark_archived_project",
    "mark_type_converted",
    "mark_key_changed",
)
# R10 — Linear has no native conversation lock; freeze uses hash-authoritative tamper-evidence.
LOCK_CAPABILITY = "degraded"
NATIVE_ISSUE_LOCK = False
IDENTIFIER_NUM = re.compile(r"-(\d+)$")
NATIVE_LINK_MARKER = re.compile(r"<!--\s*sw-native-link:([^:\s]+):([^\s]+)\s*-->")

ISSUE_FIELDS = """
id
identifier
title
description
url
updatedAt
priority
state { id name type }
labels { nodes { id name } }
comments { nodes { id body createdAt } }
""".strip()

ISSUE_CREATE_MUTATION = f"""
mutation IssueCreate($input: IssueCreateInput!) {{
  issueCreate(input: $input) {{
    success
    issue {{ {ISSUE_FIELDS} }}
  }}
}}
""".strip()

ISSUE_UPDATE_MUTATION = f"""
mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {{
  issueUpdate(id: $id, input: $input) {{
    success
    issue {{ {ISSUE_FIELDS} }}
  }}
}}
""".strip()

ISSUE_GET_QUERY = f"""
query IssueGet($id: String!) {{
  issue(id: $id) {{ {ISSUE_FIELDS} }}
}}
""".strip()

COMMENT_CREATE_MUTATION = """
mutation CommentCreate($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment { id body createdAt }
  }
}
""".strip()

ISSUES_SEARCH_QUERY = f"""
query IssuesSearch($filter: IssueFilter, $first: Int) {{
  issues(filter: $filter, first: $first) {{
    nodes {{ {ISSUE_FIELDS} }}
  }}
}}
""".strip()

LABEL_CREATE_MUTATION = """
mutation LabelCreate($input: IssueLabelCreateInput!) {
  issueLabelCreate(input: $input) {
    success
    issueLabel { id name }
  }
}
""".strip()

LABELS_BY_TEAM_QUERY = """
query LabelsByTeam($filter: IssueLabelFilter, $first: Int) {
  issueLabels(filter: $filter, first: $first) {
    nodes { id name }
  }
}
""".strip()

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



def lock_capability() -> dict[str, Any]:
    """R10 — lock surface for capability matrix / conformance docs."""
    return {
        "capability": LOCK_CAPABILITY,
        "native": NATIVE_ISSUE_LOCK,
        "mechanism": "hash-authoritative",
        "frozenLabel": FROZEN_LABEL,
        "notes": (
            "Linear has no native conversation lock. Freeze immutability is "
            "hash-authoritative via sw:frozen + sw-freeze-record (tamper-evidence on read)."
        ),
    }


def overflow_chunk_policy() -> dict[str, Any]:
    """R10 — body overflow uses generic BODY_SIZE_LIMIT + sw-chunk-overflow comments."""
    return {
        "provider": "linear",
        "bodySizeLimitBytes": BODY_SIZE_LIMIT,
        "chunkMarker": "sw-chunk-overflow",
        "chunkVia": "planning_canonical.chunk_body_if_needed",
        "notes": (
            "Oversized bodies are split with <!-- sw-chunk-overflow --> comments and a "
            "sw-chunk-manifest marker; Linear description uses the generic UTF-8 limit "
            f"({BODY_SIZE_LIMIT} bytes), not a tighter ADF-style cap."
        ),
    }


def lcd_verb_names() -> tuple[str, ...]:
    return ADAPTER_VERBS


def lifecycle_hook_names() -> tuple[str, ...]:
    return LIFECYCLE_HOOKS


def _store_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store")
    return store if isinstance(store, dict) else {}


def _label_names_from_issue(payload: dict[str, Any]) -> list[str]:
    labels = payload.get("labels")
    if isinstance(labels, dict):
        nodes = labels.get("nodes") or []
    elif isinstance(labels, list):
        nodes = labels
    else:
        nodes = []
    out: list[str] = []
    for item in nodes:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            out.append(item["name"])
        elif isinstance(item, str):
            out.append(item)
    return out


def _parse_comment(raw: dict[str, Any]) -> CommentRecord:
    body = str(raw.get("body") or "")
    markers: list[str] = []
    for marker_name in (
        "sw-freeze-record",
        "sw-chunk-overflow",
        "sw-memory-pointer",
        "lifecycle:source-removed",
    ):
        if f"<!-- {marker_name} -->" in body or f"<!--{marker_name}-->" in body:
            markers.append(marker_name)
    return CommentRecord(
        id=str(raw.get("id", "")),
        body=body,
        created_at=str(raw.get("createdAt") or raw.get("created_at") or ""),
        markers=markers,
    )


def _comments_from_issue(payload: dict[str, Any]) -> list[CommentRecord]:
    block = payload.get("comments")
    if isinstance(block, dict):
        nodes = block.get("nodes") or []
    elif isinstance(block, list):
        nodes = block
    else:
        nodes = []
    return [_parse_comment(item) for item in nodes if isinstance(item, dict)]


def _native_links_from_comments(comments: list[CommentRecord]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for comment in comments:
        for match in NATIVE_LINK_MARKER.finditer(comment.body):
            entry = {"type": match.group(1), "target": match.group(2)}
            if entry not in links:
                links.append(entry)
    return links


def _issue_number(identifier: str, *, fallback: int = 0) -> int:
    match = IDENTIFIER_NUM.search(identifier.strip())
    if match:
        return int(match.group(1))
    return fallback


def _state_to_lcd(payload: dict[str, Any]) -> str:
    state = payload.get("state")
    if isinstance(state, dict):
        stype = str(state.get("type") or "").lower()
        if stype in {"completed", "canceled", "cancelled"}:
            return "closed"
        name = str(state.get("name") or "").lower()
        if name in {"done", "canceled", "cancelled", "closed"}:
            return "closed"
    return "open"


def _record_from_issue(
    payload: dict[str, Any],
    *,
    project_key: str = "",
    native_links: list[dict[str, Any]] | None = None,
) -> Any:
    from issues_lib import IssueRecord

    body = str(payload.get("description") or payload.get("body") or "")
    labels = _label_names_from_issue(payload)
    comments = _comments_from_issue(payload)
    identifier = str(payload.get("identifier") or "")
    issue_id = str(payload.get("id") or identifier)
    number = _issue_number(identifier)
    updated = str(payload.get("updatedAt") or payload.get("updated_at") or "")
    title = str(payload.get("title") or "")
    artifact_type = (
        artifact_type_from_labels(labels) or parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
    )
    unit_id = unit_id_from_labels(labels) or parse_body_marker(body, MARKER_UNIT_ID) or ""
    locked = FROZEN_LABEL in labels or bool(payload.get("locked"))
    resolved_links = list(
        native_links if native_links is not None else _native_links_from_comments(comments)
    )
    resolved_project = project_key or parse_body_marker(body, MARKER_PROJECT_KEY) or ""
    record = IssueRecord(
        id=issue_id,
        number=number,
        title=title,
        body=body,
        state=_state_to_lcd(payload),
        labels=sorted(set(labels)),
        comments=comments,
        native_links=resolved_links,
        locked=locked,
        updated_at=updated,
        project_key=resolved_project,
        artifact_type=artifact_type,
        unit_id=unit_id,
    )
    record.etag = compute_etag(updated, body, title, record.labels)
    return record


def prepare_body_with_overflow(
    body: str,
    comments: list[CommentRecord] | None = None,
) -> tuple[str, list[CommentRecord]]:
    """Apply R10 overflow/chunk policy for Linear bodies."""
    return chunk_body_if_needed(body, list(comments or []), provider="linear")


class LinearIssuesClient:
    """Duck-typed LCD issues adapter matching FixtureIssuesStore verbs (R10).

    Hermetic path: pass ``fixture_store=`` or set ``SW_ISSUES_FIXTURE=1``.
    Live path: GraphQL mutations/queries via :func:`graphql`.
    ``issue-lock`` is always **degraded** (hash-authoritative) — Linear has no
    native conversation lock.
    """

    LOCK_CAPABILITY = LOCK_CAPABILITY
    NATIVE_ISSUE_LOCK = NATIVE_ISSUE_LOCK

    def __init__(
        self,
        root: Path,
        *,
        cfg: dict[str, Any] | None = None,
        fixture_store: Any | None = None,
        token: str | None = None,
    ) -> None:
        from issues_lib import get_fixture_store, use_fixture_mode

        self.root = Path(root)
        self.cfg = cfg if cfg is not None else load_workflow_config(self.root)
        store = _store_section(self.cfg)
        raw_key = store.get("projectKey")
        self.project_key = raw_key.strip() if isinstance(raw_key, str) else ""
        self._label_id_cache: dict[str, str] = {}
        self._team_id: str = ""
        self._token = token

        if fixture_store is not None:
            self._fixture = fixture_store
        elif use_fixture_mode():
            self._fixture = get_fixture_store(self.root)
        else:
            self._fixture = None

        if self._fixture is None:
            scope = resolve_team_scope(self.cfg)
            self._team_key = scope.get("teamKey") or ""
            self._team_id = scope.get("teamId") or ""
            token_env = resolve_token_env(self.cfg)
            auth = (token if token is not None else os.environ.get(token_env, "")).strip()
            if not auth:
                raise LinearClientError(f"missing token in {token_env}", code="missing-token")
            self._token = auth
        else:
            self._team_key = ""
            try:
                scope = resolve_team_scope(self.cfg)
                self._team_key = scope.get("teamKey") or ""
                self._team_id = scope.get("teamId") or ""
            except LinearTeamConfigError:
                pass

    def lock_capability(self) -> dict[str, Any]:
        return lock_capability()

    def overflow_chunk_policy(self) -> dict[str, Any]:
        return overflow_chunk_policy()

    def _gql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return graphql(
            self.root,
            self.cfg,
            query=query,
            variables=variables,
            token=self._token,
        )

    def _ensure_team_id(self) -> str:
        if self._team_id:
            return self._team_id
        probed = probe_team_scope(self.root, self.cfg, token=self._token)
        if probed.get("verdict") != "ok":
            raise LinearClientError(
                str(probed.get("message") or probed.get("error") or "team probe failed"),
                code=str(probed.get("error") or "team-probe-failed"),
            )
        self._team_id = str(probed.get("teamId") or "")
        if not self._team_id:
            raise LinearClientError("team probe returned no teamId", code="missing-team-id")
        return self._team_id

    def _resolve_label_ids(self, labels: list[str]) -> list[str]:
        """Map flat LCD label names to Linear IssueLabel ids (create-on-miss)."""
        want = sorted({name for name in labels if name})
        if not want:
            return []
        missing = [name for name in want if name not in self._label_id_cache]
        if missing:
            team_id = self._ensure_team_id()
            payload = self._gql(
                LABELS_BY_TEAM_QUERY,
                {"filter": {"team": {"id": {"eq": team_id}}}, "first": 250},
            )
            nodes = (((payload.get("data") or {}).get("issueLabels") or {}).get("nodes")) or []
            for node in nodes:
                if isinstance(node, dict) and isinstance(node.get("name"), str) and node.get("id"):
                    self._label_id_cache[str(node["name"])] = str(node["id"])
            for name in missing:
                if name in self._label_id_cache:
                    continue
                created = self._gql(
                    LABEL_CREATE_MUTATION,
                    {"input": {"name": name, "teamId": team_id}},
                )
                label = (
                    ((created.get("data") or {}).get("issueLabelCreate") or {}).get("issueLabel")
                ) or {}
                lid = str(label.get("id") or "")
                if not lid:
                    raise LinearClientError(
                        f"failed to create label {name!r}", code="label-create-failed"
                    )
                self._label_id_cache[name] = lid
        return [self._label_id_cache[name] for name in want]

    def _issue_payload(self, issue_id: str) -> dict[str, Any]:
        payload = self._gql(ISSUE_GET_QUERY, {"id": issue_id})
        issue = ((payload.get("data") or {}).get("issue")) or None
        if not isinstance(issue, dict):
            from issues_lib import IssueNotFound

            raise IssueNotFound(f"issue not found: {issue_id}")
        return issue

    def create(
        self,
        *,
        title: str,
        body: str,
        labels: list[str],
        project_key: str,
        artifact_type: str,
        unit_id: str,
        native_links: list[dict[str, Any]] | None = None,
    ) -> Any:
        if self._fixture is not None:
            return self._fixture.create(
                title=title,
                body=body,
                labels=labels,
                project_key=project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
                native_links=native_links,
            )
        del artifact_type, unit_id
        head, extra = prepare_body_with_overflow(body, [])
        merged = sorted(set(labels) | {project_label(project_key)})
        team_id = self._ensure_team_id()
        label_ids = self._resolve_label_ids(merged)
        created = self._gql(
            ISSUE_CREATE_MUTATION,
            {
                "input": {
                    "teamId": team_id,
                    "title": title,
                    "description": head,
                    "labelIds": label_ids,
                }
            },
        )
        issue = (((created.get("data") or {}).get("issueCreate") or {}).get("issue")) or {}
        if not isinstance(issue, dict) or not issue.get("id"):
            raise LinearClientError("issueCreate returned no issue", code="create-failed")
        issue_id = str(issue["id"])
        for comment in extra:
            self.add_comment(issue_id, comment.body, markers=list(comment.markers))
        if native_links:
            for link in native_links:
                if not isinstance(link, dict):
                    continue
                link_type = str(link.get("type") or "").strip()
                target = str(link.get("target") or "").strip()
                if link_type and target:
                    self.add_comment(
                        issue_id,
                        (
                            f"<!-- sw-native-link:{link_type}:{target} -->\n"
                            f"Cross-reference: {target} ({link_type})"
                        ),
                        markers=["sw-native-link"],
                    )
        return self.get(issue_id)

    def get(self, issue_id: str) -> Any:
        if self._fixture is not None:
            return self._fixture.get(issue_id)
        return _record_from_issue(self._issue_payload(issue_id), project_key=self.project_key)

    def update(
        self,
        issue_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
        native_links: list[dict[str, Any]] | None = None,
        if_match: str | None = None,
        allow_locked: bool = False,
    ) -> Any:
        from issues_lib import IssueRevisionConflict

        if self._fixture is not None:
            return self._fixture.update(
                issue_id,
                title=title,
                body=body,
                state=state,
                labels=labels,
                native_links=native_links,
                if_match=if_match,
                allow_locked=allow_locked,
            )
        current = self.get(issue_id)
        if if_match and current.etag != if_match:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected=if_match,
                actual=current.etag,
            )
        if current.locked and not allow_locked:
            raise IssueRevisionConflict("issue-locked")
        patch: dict[str, Any] = {}
        extra_comments: list[CommentRecord] = []
        if title is not None:
            patch["title"] = title
        if body is not None:
            head, extra_comments = prepare_body_with_overflow(body, [])
            patch["description"] = head
        if labels is not None:
            patch["labelIds"] = self._resolve_label_ids(sorted(set(labels)))
        if state == "closed" and current.state != "closed":
            patch["state"] = "completed"
        elif state == "open" and current.state == "closed":
            patch["state"] = "unstarted"
        if patch:
            self._gql(ISSUE_UPDATE_MUTATION, {"id": issue_id, "input": patch})
        for comment in extra_comments:
            self.add_comment(issue_id, comment.body, markers=list(comment.markers))
        if native_links is not None:
            for link in native_links:
                if not isinstance(link, dict):
                    continue
                link_type = str(link.get("type") or "").strip()
                target = str(link.get("target") or "").strip()
                if link_type and target:
                    self.add_comment(
                        issue_id,
                        (
                            f"<!-- sw-native-link:{link_type}:{target} -->\n"
                            f"Cross-reference: {target} ({link_type})"
                        ),
                        markers=["sw-native-link"],
                    )
        return self.get(issue_id)

    def add_comment(
        self, issue_id: str, body: str, *, markers: list[str] | None = None
    ) -> CommentRecord:
        if self._fixture is not None:
            return self._fixture.add_comment(issue_id, body, markers=markers)
        created = self._gql(
            COMMENT_CREATE_MUTATION,
            {"input": {"issueId": issue_id, "body": body}},
        )
        raw = (((created.get("data") or {}).get("commentCreate") or {}).get("comment")) or {}
        if not isinstance(raw, dict):
            raise LinearClientError("commentCreate returned no comment", code="comment-failed")
        comment = _parse_comment(raw)
        if markers:
            comment.markers = list(markers)
        return comment

    def set_labels(
        self, issue_id: str, labels: list[str], *, if_match: str | None = None
    ) -> Any:
        return self.update(issue_id, labels=labels, if_match=if_match, allow_locked=True)

    def lock(self, issue_id: str, *, if_match: str | None = None) -> Any:
        """Degraded hash-authoritative lock (R10) — apply sw:frozen; no native lock call."""
        from issues_lib import IssueRevisionConflict

        if self._fixture is not None:
            record = self._fixture.get(issue_id)
            if if_match and record.etag != if_match:
                raise IssueRevisionConflict(
                    "revision-conflict",
                    expected=if_match,
                    actual=record.etag,
                )
            if FROZEN_LABEL not in record.labels:
                record = self._fixture.update(
                    issue_id,
                    labels=sorted(set(record.labels) | {FROZEN_LABEL}),
                    if_match=record.etag,
                    allow_locked=True,
                )
            return self._fixture.lock(issue_id, if_match=record.etag)

        record = self.get(issue_id)
        if if_match and record.etag != if_match:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected=if_match,
                actual=record.etag,
            )
        if FROZEN_LABEL not in record.labels:
            return self.update(
                issue_id,
                labels=sorted(set(record.labels) | {FROZEN_LABEL}),
                if_match=record.etag,
                allow_locked=True,
            )
        record.locked = True
        return record

    def search(
        self,
        *,
        project_key: str,
        artifact_type: str | None = None,
        unit_id: str | None = None,
        labels: list[str] | None = None,
    ) -> list[Any]:
        if self._fixture is not None:
            return self._fixture.search(
                project_key=project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
                labels=labels,
            )
        wanted = [project_label(project_key)]
        if artifact_type:
            wanted.append(type_label(artifact_type))
        if labels:
            wanted.extend(labels)
        filter_obj: dict[str, Any] = {
            "labels": {"name": {"in": wanted}},
        }
        if self._team_id or self._team_key:
            team_id = self._ensure_team_id()
            filter_obj["team"] = {"id": {"eq": team_id}}
        payload = self._gql(ISSUES_SEARCH_QUERY, {"filter": filter_obj, "first": 50})
        nodes = (((payload.get("data") or {}).get("issues") or {}).get("nodes")) or []
        out: list[Any] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            record = _record_from_issue(node, project_key=project_key)
            if SOURCE_REMOVED_LABEL in record.labels:
                continue
            if unit_id and record.unit_id != unit_id:
                continue
            if artifact_type and record.artifact_type != artifact_type:
                continue
            out.append(record)
        out.sort(key=lambda r: r.number)
        return out

    def mark_tombstone(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_tombstone(issue_id)
            return
        from issues_lib import IssueNotFound

        try:
            record = self.get(issue_id)
        except IssueNotFound:
            return
        labels = sorted(set(record.labels) | {SOURCE_REMOVED_LABEL})
        self.update(
            issue_id,
            labels=labels,
            state="closed",
            if_match=record.etag,
            allow_locked=True,
        )
        self.add_comment(
            issue_id,
            "<!-- lifecycle:source-removed -->\nIssue content migrated to in-repo files.",
            markers=["lifecycle:source-removed"],
        )

    def mark_transferred(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_transferred(issue_id)
            return
        raise LinearClientError(
            "mark_transferred requires fixture harness on Linear live path",
            code="lifecycle-fixture-only",
        )

    def mark_archived_project(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_archived_project(issue_id)
            return
        raise LinearClientError(
            "mark_archived_project requires fixture harness on Linear live path",
            code="lifecycle-fixture-only",
        )

    def mark_type_converted(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_type_converted(issue_id)
            return
        raise LinearClientError(
            "mark_type_converted requires fixture harness on Linear live path",
            code="lifecycle-fixture-only",
        )

    def mark_key_changed(self, issue_id: str, new_key: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_key_changed(issue_id, new_key)
            return
        raise LinearClientError(
            "mark_key_changed requires fixture harness on Linear live path",
            code="lifecycle-fixture-only",
        )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print(json.dumps({"verdict": "fail", "error": "usage: planning_linear_client.py <root> <probe-team|doctor-oauth|lock-capability|overflow-policy>"}))
        raise SystemExit(2)
    root = Path(args[0]).resolve()
    cfg = load_workflow_config(root)
    cmd = args[1]
    if cmd == "probe-team":
        print(json.dumps(probe_team_scope(root, cfg), indent=2))
    elif cmd == "doctor-oauth":
        print(json.dumps(doctor_oauth_ci_secret_check(root), indent=2))
    elif cmd == "lock-capability":
        print(json.dumps(lock_capability(), indent=2))
    elif cmd == "overflow-policy":
        print(json.dumps(overflow_chunk_policy(), indent=2))
    else:
        print(json.dumps({"verdict": "fail", "error": f"unknown command: {cmd}"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
