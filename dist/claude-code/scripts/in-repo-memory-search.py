#!/usr/bin/env python3
"""Deterministic in-repo memory search, export/import, traversal, and derived index/log maintenance."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

OKF_VERSION = "0.1"
CANONICAL_CATEGORIES = (
    "decision",
    "learning",
    "debug",
    "design",
    "code-context",
    "research",
    "discussion",
    "progress",
    "rule",
)
RESERVED_OKF_NAMES = frozenset({"index.md", "log.md"})
INLINE_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
MEMORY_PATH_RE = re.compile(r"^(?:memories|rules|global/memories)/([^/]+)\.md$")
KNOWN_EDGES = frozenset({"supersedes", "relates-to", "file-linked"})
EXCLUDED_STATUSES = frozenset({"superseded", "resolved", "tombstone"})


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in re.split(r",\s*", inner) if item.strip()]
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = parse_scalar(value)
    body = parts[2].lstrip("\n")
    return fm, body


def format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        if value and all(isinstance(item, dict) for item in value):
            return json.dumps(value)
        items = ", ".join(json.dumps(str(item)) for item in value)
        return f"[{items}]"
    if value is None:
        return '""'
    return json.dumps(str(value))


def render_frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key in sorted(fields):
        lines.append(f"{key}: {format_scalar(fields[key])}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def render_memory_file(fields: dict[str, Any], body: str) -> str:
    return render_frontmatter(fields) + body.rstrip() + "\n"


def memory_id_from_path(path: Path) -> str:
    return path.stem


def first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def display_title(fields: dict[str, Any], body: str) -> str:
    title = fields.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    line = first_body_line(body)
    if line:
        return line[:120]
    mid = fields.get("id")
    if isinstance(mid, str) and mid:
        return mid
    return "untitled"


def iter_memory_files(store: Path) -> list[Path]:
    paths: list[Path] = []
    for sub in ("memories", "rules", "global/memories"):
        base = store / sub
        if not base.is_dir():
            continue
        paths.extend(sorted(base.rglob("*.md")))
    return paths


def read_memory_record(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)
    category = str(fm.get("category") or ("rule" if "rules" in path.parts else "learning"))
    record_id = str(fm.get("id") or memory_id_from_path(path))
    fm["id"] = record_id
    fm["category"] = category
    return {
        "id": record_id,
        "category": category,
        "fields": fm,
        "body": body,
        "path": path,
    }


def load_store_records(store: Path) -> list[dict[str, Any]]:
    return [read_memory_record(path) for path in iter_memory_files(store)]

def is_excluded_record(fields: dict[str, Any]) -> bool:
    if fields.get("inactive") is True:
        return True
    status = str(fields.get("status") or "").lower()
    return status in EXCLUDED_STATUSES


def normalize_link_target(raw: str) -> str | None:
    target = raw.strip()
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    path_match = MEMORY_PATH_RE.match(target)
    if path_match:
        return path_match.group(1)
    if target.endswith(".md"):
        return Path(target).stem
    if "/" not in target and " " not in target:
        return target
    return None


def parse_link_entry(entry: Any) -> tuple[str, str] | None:
    if isinstance(entry, str):
        tid = normalize_link_target(entry)
        return (tid, "relates-to") if tid else None
    if isinstance(entry, dict):
        raw_target = entry.get("to") or entry.get("target") or entry.get("id")
        if not raw_target:
            return None
        tid = normalize_link_target(str(raw_target))
        if not tid:
            return None
        edge = str(entry.get("edge") or entry.get("type") or "relates-to")
        return tid, edge
    return None


def extract_frontmatter_links(fields: dict[str, Any]) -> list[tuple[str, str]]:
    links_raw = fields.get("links")
    if not links_raw:
        return []
    entries = links_raw if isinstance(links_raw, list) else [links_raw]
    out: list[tuple[str, str]] = []
    for entry in entries:
        parsed = parse_link_entry(entry)
        if parsed:
            out.append(parsed)
    return out


def extract_inline_links(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for _text, target in INLINE_MD_LINK_RE.findall(body):
        tid = normalize_link_target(target)
        if tid:
            out.append((tid, "relates-to"))
    return out


def build_edge_map(
    records: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    forward: dict[str, list[dict[str, str]]] = {}
    backlinks: dict[str, list[dict[str, str]]] = {}
    known_ids = {record["id"] for record in records}

    def add_edge(source: str, target: str, edge: str, *, kind: str) -> None:
        edge_entry = {
            "target": target,
            "edge": edge,
            "kind": kind,
            "dangling": target not in known_ids,
        }
        forward.setdefault(source, []).append(edge_entry)
        backlinks.setdefault(target, []).append({"source": source, "edge": edge, "kind": kind})

    for record in records:
        source = record["id"]
        for target, edge in extract_frontmatter_links(record["fields"]):
            add_edge(source, target, edge, kind="frontmatter")
        for target, edge in extract_inline_links(record["body"]):
            add_edge(source, target, edge, kind="inline")
    return forward, backlinks


def store_title_description(content: str, *, title: str = "", description: str = "") -> tuple[str, str]:
    body = content.strip()
    first = first_body_line(body)
    resolved_title = title.strip() or (first[:120] if first else "untitled")
    resolved_desc = description.strip() or (first[:240] if first else resolved_title)
    return resolved_title, resolved_desc


def reconcile_supersede_entries(
    store: Path, entries: list[tuple[str, str, str]]
) -> dict[str, Any]:
    records = load_store_records(store)
    if not records:
        return {"reconciled": 0, "actions": []}

    forward, _backlinks = build_edge_map(records)
    actions: list[dict[str, str]] = []
    reconciled = 0

    for _date, old_path, new_path in entries:
        old_path = old_path.strip()
        new_path = new_path.strip()
        if not old_path or not new_path:
            continue

        for record in records:
            if is_excluded_record(record["fields"]):
                continue
            fields = dict(record["fields"])
            related = fields.get("relatedFiles")
            related_list = related if isinstance(related, list) else []
            if not related_list:
                continue
            updated = False
            new_related: list[Any] = []
            for item in related_list:
                item_str = str(item)
                if item_str == old_path or item_str.endswith("/" + old_path.lstrip("/")):
                    new_related.append(new_path)
                    updated = True
                    actions.append({
                        "action": "repoint-relatedFiles",
                        "id": record["id"],
                        "from": old_path,
                        "to": new_path,
                    })
                else:
                    new_related.append(item)
            if updated:
                fields["relatedFiles"] = new_related
                write_memory_record(store, {**record, "fields": fields})
                reconciled += 1

        for record in records:
            if is_excluded_record(record["fields"]):
                continue
            for edge in forward.get(record["id"], []):
                if edge.get("edge") != "supersedes":
                    continue
                target = str(edge.get("target") or "")
                if target not in {Path(old_path).stem, old_path}:
                    continue
                fields = dict(record["fields"])
                fields["status"] = "superseded"
                write_memory_record(store, {**record, "fields": fields})
                actions.append({"action": "mark-superseded", "id": record["id"], "target": target})
                reconciled += 1

    if reconciled:
        maintain_derived(store)
    return {"reconciled": reconciled, "actions": actions}


def redact_text(text: str) -> str:
    try:
        from memory_redact import redact
    except ImportError:
        return text
    return redact(text)


def record_to_jsonl(record: dict[str, Any]) -> dict[str, Any]:
    fields = dict(record["fields"])
    fields.pop("id", None)
    payload = {
        "id": record["id"],
        "content": record["body"].strip(),
        "category": record["category"],
    }
    for key, value in fields.items():
        if key == "category":
            continue
        payload[key] = value
    return payload


def jsonl_to_record(obj: dict[str, Any]) -> dict[str, Any]:
    category = str(obj.get("category") or "learning")
    record_id = str(obj.get("id") or "imported-memory")
    fields = {k: v for k, v in obj.items() if k not in {"content", "category", "id"}}
    fields["category"] = category
    fields["id"] = record_id
    if "createdAt" not in fields:
        fields["createdAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title, description = store_title_description(
        str(obj.get("content") or ""),
        title=str(fields.get("title") or ""),
        description=str(fields.get("description") or ""),
    )
    if "title" not in fields:
        fields["title"] = title
    if "description" not in fields:
        fields["description"] = description
    return {
        "id": record_id,
        "category": category,
        "fields": fields,
        "body": str(obj.get("content") or ""),
    }


def target_path_for_record(store: Path, record: dict[str, Any]) -> Path:
    category = record["category"]
    if category == "rule":
        return store / "rules" / f"{record['id']}.md"
    scope = str(record["fields"].get("scope") or "project")
    if scope == "global":
        return store / "global" / "memories" / f"{record['id']}.md"
    return store / "memories" / f"{record['id']}.md"


def relative_memory_path(record: dict[str, Any]) -> str:
    category = record["category"]
    if category == "rule":
        return f"rules/{record['id']}.md"
    scope = str(record["fields"].get("scope") or "project")
    if scope == "global":
        return f"global/memories/{record['id']}.md"
    return f"memories/{record['id']}.md"


def write_memory_record(store: Path, record: dict[str, Any]) -> Path:
    path = target_path_for_record(store, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    redacted_body = redact_text(record["body"])
    fields = dict(record["fields"])
    fields["id"] = record["id"]
    fields["category"] = record["category"]
    title, description = store_title_description(
        redacted_body,
        title=str(fields.get("title") or ""),
        description=str(fields.get("description") or ""),
    )
    if not fields.get("title"):
        fields["title"] = title
    if not fields.get("description"):
        fields["description"] = description
    path.write_text(render_memory_file(fields, redacted_body), encoding="utf-8")
    return path


def record_to_okf_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = dict(record["fields"])
    category = record["category"]
    fields.pop("category", None)
    fields["type"] = category
    fields["id"] = record["id"]
    if "timestamp" not in fields and "createdAt" in fields:
        fields["timestamp"] = fields["createdAt"]
    title = display_title(record["fields"], record["body"])
    if "title" not in fields:
        fields["title"] = title
    if "description" not in fields:
        fields["description"] = title
    return fields


def okf_fields_to_record(fields: dict[str, Any], body: str) -> dict[str, Any]:
    record_fields = dict(fields)
    type_value = str(record_fields.pop("type", record_fields.pop("category", "learning")))
    record_id = str(record_fields.pop("id", "imported-memory"))
    category = type_value
    record_fields["category"] = category
    record_fields["id"] = record_id
    if "timestamp" in record_fields and "createdAt" not in record_fields:
        record_fields["createdAt"] = record_fields["timestamp"]
    return {
        "id": record_id,
        "category": category,
        "fields": record_fields,
        "body": body,
    }


def render_store_index(records: list[dict[str, Any]], *, okf_bundle_root: bool = False) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {cat: [] for cat in CANONICAL_CATEGORIES}
    for record in records:
        grouped.setdefault(record["category"], []).append(record)

    lines: list[str] = []
    if okf_bundle_root:
        lines.extend(["---", f'okf_version: "{OKF_VERSION}"', "---", ""])

    for category in CANONICAL_CATEGORIES:
        items = grouped.get(category) or []
        if not items:
            continue
        lines.append(f"# {category}")
        lines.append("")
        for record in sorted(items, key=lambda r: r["id"]):
            title = display_title(record["fields"], record["body"])
            if okf_bundle_root:
                rel = f"{category}/{record['id']}.md"
            else:
                rel = relative_memory_path(record)
            lines.append(f"* [{title}]({rel}) — `{record['id']}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_store_log(records: list[dict[str, Any]]) -> str:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        created = str(record["fields"].get("createdAt") or record["fields"].get("timestamp") or "")
        date_key = created[:10] if len(created) >= 10 else "unknown"
        by_date.setdefault(date_key, []).append(record)

    lines = ["# Memory Update Log", ""]
    for date_key in sorted(by_date, reverse=True):
        lines.append(f"## {date_key}")
        items = sorted(by_date[date_key], key=lambda r: r["id"])
        for record in items:
            title = display_title(record["fields"], record["body"])
            rel = relative_memory_path(record)
            lines.append(f"* **Creation**: [{title}]({rel}) — `{record['id']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def maintain_derived(store: Path) -> dict[str, str]:
    records = load_store_records(store)
    index_path = store / "index.md"
    log_path = store / "log.md"
    index_path.write_text(render_store_index(records), encoding="utf-8")
    log_path.write_text(render_store_log(records), encoding="utf-8")
    return {"index": str(index_path), "log": str(log_path), "count": str(len(records))}


def cmd_search(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    results = []
    query = ns.query or ""
    for path in iter_memory_files(store):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, body = parse_frontmatter(text)
        if is_excluded_record(fm) and not ns.include_excluded:
            continue
        if ns.file_glob:
            related = fm.get("relatedFiles")
            related_text = related if isinstance(related, str) else json.dumps(related or [])
            if ns.file_glob not in related_text:
                continue
        category = str(fm.get("category") or "")
        tags = fm.get("tags")
        tag_text = tags if isinstance(tags, str) else json.dumps(tags or [])
        if ns.category and ns.category not in category:
            continue
        if ns.tag and ns.tag not in tag_text:
            continue
        if query and query.lower() not in text.lower():
            continue
        mid = str(fm.get("id") or memory_id_from_path(path))
        summary = first_body_line(body)[:200]
        results.append({"id": mid, "summary": summary})
    print(json.dumps({"results": results}, indent=2))
    return 0


def cmd_export(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    records = load_store_records(store)
    fmt = ns.format
    if fmt == "jsonl":
        out_path = Path(ns.out)
        lines = [json.dumps(record_to_jsonl(record), sort_keys=True) for record in records]
        payload = "\n".join(lines) + ("\n" if lines else "")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(json.dumps({"format": "jsonl", "count": len(records), "out": str(out_path)}))
        return 0

    if fmt == "okf":
        out_dir = Path(ns.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        for record in records:
            category = record["category"]
            category_dir = out_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            fields = record_to_okf_fields(record)
            body = redact_text(record["body"])
            target = category_dir / f"{record['id']}.md"
            target.write_text(render_memory_file(fields, body), encoding="utf-8")
        (out_dir / "index.md").write_text(
            render_store_index(records, okf_bundle_root=True), encoding="utf-8"
        )
        (out_dir / "log.md").write_text(render_store_log(records), encoding="utf-8")
        print(json.dumps({"format": "okf", "count": len(records), "out": str(out_dir)}))
        return 0

    print(json.dumps({"error": f"unsupported export format: {fmt}"}), file=sys.stderr)
    return 1


def cmd_import(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    fmt = ns.format
    imported: list[dict[str, Any]] = []

    if fmt == "jsonl":
        source = Path(ns.source)
        for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(json.dumps({"error": f"jsonl line {line_no}: {exc}"}), file=sys.stderr)
                return 1
            if not isinstance(obj, dict):
                print(json.dumps({"error": f"jsonl line {line_no}: expected object"}), file=sys.stderr)
                return 1
            imported.append(jsonl_to_record(obj))

    elif fmt == "okf":
        source = Path(ns.source)
        for path in sorted(source.rglob("*.md")):
            if path.name in RESERVED_OKF_NAMES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_frontmatter(text)
            if not fm.get("type"):
                continue
            imported.append(okf_fields_to_record(fm, body))
    else:
        print(json.dumps({"error": f"unsupported import format: {fmt}"}), file=sys.stderr)
        return 1

    for record in imported:
        write_memory_record(store, record)
    derived = maintain_derived(store)
    print(json.dumps({"format": fmt, "imported": len(imported), **derived}))
    return 0


def cmd_maintain_derived(ns: argparse.Namespace) -> int:
    result = maintain_derived(Path(ns.store))
    print(json.dumps(result))
    return 0


def cmd_traverse(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    records = load_store_records(store)
    forward, backlinks = build_edge_map(records)
    record_by_id = {record["id"]: record for record in records}
    start_ids = [part.strip() for part in ns.from_id.split(",") if part.strip()]
    edge_filter = ns.edge or ""
    max_depth = int(ns.depth)
    direction = ns.direction

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(sid, 0) for sid in start_ids]
    nodes: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []

    while queue:
        current, depth = queue.pop(0)
        if current in visited or depth > max_depth:
            continue
        visited.add(current)
        record = record_by_id.get(current)
        nodes.append({
            "id": current,
            "found": record is not None,
            "excluded": is_excluded_record(record["fields"]) if record else False,
            "depth": depth,
        })
        if depth >= max_depth:
            continue
        if direction in {"out", "both"}:
            for edge in forward.get(current, []):
                if edge_filter and edge.get("edge") != edge_filter:
                    continue
                edges_out.append({"source": current, **edge})
                target = str(edge.get("target") or "")
                if target and target not in visited:
                    queue.append((target, depth + 1))
        if direction in {"in", "both"}:
            for edge in backlinks.get(current, []):
                if edge_filter and edge.get("edge") != edge_filter:
                    continue
                source = str(edge.get("source") or "")
                edges_out.append({"target": current, **edge, "dangling": source not in record_by_id})
                if source and source not in visited:
                    queue.append((source, depth + 1))

    dangling = sorted({e["target"] for e in edges_out if e.get("dangling")})
    print(json.dumps({
        "from": start_ids,
        "direction": direction,
        "edge": edge_filter or None,
        "depth": max_depth,
        "nodes": nodes,
        "edges": edges_out,
        "dangling": dangling,
    }, indent=2))
    return 0


def cmd_expand(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    records = load_store_records(store)
    record_by_id = {record["id"]: record for record in records}
    _, backlinks = build_edge_map(records)
    ids = [part.strip() for part in ns.ids.split(",") if part.strip()]
    expanded: list[dict[str, Any]] = []

    for mid in ids:
        record = record_by_id.get(mid)
        if not record:
            expanded.append({"id": mid, "found": False, "backlinks": backlinks.get(mid, [])})
            continue
        expanded.append({
            "id": mid,
            "found": True,
            "category": record["category"],
            "fields": record["fields"],
            "body": record["body"].strip(),
            "backlinks": backlinks.get(mid, []),
            "excluded": is_excluded_record(record["fields"]),
        })
    print(json.dumps({"expanded": expanded}, indent=2))
    return 0


def cmd_reconcile_supersede(ns: argparse.Namespace) -> int:
    store = Path(ns.store)
    log_path = Path(ns.log)
    if not log_path.is_file():
        print(json.dumps({"reconciled": 0, "actions": [], "entries": 0}))
        return 0
    entries: list[tuple[str, str, str]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            entries.append((parts[0], parts[1], parts[2]))
    result = reconcile_supersede_entries(store, entries)
    result["entries"] = len(entries)
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="In-repo memory search and interchange")
    sub = parser.add_subparsers(dest="command")

    search = sub.add_parser("search", help="keyword + frontmatter search")
    search.add_argument("--store", required=True)
    search.add_argument("--query", default="")
    search.add_argument("--category", default="")
    search.add_argument("--tag", default="")
    search.add_argument("--file-glob", default="")
    search.add_argument("--include-excluded", action="store_true")

    traverse = sub.add_parser("traverse", help="walk link graph from seed ids")
    traverse.add_argument("--store", required=True)
    traverse.add_argument("--from", dest="from_id", required=True)
    traverse.add_argument("--edge", default="")
    traverse.add_argument("--depth", default="8")
    traverse.add_argument("--direction", choices=("out", "in", "both"), default="both")

    expand = sub.add_parser("expand", help="expand ids with full body and backlinks")
    expand.add_argument("--store", required=True)
    expand.add_argument("--ids", required=True)

    reconcile = sub.add_parser("reconcile-supersede", help="reconcile SUPERSEDED.log against store")
    reconcile.add_argument("--store", required=True)
    reconcile.add_argument("--log", required=True)

    export = sub.add_parser("export", help="export store to jsonl or okf bundle")
    export.add_argument("--store", required=True)
    export.add_argument("--format", choices=("jsonl", "okf"), required=True)
    export.add_argument("--out", required=True)

    imp = sub.add_parser("import", help="import jsonl or okf bundle into store")
    imp.add_argument("--store", required=True)
    imp.add_argument("--format", choices=("jsonl", "okf"), required=True)
    imp.add_argument("--source", required=True)

    maintain = sub.add_parser("maintain-derived", help="regenerate index.md and log.md")
    maintain.add_argument("--store", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    known = {
        "search", "export", "import", "maintain-derived",
        "traverse", "expand", "reconcile-supersede", "-h", "--help",
    }
    if raw_argv and raw_argv[0] not in known:
        if "--store" in raw_argv:
            legacy = parser.parse_args(["search", *raw_argv])
            return cmd_search(legacy)

    ns = parser.parse_args(raw_argv)
    if ns.command == "search":
        return cmd_search(ns)
    if ns.command == "export":
        return cmd_export(ns)
    if ns.command == "import":
        return cmd_import(ns)
    if ns.command == "traverse":
        return cmd_traverse(ns)
    if ns.command == "expand":
        return cmd_expand(ns)
    if ns.command == "reconcile-supersede":
        return cmd_reconcile_supersede(ns)
    if ns.command == "maintain-derived":
        return cmd_maintain_derived(ns)
    parser.print_help()
    return 2


if __name__ == "__main__":
    run_module_main(main)
