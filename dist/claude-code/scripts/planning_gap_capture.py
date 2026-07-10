#!/usr/bin/env python3
"""Canonical gap unit capture from feedback signals (PRD 033 R15; PRD 041 meta channel)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig
import planning_paths as pp
import planning_store as ps
import sw_state_write_lib as writer
from planning_query_cache import invalidate_all

GAP_CLAIM_DIR_REL = ".cursor/hooks/state/planning-gap-claims"
MAX_GAP_ALLOCATION_ATTEMPTS = 50

# Terminal auto-capture (PRD 057 R19, gap-032): a deliver run whose verdict
# lands in this set never mints gap units — a broken or aborted wave is noise
# about the wave itself, not evidence of unaddressed planning-store pain.
SUPPRESS_TERMINAL_VERDICTS = frozenset({"fail", "aborted", "blocked", "rejected"})
# Statuses short of "resolved" are still open for dedup purposes — a gap
# already scheduled into a wave is tracked, so terminal capture must not
# mint a second unit for the same pain.
STILL_OPEN_GAP_STATUSES = frozenset({"open", "scheduled", ""})
SUBSTANTIAL_SEVERITIES = frozenset({"high", "critical"})
SUBSTANTIAL_CATEGORIES = frozenset(
    {
        "post-merge-revert",
        "reopened-phases",
        "remediation-exhausted",
        "watchdog-halt",
    }
)
SUBSTANTIAL_MIN_RECURRENCE = 2
DEFAULT_MAX_TERMINAL_CAPTURES = 3
VERIFY_OVERRIDE_CLASSES = frozenset({"no-baseline", "unattributed"})
VERIFY_OVERRIDE_SOURCE = "verify-override"

GAP_DRAFT_INBOX_REL = ".cursor/sw-gap-draft-inbox"
DEFAULT_DRAFT_STALE_DAYS = 14

GAP_SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "problem": re.compile(r"^##\s+Problem\s*$", re.MULTILINE | re.IGNORECASE),
    "context": re.compile(r"^##\s+Context(?:/evidence)?\s*$", re.MULTILINE | re.IGNORECASE),
    "related": re.compile(r"^##\s+Related units\s*$", re.MULTILINE | re.IGNORECASE),
    "next": re.compile(r"^##\s+Suggested next step\s*$", re.MULTILINE | re.IGNORECASE),
}



def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "feedback-gap"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def meta_inbox_path(root: Path, signal_id: str) -> Path:
    return root / ".cursor" / "sw-meta-inbox" / f"{signal_id}.json"


def load_meta_draft(root: Path, signal_id: str) -> dict[str, Any]:
    path = meta_inbox_path(root, signal_id)
    if not path.is_file():
        fail("meta inbox draft not found", signalId=signal_id, halt="meta-draft-missing")
    return writer.load_store(path)





def gap_enrichment_status(content: str) -> dict[str, bool]:
    """Return which PRD 061 R17 enrichment sections are present."""
    return {key: bool(pat.search(content)) for key, pat in GAP_SECTION_PATTERNS.items()}


def require_gap_enrichment(content: str) -> None:
    """Fail closed when authoritative gap content lacks required sections (R17)."""
    status = gap_enrichment_status(content)
    missing = [key for key in ("problem", "context", "related", "next") if not status[key]]
    if missing:
        fail(
            "gap-enrichment-required",
            halt="gap-enrichment-required",
            missing=missing,
        )


def gap_draft_inbox_dir(root: Path) -> Path:
    path = pp.git_root(root) / GAP_DRAFT_INBOX_REL
    path.mkdir(parents=True, exist_ok=True)
    return path


def gap_draft_inbox_path(root: Path, signal_id: str) -> Path:
    return gap_draft_inbox_dir(root) / f"{signal_id}.json"


def put_gap_draft(root: Path, *, signal_id: str, title: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Durable store-backed gap draft inbox (PRD 061 R17)."""
    draft = {
        "signalId": signal_id,
        "title": title,
        "status": "draft",
        "capturedAt": utc_now(),
        **payload,
    }
    path = gap_draft_inbox_path(root, signal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "signalId": signal_id,
        "path": str(gap_draft_inbox_path(root, signal_id).resolve().relative_to(pp.git_root(root).resolve())),
        "status": "draft",
    }


def load_gap_draft(root: Path, signal_id: str) -> dict[str, Any]:
    path = gap_draft_inbox_path(root, signal_id)
    if not path.is_file():
        fail("gap draft inbox entry not found", signalId=signal_id, halt="gap-draft-missing")
    return writer.load_store(path)


def list_gap_drafts(root: Path, *, stale_days: int = DEFAULT_DRAFT_STALE_DAYS) -> dict[str, Any]:
    """Queryable inbox with staleness notice policy (R17a)."""
    inbox = gap_draft_inbox_dir(root)
    drafts: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for path in sorted(inbox.glob("*.json")):
        try:
            draft = writer.load_store(path)
        except Exception:
            continue
        if draft.get("status") == "materialized":
            continue
        entry = {
            "signalId": draft.get("signalId") or path.stem,
            "title": draft.get("title", ""),
            "status": draft.get("status", "draft"),
            "capturedAt": draft.get("capturedAt", ""),
        }
        drafts.append(entry)
        captured = str(draft.get("capturedAt") or "")
        if captured:
            try:
                captured_at = datetime.strptime(captured, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                age_days = (now - captured_at).days
                if age_days >= stale_days:
                    stale.append({**entry, "ageDays": age_days})
            except ValueError:
                pass
    return {
        "verdict": "ok",
        "drafts": drafts,
        "stale": stale,
        "staleNoticePolicy": f"operator-notice-after-{stale_days}-days",
    }


def build_enriched_gap_content(
    *,
    unit_id: str,
    title: str,
    problem: str,
    context: str,
    related: str = "none",
    next_step: str = "triage",
    tags: list[str] | None = None,
    extra_frontmatter: list[str] | None = None,
) -> str:
    tag_list = tags or []
    fm = [
        "---",
        f"id: {unit_id}",
        "type: gap",
        "status: open",
        f"title: {title}",
        "visibility: public",
    ]
    if tag_list:
        fm.append(f"tags: [{', '.join(tag_list)}]")
    if extra_frontmatter:
        fm.extend(extra_frontmatter)
    fm.extend(
        [
            "---",
            "",
            f"# {title}",
            "",
            "## Problem",
            "",
            problem.strip(),
            "",
            "## Context/evidence",
            "",
            context.strip(),
            "",
            "## Related units",
            "",
            related.strip(),
            "",
            "## Suggested next step",
            "",
            next_step.strip(),
            "",
        ]
    )
    return "\n".join(fm) + "\n"


def gap_body_rel(dirs: pp.PlanningDirs, unit_id: str) -> str:
    return pp.join_rel(dirs.prds, "gap", unit_id, f"{unit_id}.md")


def store_put_gap(
    root: Path,
    unit_id: str,
    body_path_rel: str,
    content: str,
    *,
    skip_enrichment: bool = False,
) -> None:
    if not skip_enrichment:
        require_gap_enrichment(content)
    backend = ps.get_backend(root)
    result = backend.put(unit_id, body_path_rel, content)
    if result.verdict not in ("ok", "deferred"):
        fail("planning_store.put failed", unitId=unit_id, backend=result.backend, reason=result.reason)
    try:
        from planning_migrate_issue_store import (
            issue_store_effective,
            refresh_gap_backlog_projection,
            sync_gap_issue_labels,
            sync_issue_native_links_from_content,
            try_sunset_gap_backlog_projection,
        )

        if issue_store_effective(root):
            sync_gap_issue_labels(root, unit_id, content)
            sync_issue_native_links_from_content(root, unit_id, content)
            refresh_gap_backlog_projection(root, apply=True)
    except ImportError:
        pass

def next_gap_number(root: Path, units: list[pig.PlanningUnit]) -> int:
    max_n = 0
    for unit in units:
        m = re.match(r"gap-(\d+)-", unit.id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    for key in ps.load_issue_unit_index(root):
        if not key.startswith("planning:gap-"):
            continue
        uid = key.split(":", 1)[1]
        m = re.match(r"gap-(\d+)-", uid)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _gap_claim_dir(root: Path) -> Path:
    path = pp.git_root(root) / GAP_CLAIM_DIR_REL
    path.mkdir(parents=True, exist_ok=True)
    return path


def _claim_gap_number(root: Path, number: int) -> bool:
    """Atomic claim-by-create for a candidate gap number (PRD 057 R25).

    ``O_CREAT | O_EXCL`` serializes concurrent allocators against the same
    worktree: the first caller to create the claim file wins the number, and
    every other concurrent caller observes ``FileExistsError`` and retries
    with the next candidate instead of racing the remote issue-store create.
    """
    claim_path = _gap_claim_dir(root) / f"{number:03d}.claim"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(claim_path, flags, 0o600)
    except FileExistsError:
        return False
    os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    os.close(fd)
    return True


def allocate_gap_unit_id(root: Path, title: str, body_path_for: Callable[[str], str]) -> tuple[str, str]:
    """Atomic gap-number allocation (PRD 057 R25).

    Invalidates the query cache before every allocation attempt so
    ``next_gap_number`` is computed against the freshest live unit-id set
    (R10), then claims the candidate number by create; a collision — either a
    local claim already held by a concurrent allocator, or a monotonic
    candidate below the last locally-attempted number — retries with the
    next number so concurrent writers never persist duplicate gap ids or
    split ``absorbs`` edges.
    """
    last_candidate = 0
    for _attempt in range(MAX_GAP_ALLOCATION_ATTEMPTS):
        invalidate_all(root)
        units = pig.discover_units(root)
        candidate = max(next_gap_number(root, units), last_candidate + 1)
        if _claim_gap_number(root, candidate):
            unit_id = f"gap-{candidate:03d}-{slugify(title)}"
            return unit_id, body_path_for(unit_id)
        last_candidate = candidate
    fail(
        "gap-number-allocation-exhausted-retries",
        attempts=MAX_GAP_ALLOCATION_ATTEMPTS,
    )


def normalize_gap_title(title: str) -> str:
    """Comparable key for title-based gap dedup (R19)."""
    return re.sub(r"\s+", " ", title.strip().lower())


def _scan_gap_titles_under(type_root: Path) -> dict[str, str]:
    """Direct frontmatter scan of a ``<root>/gap/*`` tree for still-open titles."""
    out: dict[str, str] = {}
    gap_root = type_root / "gap"
    if not gap_root.is_dir():
        return out
    for unit_dir in sorted(gap_root.iterdir()):
        if not unit_dir.is_dir():
            continue
        body = pig.body_file_for_unit_dir(unit_dir)
        if not body:
            continue
        try:
            fm = pig.parse_frontmatter(body.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not fm:
            continue
        unit_id = str(fm.get("id", "")).strip()
        title = str(fm.get("title", "")).strip()
        status = str(fm.get("status", "")).strip()
        if not unit_id or not title or status not in STILL_OPEN_GAP_STATUSES:
            continue
        out.setdefault(normalize_gap_title(title), unit_id)
    return out


def list_open_gap_titles(root: Path) -> dict[str, str]:
    """Normalized still-open gap title -> unit id (R19).

    Considers ``open`` and ``scheduled`` gaps — i.e. anything short of
    ``resolved`` — so terminal auto-capture never mints a duplicate for pain
    that is already tracked, whether or not it has been scheduled into a
    wave yet. Invalidates the query cache first so the picture is fresh
    (R10), matching the freshness discipline ``allocate_gap_unit_id`` already
    applies before every allocation attempt.

    ``discover_units`` is authoritative for the issue-store backend. For
    file-backed corpora it only scans ``dirs.planning`` (the R7 migration
    target), while ``capture_gap``/``gap_body_rel`` still write under the
    legacy ``dirs.prds`` alias — so this also scans both roots directly to
    guarantee terminal capture always sees gaps this same mechanism wrote,
    regardless of which side of that in-flight migration is active.
    """
    invalidate_all(root)
    out: dict[str, str] = {}
    for unit in pig.discover_units(root):
        if unit.type != "gap":
            continue
        if unit.status not in STILL_OPEN_GAP_STATUSES:
            continue
        title = (unit.title or "").strip()
        if not title:
            continue
        out.setdefault(normalize_gap_title(title), unit.id)
    worktree = pp.git_root(root)
    dirs = pp.load_planning_dirs(root)
    for type_dir in {dirs.planning, dirs.prds}:
        for key, unit_id in _scan_gap_titles_under(worktree / type_dir).items():
            out.setdefault(key, unit_id)
    return out


def find_duplicate_open_gap(title: str, open_titles: dict[str, str]) -> str | None:
    return open_titles.get(normalize_gap_title(title))


def redact_override_reason(reason: str) -> str:
    from memory_redact import redact

    return redact(reason)


def _normalize_override_anchor(
    *,
    unit_id: str | None,
    pr_number: int | None,
    commit_sha: str | None,
) -> str:
    parts: list[str] = []
    if unit_id:
        parts.append(f"unit:{unit_id}")
    if pr_number is not None:
        parts.append(f"pr:{pr_number}")
    if commit_sha:
        parts.append(f"commit:{commit_sha[:12]}")
    return "|".join(parts) or "global"


def verify_override_signature(
    override: dict[str, Any],
    *,
    unit_id: str | None = None,
    pr_number: int | None = None,
    commit_sha: str | None = None,
) -> str:
    """Deterministic verify-override signature (PRD 060 R9)."""
    inconclusive = str(override.get("inconclusiveClass") or "").strip().lower()
    anchor = _normalize_override_anchor(
        unit_id=unit_id,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )
    raw = f"{inconclusive}|{anchor}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _gap_tags_from_frontmatter(fm: dict[str, Any]) -> list[str]:
    tags = fm.get("tags")
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    if isinstance(tags, str) and tags.strip():
        return [tags.strip()]
    return []


def _scan_open_gap_signals(type_root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    gap_root = type_root / "gap"
    if not gap_root.is_dir():
        return out
    for unit_dir in sorted(gap_root.iterdir()):
        if not unit_dir.is_dir():
            continue
        body = pig.body_file_for_unit_dir(unit_dir)
        if not body:
            continue
        try:
            fm = pig.parse_frontmatter(body.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not fm:
            continue
        unit_id = str(fm.get("id", "")).strip()
        status = str(fm.get("status", "")).strip()
        if not unit_id or status not in STILL_OPEN_GAP_STATUSES:
            continue
        for tag in _gap_tags_from_frontmatter(fm):
            if tag.startswith("signal:"):
                out.setdefault(tag.split(":", 1)[1], unit_id)
    return out


def list_open_gap_signals(root: Path) -> dict[str, str]:
    invalidate_all(root)
    out: dict[str, str] = {}
    worktree = pp.git_root(root)
    dirs = pp.load_planning_dirs(root)
    for type_dir in {dirs.planning, dirs.prds}:
        for signal, unit_id in _scan_open_gap_signals(worktree / type_dir).items():
            out.setdefault(signal, unit_id)
    return out


def find_open_gap_by_signal(root: Path, signal_id: str) -> str | None:
    return list_open_gap_signals(root).get(signal_id)


def capture_verify_override(
    root: Path,
    override: dict[str, Any],
    *,
    unit_id: str | None = None,
    pr_number: int | None = None,
    commit_sha: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Auto-file durable follow-up gap for verify/ship overrides (PRD 060 R8–R9)."""
    inconclusive = str(override.get("inconclusiveClass") or "").strip().lower()
    if inconclusive not in VERIFY_OVERRIDE_CLASSES:
        return {
            "action": "skipped",
            "reason": f"inconclusiveClass {inconclusive!r} does not require verify-override gap",
        }
    signature = verify_override_signature(
        override,
        unit_id=unit_id,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )
    existing = find_open_gap_by_signal(root, signature)
    if existing:
        return {
            "action": "reused",
            "unitId": existing,
            "signature": signature,
            "deduped": True,
        }
    redacted_reason = redact_override_reason(str(override.get("reason") or ""))
    who = str(override.get("who") or "unknown").strip()
    title = f"Verify override follow-up: {inconclusive}"
    dirs = pp.load_planning_dirs(root)
    new_unit_id, body_path_rel = allocate_gap_unit_id(
        root, title, lambda uid: gap_body_rel(dirs, uid)
    )
    tags = [
        f"source:{VERIFY_OVERRIDE_SOURCE}",
        f"inconclusive:{inconclusive}",
        f"signal:{signature}",
    ]
    fm = [
        "---",
        f"id: {new_unit_id}",
        "type: gap",
        "status: open",
        f"title: {title}",
        "visibility: public",
        f"tags: [{', '.join(tags)}]",
    ]
    if pr_number is not None:
        fm.append(f"source_pr: {pr_number}")
    fm.extend(
        [
            "---",
            "",
            f"# {title}",
            "",
            "_Captured from verification override — override alone is insufficient; "
            "this gap tracks durable follow-up._",
            "",
            "## Problem",
            "",
            f"Verification override ({inconclusive}) requires durable follow-up.",
            "",
            "## Context/evidence",
            "",
            f"- who: {who}",
            f"- inconclusiveClass: {inconclusive}",
            f"- reason: {redacted_reason}",
            "",
            "## Related units",
            "",
            "none",
            "",
            "## Suggested next step",
            "",
            "triage",
            "",
        ]
    )
    content = "\n".join(fm) + "\n"
    if not dry_run:
        store_put_gap(root, new_unit_id, body_path_rel, content)
    return {
        "action": "created",
        "unitId": new_unit_id,
        "path": body_path_rel,
        "signature": signature,
        "deduped": False,
    }


def capture_gap(
    root: Path,
    *,
    signal_id: str,
    title: str,
    pr_number: int | None = None,
    dry_run: bool = False,
    dedupe: bool = False,
    open_titles: dict[str, str] | None = None,
    problem: str | None = None,
    context: str | None = None,
    authoritative: bool = False,
) -> dict[str, Any]:
    if dedupe:
        existing = find_duplicate_open_gap(title, open_titles if open_titles is not None else list_open_gap_titles(root))
        if existing:
            return {"unitId": existing, "signalId": signal_id, "deduped": True}
    if not authoritative and (not problem or not context):
        if dry_run:
            return {
                "signalId": signal_id,
                "action": "draft-inbox",
                "title": title,
                "deduped": False,
            }
        draft = put_gap_draft(
            root,
            signal_id=signal_id,
            title=title,
            payload={
                "prNumber": pr_number,
                "stub": True,
            },
        )
        return {"signalId": signal_id, "action": "draft-inbox", "deduped": False, **draft}
    dirs = pp.load_planning_dirs(root)
    unit_id, body_path_rel = allocate_gap_unit_id(root, title, lambda uid: gap_body_rel(dirs, uid))
    content = build_enriched_gap_content(
        unit_id=unit_id,
        title=title,
        problem=problem or title,
        context=context or f"_Captured from feedback signal `{signal_id}`._",
        related="none",
        next_step="triage",
        tags=[f"source:feedback", f"signal:{signal_id}"],
        extra_frontmatter=[f"source_pr: {pr_number}"] if pr_number is not None else None,
    )
    if not dry_run:
        store_put_gap(root, unit_id, body_path_rel, content)
    return {"unitId": unit_id, "path": body_path_rel, "signalId": signal_id, "deduped": False, "action": "gap-capture"}


def classify_pain_item(item: dict[str, Any]) -> str:
    """Substantial-vs-noise heuristic (R19, gap-032).

    A single low-severity blip is noise — never captured, so a broken wave
    cannot flood the shared planning repo. Anything that already carries
    high/critical severity, matches a category that always matters, or has
    recurred at least :data:`SUBSTANTIAL_MIN_RECURRENCE` times is substantial
    and requires human confirmation before a gap unit is minted.
    """
    severity = str(item.get("severity") or "low").strip().lower()
    category = str(item.get("category") or "").strip().lower()
    try:
        recurrence = int(item.get("recurrence") or 1)
    except (TypeError, ValueError):
        recurrence = 1
    if severity in SUBSTANTIAL_SEVERITIES:
        return "substantial"
    if category in SUBSTANTIAL_CATEGORIES:
        return "substantial"
    if recurrence >= SUBSTANTIAL_MIN_RECURRENCE:
        return "substantial"
    return "noise"


def terminal_capture(
    root: Path,
    *,
    verdict: str,
    pain_items: list[dict[str, Any]],
    max_captures: int = DEFAULT_MAX_TERMINAL_CAPTURES,
    dry_run: bool = False,
    pr_number: int | None = None,
    confirmed_signal_ids: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Terminal auto-capture of unaddressed planning-store pain (R19, gap-032).

    Scans caller-supplied ``pain_items`` (the caller derives these from its
    own run-log + loop-health scan) and, unless ``verdict`` is one of
    :data:`SUPPRESS_TERMINAL_VERDICTS`:

    - dedups every candidate against currently open gap titles — not only
      signal ids — so repeated terminal runs never mint duplicates;
    - classifies each remaining candidate via :func:`classify_pain_item`;
      noise is silently skipped;
    - never auto-captures a substantial item: it is recorded in ``pending``
      unless its ``signalId`` appears in ``confirmed_signal_ids`` (or the
      item itself carries ``confirmed: true``), modeling the required human
      confirmation gate;
    - caps the number of gap units actually written in one run at
      ``max_captures`` — confirmed items beyond the cap also land in
      ``pending`` (reason ``cap-reached``) rather than being dropped.
    """
    verdict_key = str(verdict or "").strip().lower()
    if verdict_key in SUPPRESS_TERMINAL_VERDICTS:
        return {
            "verdict": "suppressed",
            "reason": f"deliver verdict {verdict_key!r} suppresses terminal gap capture",
            "captured": [],
            "pending": [],
            "skippedDuplicate": [],
            "skippedNoise": [],
        }
    confirmed = confirmed_signal_ids or frozenset()
    open_titles = list_open_gap_titles(root)
    captured: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    skipped_duplicate: list[dict[str, Any]] = []
    skipped_noise: list[dict[str, Any]] = []
    for item in pain_items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        signal_id = str(item.get("signalId") or item.get("signal_id") or title)
        existing = find_duplicate_open_gap(title, open_titles)
        if existing:
            skipped_duplicate.append({"title": title, "signalId": signal_id, "existingUnitId": existing})
            continue
        classification = classify_pain_item(item)
        if classification == "noise":
            skipped_noise.append({"title": title, "signalId": signal_id, "classification": classification})
            continue
        if not (item.get("confirmed") or signal_id in confirmed):
            pending.append(
                {
                    "title": title,
                    "signalId": signal_id,
                    "classification": classification,
                    "reason": "awaiting-human-confirmation",
                }
            )
            continue
        if len(captured) >= max_captures:
            pending.append(
                {
                    "title": title,
                    "signalId": signal_id,
                    "classification": classification,
                    "reason": "cap-reached",
                }
            )
            continue
        out = capture_gap(
            root,
            signal_id=signal_id,
            title=title,
            pr_number=pr_number,
            dry_run=dry_run,
            dedupe=True,
            open_titles=open_titles,
        )
        captured.append(out)
        if not out.get("deduped") and out.get("unitId"):
            open_titles[normalize_gap_title(title)] = out["unitId"]
    return {
        "verdict": "pass",
        "captured": captured,
        "pending": pending,
        "skippedDuplicate": skipped_duplicate,
        "skippedNoise": skipped_noise,
        "maxCaptures": max_captures,
    }


def capture_meta_draft(
    root: Path,
    *,
    signal_id: str,
    title: str,
    summary: str = "",
) -> dict[str, Any]:
    draft = {
        "signalId": signal_id,
        "destination": "meta-shipwright",
        "gapClass": "plugin-self",
        "title": title,
        "status": "draft",
        "capturedAt": utc_now(),
    }
    if summary:
        draft["summary"] = summary
    writer.cmd_write(
        root,
        store="meta-inbox-draft",
        data=draft,
        rel=f"{signal_id}.json",
    )
    return {
        "signalId": signal_id,
        "destination": "meta-shipwright",
        "path": str(meta_inbox_path(root, signal_id).relative_to(root)),
    }


def confirm_meta_draft(root: Path, *, signal_id: str) -> dict[str, Any]:
    draft = load_meta_draft(root, signal_id)
    if draft.get("status") == "materialized":
        fail("draft already materialized", signalId=signal_id)
    draft["status"] = "confirmed"
    draft["confirmedAt"] = utc_now()
    writer.cmd_write(
        root,
        store="meta-inbox-draft",
        data=draft,
        rel=f"{signal_id}.json",
    )
    return {"signalId": signal_id, "status": "confirmed"}


def materialize_meta_gap(
    root: Path,
    *,
    signal_id: str,
    title: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    draft = load_meta_draft(root, signal_id)
    if draft.get("status") != "confirmed":
        fail("materialize requires confirmed draft", signalId=signal_id, status=draft.get("status"))
    dirs = pp.load_planning_dirs(root)
    unit_id, body_path_rel = allocate_gap_unit_id(
        root, title, lambda uid: pp.join_rel(pp.plugin_self_gap_dir(dirs), uid, f"{uid}.md")
    )
    summary = str(draft.get("summary") or "").strip()
    context = summary or f"_Materialized from meta-shipwright signal `{signal_id}`._"
    content = build_enriched_gap_content(
        unit_id=unit_id,
        title=title,
        problem=title,
        context=context,
        related="none",
        next_step="triage",
        tags=["plugin-self", "meta-shipwright", "source:feedback", f"signal:{signal_id}"],
    )
    if not dry_run:
        store_put_gap(root, unit_id, body_path_rel, content)
        draft["status"] = "materialized"
        draft["materializedUnitId"] = unit_id
        writer.cmd_write(
            root,
            store="meta-inbox-draft",
            data=draft,
            rel=f"{signal_id}.json",
        )
    return {
        "unitId": unit_id,
        "path": body_path_rel,
        "signalId": signal_id,
        "gapClass": "plugin-self",
    }



def materialize_gap_draft(
    root: Path,
    *,
    signal_id: str,
    problem: str,
    context: str,
    related: str = "none",
    next_step: str = "triage",
    dry_run: bool = False,
) -> dict[str, Any]:
    draft = load_gap_draft(root, signal_id)
    if draft.get("status") == "materialized":
        fail("draft already materialized", signalId=signal_id)
    title = str(draft.get("title") or signal_id)
    dirs = pp.load_planning_dirs(root)
    unit_id, body_path_rel = allocate_gap_unit_id(root, title, lambda uid: gap_body_rel(dirs, uid))
    tags = [f"source:feedback", f"signal:{signal_id}"]
    extra: list[str] = []
    if draft.get("prNumber") is not None:
        extra.append(f"source_pr: {draft['prNumber']}")
    content = build_enriched_gap_content(
        unit_id=unit_id,
        title=title,
        problem=problem,
        context=context,
        related=related,
        next_step=next_step,
        tags=tags,
        extra_frontmatter=extra or None,
    )
    if not dry_run:
        store_put_gap(root, unit_id, body_path_rel, content)
        draft["status"] = "materialized"
        draft["materializedUnitId"] = unit_id
        draft["materializedAt"] = utc_now()
        path = gap_draft_inbox_path(root, signal_id)
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "unitId": unit_id,
        "path": body_path_rel,
        "signalId": signal_id,
        "action": "gap-materialize",
    }


def parse_flags(rest: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"dry_run": False}
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--dry-run":
            out["dry_run"] = True
            i += 1
        elif tok == "--signal-id" and i + 1 < len(rest):
            out["signal_id"] = rest[i + 1]
            i += 2
        elif tok == "--title" and i + 1 < len(rest):
            out["title"] = rest[i + 1]
            i += 2
        elif tok == "--summary" and i + 1 < len(rest):
            out["summary"] = rest[i + 1]
            i += 2
        elif tok == "--destination" and i + 1 < len(rest):
            out["destination"] = rest[i + 1]
            i += 2
        elif tok == "--pr" and i + 1 < len(rest):
            out["pr_number"] = int(rest[i + 1])
            i += 2
        elif tok == "--unit-id" and i + 1 < len(rest):
            out["unit_id"] = rest[i + 1]
            i += 2
        elif tok == "--override" and i + 1 < len(rest):
            out["override_json"] = rest[i + 1]
            i += 2
        elif tok == "--problem" and i + 1 < len(rest):
            out["problem"] = rest[i + 1]
            i += 2
        elif tok == "--context" and i + 1 < len(rest):
            out["context"] = rest[i + 1]
            i += 2
        elif tok == "--related" and i + 1 < len(rest):
            out["related"] = rest[i + 1]
            i += 2
        elif tok == "--next-step" and i + 1 < len(rest):
            out["next_step"] = rest[i + 1]
            i += 2
        elif tok == "--content" and i + 1 < len(rest):
            out["content"] = rest[i + 1]
            i += 2
        elif tok == "--stale-days" and i + 1 < len(rest):
            out["stale_days"] = int(rest[i + 1])
            i += 2
        else:
            i += 1
    return out


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail(
            "usage: planning_gap_capture.py <repo-root> "
            "<capture|confirm|materialize|materialize-draft|draft-inbox-list|validate-enrichment|capture-verify-override> [options]"
        )
    root = Path(args[0]).resolve()
    command = args[1]
    flags = parse_flags(args[2:])

    if command == "capture":
        signal_id = flags.get("signal_id")
        title = flags.get("title")
        if not signal_id or not title:
            fail("--signal-id and --title required for capture")
        if flags.get("destination") == "meta-shipwright":
            out = capture_meta_draft(
                root,
                signal_id=signal_id,
                title=title,
                summary=str(flags.get("summary") or ""),
            )
            emit({"verdict": "pass", "action": "meta-capture", **out})
            return
        out = capture_gap(
            root,
            signal_id=signal_id,
            title=title,
            pr_number=flags.get("pr_number"),
            dry_run=bool(flags.get("dry_run")),
            problem=flags.get("problem"),
            context=flags.get("context"),
            authoritative=bool(flags.get("authoritative")),
        )
        emit({"verdict": "pass", **out})

    if command == "confirm":
        signal_id = flags.get("signal_id")
        if not signal_id:
            fail("--signal-id required for confirm")
        out = confirm_meta_draft(root, signal_id=signal_id)
        emit({"verdict": "pass", "action": "meta-confirm", **out})

    if command == "materialize":
        signal_id = flags.get("signal_id")
        title = flags.get("title")
        if not signal_id or not title:
            fail("--signal-id and --title required for materialize")
        out = materialize_meta_gap(
            root,
            signal_id=signal_id,
            title=title,
            dry_run=bool(flags.get("dry_run")),
        )
        emit({"verdict": "pass", "action": "meta-materialize", **out})



    if command == "draft-inbox-list":
        stale_days = int(flags.get("stale_days") or DEFAULT_DRAFT_STALE_DAYS)
        emit(list_gap_drafts(root, stale_days=stale_days))
        return

    if command == "materialize-draft":
        signal_id = flags.get("signal_id")
        problem = flags.get("problem")
        context = flags.get("context")
        if not signal_id or not problem or not context:
            fail("--signal-id, --problem, and --context required for materialize-draft")
        out = materialize_gap_draft(
            root,
            signal_id=signal_id,
            problem=problem,
            context=context,
            related=str(flags.get("related") or "none"),
            next_step=str(flags.get("next_step") or "triage"),
            dry_run=bool(flags.get("dry_run")),
        )
        emit({"verdict": "pass", **out})
        return

    if command == "validate-enrichment":
        content = flags.get("content")
        if not content:
            fail("--content required for validate-enrichment")
        require_gap_enrichment(content)
        emit({"verdict": "pass", "action": "validate-enrichment"})
        return

    if command == "capture-verify-override":
        override_json = flags.get("override_json")
        if not override_json:
            fail("--override required for capture-verify-override")
        payload = json.loads(override_json)
        if not isinstance(payload, dict):
            fail("capture-verify-override requires JSON override object")
        out = capture_verify_override(
            root,
            payload,
            unit_id=flags.get("unit_id"),
            pr_number=flags.get("pr_number"),
            dry_run=bool(flags.get("dry_run")),
        )
        emit({"verdict": "pass", "action": "capture-verify-override", **out})
        return

    if command == "refresh-projection":
        try:
            from planning_migrate_issue_store import (
                refresh_gap_backlog_projection,
                try_sunset_gap_backlog_projection,
            )
        except ImportError as exc:
            fail(f"refresh-projection unavailable: {exc}")
        projection = refresh_gap_backlog_projection(root, apply=not bool(flags.get("dry_run")))
        sunset = try_sunset_gap_backlog_projection(root, apply=not bool(flags.get("dry_run")))
        emit({"verdict": "pass", "action": "refresh-projection", "projection": projection, "sunset": sunset})

    fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
