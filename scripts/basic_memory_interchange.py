#!/usr/bin/env python3
"""Hermetic basic-memory JSONL/OKF interchange adapter (PRD 075 R29–R31).

Uses a file-backed project under ``projectPath`` so CI can round-trip without a live
Basic Memory MCP or cloud. Layout mirrors synthesized export/import semantics from
``core/providers/basic-memory.md`` (``memories/<note_type>/`` notes + ``links[]``).

Local and cloud share the same synthesis path — no second protocol (R31).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from planning_txn import PlanningTxnCoordinator

MANIFEST_NAME = "shipwright-bm-project.json"
LINKS_FILE = "links.json"
DEFAULT_MEMORIES_DIR = "memories"
DEFAULT_RULES_DIR = "rules"

# Canonical CAPABILITIES categories → note_type / folder under memories/ (R14).
CANONICAL_CATEGORIES = frozenset(
    {
        "decision",
        "learning",
        "debug",
        "design",
        "code-context",
        "playbook",
        "research",
        "discussion",
        "progress",
    }
)
RULE_CATEGORY = "rule"

RELATION_LINE_RE = re.compile(
    r"^\s*-\s*(?P<edge>[A-Za-z0-9_-]+)\s+\[\[(?P<target>[^\]]+)\]\]\s*$"
)


class InterchangeError(Exception):
    def __init__(self, message: str, *, cause: str = "error") -> None:
        super().__init__(message)
        self.cause = cause


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_in_repo_search():
    path = Path(__file__).resolve().parent / "in-repo-memory-search.py"
    spec = importlib.util.spec_from_file_location("in_repo_memory_search", path)
    if spec is None or spec.loader is None:
        raise InterchangeError("in-repo-memory-search.py not found", cause="missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project_root(project_path: Path) -> Path:
    return project_path.expanduser().resolve()


def _memories_dir(project_path: Path, memories_directory: str = DEFAULT_MEMORIES_DIR) -> Path:
    return _project_root(project_path) / memories_directory


def _rules_dir(project_path: Path, rules_directory: str = DEFAULT_RULES_DIR) -> Path:
    return _project_root(project_path) / rules_directory


def interchange_store_id(project_path: Path) -> str:
    root = _project_root(project_path).resolve()
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return f"basic-memory:{digest}"


def _links_path(project_path: Path) -> Path:
    return _project_root(project_path) / LINKS_FILE


def _manifest_path(project_path: Path) -> Path:
    return _project_root(project_path) / MANIFEST_NAME


def ensure_project(
    project_path: Path,
    *,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> Path:
    root = _project_root(project_path)
    root.mkdir(parents=True, exist_ok=True)
    _memories_dir(project_path, memories_directory).mkdir(parents=True, exist_ok=True)
    _rules_dir(project_path, rules_directory).mkdir(parents=True, exist_ok=True)
    manifest = _manifest_path(project_path)
    if not manifest.is_file():
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "createdAt": _utc_now(),
                    "adapter": "shipwright-basic-memory-interchange",
                    "memoriesDirectory": memories_directory,
                    "rulesDirectory": rules_directory,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    links = _links_path(project_path)
    if not links.is_file():
        links.write_text(json.dumps({"links": []}, indent=2) + "\n", encoding="utf-8")
    return root


def _safe_permalink(permalink: str) -> str:
    return re.sub(r"[^A-Za-z0-9._/-]+", "_", permalink).strip("/_") or "note"


def _category_folder(category: str) -> str:
    if category == RULE_CATEGORY:
        return RULE_CATEGORY
    if category in CANONICAL_CATEGORIES:
        return category
    return "learning"


def _note_relpath(category: str, identity: str) -> str:
    from memory_key_collision import identity_disk_relpath

    return identity_disk_relpath(category, identity)


def note_path(
    project_path: Path,
    category: str,
    permalink: str,
    *,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> Path:
    """Return on-disk path keyed by stable identity (permalink arg is the identity key)."""
    rel = _note_relpath(category, permalink)
    if category == RULE_CATEGORY:
        return _rules_dir(project_path, rules_directory) / Path(rel).name
    return _memories_dir(project_path, memories_directory) / rel


def load_links(project_path: Path) -> list[dict[str, str]]:
    path = _links_path(project_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    links = data.get("links") if isinstance(data, dict) else []
    if not isinstance(links, list):
        return []
    out: list[dict[str, str]] = []
    for entry in links:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("source") or entry.get("from") or "").strip()
        target = str(entry.get("target") or entry.get("to") or "").strip()
        edge = str(entry.get("edge") or entry.get("type") or "relates-to")
        if source and target:
            out.append({"source": source, "target": target, "edge": edge})
    return out


def save_links(
    project_path: Path,
    links: list[dict[str, str]],
    *,
    txn: PlanningTxnCoordinator | None = None,
) -> None:
    ensure_project(project_path)
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for link in links:
        key = (link["source"], link["target"], link["edge"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    payload = json.dumps({"links": deduped}, indent=2) + "\n"
    path = _links_path(project_path)
    root = _project_root(project_path)
    if txn is not None:
        txn.stage_write(path, payload)
        return
    from planning_paths import atomic_write_text

    atomic_write_text(path, payload, root=root, store_id=interchange_store_id(project_path))


def note_to_record(path: Path, *, category_hint: str | None = None) -> dict[str, Any] | None:
    search = _load_in_repo_search()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm, body = search.parse_frontmatter(text)
    permalink = str(fm.get("permalink") or fm.get("id") or path.stem).strip()
    if not permalink:
        return None
    note_type = str(fm.get("type") or fm.get("note_type") or category_hint or "learning").strip()
    if note_type == "note":
        note_type = category_hint or "learning"
    category = RULE_CATEGORY if note_type == RULE_CATEGORY else (
        note_type if note_type in CANONICAL_CATEGORIES else "learning"
    )
    fields = {k: v for k, v in fm.items() if k not in {"permalink", "type", "note_type"}}
    fields["category"] = category
    fields["id"] = permalink
    if "permalink" not in fields:
        fields["permalink"] = permalink
    # Strip Relations section from body for neutral interchange body; links live in fields/links.json.
    body_clean = _strip_relations_section(body)
    return {
        "id": permalink,
        "category": category,
        "fields": fields,
        "body": body_clean,
        "_path": str(path),
    }


def _strip_relations_section(body: str) -> str:
    lines = body.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if re.match(r"^##\s+Relations\s*$", line.strip()):
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).strip() + ("\n" if out else "")


def extract_body_relations(body: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    in_relations = False
    for line in body.splitlines():
        if re.match(r"^##\s+Relations\s*$", line.strip()):
            in_relations = True
            continue
        if in_relations and line.startswith("## "):
            break
        if not in_relations:
            continue
        match = RELATION_LINE_RE.match(line)
        if match:
            edge = match.group("edge").replace("_", "-")
            out.append({"target": match.group("target").strip(), "edge": edge})
    return out


def record_to_note(record: dict[str, Any]) -> dict[str, Any]:
    permalink = str(record["id"])
    category = str(record.get("category") or "learning")
    if category == RULE_CATEGORY:
        note_type = RULE_CATEGORY
    elif category in CANONICAL_CATEGORIES:
        note_type = category
    else:
        note_type = "learning"
        category = "learning"
    fields = dict(record.get("fields") or {})
    fields.pop("category", None)
    fields.pop("id", None)
    title = str(fields.pop("title", None) or permalink)
    tags = fields.pop("tags", [])
    links = fields.pop("links", None)
    frontmatter: dict[str, Any] = {
        "title": title,
        "type": note_type,
        "permalink": permalink,
    }
    if tags:
        frontmatter["tags"] = tags
    for key, value in fields.items():
        if key in {"permalink", "type", "note_type"}:
            continue
        frontmatter[key] = value
    if links:
        frontmatter["links"] = links
    return {
        "permalink": permalink,
        "category": category if category == RULE_CATEGORY else note_type,
        "frontmatter": frontmatter,
        "body": str(record.get("body") or ""),
        "links": links,
    }


def render_note(note: dict[str, Any]) -> str:
    search = _load_in_repo_search()
    fm = dict(note["frontmatter"])
    body = str(note.get("body") or "").rstrip()
    relations: list[str] = []
    links_raw = note.get("links") or fm.get("links")
    if links_raw:
        for entry in links_raw if isinstance(links_raw, list) else [links_raw]:
            parsed = search.parse_link_entry(entry)
            if not parsed:
                continue
            target, edge = parsed
            relations.append(f"- {edge.replace('-', '_')} [[{target}]]")
    if relations:
        body = (body + "\n\n## Relations\n" + "\n".join(relations)).strip() + "\n"
    elif body and not body.endswith("\n"):
        body += "\n"
    return search.render_memory_file(fm, body)


def write_note(
    project_path: Path,
    note: dict[str, Any],
    *,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
    txn: PlanningTxnCoordinator | None = None,
) -> Path:
    ensure_project(
        project_path,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    path = note_path(
        project_path,
        str(note["category"]),
        str(note["permalink"]),
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    rendered = render_note(note)
    if txn is not None:
        txn.stage_write(path, rendered)
        return path
    from planning_paths import atomic_write_text

    atomic_write_text(
        path,
        rendered,
        root=_project_root(project_path),
        store_id=interchange_store_id(project_path),
    )
    return path


def list_notes(
    project_path: Path,
    *,
    include_rules: bool = False,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    memories = _memories_dir(project_path, memories_directory)
    if memories.is_dir():
        for path in sorted(memories.rglob("*.md")):
            category_hint = path.parent.name if path.parent != memories else "learning"
            record = note_to_record(path, category_hint=category_hint)
            if record:
                records.append(record)
    if include_rules:
        rules = _rules_dir(project_path, rules_directory)
        if rules.is_dir():
            for path in sorted(rules.rglob("*.md")):
                record = note_to_record(path, category_hint=RULE_CATEGORY)
                if record:
                    records.append(record)
    return records


def list_permalinks(
    project_path: Path,
    *,
    include_rules: bool = True,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> list[str]:
    return [
        str(r["id"])
        for r in list_notes(
            project_path,
            include_rules=include_rules,
            memories_directory=memories_directory,
            rules_directory=rules_directory,
        )
    ]


def load_note(
    project_path: Path,
    permalink: str,
    *,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> dict[str, Any] | None:
    for record in list_notes(
        project_path,
        include_rules=True,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    ):
        if record["id"] == permalink:
            return record
    return None


def note_fingerprint(record: dict[str, Any]) -> str:
    import memory_fingerprint as fp

    return fp.note_fingerprint(record)


def _record_revision(record: dict[str, Any]) -> str | None:
    fields = dict(record.get("fields") or {})
    for key in ("revision", "contentHash", "content_hash"):
        value = record.get(key) if key in record else fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _record_project_id(record: dict[str, Any]) -> str | None:
    fields = dict(record.get("fields") or {})
    for key in ("projectId", "project", "sourceProject"):
        value = record.get(key) if key in record else fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _core_content(record: dict[str, Any]) -> str:
    body = str(record.get("body") or "")
    fields = dict(record.get("fields") or {})
    for key in ("content", "summary"):
        if key in record and str(record[key]).strip():
            return str(record[key]).strip()
        if key in fields and str(fields[key]).strip():
            return str(fields[key]).strip()
    # Strip timeline / compiled-truth scaffolding for interchange re-import compare.
    lines: list[str] = []
    skip = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            skip = stripped in {"## Timeline", "## Compiled truth", "## Relations"}
            continue
        if skip:
            continue
        if stripped.startswith("- `") and "@ " in stripped and " — " in stripped:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _semantic_drift(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    if note_fingerprint(existing) == note_fingerprint(incoming):
        return False
    return _core_content(existing) != _core_content(incoming)


def resolve_merge_identity(
    project_path: Path,
    existing_ids: set[str],
    imported_id: str,
    incoming: dict[str, Any],
    *,
    alias_index: dict[str, str] | None = None,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> tuple[str, bool]:
    """Resolve merge identity using stable id and alias fallbacks (R31).

    Resolution order: record id, source project + revision, content hash,
    supersedes. Suffix-counter collision families are not used.
    """
    from memory_import_resolve import extract_supersedes
    from memory_key_collision import assert_no_alias_collision

    incoming_fp = note_fingerprint(incoming)
    aliases = alias_index if alias_index is not None else {}

    if imported_id in existing_ids:
        current = load_note(
            project_path,
            imported_id,
            memories_directory=memories_directory,
            rules_directory=rules_directory,
        )
        if current and not _semantic_drift(current, incoming):
            return imported_id, False
        for target in extract_supersedes(incoming):
            if target in existing_ids:
                assert_no_alias_collision(aliases, incoming, canonical_id=imported_id)
                return imported_id, False
        raise InterchangeError(
            f"identity collision on {imported_id!r}: semantic drift without supersedes",
            cause="alias-collision",
        )

    for alias, canonical in aliases.items():
        if alias == imported_id or canonical == imported_id:
            existing = load_note(
                project_path,
                canonical,
                memories_directory=memories_directory,
                rules_directory=rules_directory,
            )
            if existing and not _semantic_drift(existing, incoming):
                return canonical, False

    project_id = _record_project_id(incoming)
    revision = _record_revision(incoming)
    if project_id and revision:
        for existing_id in existing_ids:
            current = load_note(
                project_path,
                existing_id,
                memories_directory=memories_directory,
                rules_directory=rules_directory,
            )
            if not current:
                continue
            if _record_project_id(current) == project_id and _record_revision(current) == revision:
                if not _semantic_drift(current, incoming):
                    return existing_id, False

    for existing_id in existing_ids:
        current = load_note(
            project_path,
            existing_id,
            memories_directory=memories_directory,
            rules_directory=rules_directory,
        )
        if current and not _semantic_drift(current, incoming):
            return existing_id, False

    for target in extract_supersedes(incoming):
        if target in existing_ids:
            assert_no_alias_collision(aliases, incoming, canonical_id=imported_id)
            return imported_id, False

    assert_no_alias_collision(aliases, incoming, canonical_id=imported_id)
    return imported_id, False


def extract_record_links(record: dict[str, Any]) -> list[dict[str, str]]:
    search = _load_in_repo_search()
    fields = dict(record.get("fields") or {})
    source = str(record["id"])
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_link(target: str, edge: str) -> None:
        key = (target, edge)
        if key in seen:
            return
        seen.add(key)
        out.append({"source": source, "target": target, "edge": edge})

    links_raw = fields.get("links")
    if links_raw is None and "links" in record:
        links_raw = record.get("links")
    for entry in _normalize_link_entries(links_raw):
        parsed = search.parse_link_entry(entry)
        if parsed:
            add_link(parsed[0], parsed[1])

    body = str(record.get("body") or fields.get("content") or "")
    for target, edge in search.extract_inline_links(body):
        add_link(target, edge)
    for rel in extract_body_relations(body):
        add_link(rel["target"], rel["edge"])
    return out


def _normalize_link_entries(links_raw: Any) -> list[Any]:
    if not links_raw:
        return []
    if isinstance(links_raw, list):
        if links_raw and all(isinstance(item, str) for item in links_raw):
            joined = ", ".join(links_raw)
            if joined.startswith("{") or joined.startswith("["):
                try:
                    parsed = json.loads(joined)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    return [parsed]
                if isinstance(parsed, list):
                    return parsed
        return links_raw
    if isinstance(links_raw, str):
        text = links_raw.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return [links_raw]
            if isinstance(parsed, dict):
                return [parsed]
            if isinstance(parsed, list):
                return parsed
        return [links_raw]
    return [links_raw]


def parse_interchange_records(fmt: str, source: Path) -> list[dict[str, Any]]:
    search = _load_in_repo_search()
    imported: list[dict[str, Any]] = []
    if fmt == "jsonl":
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InterchangeError(f"jsonl line {line_no}: {exc}", cause="malformed") from exc
            if not isinstance(obj, dict):
                raise InterchangeError(f"jsonl line {line_no}: expected object", cause="malformed")
            imported.append(search.jsonl_to_record(obj))
        return imported
    if fmt == "okf":
        for path in sorted(source.rglob("*.md")):
            if path.name in search.RESERVED_OKF_NAMES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            fm, body = search.parse_frontmatter(text)
            if not fm.get("type") and not fm.get("category"):
                continue
            imported.append(search.okf_fields_to_record(fm, body))
        return imported
    raise InterchangeError(f"unsupported format: {fmt}", cause="unsupported")


def export_project(
    project_path: Path,
    fmt: str,
    out: Path,
    *,
    include_rules: bool = False,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> dict[str, Any]:
    ensure_project(
        project_path,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    records = list_notes(
        project_path,
        include_rules=include_rules,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    kg_links = load_links(project_path)
    link_by_source: dict[str, list[dict[str, str]]] = {}
    for link in kg_links:
        link_by_source.setdefault(link["source"], []).append(
            {"to": link["target"], "edge": link["edge"]}
        )
    for record in records:
        fields = record.setdefault("fields", {})
        merged = list(fields.get("links") or [])
        for link in link_by_source.get(record["id"], []):
            if link not in merged:
                merged.append(link)
        if merged:
            fields["links"] = merged

    search = _load_in_repo_search()
    if fmt == "jsonl":
        lines = [json.dumps(search.record_to_jsonl(record), sort_keys=True) for record in records]
        payload = "\n".join(lines) + ("\n" if lines else "")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        return {"provider": "basic-memory", "format": "jsonl", "out": str(out), "count": len(records)}
    if fmt == "okf":
        out.mkdir(parents=True, exist_ok=True)
        for record in records:
            category = record["category"]
            category_dir = out / category
            category_dir.mkdir(parents=True, exist_ok=True)
            fields = search.record_to_okf_fields(record)
            body = search.redact_text(record["body"])
            target = category_dir / f"{record['id']}.md"
            target.write_text(search.render_memory_file(fields, body), encoding="utf-8")
        (out / "index.md").write_text(search.render_store_index(records, okf_bundle_root=True), encoding="utf-8")
        (out / "log.md").write_text(search.render_store_log(records), encoding="utf-8")
        return {"provider": "basic-memory", "format": "okf", "out": str(out), "count": len(records)}
    raise InterchangeError(f"unsupported export format: {fmt}", cause="unsupported")


def import_project(
    project_path: Path,
    fmt: str,
    source: Path,
    *,
    dry_run: bool,
    include_rules: bool = False,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> dict[str, Any]:
    from memory_import_resolve import ImportResolveError, two_pass_import_resolve
    from memory_key_collision import KeyCollisionError, build_alias_index

    raw_records = parse_interchange_records(fmt, source)
    try:
        records, registry = two_pass_import_resolve(raw_records)
    except ImportResolveError as exc:
        raise InterchangeError(str(exc), cause=exc.cause) from exc
    ensure_project(
        project_path,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    existing_ids = set(
        list_permalinks(
            project_path,
            include_rules=True,
            memories_directory=memories_directory,
            rules_directory=rules_directory,
        )
    )
    alias_index = build_alias_index(
        list_notes(
            project_path,
            include_rules=True,
            memories_directory=memories_directory,
            rules_directory=rules_directory,
        )
    )
    id_map: dict[str, str] = {}
    remapped: list[dict[str, str]] = []
    incoming_links: list[dict[str, str]] = []
    imported_count = 0

    def _process_record(record: dict[str, Any]) -> None:
        nonlocal imported_count
        category = str(record.get("category") or "learning")
        if category == RULE_CATEGORY and not include_rules:
            return
        note = record_to_note(record)
        original_id = str(record["id"])
        try:
            final_id, was_remapped = resolve_merge_identity(
                project_path,
                existing_ids | set(id_map.values()),
                original_id,
                {**record, "id": original_id},
                alias_index=alias_index,
                memories_directory=memories_directory,
                rules_directory=rules_directory,
            )
        except KeyCollisionError as exc:
            raise InterchangeError(str(exc), cause=exc.cause) from exc
        if was_remapped:
            remapped.append({"from": original_id, "to": final_id})
        id_map[original_id] = final_id
        note["permalink"] = final_id
        note["frontmatter"]["permalink"] = final_id
        existing_ids.add(final_id)
        imported_count += 1
        for link in extract_record_links({**record, "id": original_id}):
            incoming_links.append(
                {
                    "source": id_map.get(link["source"], link["source"]),
                    "target": id_map.get(link["target"], link["target"]),
                    "edge": link["edge"],
                }
            )

    if not dry_run:
        from planning_txn import planning_transaction

        root = _project_root(project_path)
        with planning_transaction(root, interchange_store_id(project_path)) as txn:
            for record in records:
                category = str(record.get("category") or "learning")
                if category == RULE_CATEGORY and not include_rules:
                    continue
                note = record_to_note(record)
                original_id = str(record["id"])
                try:
                    final_id, was_remapped = resolve_merge_identity(
                        project_path,
                        existing_ids | set(id_map.values()),
                        original_id,
                        {**record, "id": original_id},
                        alias_index=alias_index,
                        memories_directory=memories_directory,
                        rules_directory=rules_directory,
                    )
                except KeyCollisionError as exc:
                    raise InterchangeError(str(exc), cause=exc.cause) from exc
                if was_remapped:
                    remapped.append({"from": original_id, "to": final_id})
                id_map[original_id] = final_id
                note["permalink"] = final_id
                note["frontmatter"]["permalink"] = final_id
                write_note(
                    project_path,
                    note,
                    memories_directory=memories_directory,
                    rules_directory=rules_directory,
                    txn=txn,
                )
                existing_ids.add(final_id)
                imported_count += 1
                for link in extract_record_links({**record, "id": original_id}):
                    incoming_links.append(
                        {
                            "source": id_map.get(link["source"], link["source"]),
                            "target": id_map.get(link["target"], link["target"]),
                            "edge": link["edge"],
                        }
                    )
            if incoming_links:
                merged = load_links(project_path) + incoming_links
                save_links(project_path, merged, txn=txn)
    else:
        for record in records:
            _process_record(record)

    return {
        "verdict": "pass",
        "dryRun": dry_run,
        "format": fmt,
        "imported": imported_count,
        "plannedImport": imported_count,
        "source": str(source),
        "projectPath": str(_project_root(project_path)),
        "idRemaps": remapped,
        "linksImported": len(incoming_links),
        "registeredIds": sorted(registry.canonical.keys()),
    }
