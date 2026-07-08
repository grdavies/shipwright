#!/usr/bin/env python3
"""Feature-named terminal PR / changelog title fixture (PRD 057 R20, gap-034).

Proves, fully offline and deterministically:

1. **PRD-title derivation** — ``commitlint_safe_title`` names the landed
   feature from the PRD's H1 heading (stripped of its ``PRD <n> — ``
   prefix), not the fixed ``deliver wave`` text.
2. **Slug fallback** — when no PRD file resolves, the title-cased task-list
   / target slug names the feature instead.
3. **`prd_feature_title` heading-prefix stripping** covers ``—``, ``-``, and
   ``:`` separators and both bare and lettered PRD numbers (e.g. ``PRD 41A``).
4. **`slug_feature_title`** title-cases hyphen/underscore-separated slugs and
   preserves already-uppercase tokens (e.g. acronyms).
5. **Commit description stays within the commitlint header budget** — a very
   long feature title is truncated at a word boundary rather than exceeding
   the 100-character conventional-commit header limit, and the description
   is fully lowercase so it never trips commitlint's ``subject-case`` rule.
6. **Release-please changelog parity** — since release-please derives its
   changelog line from this same commit description, a landed-feature title
   is exactly what both the terminal PR title and the changelog will show;
   this fixture asserts the single source of truth, not two.

No network, no live issue store required.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import wave_terminal as wt  # noqa: E402


def _seed_prd(root: Path, number: str, slug: str, heading: str) -> Path:
    prd_dir = root / "docs" / "prds" / f"{number}-{slug}"
    prd_dir.mkdir(parents=True, exist_ok=True)
    path = prd_dir / f"{number}-prd-{slug}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "topic: " + slug,
                "visibility: public",
                "---",
                f"# {heading}",
                "",
                "## Overview",
                "",
                "Body text.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def check_prd_title_derivation() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_prd(root, "057", "planning-store-hardening", "PRD 057 — Planning store hardening")
        title = wt.commitlint_safe_title("feat", "planning-store-hardening", "057", root=root)
    ok = title == "feat(prd-57): planning store hardening"
    return {"name": "prd-title-derivation", "ok": ok, "detail": title}


def check_slug_fallback_without_prd_file() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs" / "prds").mkdir(parents=True, exist_ok=True)
        title = wt.commitlint_safe_title("feat", "terminal-gap-auto-capture", "999", root=root)
    ok = title == "feat(prd-999): terminal gap auto capture"
    return {"name": "slug-fallback-without-prd-file", "ok": ok, "detail": title}


def check_never_emits_fixed_deliver_wave_text() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_prd(root, "057", "planning-store-hardening", "PRD 057 — Planning store hardening")
        with_prd = wt.commitlint_safe_title("feat", "planning-store-hardening", "057", root=root)
        without_root = wt.commitlint_safe_title("feat", "some-feature-slug", None)
    ok = "deliver wave" not in with_prd and "deliver wave" not in without_root
    return {"name": "never-emits-fixed-deliver-wave-text", "ok": ok, "detail": [with_prd, without_root]}


def check_heading_prefix_stripping_variants() -> dict:
    cases = [
        ("PRD 057 — Planning store hardening", "Planning store hardening"),
        ("PRD 057 - Planning store hardening", "Planning store hardening"),
        ("PRD 057: Planning store hardening", "Planning store hardening"),
        ("PRD 41A — Memory backend hardening", "Memory backend hardening"),
        ("Planning store hardening", "Planning store hardening"),
    ]
    mismatches = []
    for heading, expected in cases:
        stripped = wt._PRD_HEADING_PREFIX_RE.sub("", heading).strip()
        if stripped != expected:
            mismatches.append((heading, expected, stripped))
    return {"name": "heading-prefix-stripping-variants", "ok": not mismatches, "detail": mismatches or "all-match"}


def check_prd_feature_title_reads_h1() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_prd(root, "058", "example-feature", "PRD 058 — Example feature name")
        title = wt.prd_feature_title(root, "058")
    ok = title == "Example feature name"
    return {"name": "prd-feature-title-reads-h1", "ok": ok, "detail": title}


def check_prd_feature_title_missing_returns_none() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        title = wt.prd_feature_title(root, "999")
    ok = title is None
    return {"name": "prd-feature-title-missing-returns-none", "ok": ok, "detail": title}


def check_slug_feature_title_casing() -> dict:
    cases = [
        ("terminal-gap-auto-capture", "Terminal Gap Auto Capture"),
        ("memory_backend_round_trip", "Memory Backend Round Trip"),
        ("", "deliver wave"),
    ]
    mismatches = [
        (slug, expected, wt.slug_feature_title(slug))
        for slug, expected in cases
        if wt.slug_feature_title(slug) != expected
    ]
    return {"name": "slug-feature-title-casing", "ok": not mismatches, "detail": mismatches or "all-match"}


def check_commit_description_lowercase_and_truncated() -> dict:
    long_title = (
        "A very extraordinarily long feature title that goes on and on describing "
        "every single nuance of the change in exhaustive detail"
    )
    prefix = "feat(prd-57): "
    desc = wt.commit_description(long_title, prefix_len=len(prefix))
    header = prefix + desc
    ok = (
        len(header) <= 100
        and desc == desc.lower()
        and not header.endswith(" ")
        and long_title.lower().startswith(desc)
    )
    return {"name": "commit-description-lowercase-and-truncated", "ok": ok, "detail": {"header": header, "len": len(header)}}


def check_commit_description_short_title_unchanged() -> dict:
    desc = wt.commit_description("Planning store hardening", prefix_len=len("feat(prd-57): "))
    ok = desc == "planning store hardening"
    return {"name": "commit-description-short-title-unchanged", "ok": ok, "detail": desc}


def check_pr_and_changelog_title_share_one_source() -> dict:
    """Terminal PR title and release-please changelog both derive from the same
    commit description — asserting the single source of truth (R20)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_prd(root, "057", "planning-store-hardening", "PRD 057 — Planning store hardening")
        pr_title = wt.commitlint_safe_title("feat", "planning-store-hardening", "057", root=root)
    # release-please parses the conventional-commit header itself; the
    # changelog entry it emits is the description half of this same title.
    changelog_line = pr_title.split(": ", 1)[1]
    ok = changelog_line == "planning store hardening" and pr_title.endswith(changelog_line)
    return {"name": "pr-and-changelog-title-share-one-source", "ok": ok, "detail": pr_title}


def main() -> int:
    checks = [
        check_prd_title_derivation(),
        check_slug_fallback_without_prd_file(),
        check_never_emits_fixed_deliver_wave_text(),
        check_heading_prefix_stripping_variants(),
        check_prd_feature_title_reads_h1(),
        check_prd_feature_title_missing_returns_none(),
        check_slug_feature_title_casing(),
        check_commit_description_lowercase_and_truncated(),
        check_commit_description_short_title_unchanged(),
        check_pr_and_changelog_title_share_one_source(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "terminal-title",
        "rid": "R20",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
