#!/usr/bin/env python3
"""Live GitLab Issues REST client for PRD 043 issue-store CRUD."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import issues_http
from host_lib import gitlab_api_base, host_section, load_workflow_config, url_encode_project
from planning_canonical import (
    FROZEN_LABEL,
    MARKER_ARTIFACT_TYPE,
    MARKER_UNIT_ID,
    SOURCE_REMOVED_LABEL,
    CommentRecord,
    compute_etag,
    parse_body_marker,
    project_label,
    type_label,
)

ISSUE_IID_RE = re.compile(r"(\d+)$")
NATIVE_LINK_MARKER = re.compile(r"<!--\s*sw-native-link:([^:\s]+):(\d+)\s*-->")
_NATIVE_LINKS_DEGRADED_EMITTED = False
SEARCH_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 10

_GITLAB_LINK_TYPE_MAP: dict[str, str] = {
    "sub-issue-of": "relates_to",
    "depends-on": "is_blocked_by",
    "blocks": "blocks",
    "relates-to": "relates_to",
}
_GITLAB_LINK_TYPE_INVERSE: dict[str, str] = {
    "relates_to": "relates-to",
    "blocks": "blocks",
    "is_blocked_by": "depends-on",
}


def _store_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store")
    return store if isinstance(store, dict) else {}


def _issues_section(cfg: dict[str, Any]) -> dict[str, Any]:
    issues = _store_section(cfg).get("issues")
    return issues if isinstance(issues, dict) else {}


def _token_env(cfg: dict[str, Any]) -> str:
    issues = _issues_section(cfg)
    raw = issues.get("tokenEnv")
    return raw.strip() if isinstance(raw, str) and raw.strip() else "ISSUES_GITLAB_TOKEN"


def _resolve_repo_target(root: Path, cfg: dict[str, Any]) -> tuple[str, str]:
    from planning_store import resolve_store_location

    location = resolve_store_location(root, cfg)
    if location.get("verdict") != "ok":
        raise RuntimeError(str(location.get("error") or "unable to resolve store location"))
    owner = location.get("owner")
    repo = location.get("repo")
    if not isinstance(owner, str) or not owner.strip() or not isinstance(repo, str) or not repo.strip():
        raise RuntimeError("store location missing owner/repo")
    return owner.strip(), repo.strip()


def _search_page_size() -> int:
    raw = os.environ.get("SW_ISSUES_PAGE_SIZE", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return SEARCH_PAGE_SIZE


def _search_max_pages() -> int:
    raw = os.environ.get("SW_ISSUES_SEARCH_MAX_PAGES", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return DEFAULT_MAX_PAGES


def _gitlab_headers(token: str) -> dict[str, str]:
    return {
        "PRIVATE-TOKEN": token,
        "User-Agent": "shipwright-gitlab-issues-client",
        "Content-Type": "application/json",
    }


def _emit_native_links_degraded(message: str = "native-links-degraded") -> None:
    global _NATIVE_LINKS_DEGRADED_EMITTED
    if _NATIVE_LINKS_DEGRADED_EMITTED:
        return
    _NATIVE_LINKS_DEGRADED_EMITTED = True
    payload = {"verdict": "notice", "notice": "native-links-degraded", "message": message}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def _norm_native_links(links: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for link in links or []:
        if not isinstance(link, dict):
            continue
        link_type = str(link.get("type") or "").strip()
        target = str(link.get("target") or "").strip()
        if not link_type or not target:
            continue
        entry = {"type": link_type, "target": target}
        if entry not in out:
            out.append(entry)
    return out


def _cross_reference_body(link_type: str, target: str) -> str:
    return f"<!-- sw-native-link:{link_type}:{target} -->\nCross-reference: #{target} ({link_type})"


def _label_names(payload: dict[str, Any]) -> list[str]:
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return []
    return [str(item) for item in labels if isinstance(item, str)]


def _parse_note(raw: dict[str, Any]) -> CommentRecord:
    body = str(raw.get("body") or "")
    markers: list[str] = []
    for marker in ("sw-freeze-record", "sw-chunk-overflow", "sw-memory-pointer", "lifecycle:source-removed"):
        if f"<!-- {marker} -->" in body or f"<!--{marker}-->" in body:
            markers.append(marker)
    return CommentRecord(
        id=str(raw.get("id", "")),
        body=body,
        created_at=str(raw.get("created_at", "")),
        markers=markers,
    )


def _native_links_from_comments(comments: list[CommentRecord]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for comment in comments:
        for match in NATIVE_LINK_MARKER.finditer(comment.body):
            entry = {"type": match.group(1), "target": match.group(2)}
            if entry not in links:
                links.append(entry)
    return links


def _record_from_issue(
    payload: dict[str, Any],
    *,
    comments: list[CommentRecord] | None = None,
    project_key: str = "",
    native_links: list[dict[str, Any]] | None = None,
) -> Any:
    from issues_lib import IssueRecord

    body = str(payload.get("description") or "")
    labels = _label_names(payload)
    state_raw = str(payload.get("state") or "opened").lower()
    state = "closed" if state_raw == "closed" else "open"
    iid = int(payload.get("iid") or 0)
    updated = str(payload.get("updated_at") or "")
    title = str(payload.get("title") or "")
    artifact_type = parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
    unit_id = parse_body_marker(body, MARKER_UNIT_ID) or ""
    locked = bool(payload.get("discussion_locked")) or FROZEN_LABEL in labels
    resolved_links = list(native_links if native_links is not None else _native_links_from_comments(comments or []))
    record = IssueRecord(
        id=str(iid),
        number=iid,
        title=title,
        body=body,
        state=state,
        labels=labels,
        comments=list(comments or []),
        native_links=resolved_links,
        locked=locked,
        updated_at=updated,
        project_key=project_key,
        artifact_type=artifact_type,
        unit_id=unit_id,
    )
    record.etag = compute_etag(updated, body, title, labels)
    return record


def _issue_iid(issue_id: str) -> int:
    match = ISSUE_IID_RE.search(issue_id.strip())
    if not match:
        raise ValueError(f"invalid GitLab issue id: {issue_id}")
    return int(match.group(1))


class GitLabIssuesClient:
    """Live GitLab Issues REST adapter (store location from planning.store.storeLocation)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cfg = load_workflow_config(root)
        self.owner, self.repo = _resolve_repo_target(root, self.cfg)
        token = os.environ.get(_token_env(self.cfg), "").strip()
        if not token:
            raise RuntimeError(f"missing GitLab issues token env {_token_env(self.cfg)}")
        self._token = token
        self.headers = _gitlab_headers(token)
        self.api_base = gitlab_api_base(host_section(self.cfg))
        self.project_path = url_encode_project(self.owner, self.repo)
        store = _store_section(self.cfg)
        raw_key = store.get("projectKey")
        self.project_key = raw_key.strip() if isinstance(raw_key, str) else ""
        self._project_id: int | None = None
        self._native_links_capable_cache: bool | None = None

    def _project_url(self, suffix: str = "") -> str:
        return f"{self.api_base}/projects/{self.project_path}{suffix}"

    def _issue_url(self, issue_iid: int, suffix: str = "") -> str:
        return f"{self._project_url()}/issues/{issue_iid}{suffix}"

    def _native_links_capable(self) -> bool:
        if self._native_links_capable_cache is not None:
            return self._native_links_capable_cache
        raw = os.environ.get("SW_NATIVE_LINKS_CAPABLE", "").strip().lower()
        if raw in {"1", "true", "yes"}:
            self._native_links_capable_cache = True
            return True
        if raw in {"0", "false", "no"}:
            self._native_links_capable_cache = False
            return False
        self._native_links_capable_cache = True
        return True

    def _http_json(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | list[Any] | None = None,
        *,
        allow_404: bool = False,
    ) -> Any:
        if allow_404:
            status, _hdrs, body = issues_http.http_request(
                method,
                url,
                headers,
                payload,
                root=self.root,
                issues_provider="gitlab-issues",
            )
            if status == 404:
                return None
            if status >= 400:
                raise RuntimeError(f"HTTP {status}: {body[:300]}")
            return json.loads(body) if body.strip() else {}
        return issues_http.http_json(
            method,
            url,
            headers,
            payload,
            root=self.root,
            issues_provider="gitlab-issues",
        )

    def _resolve_project_id(self) -> int:
        if self._project_id is not None:
            return self._project_id
        payload = self._http_json("GET", self._project_url(), self.headers)
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError("GitLab project lookup returned no id")
        self._project_id = int(payload["id"])
        return self._project_id

    def _list_notes(self, issue_iid: int) -> list[CommentRecord]:
        payload = self._http_json("GET", self._issue_url(issue_iid, "/notes"), self.headers)
        if not isinstance(payload, list):
            return []
        return [_parse_note(item) for item in payload if isinstance(item, dict)]

    def _read_issue_links(self, issue_iid: int, comments: list[CommentRecord]) -> list[dict[str, Any]]:
        links = _native_links_from_comments(comments)
        if not self._native_links_capable():
            return links
        payload = self._http_json(
            "GET",
            self._issue_url(issue_iid, "/links"),
            self.headers,
            allow_404=True,
        )
        if not isinstance(payload, list):
            return links
        for item in payload:
            if not isinstance(item, dict):
                continue
            link_type = str(item.get("link_type") or "").strip()
            target_issue = item.get("target_issue") if isinstance(item.get("target_issue"), dict) else {}
            target_iid = target_issue.get("iid")
            if target_iid is None:
                continue
            native_type = _GITLAB_LINK_TYPE_INVERSE.get(link_type, link_type.replace("_", "-"))
            entry = {"type": native_type, "target": str(target_iid)}
            if entry not in links:
                links.append(entry)
        return links

    def _add_issue_link(self, issue_iid: int, link_type: str, target_iid: int) -> bool:
        gitlab_type = _GITLAB_LINK_TYPE_MAP.get(link_type, "relates_to")
        body = {
            "target_project_id": self._resolve_project_id(),
            "target_issue_iid": target_iid,
            "link_type": gitlab_type,
        }
        try:
            self._http_json("POST", self._issue_url(issue_iid, "/links"), self.headers, body)
            return True
        except RuntimeError as exc:
            message = str(exc)
            if "HTTP 403" in message or "HTTP 404" in message or "HTTP 405" in message:
                self._native_links_capable_cache = False
                _emit_native_links_degraded()
                return False
            raise

    def _add_cross_reference_link(self, issue_iid: int, link_type: str, target: str) -> None:
        body = _cross_reference_body(link_type, target)
        existing = self._list_notes(issue_iid)
        marker = f"<!-- sw-native-link:{link_type}:{target} -->"
        if any(marker in comment.body for comment in existing):
            return
        self._http_json("POST", self._issue_url(issue_iid, "/notes"), self.headers, {"body": body})

    def _sync_native_links(
        self,
        issue_iid: int,
        want: list[dict[str, Any]],
        *,
        current: list[dict[str, Any]] | None = None,
    ) -> None:
        want_norm = _norm_native_links(want)
        if not want_norm:
            return
        current_norm = _norm_native_links(current)
        for link in want_norm:
            if link in current_norm:
                continue
            link_type = str(link.get("type") or "")
            target = str(link.get("target") or "")
            if self._native_links_capable():
                target_iid = _issue_iid(target)
                if self._add_issue_link(issue_iid, link_type, target_iid):
                    continue
            self._add_cross_reference_link(issue_iid, link_type, target)

    def _get_issue(self, issue_id: str) -> Any:
        iid = _issue_iid(issue_id)
        payload = self._http_json("GET", self._issue_url(iid), self.headers)
        if not isinstance(payload, dict):
            from issues_lib import IssueNotFound

            raise IssueNotFound(f"issue not found: {issue_id}")
        comments = self._list_notes(iid)
        native_links = self._read_issue_links(iid, comments)
        return _record_from_issue(
            payload,
            comments=comments,
            project_key=self.project_key,
            native_links=native_links,
        )

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
        del artifact_type, unit_id
        merged_labels = sorted(set(labels) | {project_label(project_key)})
        created = self._http_json(
            "POST",
            self._project_url("/issues"),
            self.headers,
            {"title": title, "description": body, "labels": ",".join(merged_labels)},
        )
        if not isinstance(created, dict) or not created.get("iid"):
            raise RuntimeError("GitLab issue-create returned no iid")
        iid = int(created["iid"])
        if native_links:
            self._sync_native_links(iid, native_links)
        return self._get_issue(str(iid))

    def get(self, issue_id: str) -> Any:
        return self._get_issue(issue_id)

    def sync_native_links(
        self,
        issue_id: str,
        native_links: list[dict[str, Any]],
        *,
        if_match: str | None = None,
    ) -> Any:
        from issues_lib import IssueRevisionConflict

        current = self._get_issue(issue_id)
        if if_match and current.etag != if_match:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected=if_match,
                actual=current.etag,
            )
        iid = _issue_iid(issue_id)
        self._sync_native_links(iid, native_links, current=current.native_links)
        return self._get_issue(issue_id)

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

        current = self._get_issue(issue_id)
        if if_match and current.etag != if_match:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected=if_match,
                actual=current.etag,
            )
        if current.locked and not allow_locked:
            raise IssueRevisionConflict("issue-locked")
        iid = _issue_iid(issue_id)
        patch: dict[str, Any] = {}
        if title is not None:
            patch["title"] = title
        if body is not None:
            patch["description"] = body
        if state is not None:
            patch["state_event"] = "close" if state == "closed" else "reopen"
        if labels is not None:
            patch["labels"] = ",".join(sorted(set(labels)))
        if patch:
            self._http_json("PUT", self._issue_url(iid), self.headers, patch)
        if native_links is not None:
            self._sync_native_links(iid, native_links, current=current.native_links)
        return self._get_issue(issue_id)

    def add_comment(self, issue_id: str, body: str, *, markers: list[str] | None = None) -> CommentRecord:
        iid = _issue_iid(issue_id)
        created = self._http_json("POST", self._issue_url(iid, "/notes"), self.headers, {"body": body})
        if not isinstance(created, dict):
            raise RuntimeError("GitLab issue-comment returned no payload")
        comment = _parse_note(created)
        if markers:
            comment.markers = list(markers)
        return comment

    def set_labels(self, issue_id: str, labels: list[str], *, if_match: str | None = None) -> Any:
        return self.update(issue_id, labels=labels, if_match=if_match, allow_locked=True)

    def lock(self, issue_id: str, *, if_match: str | None = None) -> Any:
        from issues_lib import IssueRevisionConflict

        record = self._get_issue(issue_id)
        if if_match and record.etag != if_match:
            raise IssueRevisionConflict("revision-conflict", expected=if_match, actual=record.etag)
        iid = _issue_iid(issue_id)
        if not record.locked:
            self._http_json(
                "PUT",
                self._issue_url(iid),
                self.headers,
                {"discussion_locked": True},
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
        label_filters = [project_label(project_key)]
        if artifact_type:
            label_filters.append(type_label(artifact_type))
        if labels:
            label_filters.extend(labels)
        label_filters = [label for label in label_filters if label != SOURCE_REMOVED_LABEL]
        per_page = _search_page_size()
        max_pages = _search_max_pages()
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            params = f"?labels={quote(','.join(label_filters))}&per_page={per_page}&page={page}&state=all"
            if unit_id:
                params += f"&search={quote(f'sw-unit-id: {unit_id}')}"
            payload = self._http_json("GET", f"{self._project_url('/issues')}{params}", self.headers)
            if not isinstance(payload, list) or not payload:
                break
            items.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < per_page:
                break
        out: list[Any] = []
        for item in items:
            if SOURCE_REMOVED_LABEL in _label_names(item):
                continue
            iid = int(item.get("iid") or 0)
            if not iid:
                continue
            body = str(item.get("description") or "")
            parsed_unit = parse_body_marker(body, MARKER_UNIT_ID) or ""
            parsed_type = parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
            if unit_id and parsed_unit != unit_id:
                if not body:
                    record = self._get_issue(str(iid))
                    if record.unit_id != unit_id:
                        continue
                    out.append(record)
                    continue
                continue
            if artifact_type and parsed_type != artifact_type:
                continue
            if unit_id or not body:
                out.append(self._get_issue(str(iid)))
            else:
                out.append(_record_from_issue(item, project_key=project_key))
        out.sort(key=lambda r: r.number)
        return out

    def mark_tombstone(self, issue_id: str) -> None:
        """Exclude migrated issue from search (close + source-removed label)."""
        from issues_lib import IssueNotFound

        try:
            record = self._get_issue(issue_id)
        except IssueNotFound:
            return
        labels = sorted(set(record.labels) | {SOURCE_REMOVED_LABEL})
        self.update(issue_id, labels=labels, state="closed", if_match=record.etag, allow_locked=True)
        self.add_comment(
            issue_id,
            "<!-- lifecycle:source-removed -->\nIssue content migrated to in-repo files.",
            markers=["lifecycle:source-removed"],
        )
