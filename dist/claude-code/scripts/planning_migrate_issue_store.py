#!/usr/bin/env python3
"""PRD 044 Phase 1 — issue-store migration engine (dry-run default, journaled)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import re

_FM_FIELD = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")


def parse_frontmatter_fields(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[3:end]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        match = _FM_FIELD.match(line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return fields


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config  # noqa: E402
from issues_lib import IssuesClient  # noqa: E402
from planning_canonical import (  # noqa: E402
    infer_artifact_type,
    normalize_body,
    reassemble_body,
    strip_markers_and_edges,
)
from planning_store import (  # noqa: E402
    InRepoPublicBackend,
    IssueStoreBackend,
    content_hash,
    issue_store_visibility_gate,
    validate_project_key,
)

JOURNAL_REL = ".cursor/hooks/state/issue-store-migration-journal.json"
DIRECTION_FILES_TO_ISSUES = "files-to-issues"
DIRECTION_ISSUES_TO_FILES = "issues-to-files"
DIRECTIONS = frozenset({DIRECTION_FILES_TO_ISSUES, DIRECTION_ISSUES_TO_FILES})

ARTIFACT_STATES = ("pending", "created", "verified", "source-removed")
SKIP_BASENAMES = frozenset(
    {
        "INDEX.md",
        "COMPLETION-LOG.md",
        "GAP-BACKLOG.md",
        "FEEDBACK-CHECKLIST.md",
    }
)
WALK_ROOTS = ("docs/planning", "docs/prds")


@dataclass(frozen=True)
class MigrationArtifact:
    source_path: str
    body_path: str
    unit_id: str
    content: str
    digest: str
    artifact_type: str
    issue_id: str | None = None


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def journal_path(root: Path) -> Path:
    return root / JOURNAL_REL


def idempotency_key(source_path: str, digest: str) -> str:
    return f"{source_path}:{digest}"


def load_journal(root: Path) -> dict[str, Any]:
    path = journal_path(root)
    if not path.is_file():
        return {"version": 1, "direction": None, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        fail("journal-corrupt", path=JOURNAL_REL)
    if not isinstance(data, dict):
        fail("journal-invalid", path=JOURNAL_REL)
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    if not isinstance(data["entries"], dict):
        fail("journal-invalid-entries", path=JOURNAL_REL)
    return data


def save_journal(root: Path, journal: dict[str, Any], *, apply: bool) -> None:
    if not apply:
        return
    path = journal_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def infer_unit_id(rel_path: str, content: str) -> str:
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            fm = parse_frontmatter_fields(content[: end + 4])
            unit = fm.get("id", "").strip()
            if unit:
                return unit
    stem = Path(rel_path).stem
    if stem.startswith("tasks-"):
        return stem[len("tasks-") :]
    return stem.replace("_", "-")


def rel_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def should_skip_file(rel: str) -> bool:
    base = Path(rel).name
    if base in SKIP_BASENAMES:
        return True
    if rel.startswith("docs/prds/_fixture-materialize/"):
        return True
    return False


def discover_file_artifacts(root: Path) -> list[MigrationArtifact]:
    artifacts: list[MigrationArtifact] = []
    for walk_root in WALK_ROOTS:
        base = root / walk_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if not path.is_file():
                continue
            rel = rel_path(root, path)
            if should_skip_file(rel):
                continue
            raw = path.read_text(encoding="utf-8")
            text = normalize_body(raw)
            unit_id = infer_unit_id(raw, raw)
            digest = content_hash(text)
            artifacts.append(
                MigrationArtifact(
                    source_path=rel,
                    body_path=rel,
                    unit_id=unit_id,
                    content=text,
                    digest=digest,
                    artifact_type=infer_artifact_type(rel),
                )
            )
    return artifacts


def issue_source_path(record_id: str) -> str:
    return f"issue:{record_id}"


def extract_issue_content(record: Any) -> str:
    full_body = reassemble_body(record.body, record.comments)
    return strip_markers_and_edges(full_body)


def body_path_from_journal(root: Path, unit_id: str) -> str | None:
    journal = load_journal(root)
    for entry in journal.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("unitId") == unit_id and entry.get("bodyPath"):
            return str(entry["bodyPath"])
    return None


def default_body_path(unit_id: str, artifact_type: str) -> str:
    if artifact_type == "brainstorm":
        return f"docs/brainstorms/{unit_id}.md"
    if artifact_type == "gap":
        return f"docs/planning/gap/{unit_id}.md"
    if artifact_type == "tasks":
        return f"docs/prds/tasks-{unit_id}.md"
    return f"docs/prds/{unit_id}/{unit_id}.md"


def discover_issue_artifacts(root: Path, cfg: dict[str, Any]) -> list[MigrationArtifact]:
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        fail(key_result.get("message") or key_result.get("error", "invalid-project-key"))
    project_key = str(key_result["projectKey"])
    store = cfg.get("planning", {}).get("store", {})
    provider = str(store.get("issuesProvider", "none"))
    client = IssuesClient(root, provider)
    records = client.issue_search(project_key=project_key)
    artifacts: list[MigrationArtifact] = []
    for record in records:
        content = extract_issue_content(record)
        digest = content_hash(content)
        artifact_type = record.artifact_type or "prd"
        body_path = body_path_from_journal(root, record.unit_id) or default_body_path(
            record.unit_id, artifact_type
        )
        src = issue_source_path(record.id)
        artifacts.append(
            MigrationArtifact(
                source_path=src,
                body_path=body_path,
                unit_id=record.unit_id,
                content=content,
                digest=digest,
                artifact_type=record.artifact_type or infer_artifact_type(body_path),
                issue_id=record.id,
            )
        )
    return artifacts


def discover_artifacts(root: Path, direction: str, cfg: dict[str, Any]) -> list[MigrationArtifact]:
    if direction == DIRECTION_FILES_TO_ISSUES:
        return discover_file_artifacts(root)
    if direction == DIRECTION_ISSUES_TO_FILES:
        return discover_issue_artifacts(root, cfg)
    fail("invalid-direction", direction=direction)


def _maybe_inject_fail(after_state: str) -> None:
    target = os.environ.get("SW_MIGRATE_INJECT_FAIL_AFTER", "").strip()
    if target and target == after_state:
        fail("injected-failure", code="inject-fail", after=after_state)


def _journal_entry(journal: dict[str, Any], artifact: MigrationArtifact) -> dict[str, Any]:
    key = idempotency_key(artifact.source_path, artifact.digest)
    entries = journal["entries"]
    raw = entries.get(key)
    if isinstance(raw, dict):
        return raw
    return {
        "state": "pending",
        "idempotencyKey": key,
        "sourcePath": artifact.source_path,
        "bodyPath": artifact.body_path,
        "unitId": artifact.unit_id,
        "contentHash": artifact.digest,
    }


def _set_entry(journal: dict[str, Any], artifact: MigrationArtifact, entry: dict[str, Any]) -> None:
    key = idempotency_key(artifact.source_path, artifact.digest)
    journal["entries"][key] = entry


def _visibility_ok(root: Path, cfg: dict[str, Any], artifact: MigrationArtifact) -> bool:
    try:
        issue_store_visibility_gate(root, cfg, artifact.unit_id, artifact.body_path, artifact.content)
    except SystemExit:
        return False
    except BaseException:
        return False
    return True


def _create_target(
    root: Path,
    cfg: dict[str, Any],
    direction: str,
    artifact: MigrationArtifact,
    file_backend: InRepoPublicBackend,
    issue_backend: IssueStoreBackend,
    *,
    apply: bool,
) -> str | None:
    if direction == DIRECTION_FILES_TO_ISSUES:
        if not _visibility_ok(root, cfg, artifact):
            return None
        if apply:
            result = issue_backend.put(artifact.unit_id, artifact.body_path, artifact.content)
            if result.verdict != "ok":
                fail("issue-create-failed", unitId=artifact.unit_id, bodyPath=artifact.body_path)
            idx_path = root / ".cursor/hooks/state/issue-store-unit-index.json"
            if idx_path.is_file():
                data = json.loads(idx_path.read_text(encoding="utf-8"))
                units = data.get("units", {})
                for _, issue_id in units.items():
                    if artifact.unit_id in str(_):
                        return str(issue_id)
            client = IssuesClient(root, str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none")))
            matches = client.issue_search(
                project_key=issue_backend.project_key,
                unit_id=artifact.unit_id,
                artifact_type=artifact.artifact_type,
            )
            if matches:
                return matches[0].id
        return "dry-run-issue"
    if apply:
        result = file_backend.put(artifact.unit_id, artifact.body_path, artifact.content)
        if result.verdict != "ok":
            fail("file-create-failed", unitId=artifact.unit_id, bodyPath=artifact.body_path)
    return artifact.body_path


def _verify_target(
    direction: str,
    artifact: MigrationArtifact,
    file_backend: InRepoPublicBackend,
    issue_backend: IssueStoreBackend,
    *,
    apply: bool,
) -> bool:
    if not apply:
        return True
    if direction == DIRECTION_FILES_TO_ISSUES:
        got = issue_backend.get(artifact.unit_id, artifact.body_path)
        if got.verdict != "ok" or got.content is None:
            return False
        return content_hash(got.content) == artifact.digest
    got = file_backend.get(artifact.unit_id, artifact.body_path)
    if got.verdict != "ok" or got.content is None:
        return False
    return content_hash(got.content) == artifact.digest


def _remove_source(
    root: Path,
    direction: str,
    artifact: MigrationArtifact,
    *,
    apply: bool,
) -> None:
    if not apply:
        return
    if direction == DIRECTION_FILES_TO_ISSUES:
        src = root / artifact.source_path
        if src.is_file():
            src.unlink()
        return
    if artifact.issue_id:
        store = cfg_issues_client(root)
        store.mark_tombstone(artifact.issue_id)


def cfg_issues_client(root: Path) -> IssuesClient:
    cfg = load_workflow_config(root)
    provider = str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none"))
    return IssuesClient(root, provider)


def process_artifact(
    root: Path,
    cfg: dict[str, Any],
    direction: str,
    artifact: MigrationArtifact,
    journal: dict[str, Any],
    file_backend: InRepoPublicBackend,
    issue_backend: IssueStoreBackend,
    *,
    apply: bool,
    plan: list[dict[str, Any]],
) -> None:
    entry = _journal_entry(journal, artifact)
    state = str(entry.get("state", "pending"))
    if state == "source-removed":
        plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "skip", "state": state})
        return

    while state != "source-removed":
        if state == "pending":
            plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "create"})
            target_ref = _create_target(
                root, cfg, direction, artifact, file_backend, issue_backend, apply=apply
            )
            if target_ref is None:
                plan.append(
                    {
                        "unitId": artifact.unit_id,
                        "sourcePath": artifact.source_path,
                        "action": "refused",
                        "reason": "visibility",
                    }
                )
                return
            entry["state"] = "created"
            entry["targetRef"] = target_ref
            _set_entry(journal, artifact, entry)
            save_journal(root, journal, apply=apply)
            _maybe_inject_fail("created")
            state = "created"
            continue

        if state == "created":
            plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "verify"})
            if not _verify_target(direction, artifact, file_backend, issue_backend, apply=apply):
                fail("verify-failed", unitId=artifact.unit_id, sourcePath=artifact.source_path)
            entry["state"] = "verified"
            _set_entry(journal, artifact, entry)
            save_journal(root, journal, apply=apply)
            _maybe_inject_fail("verified")
            state = "verified"
            continue

        if state == "verified":
            plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "remove-source"})
            _remove_source(root, direction, artifact, apply=apply)
            entry["state"] = "source-removed"
            _set_entry(journal, artifact, entry)
            save_journal(root, journal, apply=apply)
            _maybe_inject_fail("source-removed")
            state = "source-removed"
            continue

        fail("invalid-journal-state", state=state, unitId=artifact.unit_id)


def run_store_migration(root: Path, direction: str, *, apply: bool = False) -> None:
    root = root.resolve()
    if direction not in DIRECTIONS:
        fail("invalid-direction", direction=direction)
    cfg = load_workflow_config(root)
    journal = load_journal(root)
    if journal.get("direction") and journal["direction"] != direction:
        entries = journal.get("entries", {})
        incomplete = [
            key
            for key, entry in entries.items()
            if isinstance(entry, dict) and entry.get("state") != "source-removed"
        ]
        if incomplete:
            fail(
                "journal-direction-mismatch",
                journalDirection=journal["direction"],
                requested=direction,
                incomplete=incomplete,
            )
    journal["direction"] = direction

    file_backend = InRepoPublicBackend(root, cfg)
    issue_backend = IssueStoreBackend(root, cfg)

    artifacts = discover_artifacts(root, direction, cfg)
    plan: list[dict[str, Any]] = []
    for artifact in artifacts:
        process_artifact(
            root,
            cfg,
            direction,
            artifact,
            journal,
            file_backend,
            issue_backend,
            apply=apply,
            plan=plan,
        )

    emit(
        {
            "verdict": "pass",
            "mode": "apply" if apply else "dry-run",
            "direction": direction,
            "artifactCount": len(artifacts),
            "plan": plan,
            "journalPath": JOURNAL_REL,
        }
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Issue-store migration engine")
    parser.add_argument("repo_root")
    parser.add_argument("direction", choices=sorted(DIRECTIONS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run_store_migration(Path(args.repo_root), args.direction, apply=args.apply)
