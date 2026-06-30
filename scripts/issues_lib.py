#!/usr/bin/env python3
"""PRD 043 — REST-primary issues provider abstraction with hermetic fixture backend."""

from __future__ import annotations

import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

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

DEFAULT_CALL_BUDGET = 500
MAX_BACKOFF_ATTEMPTS = 4
BASE_BACKOFF_SECONDS = 0.05

T = TypeVar("T")


class IssueRevisionConflict(Exception):
    def __init__(self, message: str, *, expected: str | None = None, actual: str | None = None) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class IssueNotFound(Exception):
    pass


class IssueTombstone(IssueNotFound):
    """Issue deleted or 410 tombstone (R40)."""


class IssueTransferred(Exception):
    """Issue transferred to another project (R40)."""


class IssueCapabilityError(Exception):
    pass


class IssueBudgetExhausted(Exception):
    """Per-run API call budget exhausted (R39)."""


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
    tombstoned: bool = False
    transferred: bool = False

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
            "tombstoned": self.tombstoned,
            "transferred": self.transferred,
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
            tombstoned=bool(data.get("tombstoned")),
            transferred=bool(data.get("transferred")),
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

    def _resolve_get(self, issue_id: str) -> IssueRecord:
        record = self._issues.get(issue_id)
        if record is None:
            raise IssueNotFound(f"issue not found: {issue_id}")
        if record.transferred:
            raise IssueTransferred(f"issue transferred: {issue_id}")
        if record.tombstoned:
            raise IssueTombstone(f"issue tombstoned: {issue_id}")
        return record

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
        return self._resolve_get(issue_id)

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
    ) -> IssueRecord:
        record = self._resolve_get(issue_id)
        if if_match and record.etag != if_match:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected=if_match,
                actual=record.etag,
            )
        if record.locked and not allow_locked:
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
        record = self._resolve_get(issue_id)
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
        return self.update(issue_id, labels=labels, if_match=if_match, allow_locked=True)

    def lock(self, issue_id: str, *, if_match: str | None = None) -> IssueRecord:
        record = self._resolve_get(issue_id)
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
            if record.tombstoned or record.transferred:
                continue
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

    def mark_tombstone(self, issue_id: str) -> None:
        record = self._issues.get(issue_id)
        if record is None:
            raise IssueNotFound(f"issue not found: {issue_id}")
        record.tombstoned = True
        self._persist()

    def mark_transferred(self, issue_id: str) -> None:
        record = self._issues.get(issue_id)
        if record is None:
            raise IssueNotFound(f"issue not found: {issue_id}")
        record.transferred = True
        self._persist()

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


def resolve_call_budget() -> int:
    raw = os.environ.get("SW_ISSUES_CALL_BUDGET", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return DEFAULT_CALL_BUDGET


class IssuesClient:
    """Selector-facing issues client; fixture mode when SW_ISSUES_FIXTURE=1."""

    def __init__(self, root: Path, provider: str) -> None:
        self.root = root
        self.provider = provider
        self._fixture = get_fixture_store(root) if use_fixture_mode() else None
        self._call_count = 0
        self._budget = resolve_call_budget()

    def _charge_budget(self) -> None:
        if self._call_count >= self._budget:
            raise IssueBudgetExhausted("deliver-aborted-inconsistent: issue API call budget exhausted")
        self._call_count += 1

    def _with_resilience(self, verb: str, fn: Callable[[], T]) -> T:
        last_exc: Exception | None = None
        for attempt in range(MAX_BACKOFF_ATTEMPTS):
            self._charge_budget()
            try:
                return fn()
            except (IssueRevisionConflict, IssueNotFound, IssueTombstone, IssueTransferred, IssueBudgetExhausted):
                raise
            except IssueCapabilityError as exc:
                last_exc = exc
                if attempt + 1 >= MAX_BACKOFF_ATTEMPTS:
                    raise
            except Exception as exc:
                last_exc = exc
                if attempt + 1 >= MAX_BACKOFF_ATTEMPTS:
                    raise
            delay = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, BASE_BACKOFF_SECONDS)
            time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise IssueCapabilityError(f"{verb} failed after retries")

    def _require_fixture(self) -> FixtureIssuesStore:
        if self._fixture is None:
            raise IssueCapabilityError(
                f"live {self.provider} API not available without SW_ISSUES_FIXTURE=1 in CI"
            )
        return self._fixture

    def issue_create(self, **kwargs: Any) -> IssueRecord:
        return self._with_resilience("issue-create", lambda: self._require_fixture().create(**kwargs))

    def issue_get(self, issue_id: str) -> IssueRecord:
        return self._with_resilience("issue-get", lambda: self._require_fixture().get(issue_id))

    def issue_update(self, issue_id: str, **kwargs: Any) -> IssueRecord:
        return self._with_resilience("issue-update", lambda: self._require_fixture().update(issue_id, **kwargs))

    def issue_comment(self, issue_id: str, body: str, *, markers: list[str] | None = None) -> CommentRecord:
        return self._with_resilience("issue-comment", lambda: self._require_fixture().add_comment(issue_id, body, markers=markers))

    def issue_label(self, issue_id: str, labels: list[str], *, if_match: str | None = None) -> IssueRecord:
        return self._with_resilience("issue-label", lambda: self._require_fixture().set_labels(issue_id, labels, if_match=if_match))

    def issue_lock(self, issue_id: str, *, if_match: str | None = None) -> IssueRecord:
        return self._with_resilience("issue-lock", lambda: self._require_fixture().lock(issue_id, if_match=if_match))

    def issue_search(self, **kwargs: Any) -> list[IssueRecord]:
        return self._with_resilience("issue-search", lambda: self._require_fixture().search(**kwargs))

    def mark_tombstone(self, issue_id: str) -> None:
        self._with_resilience("issue-tombstone", lambda: self._require_fixture().mark_tombstone(issue_id))

    def mark_transferred(self, issue_id: str) -> None:
        self._with_resilience("issue-transfer", lambda: self._require_fixture().mark_transferred(issue_id))
