#!/usr/bin/env python3
"""Native context compression for Task-dispatch prompt blocks (PRD 058 gap-083 R18, R27)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

CONTENT_JSON = "json"
CONTENT_DIFF = "diff"
CONTENT_LOG = "log"
CONTENT_PROSE = "prose"
CONTENT_TYPES = frozenset({CONTENT_JSON, CONTENT_DIFF, CONTENT_LOG, CONTENT_PROSE})

_CHARS_PER_TOKEN = 4

_DIFF_FILE_HEADER = re.compile(r"^(diff --git |--- |\+\+\+ )", re.MULTILINE)
_DIFF_HUNK = re.compile(r"^@@ .+ @@", re.MULTILINE)
_LOG_LINE = re.compile(
    r"^("
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"|\[(?:DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|TRACE)\]"
    r"|\w+\s+(?:DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL)\b"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
_FENCE_RE = re.compile(r"^(```+|~~~+)(.*)$", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class CompressResult:
    compressed: bool
    text: str
    contentType: str
    retrieveKey: str | None = None


def estimate_tokens(text: str) -> int:
    """Shared chars-per-token heuristic for threshold gating and telemetry."""
    if not text:
        return 0
    words = len(text.split())
    char_est = max(1, len(text) // _CHARS_PER_TOKEN)
    word_est = max(1, (words * 4) // 3) if words else 1
    return max(char_est, word_est)


def detect_content_type(text: str) -> str:
    """Classify text as json, diff, log, or prose."""
    stripped = text.strip()
    if not stripped:
        return CONTENT_PROSE

    if _looks_like_diff(stripped):
        return CONTENT_DIFF
    if _looks_like_json(stripped):
        return CONTENT_JSON
    if _looks_like_log(stripped):
        return CONTENT_LOG
    return CONTENT_PROSE


def compress(
    text: str,
    *,
    content_type: str | None = None,
    budget_tokens: int | None = None,
) -> CompressResult:
    """Compress *text* when it exceeds *budget_tokens* using a type-appropriate strategy."""
    ctype = content_type or detect_content_type(text)
    if ctype not in CONTENT_TYPES:
        ctype = CONTENT_PROSE

    if budget_tokens is None or estimate_tokens(text) <= budget_tokens:
        return CompressResult(compressed=False, text=text, contentType=ctype, retrieveKey=None)

    strategy = _STRATEGIES.get(ctype, _compress_prose)
    compressed_text = strategy(text, budget_tokens)
    changed = compressed_text != text
    return CompressResult(
        compressed=changed,
        text=compressed_text,
        contentType=ctype,
        retrieveKey=None,
    )


def _looks_like_diff(text: str) -> bool:
    if text.startswith("diff --git "):
        return True
    if _DIFF_HUNK.search(text):
        return True
    if _DIFF_FILE_HEADER.search(text) and ("@@" in text or text.count("\n") >= 2):
        return True
    return False


def _looks_like_json(text: str) -> bool:
    first = text.lstrip()
    if not first or first[0] not in "{[":
        return False
    try:
        json.loads(text)
        return True
    except json.JSONDecodeError:
        pass
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    parsed = 0
    for line in lines[: min(5, len(lines))]:
        try:
            json.loads(line)
            parsed += 1
        except json.JSONDecodeError:
            return False
    return parsed >= 2


def _looks_like_log(text: str) -> bool:
    lines = text.splitlines()
    if not lines:
        return False
    matches = sum(1 for ln in lines[:20] if _LOG_LINE.match(ln))
    return matches >= max(2, len(lines[:20]) // 3)


def _truncate_to_budget(text: str, budget_tokens: int) -> str:
    if estimate_tokens(text) <= budget_tokens:
        return text
    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low]


def _split_fence_segments(text: str) -> list[tuple[bool, str]]:
    """Split into (is_fence, segment) preserving fence integrity."""
    segments: list[tuple[bool, str]] = []
    pos = 0
    in_fence = False
    opener = ""
    for match in _FENCE_RE.finditer(text):
        start, end = match.span()
        if start > pos:
            segments.append((in_fence, text[pos:start]))
        marker = match.group(1)
        if not in_fence:
            in_fence = True
            opener = marker
            segments.append((True, text[start:end]))
        elif marker == opener or marker.startswith(opener[0]):
            in_fence = False
            segments.append((True, text[start:end]))
            opener = ""
        else:
            segments.append((True, text[start:end]))
        pos = end
    if pos < len(text):
        segments.append((in_fence, text[pos:]))
    return segments


def _compress_fence_safe(text: str, budget_tokens: int, inner_compress: Callable[[str, int], str]) -> str:
    segments = _split_fence_segments(text)
    if not any(is_fence for is_fence, _ in segments):
        return inner_compress(text, budget_tokens)

    fence_text = "".join(seg for is_fence, seg in segments if is_fence)
    fence_budget = estimate_tokens(fence_text)
    remaining = max(1, budget_tokens - fence_budget)

    parts: list[str] = []
    for is_fence, seg in segments:
        if is_fence:
            parts.append(seg)
        elif seg.strip():
            parts.append(inner_compress(seg, remaining))
        else:
            parts.append(seg)
    joined = "".join(parts)
    if estimate_tokens(joined) <= budget_tokens:
        return joined
    return _truncate_to_budget(joined, budget_tokens)


def _compress_json(text: str, budget_tokens: int) -> str:
    def _inner(raw: str, budget: int) -> str:
        stripped = raw.strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return _compress_prose(raw, budget)

        if isinstance(parsed, list):
            return _summarize_json_list(parsed, budget)
        if isinstance(parsed, dict):
            return _summarize_json_dict(parsed, budget)
        return _truncate_to_budget(stripped, budget)

    return _compress_fence_safe(text, budget_tokens, _inner)


def _summarize_json_list(items: list[object], budget_tokens: int) -> str:
    kept: list[object] = []
    for item in items:
        candidate = json.dumps(kept + [item], indent=2, ensure_ascii=False)
        if estimate_tokens(candidate) > budget_tokens and kept:
            break
        kept.append(item)
        if estimate_tokens(candidate) > budget_tokens:
            break
    omitted = len(items) - len(kept)
    body = json.dumps(kept, indent=2, ensure_ascii=False)
    if omitted > 0:
        body = f"{body}\n/* ... {omitted} more item(s) omitted */"
    return body


def _summarize_json_dict(data: dict[str, object], budget_tokens: int) -> str:
    kept: dict[str, object] = {}
    for key in data:
        candidate = json.dumps({**kept, key: data[key]}, indent=2, ensure_ascii=False)
        if estimate_tokens(candidate) > budget_tokens and kept:
            break
        kept[key] = data[key]
        if estimate_tokens(candidate) > budget_tokens:
            break
    omitted = len(data) - len(kept)
    body = json.dumps(kept, indent=2, ensure_ascii=False)
    if omitted > 0:
        body = f"{body}\n/* ... {omitted} more key(s) omitted */"
    return body


def _compress_diff(text: str, budget_tokens: int) -> str:
    def _inner(raw: str, budget: int) -> str:
        lines = raw.splitlines(keepends=True)
        if not lines:
            return raw

        header: list[str] = []
        body_start = 0
        for idx, line in enumerate(lines):
            if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ "):
                header.append(line)
                body_start = idx + 1
            elif line.startswith("@@"):
                body_start = idx
                break
            elif header and not line.strip():
                header.append(line)
                body_start = idx + 1

        prefix = "".join(header if header else lines[:body_start])
        rest = lines[body_start:]
        if estimate_tokens(prefix) >= budget:
            return _truncate_to_budget("".join(lines), budget)

        hunks: list[list[str]] = []
        current: list[str] = []
        for line in rest:
            if line.startswith("@@") and current:
                hunks.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            hunks.append(current)

        out: list[str] = [prefix]
        budget_left = budget - estimate_tokens(prefix)
        for hunk in hunks:
            hunk_text = _summarize_diff_hunk(hunk, max(1, budget_left))
            out.append(hunk_text)
            budget_left -= estimate_tokens(hunk_text)
            if budget_left <= 0:
                break
        if len(hunks) > len(out) - 1:
            omitted = len(hunks) - (len(out) - 1)
            out.append(f"\n... {omitted} more hunk(s) omitted\n")
        return "".join(out)

    return _compress_fence_safe(text, budget_tokens, _inner)


def _summarize_diff_hunk(hunk: list[str], budget_tokens: int) -> str:
    if not hunk:
        return ""
    full = "".join(hunk)
    if estimate_tokens(full) <= budget_tokens:
        return full

    header = hunk[0] if hunk[0].startswith("@@") else ""
    body = hunk[1:] if header else hunk
    if not body:
        return header

    head_count = max(1, len(body) // 4)
    tail_count = max(1, len(body) // 4)
    head = body[:head_count]
    tail = body[-tail_count:] if tail_count < len(body) else []
    omitted = len(body) - len(head) - len(tail)
    summary = f"... {omitted} diff line(s) omitted ...\n" if omitted > 0 else ""
    condensed = [header, *head, summary, *tail] if header else [*head, summary, *tail]
    result = "".join(condensed)
    if estimate_tokens(result) > budget_tokens:
        return _truncate_to_budget("".join(hunk[: max(1, len(hunk) // 2)]), budget_tokens)
    return result


def _compress_log(text: str, budget_tokens: int) -> str:
    def _inner(raw: str, budget: int) -> str:
        lines = raw.splitlines(keepends=True)
        if not lines:
            return raw
        if estimate_tokens(raw) <= budget:
            return raw

        head_count = max(2, len(lines) // 5)
        tail_count = max(2, len(lines) // 5)
        if head_count + tail_count >= len(lines):
            return _truncate_to_budget(raw, budget)

        head = lines[:head_count]
        tail = lines[-tail_count:]
        omitted = len(lines) - len(head) - len(tail)
        summary = f"... {omitted} log line(s) omitted ...\n"
        condensed = "".join([*head, summary, *tail])
        if estimate_tokens(condensed) > budget:
            return _truncate_to_budget(raw, budget)
        return condensed

    return _compress_fence_safe(text, budget_tokens, _inner)


def _compress_prose(text: str, budget_tokens: int) -> str:
    def _inner(raw: str, budget: int) -> str:
        if estimate_tokens(raw) <= budget:
            return raw

        paragraphs = re.split(r"\n\s*\n", raw)
        if len(paragraphs) > 1:
            kept: list[str] = []
            for para in paragraphs:
                candidate = "\n\n".join([*kept, para])
                if estimate_tokens(candidate) > budget and kept:
                    break
                kept.append(para)
                if estimate_tokens(candidate) > budget:
                    break
            omitted = len(paragraphs) - len(kept)
            body = "\n\n".join(kept)
            if omitted > 0:
                body = f"{body}\n\n... {omitted} more paragraph(s) omitted ..."
            if estimate_tokens(body) <= budget:
                return body

        sentences = _SENTENCE_END.split(raw.strip())
        if len(sentences) > 1:
            kept_s: list[str] = []
            for sentence in sentences:
                candidate = " ".join([*kept_s, sentence])
                if estimate_tokens(candidate) > budget and kept_s:
                    break
                kept_s.append(sentence)
                if estimate_tokens(candidate) > budget:
                    break
            omitted = len(sentences) - len(kept_s)
            body = " ".join(kept_s)
            if omitted > 0:
                body = f"{body} ... {omitted} more sentence(s) omitted ..."
            if estimate_tokens(body) <= budget:
                return body

        return _truncate_to_budget(raw, budget)

    return _compress_fence_safe(text, budget_tokens, _inner)


_STRATEGIES: dict[str, Callable[[str, int], str]] = {
    CONTENT_JSON: _compress_json,
    CONTENT_DIFF: _compress_diff,
    CONTENT_LOG: _compress_log,
    CONTENT_PROSE: _compress_prose,
}
