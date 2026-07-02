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
        "scripts/spec-union.py",
        "scripts/spec-rigor-check.py",
        "scripts/traceability-check.py",
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
SUBTASK_CHECKBOX = re.compile(r"^-\s+\[([ xX])\]\s+(\d+(?:\.\d+)+)\s+(.+)$")
REF_ID_PATTERN = re.compile(r"^\d+(?:\.\d+)+$")


def ref_sort_key(ref_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in ref_id.split("."))


def extract_executable_subtasks(text: str, phase_id: str) -> list[dict[str, Any]]:
    """Parse executable sub-tasks for one phase (PRD 053 R5, R29)."""
    chunk = phase_section_text(text, phase_id)
    if not chunk:
        return []
    subtasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in chunk.splitlines():
        match = SUBTASK_CHECKBOX.match(line)
        if match:
            if current:
                subtasks.append(current)
            ref_id = match.group(2)
            if not REF_ID_PATTERN.match(ref_id):
                continue
            current = {
                "id": ref_id,
                "title": match.group(3).strip(),
                "files": [],
                "checked": match.group(1).lower() == "x",
            }
            continue
        if current and "**File:**" in line:
            raw = re.sub(r"^\s*-?\s*\*\*File:\*\*\s*", "", line).strip()
            backtick_paths = re.findall(r"`([^`]+)`", raw)
            if backtick_paths:
                paths = [normalize_file_path(p) for p in backtick_paths if p.strip()]
            else:
                paths = [
                    normalize_file_path(p.strip())
                    for p in re.split(r"[,]|(?:\s+and\s+)|(?:\s+or\s+)", raw)
                    if p.strip()
                ]
            current["files"].extend(paths)
    if current:
        subtasks.append(current)
  # keep only unchecked executable items with at least one file
    return [
        {
            "id": st["id"],
            "title": st["title"],
            "files": sorted(set(st.get("files") or [])),
        }
        for st in subtasks
        if not st.get("checked") and st.get("files")
    ]


def phase_section_text(text: str, phase_id: str) -> str:
    body = split_frontmatter(text)[1]
    sections = re.split(r"^###\s+(\d+)\.", body, flags=re.MULTILINE)
    for idx in range(1, len(sections), 2):
        if sections[idx] == phase_id:
            return sections[idx + 1] if idx + 1 < len(sections) else ""
    return ""




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


EXCEPTION_MANIFEST_REL = (
    "docs/prds/031-planning-unit-model-and-migration/tokenizer-exception-manifest.json"
)
EXCEPTION_MANIFEST_CAP = 64

RID_BULLET_NONCANON = re.compile(
    r"^- \*\*([RD]\d+)[.:]+\*\*\s*(.*)$", re.I
)
PHASE_HEADING_NONCANON = re.compile(
    r"^###\s+(?:Phase\s+)?(\d+)\s*(?:[.:—\-]|$)", re.I
)

SLOT_TEMPLATES: dict[str, str] = {
    "prd_requirement": "- **{id}** {body}",
    "prd_section": "## {title}",
    "decision_bullet": "- **{id}** {body}",
    "task_phase": "### {phase}. {title}",
    "task_file": "  - **File:** `{path}`",
    "traceability_row": "| {rid} | {task} | {scenario} |",
    "directive_inline": "{key}: [{ids}]",
    "directive_block": "{key}:\n  - {id}",
}


@dataclass
class Finding:
    file: str
    line: int
    expected: str
    found: str
    klass: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "expected": self.expected,
            "found": self.found,
            "class": self.klass,
        }


def id_sort_key(rid: str) -> tuple[str, int | str]:
    m = ID_PATTERN.match(rid)
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return ("Z", rid)


def parse_frontmatter_scalar(text: str, key: str) -> str | None:
    fm, _ = split_frontmatter(text)
    if fm is None:
        return None
    for line in fm.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def parse_frontmatter_directives(text: str) -> dict[str, list[str]]:
    fm, _ = split_frontmatter(text)
    out: dict[str, list[str]] = {k: [] for k in DIRECTIVE_KEYS}
    if fm is None:
        return out
    for key in DIRECTIVE_KEYS:
        out[key] = parse_directive_list(fm, key)
    return out


def extract_rd_bullets(text: str) -> list[tuple[str, str]]:
    doc = tokenize(text)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for tok in doc.tokens:
        if tok.kind != TokenKind.RD_ID_BULLET:
            continue
        rid = tok.data["id"]
        if rid in seen:
            continue
        seen.add(rid)
        out.append((rid, tok.data.get("body", "")))
    out.sort(key=lambda x: id_sort_key(x[0]))
    return out


def extract_traceability_rows(text: str) -> list[dict[str, str]]:
    doc = tokenize(text)
    return [
        {
            "rid": t.data["rid"],
            "task": t.data["task"],
            "testScenario": t.data["testScenario"],
        }
        for t in doc.tokens
        if t.kind == TokenKind.TRACEABILITY_ROW
    ]


def extract_phases(text: str) -> list[dict[str, str]]:
    doc = tokenize(text)
    phases: list[dict[str, str]] = []
    for tok in doc.tokens:
        if tok.kind != TokenKind.PHASE_HEADING:
            continue
        title = tok.data.get("title", "")
        phases.append(
            {
                "id": tok.data.get("phase", ""),
                "title": title,
                "slug": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
            }
        )
    return phases


def extract_phase_dependencies(text: str) -> list[dict[str, str]] | None:
    doc = tokenize(text)
    rows = [
        {"phase": t.data["phase"], "depends_on": t.data["depends_on"]}
        for t in doc.tokens
        if t.kind == TokenKind.PHASE_DEPENDENCIES_ROW
    ]
    return rows if rows else None


def extract_phase_files(text: str) -> dict[str, list[str]]:
    doc = tokenize(text)
    phases = extract_phases(text)
    phase_ids = [p["id"] for p in phases]
    out: dict[str, list[str]] = {pid: [] for pid in phase_ids}
    current_phase = ""
    body_lines = split_frontmatter(text)[1].splitlines()
    body_start = text.count("\n", 0, text.find(body_lines[0]) if body_lines else 0) + 1
    line_to_phase: dict[int, str] = {}
    for tok in doc.tokens:
        if tok.kind == TokenKind.PHASE_HEADING:
            current_phase = tok.data.get("phase", "")
        elif tok.kind == TokenKind.FILE_REFERENCE and current_phase:
            line_to_phase[tok.line] = current_phase
    for tok in doc.tokens:
        if tok.kind != TokenKind.FILE_REFERENCE:
            continue
        phase = line_to_phase.get(tok.line, current_phase)
        if phase and phase in out:
            out[phase].extend(tok.data.get("paths", []))
    return out


def emit_template(kind: str) -> str:
    if kind not in SLOT_TEMPLATES:
        raise KeyError(f"unknown template kind: {kind}")
    return SLOT_TEMPLATES[kind]


def structural_check(text: str, path: str = "") -> list[Finding]:
    findings: list[Finding] = []
    fm, body = split_frontmatter(text)
    file_ref = path or "<stdin>"

    if fm is not None:
        fm_start = 2
        for key in DIRECTIVE_KEYS:
            ids = parse_directive_list(fm, key)
            key_line = None
            for i, line in enumerate(fm.splitlines()):
                if line.startswith(f"{key}:"):
                    key_line = fm_start + i
                    val = line.split(":", 1)[1].strip()
                    if val or any(
                        ln.strip().startswith("-")
                        for ln in fm.splitlines()[i + 1 :]
                        if ln.startswith(" ") or ln.startswith("\t")
                    ):
                        if not ids:
                            findings.append(
                                Finding(
                                    file=file_ref,
                                    line=key_line,
                                    expected=f"{key} with at least one id",
                                    found=f"{key}: (zero parsed ids)",
                                    klass="directive-empty-ids",
                                )
                            )
                    break

    body_start = (fm.count("\n") + 3) if fm is not None else 1
    for idx, line in enumerate(body.splitlines()):
        line_no = body_start + idx
        m = RID_BULLET_NONCANON.match(line)
        if m:
            rid = norm_id(m.group(1))
            findings.append(
                Finding(
                    file=file_ref,
                    line=line_no,
                    expected=f"- **{rid}** …",
                    found=line.strip(),
                    klass="rid-bullet-variant",
                )
            )
        m = PHASE_HEADING_NONCANON.match(line)
        if m and not PHASE_HEADING.match(line):
            findings.append(
                Finding(
                    file=file_ref,
                    line=line_no,
                    expected=f"### {m.group(1)}. Title",
                    found=line.strip(),
                    klass="phase-heading-variant",
                )
            )
    return findings


def check_document(text: str, path: str = "") -> tuple[str, list[Finding]]:
    findings = structural_check(text, path)
    verdict = "pass" if not findings else "fail"
    return verdict, findings


def _body_prefix(text: str) -> tuple[str, str]:
    fm, _ = split_frontmatter(text)
    if fm is None:
        return "", text
    end = text.find("\n---", 3)
    offset = end + 4
    if offset < len(text) and text[offset] == "\n":
        offset += 1
    return text[:offset], text[offset:]


def write_document(text: str) -> str:
    if not text:
        return text
    prefix, body = _body_prefix(text)
    changed = False
    new_body_lines: list[str] = []
    for line in body.splitlines(keepends=True):
        raw = line.rstrip("\n\r")
        newline = line[len(raw):] if len(line) > len(raw) else "\n"
        m = RID_BULLET_NONCANON.match(raw)
        if m:
            rid = norm_id(m.group(1))
            body_text = m.group(2).strip()
            new_line = f"- **{rid}** {body_text}{newline}"
            if new_line != line:
                changed = True
            new_body_lines.append(new_line)
            continue
        m = PHASE_HEADING_NONCANON.match(raw)
        if m and not PHASE_HEADING.match(raw):
            title = re.sub(r"^[.:—\-\s]+", "", raw.split(str(m.group(1)), 1)[-1]).strip()
            title = re.sub(r"^[:.\-\s]+", "", title).strip() or "Untitled"
            new_line = f"### {m.group(1)}. {title}{newline}"
            if new_line != line:
                changed = True
            new_body_lines.append(new_line)
            continue
        new_body_lines.append(line)

    candidate = prefix + "".join(new_body_lines)
    if changed:
        return write_document(candidate)
    return candidate


def load_exception_manifest(root: Path) -> dict[str, Any]:
    path = root / EXCEPTION_MANIFEST_REL
    if not path.is_file():
        return {"version": 1, "cap": EXCEPTION_MANIFEST_CAP, "signoff": "", "exceptions": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if len(data.get("exceptions", [])) > data.get("cap", EXCEPTION_MANIFEST_CAP):
        raise ValueError("exception manifest exceeds cap")
    return data


def manifest_allows(
    manifest: dict[str, Any],
    *,
    file: str,
    consumer: str,
    klass: str,
) -> bool:
    for exc in manifest.get("exceptions", []):
        if (
            exc.get("file") == file
            and exc.get("consumer") == consumer
            and exc.get("class") == klass
        ):
            return True
    return False


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
        choices=[
            "tokenize",
            "emit",
            "lint-callsites",
            "check",
            "write",
            "template",
        ],
        nargs="?",
        default="tokenize",
    )
    parser.add_argument("path", nargs="?", help="Markdown file path or template kind")
    parser.add_argument("--map", dest="map_path", help="call-site-map.md for lint-callsites")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--inplace", action="store_true", help="write mode: overwrite file")
    args = parser.parse_args(argv)

    if args.command == "lint-callsites":
        errors = lint_call_site_map(Path(args.map_path or ""))
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            return 20
        print(json.dumps({"verdict": "pass", "consumers": sorted(RUNTIME_CALL_SITES)}))
        return 0

    if args.command == "template":
        kind = args.path or ""
        try:
            print(emit_template(kind))
        except KeyError as exc:
            print(json.dumps({"verdict": "fail", "error": str(exc)}), file=sys.stderr)
            return 2
        return 0

    if args.command in ("check", "write"):
        if not args.path:
            parser.error("path required for check/write")
        p = Path(args.path)
        text = p.read_text(encoding="utf-8") if p.is_file() else args.path
        file_ref = str(p) if p.is_file() else "<stdin>"
        if args.command == "check":
            verdict, findings = check_document(text, file_ref)
            payload = {
                "verdict": verdict,
                "findings": [f.to_dict() for f in findings],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            if verdict != "pass":
                for f in findings:
                    print(
                        f"{f.file}:{f.line}: expected {f.expected!r}, found {f.found!r} [{f.klass}]",
                        file=sys.stderr,
                    )
            return 0 if verdict == "pass" else 20
        canonical = write_document(text)
        if args.inplace and p.is_file():
            p.write_text(canonical, encoding="utf-8")
        else:
            sys.stdout.write(canonical)
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
