#!/usr/bin/env python3
"""Live GitHub Issues REST client for PRD 043 issue-store CRUD."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import issues_http
from host_lib import (
    github_api_base,
    host_section,
    load_workflow_config,
)
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

SEARCH_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 10
ISSUE_NUMBER_RE = re.compile(r"(\d+)$")
SUB_ISSUE_API_VERSION = "2026-03-10"
NATIVE_LINK_MARKER = re.compile(r"<!--\s*sw-native-link:([^:\s]+):(\d+)\s*-->")
_NATIVE_LINKS_DEGRADED_EMITTED = False


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
    return raw.strip() if isinstance(raw, str) and raw.strip() else "ISSUES_GITHUB_TOKEN"


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


def _github_headers(token: str, cfg: dict[str, Any], *, api_version: str = "2022-11-28") -> dict[str, str]:
    del cfg
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": api_version,
        "User-Agent": "shipwright-github-issues-client",
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
    out: list[str] = []
    for item in labels:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            out.append(item["name"])
        elif isinstance(item, str):
            out.append(item)
    return out


def _parse_comment(raw: dict[str, Any]) -> CommentRecord:
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

    body = str(payload.get("body") or "")
    labels = _label_names(payload)
    state_raw = str(payload.get("state") or "open").lower()
    state = "closed" if state_raw == "closed" else "open"
    number = int(payload.get("number") or 0)
    updated = str(payload.get("updated_at") or "")
    title = str(payload.get("title") or "")
    artifact_type = parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
    unit_id = parse_body_marker(body, MARKER_UNIT_ID) or ""
    locked = bool(payload.get("locked")) or FROZEN_LABEL in labels
    resolved_links = list(native_links if native_links is not None else _native_links_from_comments(comments or []))
    record = IssueRecord(
        id=str(number),
        number=number,
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


def _issue_number(issue_id: str) -> int:
    match = ISSUE_NUMBER_RE.search(issue_id.strip())
    if not match:
        raise ValueError(f"invalid GitHub issue id: {issue_id}")
    return int(match.group(1))


class GitHubIssuesClient:
    """Live GitHub Issues REST adapter (store location from planning.store.storeLocation)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cfg = load_workflow_config(root)
        self.owner, self.repo = _resolve_repo_target(root, self.cfg)
        token = os.environ.get(_token_env(self.cfg), "").strip()
        if not token:
            raise RuntimeError(f"missing GitHub issues token env {_token_env(self.cfg)}")
        self._token = token
        self.headers = _github_headers(token, self.cfg)
        self.api_base = github_api_base(host_section(self.cfg))
        store = _store_section(self.cfg)
        raw_key = store.get("projectKey")
        self.project_key = raw_key.strip() if isinstance(raw_key, str) else ""
        self._native_links_capable_cache: bool | None = None

    def _sub_issue_headers(self) -> dict[str, str]:
        return _github_headers(self._token, self.cfg, api_version=SUB_ISSUE_API_VERSION)

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
                issues_provider="github-issues",
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
            issues_provider="github-issues",
        )

    def _http_empty(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        *,
        allow_404: bool = False,
    ) -> None:
        issues_http.http_empty(
            method,
            url,
            headers,
            payload,
            root=self.root,
            issues_provider="github-issues",
            allow_404=allow_404,
        )

    def _issue_url(self, issue_number: int, suffix: str = "") -> str:
        base = f"{self.api_base}/repos/{self.owner}/{self.repo}/issues/{issue_number}"
        return f"{base}{suffix}"

    def _list_comments(self, issue_number: int) -> list[CommentRecord]:
        payload = self._http_json("GET", self._issue_url(issue_number, "/comments"), self.headers)
        if not isinstance(payload, list):
            return []
        return [_parse_comment(item) for item in payload if isinstance(item, dict)]

    def _read_parent_issue_number(self, issue_number: int) -> str | None:
        if not self._native_links_capable():
            return None
        payload = self._http_json(
            "GET",
            self._issue_url(issue_number, "/parent"),
            self._sub_issue_headers(),
            allow_404=True,
        )
        if not isinstance(payload, dict):
            return None
        parent_number = payload.get("number")
        if parent_number is None:
            return None
        return str(parent_number)

    def _read_native_links(self, issue_number: int, comments: list[CommentRecord]) -> list[dict[str, Any]]:
        links = _native_links_from_comments(comments)
        parent = self._read_parent_issue_number(issue_number)
        if parent:
            entry = {"type": "sub-issue-of", "target": parent}
            if entry not in links:
                links.append(entry)
        return links

    def _add_sub_issue_link(self, parent_number: int, child_db_id: int) -> bool:
        try:
            self._http_json(
                "POST",
                self._issue_url(parent_number, "/sub_issues"),
                self._sub_issue_headers(),
                {"sub_issue_id": child_db_id},
            )
            return True
        except RuntimeError as exc:
            message = str(exc)
            if "HTTP 403" in message or "HTTP 404" in message:
                self._native_links_capable_cache = False
                _emit_native_links_degraded()
                return False
            raise

    def _add_cross_reference_link(self, issue_number: int, link_type: str, target: str) -> None:
        body = _cross_reference_body(link_type, target)
        existing = self._list_comments(issue_number)
        marker = f"<!-- sw-native-link:{link_type}:{target} -->"
        if any(marker in comment.body for comment in existing):
            return
        self._http_json(
            "POST",
            self._issue_url(issue_number, "/comments"),
            self.headers,
            {"body": body},
        )

    def _sync_native_links(
        self,
        issue_number: int,
        issue_db_id: int,
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
            if link_type == "sub-issue-of" and self._native_links_capable():
                parent_number = _issue_number(target)
                if self._add_sub_issue_link(parent_number, issue_db_id):
                    continue
            self._add_cross_reference_link(issue_number, link_type, target)

    def _get_issue(self, issue_id: str) -> Any:
        number = _issue_number(issue_id)
        payload = self._http_json("GET", self._issue_url(number), self.headers)
        if not isinstance(payload, dict):
            from issues_lib import IssueNotFound

            raise IssueNotFound(f"issue not found: {issue_id}")
        comments = self._list_comments(number)
        native_links = self._read_native_links(number, comments)
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
            f"{self.api_base}/repos/{self.owner}/{self.repo}/issues",
            self.headers,
            {"title": title, "body": body, "labels": merged_labels},
        )
        if not isinstance(created, dict) or not created.get("number"):
            raise RuntimeError("GitHub issue-create returned no number")
        number = int(created["number"])
        db_id = int(created.get("id") or 0)
        if native_links and db_id:
            self._sync_native_links(number, db_id, native_links)
        return self._get_issue(str(number))

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
        number = _issue_number(issue_id)
        payload = self._http_json("GET", self._issue_url(number), self.headers)
        db_id = int(payload.get("id") or 0) if isinstance(payload, dict) else 0
        if db_id:
            self._sync_native_links(number, db_id, native_links, current=current.native_links)
        return self._get_issue(issue_id)

    def _sync_labels(self, issue_number: int, want: list[str], *, current: list[str]) -> None:
        want_set = set(want)
        have_set = set(current)
        for name in sorted(have_set - want_set):
            self._http_empty(
                "DELETE",
                self._issue_url(issue_number, f"/labels/{quote(name, safe='')}"),
                self.headers,
            )
        add = sorted(want_set - have_set)
        if add:
            self._http_json("POST", self._issue_url(issue_number, "/labels"), self.headers, add)

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
        number = _issue_number(issue_id)
        patch: dict[str, Any] = {}
        if title is not None:
            patch["title"] = title
        if body is not None:
            patch["body"] = body
        if state is not None:
            patch["state"] = "closed" if state == "closed" else "open"
        if patch:
            self._http_json("PATCH", self._issue_url(number), self.headers, patch)
        if labels is not None:
            self._sync_labels(number, sorted(set(labels)), current=current.labels)
        if native_links is not None:
            payload = self._http_json("GET", self._issue_url(number), self.headers)
            db_id = int(payload.get("id") or 0) if isinstance(payload, dict) else 0
            if db_id:
                self._sync_native_links(number, db_id, native_links, current=current.native_links)
        return self._get_issue(issue_id)

    def add_comment(self, issue_id: str, body: str, *, markers: list[str] | None = None) -> CommentRecord:
        number = _issue_number(issue_id)
        created = self._http_json("POST", self._issue_url(number, "/comments"), self.headers, {"body": body})
        if not isinstance(created, dict):
            raise RuntimeError("GitHub issue-comment returned no payload")
        comment = _parse_comment(created)
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
        number = _issue_number(issue_id)
        if not record.locked:
            self._http_empty(
                "PUT",
                self._issue_url(number, "/lock"),
                self.headers,
                {"lock_reason": "resolved"},
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
        clauses = [
            f"repo:{self.owner}/{self.repo}",
            "is:issue",
            f'label:"{project_label(project_key)}"',
            f'-label:"{SOURCE_REMOVED_LABEL}"',
        ]
        if artifact_type:
            clauses.append(f'label:"{type_label(artifact_type)}"')
        if labels:
            for label in labels:
                clauses.append(f'label:"{label}"')
        query = " ".join(clauses)
        per_page = _search_page_size()
        max_pages = _search_max_pages()
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            url = (
                f"{self.api_base}/search/issues?q={quote(query)}"
                f"&per_page={per_page}&page={page}"
            )
            payload = self._http_json("GET", url, self.headers)
            if not isinstance(payload, dict):
                break
            batch = payload.get("items")
            if not isinstance(batch, list) or not batch:
                break
            items.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < per_page:
                break
        out: list[Any] = []
        for item in items:
            number = int(item.get("number") or 0)
            if not number:
                continue
            body = str(item.get("body") or "")
            parsed_unit = parse_body_marker(body, MARKER_UNIT_ID) or ""
            parsed_type = parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
            if unit_id and parsed_unit != unit_id:
                if not body:
                    record = self._get_issue(str(number))
                    if record.unit_id != unit_id:
                        continue
                    out.append(record)
                    continue
                continue
            if artifact_type and parsed_type != artifact_type:
                continue
            if unit_id or not body:
                out.append(self._get_issue(str(number)))
            else:
                out.append(_record_from_issue(item, project_key=project_key))
        out.sort(key=lambda r: r.number)
        return out

    def mark_tombstone(self, issue_id: str) -> None:
        """Exclude migrated issue from search (GitHub has no issue DELETE REST API)."""
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
