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
from typing import Any

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


def _note_relpath(category: str, permalink: str) -> str:
    folder = _category_folder(category)
    safe = _safe_permalink(permalink).replace("/", "_")
    return f"{folder}/{safe}.md"


def note_path(
    project_path: Path,
    category: str,
    permalink: str,
    *,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> Path:
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


def save_links(project_path: Path, links: list[dict[str, str]]) -> None:
    ensure_project(project_path)
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for link in links:
        key = (link["source"], link["target"], link["edge"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    _links_path(project_path).write_text(json.dumps({"links": deduped}, indent=2) + "\n", encoding="utf-8")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_note(note), encoding="utf-8")
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
    payload = {
        "id": record.get("id"),
        "category": record.get("category"),
        "body": record.get("body"),
        "fields": {
            k: v
            for k, v in dict(record.get("fields") or {}).items()
            if k not in {"id", "updatedAt", "createdAt"}
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def remap_permalink_for_merge(
    project_path: Path,
    existing_ids: set[str],
    imported_id: str,
    incoming: dict[str, Any],
    *,
    memories_directory: str = DEFAULT_MEMORIES_DIR,
    rules_directory: str = DEFAULT_RULES_DIR,
) -> tuple[str, bool]:
    if imported_id not in existing_ids:
        return imported_id, False
    current = load_note(
        project_path,
        imported_id,
        memories_directory=memories_directory,
        rules_directory=rules_directory,
    )
    if current and note_fingerprint(current) == note_fingerprint(incoming):
        return imported_id, False
    suffix = hashlib.sha256(imported_id.encode("utf-8")).hexdigest()[:8]
    candidate = f"{imported_id}-sw-{suffix}"
    counter = 1
    while candidate in existing_ids:
        candidate = f"{imported_id}-sw-{suffix}-{counter}"
        counter += 1
    return candidate, True


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
    records = parse_interchange_records(fmt, source)
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
    id_map: dict[str, str] = {}
    remapped: list[dict[str, str]] = []
    incoming_links: list[dict[str, str]] = []
    imported_count = 0

    for record in records:
        category = str(record.get("category") or "learning")
        if category == RULE_CATEGORY and not include_rules:
            # Ordinary import skips rule-class unless explicitly requested.
            continue
        note = record_to_note(record)
        original_id = str(record["id"])
        final_id, was_remapped = remap_permalink_for_merge(
            project_path,
            existing_ids | set(id_map.values()),
            original_id,
            {**record, "id": original_id},
            memories_directory=memories_directory,
            rules_directory=rules_directory,
        )
        if was_remapped:
            remapped.append({"from": original_id, "to": final_id})
        id_map[original_id] = final_id
        note["permalink"] = final_id
        note["frontmatter"]["permalink"] = final_id
        if not dry_run:
            write_note(
                project_path,
                note,
                memories_directory=memories_directory,
                rules_directory=rules_directory,
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

    if not dry_run and incoming_links:
        merged = load_links(project_path) + incoming_links
        save_links(project_path, merged)

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
    }
