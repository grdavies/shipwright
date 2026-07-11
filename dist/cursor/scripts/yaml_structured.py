"""Structured YAML subset parser for markdown frontmatter (stdlib-only)."""

from __future__ import annotations

import re
from typing import Any

_SCALAR_RE = re.compile(
    r"^(?:"
    r"(?P<dq>\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<sq>'(?:[^'\\]|\\.)*')"
    r"|(?P<plain>[^\s#]+)"
    r")(?:\s+#.*)?$"
)


def _sequence_item_rest(content: str) -> str | None:
    """Return remainder after list marker, or None when the line is not a sequence item."""
    if content == "-":
        return ""
    if content.startswith("- "):
        return content[2:].strip()
    return None


def safe_load(text: str) -> Any:
    lines = _normalize_lines(text)
    if not lines:
        return {}
    value, _ = _parse_value(lines, 0, lines[0][0])
    return value


def _normalize_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        out.append((indent, raw.strip()))
    return out


def _parse_value(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    line_indent, content = lines[index]
    if line_indent < indent:
        return {}, index
    if _sequence_item_rest(content) is not None:
        return _parse_sequence(lines, index, line_indent)
    return _parse_mapping(lines, index, line_indent)


def _parse_mapping(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    i = index
    while i < len(lines):
        line_indent, content = lines[i]
        if line_indent < indent:
            break
        if line_indent > indent:
            break
        if _sequence_item_rest(content) is not None:
            break
        key, value = _split_key_value(content)
        if key is None:
            break
        if value is not None:
            mapping[key] = _parse_scalar(value)
            i += 1
            continue
        i += 1
        if i < len(lines) and lines[i][0] > indent:
            if _sequence_item_rest(lines[i][1]) is not None:
                child, i = _parse_sequence(lines, i, lines[i][0])
            else:
                child, i = _parse_value(lines, i, lines[i][0])
            mapping[key] = child
        elif i < len(lines) and lines[i][0] == indent and _sequence_item_rest(lines[i][1]) is not None:
            child, i = _parse_sequence(lines, i, lines[i][0])
            mapping[key] = child
        else:
            mapping[key] = None
    return mapping, i


def _parse_sequence(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    i = index
    while i < len(lines):
        line_indent, content = lines[i]
        rest = _sequence_item_rest(content)
        if line_indent != indent or rest is None:
            break
        i += 1
        if not rest:
            if i < len(lines) and lines[i][0] > indent:
                child, i = _parse_value(lines, i, lines[i][0])
                items.append(child)
            else:
                items.append(None)
            continue
        key, value = _split_key_value(rest)
        if key is None:
            items.append(_parse_scalar(rest))
            continue
        item: dict[str, Any] = {key: _parse_scalar(value) if value is not None else None}
        if value is None:
            if i < len(lines) and lines[i][0] > indent:
                child, i = _parse_value(lines, i, lines[i][0])
                item[key] = child
            elif i < len(lines) and lines[i][0] == indent and _sequence_item_rest(lines[i][1]) is not None:
                child, i = _parse_sequence(lines, i, lines[i][0])
                item[key] = child
            items.append(item)
            continue
        child_indent = indent + 2
        while i < len(lines) and lines[i][0] >= child_indent:
            if lines[i][0] != child_indent:
                break
            sub_indent, sub_content = lines[i]
            if _sequence_item_rest(sub_content) is not None:
                break
            sub_key, sub_value = _split_key_value(sub_content)
            if sub_key is None:
                break
            if sub_value is not None:
                item[sub_key] = _parse_scalar(sub_value)
                i += 1
                continue
            i += 1
            if i < len(lines) and lines[i][0] > sub_indent:
                child, i = _parse_value(lines, i, lines[i][0])
                item[sub_key] = child
            elif i < len(lines) and lines[i][0] == sub_indent and _sequence_item_rest(lines[i][1]) is not None:
                child, i = _parse_sequence(lines, i, lines[i][0])
                item[sub_key] = child
            else:
                item[sub_key] = None
        items.append(item)
    return items, i


def _split_key_value(content: str) -> tuple[str | None, str | None]:
    if ":" not in content:
        return None, None
    key, _, value = content.partition(":")
    key = key.strip()
    value = value.strip()
    if not key:
        return None, None
    if not value:
        return key, None
    return key, value


def _parse_scalar(raw: str) -> Any:
    match = _SCALAR_RE.match(raw)
    if not match:
        return raw
    if match.group("dq"):
        inner = match.group("dq")[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    if match.group("sq"):
        return match.group("sq")[1:-1]
    plain = match.group("plain")
    lowered = plain.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if lowered in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", plain):
        return int(plain)
    return plain
