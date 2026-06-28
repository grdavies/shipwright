#!/usr/bin/env python3
"""Canonical doc-format tokenizer for planning-unit frontmatter and body (PRD 031 R11)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

TOKENIZER_VERSION = 1
OFFLINE_GUARANTEE = True

DIRECTIVE_KEYS = frozenset({"absorbs", "supersedes", "retracts"})

RUNTIME_CALL_SITES = frozenset(
    {
        "scripts/spec-union.sh",
        "scripts/spec-rigor-check.sh",
        "scripts/traceability-check.sh",
        "scripts/wave_deliver.py",
    }
)

ID_PATTERN = re.compile(r"^([RD])(\d+)$", re.I)


class TokenKind(str, Enum):
    FRONTMATTER = "frontmatter"
    FM_SCALAR = "frontmatter_scalar"
    FM_DIRECTIVE_LIST = "frontmatter_directive_list"
    SECTION_HEADING = "section_heading"
    RD_ID_BULLET = "rd_id_bullet"
    TRACEABILITY_ROW = "traceability_row"
    PHASE_HEADING = "phase_heading"
    PHASE_DEPENDENCIES_ROW = "phase_dependencies_row"
    FILE_REFERENCE = "file_reference"


@dataclass
class Token:
    kind: TokenKind
    line: int
    column: int
    text: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "line": self.line,
            "column": self.column,
            "text": self.text,
            "data": self.data,
        }


@dataclass
class Document:
    source: str
    tokens: list[Token]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TOKENIZER_VERSION,
            "offline": OFFLINE_GUARANTEE,
            "tokens": [t.to_dict() for t in self.tokens],
        }


def norm_id(raw: str) -> str:
    raw = raw.strip()
    m = ID_PATTERN.match(raw)
    if m:
        return f"{m.group(1).upper()}{m.group(2)}"
    if raw.isdigit():
        return f"R{raw}"
    return raw


def parse_directive_list(block: str, key: str) -> list[str]:
    lines = block.splitlines()
    ids: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith(f"{key}:"):
            i += 1
            continue
        val = line.split(":", 1)[1].strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if inner:
                ids.extend(norm_id(x.strip()) for x in re.split(r",\s*", inner) if x.strip())
            return ids
        if val:
            ids.append(norm_id(val))
            return ids
        i += 1
        while i < len(lines):
            item = lines[i]
            if not item.startswith(" ") and not item.startswith("\t"):
                break
            m = re.match(r"^\s*-\s+(.+)$", item)
            if m:
                ids.append(norm_id(m.group(1).strip().strip('"').strip("'")))
            i += 1
        return ids
    return ids


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    fm = text[3:end].strip("\n")
    body = text[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    return fm, body


def _tokenize_frontmatter(fm: str, line_offset: int = 1) -> list[Token]:
    tokens: list[Token] = []
    if not fm.strip():
        return tokens
    tokens.append(
        Token(
            kind=TokenKind.FRONTMATTER,
            line=line_offset,
            column=1,
            text=fm,
            data={"lines": fm.count("\n") + 1},
        )
    )
    i = 0
    fm_lines = fm.splitlines()
    while i < len(fm_lines):
        line = fm_lines[i]
        if ":" not in line:
            i += 1
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        abs_line = line_offset + 1 + i
        if key in DIRECTIVE_KEYS:
            block = "\n".join(fm_lines[i:])
            ids = parse_directive_list(block, key)
            tokens.append(
                Token(
                    kind=TokenKind.FM_DIRECTIVE_LIST,
                    line=abs_line,
                    column=1,
                    text=line,
                    data={"key": key, "ids": ids},
                )
            )
            if val.startswith("[") or not val:
                if not val:
                    i += 1
                    while i < len(fm_lines) and (
                        fm_lines[i].startswith(" ") or fm_lines[i].startswith("\t")
                    ):
                        i += 1
                else:
                    i += 1
            else:
                i += 1
            continue
        tokens.append(
            Token(
                kind=TokenKind.FM_SCALAR,
                line=abs_line,
                column=1,
                text=line,
                data={"key": key, "value": val.strip('"').strip("'")},
            )
        )
        i += 1
    return tokens


RID_BULLET = re.compile(r"^- \*\*([RD]\d+)\*\*\s*(.*)$", re.I)
RID_BULLET_ALT = re.compile(r"^\*\*([RD]\d+)\*\*\s*(.*)$", re.I)
RID_SECTION = re.compile(r"^##\s+([RD]\d+)\b(?:\s*\((.*)\))?\s*$", re.I)
SECTION_HEADING = re.compile(r"^(##\s+.+)$")
PHASE_HEADING = re.compile(r"^(###\s+\d+\.\s+.+)$")
FILE_REFERENCE = re.compile(r"^(\s*-?\s*\*\*File:\*\*\s*.+)$")
TRACEABILITY_HEADER = re.compile(r"^##\s+Traceability\s*$", re.I)
PHASE_DEPS_HEADER = re.compile(r"^##\s+Phase Dependencies\s*$", re.I)
TRACE_ROW = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]+)\|")
PHASE_DEP_ROW = re.compile(r"^\|([^|]+)\|([^|]+)\|")


def normalize_file_path(raw: str) -> str:
    path = raw.strip().strip("`").strip()
    return re.sub(r"\s*→\s*.*$", "", path).strip()


def tokenize(source: str) -> Document:
    tokens: list[Token] = []
    fm, body = split_frontmatter(source)
    body_start_line = 1
    if fm is not None:
        tokens.extend(_tokenize_frontmatter(fm, line_offset=1))
        body_start_line = fm.count("\n") + 3

    mode = "body"
    for idx, line in enumerate(body.splitlines()):
        line_no = body_start_line + idx
        if TRACEABILITY_HEADER.match(line):
            mode = "traceability"
            tokens.append(
                Token(
                    kind=TokenKind.SECTION_HEADING,
                    line=line_no,
                    column=1,
                    text=line,
                    data={"title": line.lstrip("#").strip()},
                )
            )
            continue
        if PHASE_DEPS_HEADER.match(line):
            mode = "phase_dependencies"
            tokens.append(
                Token(
                    kind=TokenKind.SECTION_HEADING,
                    line=line_no,
                    column=1,
                    text=line,
                    data={"title": line.lstrip("#").strip()},
                )
            )
            continue
        if line.startswith("## ") and mode in ("traceability", "phase_dependencies"):
            mode = "body"
        if mode == "traceability":
            m = TRACE_ROW.match(line.strip())
            if m:
                rid, task_ref, scenario = (p.strip() for p in m.groups())
                if rid.lower() != "r-id" and not re.match(r"^[-:\s|]+$", rid):
                    tokens.append(
                        Token(
                            kind=TokenKind.TRACEABILITY_ROW,
                            line=line_no,
                            column=1,
                            text=line,
                            data={
                                "rid": norm_id(rid) if re.match(r"^R\d+$", rid, re.I) else rid,
                                "task": task_ref,
                                "testScenario": scenario,
                            },
                        )
                    )
                    continue
        if mode == "phase_dependencies":
            m = PHASE_DEP_ROW.match(line.strip())
            if m:
                phase, depends = (p.strip() for p in m.groups())
                if phase.lower() != "phase" and re.match(r"^\d+$", phase):
                    tokens.append(
                        Token(
                            kind=TokenKind.PHASE_DEPENDENCIES_ROW,
                            line=line_no,
                            column=1,
                            text=line,
                            data={"phase": phase, "depends_on": depends},
                        )
                    )
                    continue
        if PHASE_HEADING.match(line):
            pm = re.match(r"^###\s+(\d+)\.\s+(.+)$", line)
            tokens.append(
                Token(
                    kind=TokenKind.PHASE_HEADING,
                    line=line_no,
                    column=1,
                    text=line,
                    data={
                        "phase": pm.group(1) if pm else "",
                        "title": pm.group(2).strip() if pm else "",
                    },
                )
            )
            continue
        if FILE_REFERENCE.match(line):
            raw = re.sub(r"^\s*-?\s*\*\*File:\*\*\s*", "", line).strip()
            paths = [
                normalize_file_path(p.strip())
                for p in re.split(r"[,]|(?:\s+and\s+)", raw)
                if p.strip()
            ]
            tokens.append(
                Token(
                    kind=TokenKind.FILE_REFERENCE,
                    line=line_no,
                    column=1,
                    text=line,
                    data={"paths": paths},
                )
            )
            continue
        m = RID_BULLET.match(line)
        if m:
            tokens.append(
                Token(
                    kind=TokenKind.RD_ID_BULLET,
                    line=line_no,
                    column=1,
                    text=line,
                    data={"id": norm_id(m.group(1)), "body": m.group(2).strip(), "form": "bullet"},
                )
            )
            continue
        m = RID_BULLET_ALT.match(line)
        if m and not line.startswith("- "):
            tokens.append(
                Token(
                    kind=TokenKind.RD_ID_BULLET,
                    line=line_no,
                    column=1,
                    text=line,
                    data={"id": norm_id(m.group(1)), "body": m.group(2).strip(), "form": "bold"},
                )
            )
            continue
        m = RID_SECTION.match(line)
        if m:
            tokens.append(
                Token(
                    kind=TokenKind.RD_ID_BULLET,
                    line=line_no,
                    column=1,
                    text=line,
                    data={
                        "id": norm_id(m.group(1)),
                        "body": (m.group(2) or "").strip(),
                        "form": "section",
                    },
                )
            )
            continue
        if SECTION_HEADING.match(line):
            tokens.append(
                Token(
                    kind=TokenKind.SECTION_HEADING,
                    line=line_no,
                    column=1,
                    text=line,
                    data={"title": line.lstrip("#").strip()},
                )
            )
    return Document(source=source, tokens=tokens)


def emit(document: Document) -> str:
    return document.source


def emit_canonical(document: Document) -> str:
    lines = document.source.splitlines(keepends=True)
    if not lines:
        return document.source
    out_lines = list(lines)
    for tok in document.tokens:
        idx = tok.line - 1
        if idx < 0 or idx >= len(out_lines):
            continue
        if tok.kind == TokenKind.RD_ID_BULLET and tok.data.get("form") == "bullet":
            out_lines[idx] = f"- **{tok.data['id']}** {tok.data.get('body', '')}\n"
        elif tok.kind == TokenKind.PHASE_HEADING:
            out_lines[idx] = f"### {tok.data.get('phase', '')}. {tok.data.get('title', '')}\n"
        elif tok.kind == TokenKind.SECTION_HEADING:
            title = tok.data.get("title", out_lines[idx].lstrip("#").strip())
            out_lines[idx] = f"## {title}\n"
    return "".join(out_lines)


def assert_offline_module(path: Path) -> list[str]:
    forbidden = {
        "urllib",
        "urllib3",
        "http",
        "socket",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "smtplib",
    }
    tree = ast.parse(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in forbidden:
                    errors.append(f"forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in forbidden:
                errors.append(f"forbidden import from: {node.module}")
    return errors


def lint_call_site_map(map_path: Path) -> list[str]:
    if not map_path.is_file():
        return [f"missing call-site map: {map_path}"]
    raw = map_path.read_text(encoding="utf-8")
    if "## Writer surfaces" in raw:
        text = raw.split("## Writer surfaces", 1)[0]
    else:
        text = raw
    found: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 1:
            continue
        consumer = parts[0].strip("`")
        if consumer.startswith("scripts/") and consumer.endswith((".sh", ".py")):
            found.add(consumer)
    errors: list[str] = []
    for site in sorted(RUNTIME_CALL_SITES - found):
        errors.append(f"call-site map missing consumer: {site}")
    for site in sorted(found - RUNTIME_CALL_SITES):
        errors.append(f"call-site map lists non-authoritative consumer: {site}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Doc-format tokenizer (PRD 031)")
    parser.add_argument(
        "command",
        choices=["tokenize", "emit", "lint-callsites"],
        nargs="?",
        default="tokenize",
    )
    parser.add_argument("path", nargs="?", help="Markdown file path")
    parser.add_argument("--map", dest="map_path", help="call-site-map.md for lint-callsites")
    parser.add_argument("--json", action="store_true", help="JSON output for tokenize")
    args = parser.parse_args(argv)

    if args.command == "lint-callsites":
        errors = lint_call_site_map(Path(args.map_path or ""))
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            return 20
        print(json.dumps({"verdict": "pass", "consumers": sorted(RUNTIME_CALL_SITES)}))
        return 0

    if not args.path:
        parser.error("path required")
    doc = tokenize(Path(args.path).read_text(encoding="utf-8"))
    if args.command == "emit":
        sys.stdout.write(emit(doc))
        return 0
    payload = json.dumps(
        doc.to_dict(),
        ensure_ascii=False,
        sort_keys=True if args.json else False,
        indent=None if args.json else 2,
    )
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
