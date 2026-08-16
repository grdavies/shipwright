#!/usr/bin/env python3
"""Path glob matching for detector intake surfaces."""
from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    chunks = pattern.split("**")
    for index, chunk in enumerate(chunks):
        chunk = chunk.strip("/")
        if chunk:
            parts.append(
                re.escape(chunk).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
            )
        if index < len(chunks) - 1:
            parts.append(".*")
    return re.compile("^" + "".join(parts) + "$")


def path_matches_glob(path: str, pattern: str) -> bool:
    """Match a repo-relative posix path against a glob pattern."""
    normalized = path.replace("\\", "/").lstrip("./")
    if pattern.startswith("**/") and pattern.endswith("/**"):
        middle = pattern[3:-3]
        haystack = f"/{normalized}/"
        return f"/{middle}/" in haystack
    if "**" in pattern:
        return _glob_to_regex(pattern).match(normalized) is not None
    return fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(
        PurePosixPath(normalized).name, pattern
    )


def classify_path(path: str, intake_surfaces: tuple[str, ...]) -> bool:
    return any(path_matches_glob(path, surface) for surface in intake_surfaces)
