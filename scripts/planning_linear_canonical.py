#!/usr/bin/env python3
"""PRD 066 — Linear Public Markdown canonicalization + fidelity suite (R15).

Supported adapter contract is Linear **Public Markdown** fields (issue/document
``description`` / ``content``). Internal ProseMirror ``contentData`` and Yjs
``contentState`` are explicitly **not** adapter-complete and must not be used as
freeze-hash or round-trip authority.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from typing import Any

from planning_canonical import (
    BODY_SIZE_LIMIT,
    CHUNK_TOKEN_MARKER_PREFIX,
    CommentRecord,
    IssueSnapshot,
    MARKER_CHUNK_MANIFEST,
    canonical_form,
    canonical_hash,
    decode_linear_public_markdown_json,
    normalize_body,
    require_linear_size_pin,
    strip_markers_and_edges,
)

SUPPORTED_CONTRACT = "public-markdown"
UNSUPPORTED_INTERNAL_FIELDS = frozenset({"contentData", "contentState"})

# Linear GraphQL Public Markdown mention submit form (developers.linear.app):
# bare workspace URLs become @mentions in the editor; we canonicalize to URLs.
_MENTION_MD_LINK = re.compile(
    r"\[@[^\]]+\]\((https://linear\.app/[^)\s]+)\)"
)

# +++ Title ... +++ collapsible sections (Linear Public Markdown).
_COLLAPSIBLE = re.compile(
    r"^\+\+\+\s*(?P<title>[^\n]*)\n(?P<body>.*?)^\+\+\+\s*$",
    re.MULTILINE | re.DOTALL,
)

_HTML_DETAILS = re.compile(r"<details\b", re.IGNORECASE)
_HTML_SUMMARY = re.compile(r"<summary\b", re.IGNORECASE)


class LinearCanonicalContractError(ValueError):
    """Raised when a payload claims an unsupported Linear content contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LinearCanonicalDegradeError(ValueError):
    """Raised when a construct cannot round-trip via Public Markdown."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def assert_public_markdown_contract(payload: dict[str, Any] | None) -> None:
    """Fail closed when ProseMirror/Yjs internal fields are treated as supported."""
    if not isinstance(payload, dict):
        return
    present = sorted(UNSUPPORTED_INTERNAL_FIELDS.intersection(payload.keys()))
    if present:
        raise LinearCanonicalContractError(
            "unsupported-internal-content-contract",
            "Linear adapter contract is Public Markdown only; "
            f"internal fields not adapter-complete: {', '.join(present)}",
        )


def is_adapter_complete_field(field_name: str) -> bool:
    """Return True only for Public Markdown content fields."""
    if field_name in UNSUPPORTED_INTERNAL_FIELDS:
        return False
    return field_name in {"description", "content", "body", "markdown", "publicMarkdown"}


def _normalize_mention_urls(text: str) -> str:
    """Canonical mention form is the bare Linear resource URL (API submit shape)."""

    def _link_to_url(match: re.Match[str]) -> str:
        return match.group(1).rstrip("/")

    return _MENTION_MD_LINK.sub(_link_to_url, text)


def _normalize_collapsibles(text: str) -> str:
    """Normalize +++ collapsible blocks to a stable Public Markdown shape."""

    def _repl(match: re.Match[str]) -> str:
        title = match.group("title").strip()
        body = normalize_body(match.group("body"))
        if body:
            return f"+++ {title}\n\n{body}\n\n+++"
        return f"+++ {title}\n\n+++"

    return _COLLAPSIBLE.sub(_repl, text)


def _normalize_fenced_code_langs(text: str) -> str:
    """Preserve language tags; empty fence opener stays language-less (GFM)."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        if line.startswith("```"):
            if not in_fence:
                lang = line[3:].strip()
                out.append(f"```{lang}" if lang else "```")
                in_fence = True
            else:
                out.append("```")
                in_fence = False
        else:
            out.append(line)
    return "\n".join(out)


def reject_non_round_trippable(markdown: str) -> None:
    """Reject constructs that Linear cannot round-trip via Public Markdown alone."""
    if _HTML_DETAILS.search(markdown) or _HTML_SUMMARY.search(markdown):
        raise LinearCanonicalDegradeError(
            "html-details-not-public-markdown",
            "HTML <details>/<summary> is not Linear Public Markdown; use +++ collapsibles",
        )
    stripped = markdown.strip()
    if stripped.startswith("{") and (
        '"contentData"' in stripped or '"contentState"' in stripped
    ):
        try:
            blob = json.loads(stripped)
        except json.JSONDecodeError:
            blob = None
        if isinstance(blob, dict):
            assert_public_markdown_contract(blob)


def linear_markdown_canonical(markdown: str) -> str:
    """Normalize Linear Public Markdown into the PRD 043 body subset for freeze hash."""
    reject_non_round_trippable(markdown)
    text = normalize_body(markdown)
    text = _normalize_mention_urls(text)
    text = _normalize_collapsibles(text)
    text = _normalize_fenced_code_langs(text)
    return normalize_body(text)


# PRD 358 R6 — comparison-only Linear Public Markdown rewrites. Freeze/hash still
# uses original bytes via canonical_hash (excludes sw-freeze-record / sw-chunk-overflow).
LINEAR_PUBLIC_MARKDOWN_R6_REWRITES = frozenset(
    {
        "list-marker",
        "bold-delimiter",
        "code-span",
        "table-formatting",
        "plain-domain-autolink",
        "bold-around-inline-code",
        "mixed-bold-inline-code-both-sides-unwrap",
        "italic-delimiter",
        "ordered-list-leading-space",
        "literal-punctuation-escape",
        "post-code-underscore-unescape",
        "acceptance-criteria-underscore-full-line",
        "implicit-domain-http-autolink",
    }
)

# PRD 366 phase 6 — leftover redacted fixture families bind to named closed-set members only.
PRD366_ADDED_R6_REWRITE_FAMILIES = frozenset(
    {
        "mixed-bold-inline-code-both-sides-unwrap",
        "acceptance-criteria-underscore-full-line",
    }
)

PRD366_REDACTED_FAMILY_REGISTRY_BINDINGS: dict[str, frozenset[str]] = {
    "version-section-token-domain-rewrite": frozenset({"plain-domain-autolink"}),
    "implicit-domain-http-autolink": frozenset(
        {"implicit-domain-http-autolink", "plain-domain-autolink"}
    ),
    "mixed-bold-inline-code-both-sides-unwrap": frozenset(
        {"mixed-bold-inline-code-both-sides-unwrap", "bold-around-inline-code"}
    ),
    "acceptance-criteria-underscore-full-line": frozenset(
        {"acceptance-criteria-underscore-full-line", "post-code-underscore-unescape"}
    ),
}


def prd366_leftover_rewrite_families_registered(
    redacted_families: frozenset[str] | None = None,
) -> list[str]:
    """Return errors when a PRD 366 leftover family is not bound to named R6 members."""
    errors: list[str] = []
    families = redacted_families or frozenset(PRD366_REDACTED_FAMILY_REGISTRY_BINDINGS)
    for name in sorted(families):
        members = PRD366_REDACTED_FAMILY_REGISTRY_BINDINGS.get(name)
        if members is None:
            errors.append(f"unbound PRD 366 leftover family: {name}")
            continue
        missing = sorted(m for m in members if m not in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES)
        if missing:
            errors.append(f"{name} binds missing registry members: {missing}")
    return errors


# PRD 366 R7 — redacted full-line witness; excerpt without acceptance-criteria context is not proof.
R7_ACCEPTANCE_CRITERIA_FULL_LINE_SUBMITTED = (
    "- **Acceptance criteria:** after `token`_suffix on the complete line.\n"
)
R7_ACCEPTANCE_CRITERIA_FULL_LINE_REFETCHED = (
    "- **Acceptance criteria:** after `token`\\_suffix on the complete line.\n"
)
R7_ACCEPTANCE_CRITERIA_EXCERPT_SUBMITTED = "`token`_suffix\n"
R7_ACCEPTANCE_CRITERIA_EXCERPT_REFETCHED = "`token`\\_suffix\n"

# PRD 366 D4 — parser-grade AST compare is explicitly out of scope for the 2.22.0 follow-up.
LINEAR_PUBLIC_MARKDOWN_EQUIVALENCE_STRATEGY = "named-closed-set-families"
LINEAR_PUBLIC_MARKDOWN_PARSER_GRADE_AST_COMPARE = "rejected"


def linear_public_markdown_equivalence_strategy() -> dict[str, str]:
    """Document the binding leftover equality method (stance A; stance D rejected)."""
    return {
        "strategy": LINEAR_PUBLIC_MARKDOWN_EQUIVALENCE_STRATEGY,
        "parserGradeAstCompare": LINEAR_PUBLIC_MARKDOWN_PARSER_GRADE_AST_COMPARE,
        "rewriteRegistry": "LINEAR_PUBLIC_MARKDOWN_R6_REWRITES",
    }

# PRD 359 R5 — fixture-enumerated punctuation unescape alphabet (excludes delimiter ticks).
_LITERAL_PUNCTUATION_UNESCAPE_CHARS = frozenset(".,;:!?#'\"+-=&")

_FENCED_BLOCK = re.compile(r"^```[^\n]*\n.*?^```", re.MULTILINE | re.DOTALL)
_INLINE_CODE = re.compile(r"(?<!`)(`+)([^`]+)\1(?!`)")
_UNORDERED_LIST = re.compile(r"^(\s*)[-+](?= \S)", re.MULTILINE)
_BOLD_UNDERSCORE = re.compile(r"(?<!\w)__([^_\n]+?)__(?!\w)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_AUTO_LINK = re.compile(r"<([^<>\s]+)>")
_ORDERED_LIST = re.compile(r"^(\s*)(\d+)\.(\s+)(\S)", re.MULTILINE)
# PRD 363 R3 — exactly one ASCII space before a top-level ordered marker (not tab / 2+ spaces).
_TOP_LEVEL_ORDERED_ONE_SPACE_PAD = re.compile(r"^ (\d+\. )", re.MULTILINE)
_ITALIC_UNDERSCORE = re.compile(r"(?<!\w)_(?!_)([^_\n]+?)_(?!\w)")
_LITERAL_PUNCTUATION_ESCAPE = re.compile(
    r"\\([" + re.escape("".join(sorted(_LITERAL_PUNCTUATION_UNESCAPE_CHARS))) + r"])"
)
_BARE_DOMAIN = re.compile(
    r"(?<![\w./:@])"
    r"((?:https?://)?(?:www\.)?"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)+"
    r"(?:/[^\s)\]>\"']*)?)"
)
_VERSION_TOKEN = re.compile(r"^v\d+(?:\.\d+)*$", re.IGNORECASE)
_SECTION_TOKEN = re.compile(r"^§?\d+(?:\.\d+)+$")
# Underscore is a word char, so `\bR6\b` misses `__R6__` Linear bold delimiters.
_RID_TOKEN = re.compile(r"(?<![A-Za-z0-9])([RD]\d+)(?![A-Za-z0-9])")
_UUID_TOKEN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_SW_TOKEN = re.compile(r"\bsw[:\-][A-Za-z0-9:._-]+\b")


def original_bytes_hash_body(markdown: str) -> str:
    """Freeze/hash witness: original bytes after newline normalize. Not R6 form."""
    return normalize_body(markdown)


def _placeholder_protect(text: str, pattern: re.Pattern[str], prefix: str) -> tuple[str, list[str]]:
    stored: list[str] = []

    def _save(match: re.Match[str]) -> str:
        stored.append(match.group(0))
        return f"\x00{prefix}{len(stored) - 1}\x00"

    return pattern.sub(_save, text), stored


def _placeholder_restore(text: str, stored: list[str], prefix: str) -> str:
    for index, block in enumerate(stored):
        text = text.replace(f"\x00{prefix}{index}\x00", block)
    return text


def _looks_like_version_or_section_token(label: str) -> bool:
    """PRD 366 R4 — semver and section refs are not bare domains."""
    host = label.strip().split("/", 1)[0]
    if _VERSION_TOKEN.fullmatch(host):
        return True
    return bool(_SECTION_TOKEN.fullmatch(host))


def _looks_like_domain(label: str) -> bool:
    stripped = label.strip()
    if not stripped or " " in stripped:
        return False
    if _looks_like_version_or_section_token(stripped):
        return False
    return bool(_BARE_DOMAIN.fullmatch(stripped))


def _unwrap_angle_brackets(url: str) -> str:
    """Unwrap a single `<destination>` pair (PRD 359 R6 / D8). No loop or remainder concat."""
    text = url.strip()
    if not text.startswith("<") or not text.endswith(">"):
        return text
    if text.count("<") != 1 or text.count(">") != 1:
        return text
    return text[1:-1].strip()


def _canon_url(url: str) -> str:
    text = _unwrap_angle_brackets(url.strip())
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return text
    if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", text):
        return text
    return f"https://{text}"


def _schemeless_domain_hostpath(url: str) -> str | None:
    """Host/path for a bare or http-schemed domain destination (PRD 363 R5)."""
    text = _unwrap_angle_brackets(url.strip())
    if text.startswith("http://"):
        text = text[7:]
    elif text.startswith(("https://", "//")) or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", text):
        return None
    if _looks_like_domain(text):
        return text
    return None


def _named_schemeless_link_identity(hostpath: str) -> str:
    return f"schemeless:{hostpath}"


def _md_link_href_identity(label: str, href: str) -> str:
    stripped_label = label.strip()
    if _looks_like_domain(stripped_label):
        return _named_schemeless_link_identity(stripped_label)
    return _autolink_identity(href)


def _implicit_autolink_policy(raw: str) -> tuple[str, str]:
    """Shared R5 policy: identity token and R6 comparison URL for one destination."""
    text = _unwrap_angle_brackets(raw.strip())
    hostpath = _schemeless_domain_hostpath(text)
    if hostpath is not None:
        return (
            _named_schemeless_link_identity(hostpath),
            _canon_url(hostpath),
        )
    comparison = _canon_url(text)
    if text.startswith("https://"):
        identity = text
    else:
        identity = comparison
    return (identity, comparison)


def _autolink_identity(raw: str) -> str:
    return _implicit_autolink_policy(raw)[0]


def _bare_domain_link_identity(raw: str) -> str:
    return _implicit_autolink_policy(raw)[0]


def _autolink_comparison_url(raw: str) -> str:
    """R6 comparison form for angle autolinks (http provider → https witness)."""
    return _implicit_autolink_policy(raw)[1]


def _normalize_list_markers(text: str) -> str:
    return _UNORDERED_LIST.sub(r"\1*", text)


def _normalize_bold_delimiters(text: str) -> str:
    return _BOLD_UNDERSCORE.sub(r"**\1**", text)


def _normalize_italic_delimiters(text: str) -> str:
    return _ITALIC_UNDERSCORE.sub(r"*\1*", text)


def _normalize_ordered_list_spacing(text: str) -> str:
    return _ORDERED_LIST.sub(r"\1\2. \4", text)


def _normalize_top_level_ordered_one_space_pad(text: str) -> str:
    """Strip one leading ASCII space before top-level ordered markers (PRD 363 R3)."""

    return _TOP_LEVEL_ORDERED_ONE_SPACE_PAD.sub(r"\1", text)


def _normalize_literal_punctuation_escapes(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        return match.group(1)

    return _LITERAL_PUNCTUATION_ESCAPE.sub(_repl, text)


_BOLD_ASTERISK_RUN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def _phrase_internal_multi_span_bold(run_inner: str) -> bool:
    """True when a ** run contains inline code plus phrase prose or multiple codes (PRD 363 R2)."""
    codes = list(_INLINE_CODE.finditer(run_inner))
    if not codes:
        return False
    if len(codes) >= 2:
        return True
    only = codes[0]
    before = run_inner[: only.start()].strip()
    after = run_inner[only.end() :].strip()
    return bool(before or after)


def _normalize_phrase_internal_multi_span_bold(text: str) -> str:
    """Unwrap phrase-internal ** runs that contain inline code spans (PRD 363 R2)."""

    def _repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if _phrase_internal_multi_span_bold(inner):
            return inner
        return match.group(0)

    return _BOLD_ASTERISK_RUN.sub(_repl, text)


def _underscore_starts_or_ends_emphasis_run(text: str, idx: int) -> bool:
    """True when a single `_` at idx opens or closes an underscore emphasis run (PRD 363 R4)."""
    if idx < 0 or idx >= len(text) or text[idx] != "_":
        return False
    if idx > 0 and text[idx - 1] == "_":
        return False
    if idx + 1 < len(text) and text[idx + 1] == "_":
        return False
    line_start = text.rfind("\n", 0, idx) + 1
    line = text[line_start:]
    rel = idx - line_start
    for match in _ITALIC_UNDERSCORE.finditer(line):
        if match.start() == rel or match.end() - 1 == rel:
            return True
    remainder = text[idx:]
    if _ITALIC_UNDERSCORE.match(remainder):
        return True
    after = text[idx + 1 :]
    word = re.match(r"(\w+)", after)
    if not word:
        return False
    word_end = idx + 1 + word.end()
    rest = text[word_end:]
    if rest.startswith("_"):
        return True
    if not rest or rest[0] == "\n":
        return True
    if rest[0].isspace():
        return False
    return False


def _rewrite_post_code_underscore_prefix(text: str, pos: int, out: list[str]) -> int:
    """Normalize at most one underscore escape immediately after an inline code span."""
    if pos >= len(text):
        return pos
    if text.startswith("\\_", pos):
        underscore = pos + 1
        if not _underscore_starts_or_ends_emphasis_run(text, underscore):
            out.append("_")
            return pos + 2
        return pos
    if text[pos] != "_":
        return pos
    if _underscore_starts_or_ends_emphasis_run(text, pos):
        word = re.match(r"_(\w+)", text[pos:])
        if word and (
            pos + word.end() >= len(text) or text[pos + word.end()] in "\n"
        ):
            out.append(f"*{word.group(1)}*")
            return pos + word.end()
        return pos
    out.append("_")
    return pos + 1


def _normalize_post_code_literal_underscore_escapes(text: str) -> str:
    """Unescape post-code `\\_` only when it would not start or end emphasis (PRD 363 R4)."""
    out: list[str] = []
    index = 0
    for match in _INLINE_CODE.finditer(text):
        out.append(text[index : match.end()])
        index = _rewrite_post_code_underscore_prefix(text, match.end(), out)
    out.append(text[index:])
    return "".join(out)


def prove_r7_acceptance_criteria_underscore_full_line() -> dict[str, bool]:
    """Prove post-code underscore on the complete acceptance-criteria line (PRD 366 R7).

    A reduced excerpt that drops triggering acceptance-criteria context is not proof.
    """
    full_ok = linear_public_markdown_equivalent(
        R7_ACCEPTANCE_CRITERIA_FULL_LINE_SUBMITTED,
        R7_ACCEPTANCE_CRITERIA_FULL_LINE_REFETCHED,
    )
    excerpt_ok = linear_public_markdown_equivalent(
        R7_ACCEPTANCE_CRITERIA_EXCERPT_SUBMITTED,
        R7_ACCEPTANCE_CRITERIA_EXCERPT_REFETCHED,
    )
    return {
        "fullLineEquivalent": full_ok,
        "excerptNotProof": not excerpt_ok,
        "ok": full_ok and not excerpt_ok,
    }


def _inline_code_bold_wrapped(text: str, start: int, end: int) -> bool:
    return (
        start >= 2
        and end + 2 <= len(text)
        and text[start - 2 : start] == "**"
        and text[end : end + 2] == "**"
    )


def _mixed_bold_inline_code_phrase(line: str) -> bool:
    """True when a line has 2+ inline code spans (PRD 366 R6 mixed phrase unwrap)."""
    return len(list(_INLINE_CODE.finditer(line))) >= 2


def _unwrap_bold_wrapped_inline_codes(segment: str) -> str:
    """Drop ** around inline code spans within one segment (both-sides unwrap only)."""
    out: list[str] = []
    index = 0
    for match in _INLINE_CODE.finditer(segment):
        start, end = match.start(), match.end()
        bold_wrapped = _inline_code_bold_wrapped(segment, start, end)
        slice_start = start - 2 if bold_wrapped else start
        out.append(segment[index:slice_start])
        out.append(match.group(0))
        index = end + 2 if bold_wrapped else end
    out.append(segment[index:])
    return "".join(out)


def _normalize_mixed_bold_inline_code_both_sides_unwrap(text: str) -> str:
    """Unwrap bold on inline codes in mixed phrases on both sides of compare (PRD 366 R6)."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        if _mixed_bold_inline_code_phrase(line):
            out.append(_unwrap_bold_wrapped_inline_codes(line))
        else:
            out.append(line)
    return "\n".join(out)


def _normalize_bold_around_inline_code(text: str) -> str:
    """Drop bold wrapping a lone inline code span (PRD 359 R3 — not mixed phrases)."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        if _mixed_bold_inline_code_phrase(line):
            out.append(line)
        else:
            out.append(_unwrap_bold_wrapped_inline_codes(line))
    return "\n".join(out)


def _normalize_table_line(line: str) -> str:
    stripped = line.strip()
    if not _is_gfm_table_line(stripped):
        return line
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    normalized: list[str] = []
    for cell in cells:
        compact = cell.replace(" ", "")
        if re.fullmatch(r":?-{1,}:?", compact):
            left = compact.startswith(":")
            right = compact.endswith(":") and compact != ":"
            if left and right:
                normalized.append(":---:")
            elif left:
                normalized.append(":---")
            elif right:
                normalized.append("---:")
            else:
                normalized.append("---")
        else:
            normalized.append(cell)
    return "| " + " | ".join(normalized) + " |"


def _normalize_tables(text: str) -> str:
    return "\n".join(_normalize_table_line(line) for line in text.split("\n"))


def _normalize_autolinks(text: str) -> str:
    def _md_link(match: re.Match[str]) -> str:
        label, href = match.group(1), match.group(2)
        canon = _canon_url(href)
        stripped_label = label.strip()
        if _looks_like_domain(label) and _canon_url(label) == canon:
            return canon
        if stripped_label == href.strip() or stripped_label == canon:
            return canon
        if stripped_label.startswith(("http://", "https://", "//")) and stripped_label == canon:
            return canon
        return f"[{label}]({canon})"

    def _bare_domain_sub(match: re.Match[str]) -> str:
        raw = match.group(1)
        if not _looks_like_domain(raw):
            return raw
        return _canon_url(raw)

    text = _MD_LINK.sub(_md_link, text)
    text = _AUTO_LINK.sub(lambda match: _autolink_comparison_url(match.group(1)), text)
    return _BARE_DOMAIN.sub(_bare_domain_sub, text)


def _r6_rewrite_outside_code(text: str) -> str:
    text = _normalize_list_markers(text)
    text = _normalize_top_level_ordered_one_space_pad(text)
    text = _normalize_ordered_list_spacing(text)
    text = _normalize_bold_delimiters(text)
    text = _normalize_italic_delimiters(text)
    text = _normalize_literal_punctuation_escapes(text)
    text = _normalize_tables(text)
    return _normalize_autolinks(text)


def _normalize_inline_code_span(match: re.Match[str]) -> str:
    ticks, inner = match.group(1), match.group(2)
    return f"{ticks}{inner.strip()}{ticks}"


def linear_public_markdown_r6_form(markdown: str) -> str:
    """Enumerated Linear Public Markdown comparison form (PRD 358 R6). Not a hash witness."""
    text = decode_linear_public_markdown_json(markdown)
    text = strip_markers_and_edges(text)
    text = linear_markdown_canonical(text)
    text, fences = _placeholder_protect(text, _FENCED_BLOCK, "FENCE")
    text = _INLINE_CODE.sub(_normalize_inline_code_span, text)
    text = _normalize_phrase_internal_multi_span_bold(text)
    text = _normalize_mixed_bold_inline_code_both_sides_unwrap(text)
    text = _normalize_bold_around_inline_code(text)
    text = _normalize_post_code_literal_underscore_escapes(text)
    text, codes = _placeholder_protect(text, _INLINE_CODE, "CODE")
    text = _r6_rewrite_outside_code(text)
    text = _placeholder_restore(text, codes, "CODE")
    text = _placeholder_restore(text, fences, "FENCE")
    return normalize_body(text)


def _inline_code_bold_attachments(text: str) -> tuple[str, ...]:
    """Occurrence-ordered inline code plus bold-wrap flag (PRD 359 R3)."""
    attachments: list[str] = []
    for match in _INLINE_CODE.finditer(text):
        inner = match.group(2).strip()
        start, end = match.start(), match.end()
        bold_wrapped = (
            start >= 2
            and end + 2 <= len(text)
            and text[start - 2 : start] == "**"
            and text[end : end + 2] == "**"
        )
        attachments.append(f"{inner}|bold={int(bold_wrapped)}")
    return tuple(attachments)


def _extract_code_contents(text: str) -> tuple[str, ...]:
    spans = [match.group(2).strip() for match in _INLINE_CODE.finditer(text)]
    fences = []
    for match in _FENCED_BLOCK.finditer(text):
        body = match.group(0)
        lines = body.split("\n")
        inner = "\n".join(lines[1:-1]).strip()
        if inner:
            fences.append(inner)
    return tuple(sorted(spans + fences))


def _extract_links(text: str) -> tuple[str, ...]:
    found: set[str] = set()
    remainder = text
    for match in _MD_LINK.finditer(text):
        found.add(_md_link_href_identity(match.group(1), match.group(2)))
        remainder = remainder.replace(match.group(0), " ", 1)
    for match in _AUTO_LINK.finditer(remainder):
        found.add(_autolink_identity(match.group(1)))
        remainder = remainder.replace(match.group(0), " ", 1)
    for match in _BARE_DOMAIN.finditer(remainder):
        raw = match.group(1)
        if _looks_like_domain(raw):
            found.add(_bare_domain_link_identity(raw))
    return tuple(sorted(found))


def _r6_identity_tokens(markdown: str) -> dict[str, tuple[str, ...]]:
    text = decode_linear_public_markdown_json(markdown)
    text = strip_markers_and_edges(text)
    return {
        "rids": tuple(sorted(set(_RID_TOKEN.findall(text)))),
        "code": _extract_code_contents(text),
        "links": _extract_links(text),
        "ids": tuple(sorted(set(_UUID_TOKEN.findall(text) + _SW_TOKEN.findall(text)))),
    }


def linear_public_markdown_equivalent(left: str, right: str) -> bool:
    """True only for enumerated Linear Public Markdown rewrites (PRD 358 R6 / AS7)."""
    if _r6_identity_tokens(left) != _r6_identity_tokens(right):
        return False
    return linear_public_markdown_r6_form(left) == linear_public_markdown_r6_form(right)


def simulate_public_markdown_round_trip(submit_markdown: str) -> str:
    """Simulate submit→refetch through Public Markdown fields only (no contentData)."""
    return linear_markdown_canonical(submit_markdown)


def snapshot_from_linear_markdown(
    *,
    title: str,
    markdown: str,
    state: str = "open",
    labels: list[str] | None = None,
    comments: list[dict[str, Any]] | None = None,
) -> IssueSnapshot:
    body = linear_markdown_canonical(markdown)
    comment_records = [
        CommentRecord(
            id=str(c.get("id", "")),
            body=linear_markdown_canonical(str(c.get("body", ""))),
            created_at=str(c.get("created_at", "")),
            markers=list(c.get("markers") or []),
        )
        for c in (comments or [])
    ]
    return IssueSnapshot(
        title=title,
        body=body,
        state=state,
        labels=list(labels or []),
        comments=comment_records,
    )


def _body_from_fixture(data: dict[str, Any]) -> str:
    assert_public_markdown_contract(data)
    if isinstance(data.get("refetchedMarkdown"), str):
        return linear_markdown_canonical(data["refetchedMarkdown"])
    if isinstance(data.get("submitMarkdown"), str):
        return simulate_public_markdown_round_trip(data["submitMarkdown"])
    if isinstance(data.get("body"), str):
        return linear_markdown_canonical(data["body"])
    raise LinearCanonicalContractError(
        "missing-public-markdown",
        "fixture requires submitMarkdown, refetchedMarkdown, or body (Public Markdown)",
    )


def snapshot_from_fixture(data: dict[str, Any]) -> IssueSnapshot:
    assert_public_markdown_contract(data)
    return snapshot_from_linear_markdown(
        title=str(data.get("title") or "linear-canonical-fixture"),
        markdown=_body_from_fixture(data),
        state=str(data.get("state") or "open"),
        labels=list(data.get("labels") or []),
        comments=list(data.get("comments") or []),
    )


CHUNK_OVERFLOW_MARKER = "<!-- sw-chunk-overflow -->\n"
_LINEAR_CHUNK_LIMIT = BODY_SIZE_LIMIT
# PRD 358 D4 — Linear overflow comment ids are 36-char UUID strings after post.
LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN = 36


class LinearChunkHeadBudgetError(RuntimeError):
    """No description head fits within the limit after UUID manifest rewrite (PRD 358 R2)."""


class LinearOversizedConstructError(RuntimeError):
    """Closed-set Markdown construct exceeds Linear overflow budget (PRD 359 R9/D6).

    Message is opaque JSON: kind, length, code — never the span text.
    """

    def __init__(self, *, kind: str, length: int, code: str = "oversized-closed-set") -> None:
        payload = json.dumps(
            {"code": code, "kind": kind, "length": length},
            sort_keys=True,
            ensure_ascii=True,
        )
        super().__init__(payload)
        self.kind = kind
        self.length = length
        self.code = code


def _utf8_byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _is_gfm_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "|" not in stripped:
        return False
    if stripped.startswith("|") and stripped.endswith("|"):
        return True
    if re.match(r"^[\s|:-]+$", stripped.replace("|", "")):
        return True
    parts = [p.strip() for p in stripped.split("|") if p.strip()]
    return len(parts) >= 2 and "|" in stripped


_EMPHASIS_BOLD_STAR = re.compile(r"\*\*[^*\n]+?\*\*")
_EMPHASIS_BOLD_US = re.compile(r"(?<!\w)__[^_\n]+?__(?!\w)")
_EMPHASIS_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)[^*\n]+?\*(?!\*)")
_EMPHASIS_ITALIC_US = re.compile(r"(?<!\w)_(?!_)[^_\n]+?_(?!\w)")
_MD_IMAGE_OR_LINK = re.compile(r"!?\[(?:[^\]]*)\]\([^)]+\)")


def _spans_overlap(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    for occ_start, occ_end in occupied:
        if start < occ_end and end > occ_start:
            return True
    return False


def _is_list_marker_open(text: str, star_index: int) -> bool:
    line_start = text.rfind("\n", 0, star_index) + 1
    prefix = text[line_start:star_index]
    if prefix.strip():
        return False
    return star_index + 1 < len(text) and text[star_index + 1] in " \t"


def _collect_regex_spans(
    text: str,
    pattern: re.Pattern[str],
    kind: str,
    occupied: list[tuple[int, int]],
    *,
    skip_list_star: bool = False,
) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for match in pattern.finditer(text):
        start, end = match.start(), match.end()
        if skip_list_star and _is_list_marker_open(text, start):
            continue
        if _spans_overlap(start, end, occupied):
            continue
        found.append((start, end, kind))
        occupied.append((start, end))
    return found


def _table_and_fence_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in _FENCED_BLOCK.finditer(text):
        spans.append((match.start(), match.end(), "fenced-code"))
    in_table = False
    table_start = 0
    index = 0
    length = len(text)
    occupied_fences = [(s, e) for s, e, k in spans if k == "fenced-code"]
    while index <= length:
        newline = text.find("\n", index)
        line_end = length if newline == -1 else newline
        line = text[index:line_end]
        inside_fence = _spans_overlap(index, line_end, occupied_fences)
        is_table = (not inside_fence) and _is_gfm_table_line(line)
        if is_table and not in_table:
            in_table = True
            table_start = index
        elif in_table and not is_table:
            spans.append((table_start, index, "gfm-table"))
            in_table = False
        if newline == -1:
            if in_table:
                spans.append((table_start, length, "gfm-table"))
            break
        index = newline + 1
    return spans


def _closed_set_spans(text: str) -> list[tuple[int, int, str]]:
    """Non-overlapping closed-set indivisibles: fences, tables, code, links, emphasis."""
    spans = _table_and_fence_spans(text)
    occupied = [(s, e) for s, e, _k in spans]
    spans.extend(_collect_regex_spans(text, _INLINE_CODE, "inline-code", occupied))
    spans.extend(_collect_regex_spans(text, _MD_IMAGE_OR_LINK, "markdown-link", occupied))
    spans.extend(_collect_regex_spans(text, _AUTO_LINK, "markdown-link", occupied))
    spans.extend(_collect_regex_spans(text, _EMPHASIS_BOLD_STAR, "emphasis", occupied))
    spans.extend(_collect_regex_spans(text, _EMPHASIS_BOLD_US, "emphasis", occupied))
    spans.extend(
        _collect_regex_spans(
            text, _EMPHASIS_ITALIC_STAR, "emphasis", occupied, skip_list_star=True
        )
    )
    spans.extend(_collect_regex_spans(text, _EMPHASIS_ITALIC_US, "emphasis", occupied))
    spans.sort(key=lambda item: (item[0], item[1]))
    return spans


def _offset_inside_closed_set(pos: int, spans: list[tuple[int, int, str]]) -> bool:
    return any(start < pos < end for start, end, _kind in spans)


def _merge_closed_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged: list[tuple[int, int]] = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _forbidden_interior_merged(spans: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
    forbidden: list[tuple[int, int]] = []
    for start, end, _kind in spans:
        inner_lo = start + 1
        inner_hi = end - 1
        if inner_lo <= inner_hi:
            forbidden.append((inner_lo, inner_hi))
    return _merge_closed_intervals(forbidden)


def _add_interior_legal_cuts_on_line(
    positions: set[int],
    line_start: int,
    line_end: int,
    forbidden_merged: list[tuple[int, int]],
) -> None:
    """Add in-line legal cuts via merged closed-set interior gaps (PRD 363 R6)."""
    lo = line_start + 1
    hi = line_end
    if lo > hi:
        return
    if not forbidden_merged:
        positions.update(range(lo, hi + 1))
        return
    cursor = lo
    for f_start, f_end in forbidden_merged:
        if f_end < lo:
            continue
        if f_start > hi:
            break
        clip_start = max(f_start, lo)
        clip_end = min(f_end, hi)
        if cursor < clip_start:
            positions.update(range(cursor, clip_start))
        cursor = max(cursor, clip_end + 1)
        if cursor > hi:
            return
    if cursor <= hi:
        positions.update(range(cursor, hi + 1))


def _leading_closed_set(text: str) -> tuple[str, int] | None:
    for start, end, kind in _closed_set_spans(text):
        if start == 0:
            return kind, _utf8_byte_len(text[:end])
    return None


def _overflow_marker_overhead_bytes() -> int:
    return _utf8_byte_len(_overflow_comment_prefix("0" * 12))


def _raise_if_oversized_closed_set(text: str) -> None:
    overhead = _overflow_marker_overhead_bytes()
    budget = _LINEAR_CHUNK_LIMIT - overhead
    if budget < 0:
        budget = 0
    for start, end, kind in _closed_set_spans(text):
        length = _utf8_byte_len(text[start:end])
        if length > budget:
            raise LinearOversizedConstructError(kind=kind, length=length)


def _split_positions(text: str) -> list[int]:
    """Legal cuts: newlines outside fences/tables, and closed-set boundaries (R8/R10).

    Never returns an offset strictly inside inline code, Markdown links, emphasis
    runs, fenced code, or GFM tables.
    """
    spans = _closed_set_spans(text)
    forbidden_merged = _forbidden_interior_merged(spans)
    positions: set[int] = {0}
    in_fence = False
    in_table = False
    index = 0
    length = len(text)
    while index < length:
        newline = text.find("\n", index)
        line_end = length if newline == -1 else newline
        line = text[index:line_end]
        line_start = index
        if line.strip().startswith("```"):
            in_fence = not in_fence
            in_table = False
            if not in_fence and newline != -1:
                positions.add(newline + 1)
        elif in_fence:
            pass
        else:
            if not line.strip():
                in_table = False
                if newline != -1:
                    positions.add(newline + 1)
            elif _is_gfm_table_line(line):
                if not in_table:
                    positions.add(line_start)
                in_table = True
            else:
                if in_table:
                    in_table = False
                if newline != -1:
                    positions.add(newline + 1)
                _add_interior_legal_cuts_on_line(
                    positions, line_start, line_end, forbidden_merged
                )
        if newline == -1:
            break
        index = newline + 1
    for start, end, _kind in spans:
        positions.add(start)
        positions.add(end)
    positions.add(length)
    return sorted(positions)


def _max_prefix_chars(text: str, max_bytes: int) -> int:
    """Largest prefix length (Unicode code points) whose UTF-8 encoding fits max_bytes."""
    if not text:
        return 0
    lo, hi = 0, len(text)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if _utf8_byte_len(text[:mid]) <= max_bytes:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _max_prefix_bytes(text: str, *, limit: int, positions: list[int] | None = None) -> int:
    if not text:
        return 0
    if _utf8_byte_len(text) <= limit:
        return len(text)
    cuts = positions if positions is not None else _split_positions(text)
    lo, hi = 0, len(cuts) - 1
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        pos = cuts[mid]
        if _utf8_byte_len(text[:pos]) <= limit:
            best = pos
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _overflow_comment_prefix(write_token: str) -> str:
    return (
        f"{CHUNK_OVERFLOW_MARKER}"
        f"<!-- {CHUNK_TOKEN_MARKER_PREFIX}{write_token} -->\n"
    )


def _overflow_comment_markers(write_token: str) -> list[str]:
    return [
        "sw-chunk-overflow",
        f"{CHUNK_TOKEN_MARKER_PREFIX}{write_token}",
    ]


def _split_overflow_comments(
    overflow: str,
    comments: list[CommentRecord],
    *,
    write_token: str,
) -> list[CommentRecord]:
    new_comments = list(comments)
    prefix = _overflow_comment_prefix(write_token)
    remaining = overflow
    prefix_bytes = _utf8_byte_len(prefix)
    max_piece_bytes = _LINEAR_CHUNK_LIMIT - prefix_bytes
    if max_piece_bytes <= 0:
        raise RuntimeError("Linear body chunking failed: overflow marker exceeds comment limit")
    while remaining:
        positions = _split_positions(remaining)
        chunk_len = _max_prefix_bytes(remaining, limit=max_piece_bytes, positions=positions)
        if chunk_len <= 0:
            leading = _leading_closed_set(remaining)
            if leading is not None:
                kind, length = leading
                raise LinearOversizedConstructError(kind=kind, length=length)
            chunk_len = _max_prefix_chars(remaining, max_piece_bytes)
        if chunk_len <= 0:
            raise RuntimeError("Linear body chunking failed: overflow fragment exceeds comment limit")
        chunk_id = f"chunk-{len(new_comments)}"
        piece = remaining[:chunk_len]
        remaining = remaining[chunk_len:]
        new_comments.append(
            CommentRecord(
                id=chunk_id,
                body=f"{prefix}{piece}",
                markers=_overflow_comment_markers(write_token),
            )
        )
    return new_comments


def _worst_case_linear_overflow_comment_ids(count: int) -> list[str]:
    """Worst-case UTF-8 length for post-posting Linear overflow comment ids."""
    if count <= 0:
        return []
    pad = "a" * LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN
    return [pad for _ in range(count)]


def _head_fits_after_uuid_manifest_rewrite(head: str, overflow_chunk_count: int) -> bool:
    """True when rewrite_chunk_manifest_ids cannot push the head over the Linear limit."""
    if overflow_chunk_count <= 0:
        return _utf8_byte_len(head) <= _LINEAR_CHUNK_LIMIT
    from planning_canonical import rewrite_chunk_manifest_ids

    rewritten = rewrite_chunk_manifest_ids(
        head, _worst_case_linear_overflow_comment_ids(overflow_chunk_count)
    )
    return _utf8_byte_len(rewritten) <= _LINEAR_CHUNK_LIMIT


def _attach_chunk_manifest(
    head: str,
    chunk_comments: list[CommentRecord],
    *,
    write_token: str,
) -> str:
    if not chunk_comments:
        return head
    manifest = {
        "version": 1,
        "chunks": [{"index": idx, "commentId": c.id} for idx, c in enumerate(chunk_comments)],
        "writeToken": write_token,
    }
    marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
    if MARKER_CHUNK_MANIFEST.search(head):
        return MARKER_CHUNK_MANIFEST.sub(marker, head)
    return head + marker


def chunk_body_for_linear(
    body: str,
    comments: list[CommentRecord],
) -> tuple[str, list[CommentRecord]]:
    """Split markdown for Linear description/comment UTF-8 byte limits (PRD 357 R8–R11)."""
    require_linear_size_pin()
    if _utf8_byte_len(body) <= _LINEAR_CHUNK_LIMIT:
        return body, comments

    write_token = uuid.uuid4().hex[:12]
    _raise_if_oversized_closed_set(body)
    positions = _split_positions(body)
    lo, hi = 0, len(positions) - 1
    best: tuple[str, list[CommentRecord]] | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        head_len = positions[mid]
        overflow = body[head_len:]
        extra = (
            _split_overflow_comments(overflow, list(comments), write_token=write_token)
            if overflow
            else list(comments)
        )
        chunk_only = extra[len(comments) :]
        candidate = _attach_chunk_manifest(body[:head_len], chunk_only, write_token=write_token)
        if _utf8_byte_len(candidate) <= _LINEAR_CHUNK_LIMIT and _head_fits_after_uuid_manifest_rewrite(
            candidate, len(chunk_only)
        ):
            best = (candidate, extra)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        leading = _leading_closed_set(body)
        if leading is not None:
            kind, length = leading
            raise LinearOversizedConstructError(kind=kind, length=length)
        raise LinearChunkHeadBudgetError(
            "Linear body chunking failed: no description head fits after UUID manifest rewrite"
        )
    return best


def normalize_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    snap = snapshot_from_fixture(data)
    return {
        "verdict": "ok",
        "contract": SUPPORTED_CONTRACT,
        "canonical": canonical_form(snap),
        "hash": canonical_hash(snap),
        "body": snap.body,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Linear Public Markdown canonicalization (PRD 066 R15)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    norm = sub.add_parser("normalize", help="Normalize a Linear canonical fixture")
    norm.add_argument("--fixture", required=True, help="Path to fixture JSON")
    args = parser.parse_args(argv)
    if args.command == "normalize":
        try:
            result = normalize_fixture(Path(args.fixture))
        except (LinearCanonicalContractError, LinearCanonicalDegradeError) as exc:
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "code": exc.code,
                        "error": exc.message,
                        "contract": SUPPORTED_CONTRACT,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 2
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
