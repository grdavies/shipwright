#!/usr/bin/env python3
"""PRD 043 — REST-primary issues provider abstraction with hermetic fixture backend."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planning_canonical import CommentRecord, compute_etag

ISSUE_VERBS = frozenset({
    "issue-create",
    "issue-get",
    "issue-update",
    "issue-comment",
    "issue-label",
    "issue-lock",
    "issue-search",
})


class IssueRevisionConflict(Exception):
    def __init__(self, message: str, *, expected: str | None = None, actual: str | None = None) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class IssueNotFound(Exception):
    pass


class IssueCapabilityError(Exception):
    pass


@dataclass
class IssueRecord:
    id: str
    number: int
    title: str
    body: str
    state: str
    labels: list[str]
    comments: list[CommentRecord] = field(default_factory=list)
    native_links: list[dict[str, Any]] = field(default_factory=list)
    locked: bool = False
    updated_at: str = ""
    etag: str = ""
    project_key: str = ""
    artifact_type: str = ""
    unit_id: str = ""

    def touch(self) -> None:
        self.updated_at = str(int(time.time()))
        self.etag = compute_etag(self.updated_at, self.body, self.title, self.labels)

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "state": self.state,
            "labels": list(self.labels),
            "comments": [
                {"id": c.id, "body": c.body, "created_at": c.created_at, "markers": c.markers}
                for c in self.comments
            ],
            "native_links": list(self.native_links),
            "locked": self.locked,
            "updated_at": self.updated_at,
            "etag": self.etag,
            "project_key": self.project_key,
            "artifact_type": self.artifact_type,
            "unit_id": self.unit_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueRecord:
        comments = []
        for raw in data.get("comments") or []:
            if not isinstance(raw, dict):
                continue
            comments.append(
                CommentRecord(
                    id=str(raw.get("id", "")),
                    body=str(raw.get("body", "")),
                    created_at=str(raw.get("created_at", "")),
                    markers=list(raw.get("markers") or []),
                )
            )
        return cls(
            id=str(data.get("id", "")),
            number=int(data.get("number", 0)),
            title=str(data.get("title", "")),
            body=str(data.get("body", "")),
            state=str(data.get("state", "open")),
            labels=[str(x) for x in (data.get("labels") or [])],
            comments=comments,
            native_links=list(data.get("native_links") or []),
            locked=bool(data.get("locked")),
            updated_at=str(data.get("updated_at", "")),
            etag=str(data.get("etag", "")),
            project_key=str(data.get("project_key", "")),
            artifact_type=str(data.get("artifact_type", "")),
            unit_id=str(data.get("unit_id", "")),
        )


class FixtureIssuesStore:
    """In-memory issue store for hermetic fixtures (no network)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._issues: dict[str, IssueRecord] = {}
        self._counter = 0
        if path and path.is_file():
            self._load()

    def _load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        self._counter = int(data.get("counter", 0))
        issues = data.get("issues")
        if isinstance(issues, dict):
            for key, raw in issues.items():
                if isinstance(raw, dict):
                    self._issues[key] = IssueRecord.from_dict(raw)

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "counter": self._counter,
            "issues": {k: v.to_snapshot_dict() for k, v in self._issues.items()},
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

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
    ) -> IssueRecord:
        self._counter += 1
        issue_id = str(uuid.uuid4())
        record = IssueRecord(
            id=issue_id,
            number=self._counter,
            title=title,
            body=body,
            state="open",
            labels=sorted(set(labels)),
            native_links=list(native_links or []),
            project_key=project_key,
            artifact_type=artifact_type,
            unit_id=unit_id,
        )
        record.touch()
        self._issues[issue_id] = record
        self._persist()
        return record

    def get(self, issue_id: str) -> IssueRecord:
        record = self._issues.get(issue_id)
        if record is None:
            raise IssueNotFound(f"issue not found: {issue_id}")
        return record

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
    ) -> IssueRecord:
        record = self.get(issue_id)
        if if_match and record.etag != if_match:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected=if_match,
                actual=record.etag,
            )
        if record.locked:
            raise IssueRevisionConflict("issue-locked")
        if title is not None:
            record.title = title
        if body is not None:
            record.body = body
        if state is not None:
            record.state = state
        if labels is not None:
            record.labels = sorted(set(labels))
        if native_links is not None:
            record.native_links = list(native_links)
        record.touch()
        self._persist()
        return record

    def add_comment(self, issue_id: str, body: str, *, markers: list[str] | None = None) -> CommentRecord:
        record = self.get(issue_id)
        comment = CommentRecord(
            id=f"comment-{len(record.comments)}",
            body=body,
            created_at=str(int(time.time())),
            markers=list(markers or []),
        )
        record.comments.append(comment)
        record.touch()
        self._persist()
        return comment

    def set_labels(self, issue_id: str, labels: list[str], *, if_match: str | None = None) -> IssueRecord:
        return self.update(issue_id, labels=labels, if_match=if_match)

    def lock(self, issue_id: str, *, if_match: str | None = None) -> IssueRecord:
        record = self.get(issue_id)
        if if_match and record.etag != if_match:
            raise IssueRevisionConflict("revision-conflict", expected=if_match, actual=record.etag)
        record.locked = True
        record.touch()
        self._persist()
        return record

    def search(
        self,
        *,
        project_key: str,
        artifact_type: str | None = None,
        unit_id: str | None = None,
        labels: list[str] | None = None,
    ) -> list[IssueRecord]:
        out: list[IssueRecord] = []
        for record in self._issues.values():
            if record.project_key != project_key:
                continue
            if artifact_type and record.artifact_type != artifact_type:
                continue
            if unit_id and record.unit_id != unit_id:
                continue
            if labels:
                label_set = set(record.labels)
                if not all(label in label_set for label in labels):
                    continue
            out.append(record)
        out.sort(key=lambda r: r.number)
        return out

    def find_by_unit(self, project_key: str, unit_id: str) -> IssueRecord | None:
        matches = self.search(project_key=project_key, unit_id=unit_id)
        return matches[0] if matches else None

    def clear(self) -> None:
        self._issues.clear()
        self._counter = 0
        self._persist()


def fixture_store_path(root: Path) -> Path:
    return root / ".cursor/hooks/state/issue-store-fixture.json"


def use_fixture_mode() -> bool:
    return os.environ.get("SW_ISSUES_FIXTURE", "").strip() in {"1", "true", "yes"}


def get_fixture_store(root: Path) -> FixtureIssuesStore:
    return FixtureIssuesStore(fixture_store_path(root))


class IssuesClient:
    """Selector-facing issues client; fixture mode when SW_ISSUES_FIXTURE=1."""

    def __init__(self, root: Path, provider: str) -> None:
        self.root = root
        self.provider = provider
        self._fixture = get_fixture_store(root) if use_fixture_mode() else None

    def _require_fixture(self) -> FixtureIssuesStore:
        if self._fixture is None:
            raise IssueCapabilityError(
                f"live {self.provider} API not available without SW_ISSUES_FIXTURE=1 in CI"
            )
        return self._fixture

    def issue_create(self, **kwargs: Any) -> IssueRecord:
        return self._require_fixture().create(**kwargs)

    def issue_get(self, issue_id: str) -> IssueRecord:
        return self._require_fixture().get(issue_id)

    def issue_update(self, issue_id: str, **kwargs: Any) -> IssueRecord:
        return self._require_fixture().update(issue_id, **kwargs)

    def issue_comment(self, issue_id: str, body: str, *, markers: list[str] | None = None) -> CommentRecord:
        return self._require_fixture().add_comment(issue_id, body, markers=markers)

    def issue_label(self, issue_id: str, labels: list[str], *, if_match: str | None = None) -> IssueRecord:
        return self._require_fixture().set_labels(issue_id, labels, if_match=if_match)

    def issue_lock(self, issue_id: str, *, if_match: str | None = None) -> IssueRecord:
        return self._require_fixture().lock(issue_id, if_match=if_match)

    def issue_search(self, **kwargs: Any) -> list[IssueRecord]:
        return self._require_fixture().search(**kwargs)
