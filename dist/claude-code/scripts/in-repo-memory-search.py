#!/usr/bin/env python3
"""Deterministic in-repo memory search, export/import, and derived index/log maintenance."""
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="In-repo memory search and interchange")
    sub = parser.add_subparsers(dest="command")

    search = sub.add_parser("search", help="keyword + frontmatter search")
    search.add_argument("--store", required=True)
    search.add_argument("--query", default="")
    search.add_argument("--category", default="")
    search.add_argument("--tag", default="")
    search.add_argument("--file-glob", default="")

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

    if raw_argv and raw_argv[0] not in {"search", "export", "import", "maintain-derived", "-h", "--help"}:
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
    if ns.command == "maintain-derived":
        return cmd_maintain_derived(ns)
    parser.print_help()
    return 2


if __name__ == "__main__":
    run_module_main(main)
