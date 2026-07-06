#!/usr/bin/env python3
"""Live Jira Cloud/DC REST client for PRD 047 issue-store CRUD (R32a, R101)."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import issues_http
from host_lib import load_workflow_config
from planning_canonical import (
    MARKER_ARTIFACT_TYPE,
    MARKER_UNIT_ID,
    SOURCE_REMOVED_LABEL,
    compute_etag,
    parse_body_marker,
    type_label,
)
from planning_jira_canonical import (
    JIRA_CLOUD_DESCRIPTION_LIMIT,
    adf_to_markdown,
    jira_adf_payload_size,
    markdown_to_adf,
    wiki_to_markdown,
)
from planning_jira_probe import (
    resolve_field_defaults,
    resolve_jira_email_env,
    resolve_jira_endpoint,
    resolve_jira_flavor,
    resolve_jira_api_project_key,
    resolve_jira_issue_type,
    resolve_jira_project_key,
)

JIRA_CLOUD_API = "/rest/api/3"
JIRA_DC_API = "/rest/api/2"
ISSUE_KEY_NUM = re.compile(r"-(\d+)$")
SEARCH_PAGE_SIZE = 50


def _issues_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    issues = store.get("issues")
    return issues if isinstance(issues, dict) else {}


def _token_env(cfg: dict[str, Any]) -> str:
    issues = _issues_section(cfg)
    raw = issues.get("tokenEnv")
    return raw.strip() if isinstance(raw, str) and raw.strip() else "ISSUES_JIRA_TOKEN"


def _api_base(cfg: dict[str, Any]) -> str:
    endpoint = resolve_jira_endpoint(cfg)
    suffix = JIRA_DC_API if resolve_jira_flavor(cfg) == "dc" else JIRA_CLOUD_API
    return f"{endpoint}{suffix}" if endpoint else ""


def _auth_header(cfg: dict[str, Any], token: str) -> dict[str, str]:
    if resolve_jira_flavor(cfg) == "dc":
        return {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
    email = os.environ.get(resolve_jira_email_env(cfg), "").strip()
    if not email:
        return {}
    cred = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {cred}", "Accept": "application/json", "Content-Type": "application/json"}


def _description_to_markdown(description: Any, *, flavor: str) -> str:
    if flavor == "dc":
        return wiki_to_markdown(str(description or ""))
    if isinstance(description, dict):
        return adf_to_markdown(description)
    return str(description or "")


def _parse_comment(raw: dict[str, Any], *, flavor: str) -> Any:
    from planning_canonical import CommentRecord

    body = _description_to_markdown(raw.get("body"), flavor=flavor)
    markers: list[str] = []
    for marker in ("sw-freeze-record", "sw-chunk-overflow", "sw-memory-pointer"):
        if f"<!-- {marker} -->" in body or f"<!--{marker}-->" in body:
            markers.append(marker)
    return CommentRecord(
        id=str(raw.get("id", "")),
        body=body,
        created_at=str(raw.get("created", "")),
        markers=markers,
    )


def _issue_state(fields: dict[str, Any]) -> str:
    status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    category = status.get("statusCategory") if isinstance(status.get("statusCategory"), dict) else {}
    key = str(category.get("key", "")).lower()
    return "closed" if key == "done" else "open"


def _record_from_issue(payload: dict[str, Any], *, flavor: str) -> Any:
    from issues_lib import IssueRecord

    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    key = str(payload.get("key", ""))
    body = _description_to_markdown(fields.get("description"), flavor=flavor)
    labels = [str(x) for x in (fields.get("labels") or [])]
    comments_raw = []
    comment_block = fields.get("comment")
    if isinstance(comment_block, dict):
        comments_raw = comment_block.get("comments") or []
    comments = [_parse_comment(c, flavor=flavor) for c in comments_raw if isinstance(c, dict)]
    updated = str(fields.get("updated") or "")
    artifact_type = parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
    unit_id = parse_body_marker(body, MARKER_UNIT_ID) or ""
    num_match = ISSUE_KEY_NUM.search(key)
    number = int(num_match.group(1)) if num_match else 0
    locked = "sw:frozen" in labels
    record = IssueRecord(
        id=key,
        number=number,
        title=str(fields.get("summary") or ""),
        body=body,
        state=_issue_state(fields),
        labels=labels,
        comments=comments,
        native_links=[],
        locked=locked,
        updated_at=updated,
        project_key="",
        artifact_type=artifact_type,
        unit_id=unit_id,
    )
    record.etag = compute_etag(updated, body, record.title, labels)
    return record


def _jql_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class JiraIssuesClient:
    """Live Jira REST issues adapter (Cloud ADF primary; DC wiki)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cfg = load_workflow_config(root)
        self.flavor = resolve_jira_flavor(self.cfg)
        self.base = _api_base(self.cfg)
        token = os.environ.get(_token_env(self.cfg), "").strip()
        if not token:
            raise RuntimeError(f"missing Jira token env {_token_env(self.cfg)}")
        self.headers = _auth_header(self.cfg, token)
        if not self.headers:
            raise RuntimeError(f"missing Jira email env {resolve_jira_email_env(self.cfg)}")
        self.project_key = resolve_jira_project_key(self.cfg)
        self.api_project_key = resolve_jira_api_project_key(self.cfg, token, root)
        self.issue_type = resolve_jira_issue_type(self.cfg)
        self.field_defaults = resolve_field_defaults(self.cfg)

    def _http_json(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> Any:
        from issues_lib import IssueArchivedProject

        hdrs = {**headers, "User-Agent": "shipwright-jira-client"}
        status, _hdrs, body = issues_http.http_request(
            method,
            url,
            hdrs,
            payload,
            root=self.root,
            issues_provider="jira",
        )
        if status in {404, 410}:
            raise IssueArchivedProject(f"archived or missing: {url}")
        if status >= 400:
            raise RuntimeError(f"Jira HTTP {status}: {body[:300]}")
        return json.loads(body) if body.strip() else {}

    def _get_issue(self, issue_id: str) -> Any:
        payload = self._http_json("GET", f"{self.base}/issue/{issue_id}?expand=comments", self.headers)
        if not isinstance(payload, dict):
            from issues_lib import IssueNotFound

            raise IssueNotFound(f"issue not found: {issue_id}")
        return _record_from_issue(payload, flavor=self.flavor)

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
        del native_links, artifact_type, unit_id
        api_key = self.api_project_key if project_key == self.project_key else project_key
        fields: dict[str, Any] = {
            "project": {"key": api_key},
            "summary": title,
            "issuetype": {"name": self.issue_type},
            "labels": sorted(set(labels)),
        }
        for field_id, value in self.field_defaults.items():
            fields[field_id] = value
        if self.flavor != "dc" and jira_adf_payload_size(body) > JIRA_CLOUD_DESCRIPTION_LIMIT:
            raise RuntimeError(
                "Jira description exceeds Cloud ADF limit; run chunk_body_for_jira_cloud before create"
            )
        fields["description"] = body if self.flavor == "dc" else markdown_to_adf(body)
        created = self._http_json("POST", f"{self.base}/issue", self.headers, {"fields": fields})
        key = str((created or {}).get("key", ""))
        if not key:
            raise RuntimeError("Jira issue-create returned no key")
        return self._get_issue(key)

    def get(self, issue_id: str) -> Any:
        from issues_lib import IssueArchivedProject, IssueNotFound

        try:
            return self._get_issue(issue_id)
        except IssueArchivedProject as exc:
            raise IssueNotFound(str(exc)) from exc

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

        del native_links
        current = self._get_issue(issue_id)
        if if_match and current.etag != if_match:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected=if_match,
                actual=current.etag,
            )
        if current.locked and not allow_locked:
            raise IssueRevisionConflict("issue-locked")
        fields: dict[str, Any] = {}
        if title is not None:
            fields["summary"] = title
        if body is not None:
            if self.flavor != "dc" and jira_adf_payload_size(body) > JIRA_CLOUD_DESCRIPTION_LIMIT:
                raise RuntimeError(
                    "Jira description exceeds Cloud ADF limit; run chunk_body_for_jira_cloud before update"
                )
            fields["description"] = body if self.flavor == "dc" else markdown_to_adf(body)
        if labels is not None:
            fields["labels"] = sorted(set(labels))
        if fields:
            self._http_json("PUT", f"{self.base}/issue/{issue_id}", self.headers, {"fields": fields})
        if state == "closed" and current.state != "closed":
            self._transition_close(issue_id)
        elif state == "open" and current.state == "closed":
            self._transition_open(issue_id)
        return self._get_issue(issue_id)

    def add_comment(self, issue_id: str, body: str, *, markers: list[str] | None = None) -> Any:
        from planning_canonical import CommentRecord

        payload_body: Any = body if self.flavor == "dc" else markdown_to_adf(body)
        created = self._http_json(
            "POST",
            f"{self.base}/issue/{issue_id}/comment",
            self.headers,
            {"body": payload_body},
        )
        cid = str((created or {}).get("id", ""))
        return CommentRecord(id=cid, body=body, created_at=str((created or {}).get("created", "")), markers=list(markers or []))

    def set_labels(self, issue_id: str, labels: list[str], *, if_match: str | None = None) -> Any:
        return self.update(issue_id, labels=labels, if_match=if_match, allow_locked=True)

    def lock(self, issue_id: str, *, if_match: str | None = None) -> Any:
        from issues_lib import IssueRevisionConflict
        from planning_canonical import FROZEN_LABEL

        record = self._get_issue(issue_id)
        if if_match and record.etag != if_match:
            raise IssueRevisionConflict("revision-conflict", expected=if_match, actual=record.etag)
        if FROZEN_LABEL not in record.labels:
            labels = sorted(set(record.labels) | {FROZEN_LABEL})
            return self.update(issue_id, labels=labels, if_match=record.etag, allow_locked=True)
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
        clauses = [f'project = "{_jql_escape(project_key)}"']
        clauses.append(f'labels = "sw:project:{_jql_escape(project_key)}"')
        clauses.append(f'labels != "{_jql_escape(SOURCE_REMOVED_LABEL)}"')
        if artifact_type:
            clauses.append(f'labels = "{_jql_escape(type_label(artifact_type))}"')
        if unit_id:
            clauses.append(f'description ~ "sw-unit-id: {_jql_escape(unit_id)}"')
        if labels:
            for label in labels:
                clauses.append(f'labels = "{_jql_escape(label)}"')
        jql = " AND ".join(clauses) + " ORDER BY created ASC"
        search_fields = ["summary", "description", "labels", "status", "comment", "updated"]
        issues: list[dict[str, Any]] = []
        if self.flavor == "dc":
            start_at = 0
            while True:
                url = (
                    f"{self.base}/search?jql={jql.replace(' ', '%20')}"
                    f"&startAt={start_at}&maxResults={SEARCH_PAGE_SIZE}"
                )
                payload = self._http_json("GET", url, self.headers) or {}
                batch = payload.get("issues") or []
                if not isinstance(batch, list):
                    break
                issues.extend(item for item in batch if isinstance(item, dict))
                total = int(payload.get("total") or 0)
                if start_at + len(batch) >= total or not batch:
                    break
                start_at += len(batch)
        else:
            next_page_token: str | None = None
            while True:
                body: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": SEARCH_PAGE_SIZE,
                    "fields": search_fields,
                }
                if next_page_token:
                    body["nextPageToken"] = next_page_token
                payload = self._http_json("POST", f"{self.base}/search/jql", self.headers, body) or {}
                batch = payload.get("issues") or []
                if not isinstance(batch, list):
                    break
                issues.extend(item for item in batch if isinstance(item, dict))
                if payload.get("isLast", True) or not batch:
                    break
                next_page_token = payload.get("nextPageToken")
                if not isinstance(next_page_token, str) or not next_page_token.strip():
                    break
                next_page_token = next_page_token.strip()
        out: list[Any] = []
        for item in issues:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if key and not item.get("fields"):
                out.append(self._get_issue(key))
            else:
                out.append(_record_from_issue(item, flavor=self.flavor))
        if unit_id:
            out = [r for r in out if r.unit_id == unit_id]
        if artifact_type:
            out = [r for r in out if r.artifact_type == artifact_type]
        out.sort(key=lambda r: r.number)
        return out

    def _transition(self, issue_id: str, category: str) -> None:
        meta = self._http_json("GET", f"{self.base}/issue/{issue_id}/transitions", self.headers)
        transitions = (meta or {}).get("transitions") or []
        target_id: str | None = None
        for tr in transitions:
            if not isinstance(tr, dict):
                continue
            to = tr.get("to") if isinstance(tr.get("to"), dict) else {}
            cat = to.get("statusCategory") if isinstance(to.get("statusCategory"), dict) else {}
            if str(cat.get("key", "")).lower() == category:
                target_id = str(tr.get("id", ""))
                break
        if not target_id and transitions:
            target_id = str(transitions[0].get("id", ""))
        if target_id:
            self._http_json(
                "POST",
                f"{self.base}/issue/{issue_id}/transitions",
                self.headers,
                {"transition": {"id": target_id}},
            )

    def _transition_close(self, issue_id: str) -> None:
        self._transition(issue_id, "done")

    def _transition_open(self, issue_id: str) -> None:
        self._transition(issue_id, "new")

    def mark_tombstone(self, issue_id: str) -> None:
        """Remove migrated issue from active Jira discovery (DELETE, or label fallback)."""
        url = f"{self.base}/issue/{issue_id}"
        hdrs = {**self.headers, "User-Agent": "shipwright-jira-client"}
        status, _hdrs, body = issues_http.http_request(
            "DELETE",
            url,
            hdrs,
            root=self.root,
            issues_provider="jira",
        )
        if status in {404, 410}:
            return
        if status in {401, 403, 405}:
            self._mark_tombstone_degraded(issue_id)
            return
        if status >= 400:
            raise RuntimeError(f"Jira HTTP {status}: {body[:300]}")

    def _mark_tombstone_degraded(self, issue_id: str) -> None:
        """When DELETE is unavailable, exclude from search via label + close."""
        record = self._get_issue(issue_id)
        labels = sorted(set(record.labels) | {SOURCE_REMOVED_LABEL})
        self.update(issue_id, labels=labels, state="closed", if_match=record.etag, allow_locked=True)
        self.add_comment(
            issue_id,
            "<!-- lifecycle:source-removed -->\nIssue content migrated to in-repo files.",
            markers=["lifecycle:source-removed"],
        )
