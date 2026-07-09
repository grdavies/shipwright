#!/usr/bin/env python3
"""Native context compression for Task-dispatch prompt blocks (PRD 058 gap-083 R18, R27, R20-R22)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_store import contains_raw_transcript, redact_content
from wave_json_io import read_json, write_json

CONTENT_JSON = "json"
CONTENT_DIFF = "diff"
CONTENT_LOG = "log"
CONTENT_PROSE = "prose"
CONTENT_TYPES = frozenset({CONTENT_JSON, CONTENT_DIFF, CONTENT_LOG, CONTENT_PROSE})

_CHARS_PER_TOKEN = 4
CACHE_DIR_REL = Path(".cursor/hooks/state/context-compress-cache")
CACHE_TTL_SECONDS = 7 * 24 * 3600
_CACHE_KEY_RE = re.compile(r"^[a-f0-9]{64}$")
_CACHE_LOCK_RETRIES = 50
_CACHE_LOCK_SLEEP_S = 0.01

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


class ContextRetrieveError(Exception):
    """Base class for CCR retrieval failures."""


class RawTranscriptRejected(ContextRetrieveError):
    """Raised when raw transcript markers block a CCR cache write."""


class ContextRetrieveKeyUnknown(ContextRetrieveError):
    """Raised when a retrieve key is absent from the CCR cache."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"unknown retrieve key: {key}")


class ContextRetrieveKeyExpired(ContextRetrieveError):
    """Raised when a cache entry was pruned or exceeded TTL."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"expired or pruned retrieve key: {key}")


class ContextCacheWriteError(ContextRetrieveError):
    """Raised when a concurrent cache write cannot be completed safely."""


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
    root: Path | None = None,
) -> CompressResult:
    """Compress *text* when it exceeds *budget_tokens* using a type-appropriate strategy."""
    ctype = content_type or detect_content_type(text)
    if ctype not in CONTENT_TYPES:
        ctype = CONTENT_PROSE

    if budget_tokens is None or estimate_tokens(text) <= budget_tokens:
        return CompressResult(compressed=False, text=text, contentType=ctype, retrieveKey=None)

    redacted = _prepare_for_cache(text)
    strategy = _STRATEGIES.get(ctype, _compress_prose)
    compressed_text = strategy(redacted, budget_tokens)
    changed = compressed_text != redacted
    retrieve_key: str | None = None
    if changed:
        retrieve_key = _cache_store(redacted, root=root)
    return CompressResult(
        compressed=changed,
        text=compressed_text,
        contentType=ctype,
        retrieveKey=retrieve_key,
    )


def retrieve(retrieve_key: str, *, root: Path | None = None) -> str:
    """Return the full redacted content for *retrieve_key* (or raise a typed error)."""
    if not _CACHE_KEY_RE.fullmatch(retrieve_key):
        raise ContextRetrieveKeyUnknown(retrieve_key)

    repo = (root or Path.cwd()).resolve()
    entry_path = _cache_entry_path(_cache_dir(repo), retrieve_key)
    if not entry_path.is_file():
        raise ContextRetrieveKeyUnknown(retrieve_key)

    data = read_json(entry_path, absent_ok=False)
    content = data.get("content")
    if not isinstance(content, str):
        raise ContextRetrieveKeyUnknown(retrieve_key)

    created_at = data.get("createdAt")
    if isinstance(created_at, str) and _is_cache_expired(created_at):
        raise ContextRetrieveKeyExpired(retrieve_key)

    return content


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_cache_expired(created_at: str) -> bool:
    try:
        created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    age = datetime.now(timezone.utc) - created
    return age.total_seconds() > CACHE_TTL_SECONDS


def _cache_dir(root: Path) -> Path:
    return root / CACHE_DIR_REL


def _cache_entry_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def _cache_key(redacted: str) -> str:
    return hashlib.sha256(redacted.encode("utf-8")).hexdigest()


def _prepare_for_cache(content: str) -> str:
    if contains_raw_transcript(content):
        raise RawTranscriptRejected("raw transcript content refused before CCR cache write")
    return redact_content(content)


def _cache_store(redacted: str, *, root: Path | None = None) -> str:
    repo = (root or Path.cwd()).resolve()
    key = _cache_key(redacted)
    cache_dir = _cache_dir(repo)
    entry_path = _cache_entry_path(cache_dir, key)
    if entry_path.is_file():
        _assert_cache_entry_matches(entry_path, redacted, key)
        return key

    with _cache_write_lock(cache_dir, key):
        if entry_path.is_file():
            _assert_cache_entry_matches(entry_path, redacted, key)
            return key
        write_json(entry_path, {"content": redacted, "createdAt": _utc_now()})
    return key


def _assert_cache_entry_matches(entry_path: Path, redacted: str, key: str) -> None:
    data = read_json(entry_path, absent_ok=False)
    existing = data.get("content")
    if existing != redacted:
        raise ContextCacheWriteError(
            f"cache key collision for {key}: existing entry content mismatch"
        )


@contextmanager
def _cache_write_lock(cache_dir: Path, key: str) -> Iterator[None]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cache_dir / f"{key}.lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    acquired = False
    for _ in range(_CACHE_LOCK_RETRIES):
        try:
            fd = os.open(lock_path, flags, 0o600)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            if _cache_entry_path(cache_dir, key).is_file():
                yield
                return
            time.sleep(_CACHE_LOCK_SLEEP_S)
    if not acquired:
        raise ContextCacheWriteError(f"cache write lock timeout for key {key}")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


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
