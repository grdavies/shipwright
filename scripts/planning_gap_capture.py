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
VERIFY_OVERRIDE_RECURRENCE_REL = ".cursor/hooks/state/verify-override-recurrence"

GAP_DRAFT_INBOX_REL = ".cursor/sw-gap-draft-inbox"
DEFAULT_DRAFT_STALE_DAYS = 14
RETRO_GAP_ROUTE_REL = ".cursor/hooks/state/retro-gap-routes"
RETRO_GAP_KIND = "painful"
DEFAULT_RETRO_MAX_CAPTURES = 3

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
) -> dict[str, Any]:
    """Store gap body respecting write disposition for projection writes (R26 phase 8)."""
    import planning_authority as pa
    import planning_projection_ledger as ppl
    import planning_refusal_ledger as prl

    if not skip_enrichment:
        require_gap_enrichment(content)
    cfg = ps.load_workflow_config(root)
    from planning_projection_ledger import load_projection_ledger

    ledger = load_projection_ledger(root)
    decision = pa.resolve_authority(
        root,
        cfg,
        projection_available=not ppl.projection_is_dirty(root),
    )
    disposition = pa.apply_write_disposition(decision, write_class="projection", root=root)
    if disposition.get("verdict") == "refused":
        return {
            "verdict": "refused",
            "action": "store-put-gap",
            "disposition": disposition.get("disposition"),
            "reason": disposition.get("reason") or decision.reason,
            "unitId": unit_id,
        }
    if disposition.get("disposition") == "refuse-ledger":
        ledger = prl.record_refusal(
            root,
            unit_id=unit_id,
            operation="gap-projection",
            intended_body=content,
            authority_state=decision.authorityState,
            authority_reason=decision.reason,
            projection_destination=decision.configured,
            cfg=cfg,
        )
        return {
            "verdict": "ok",
            "action": "store-put-gap",
            "disposition": "refuse-ledger",
            "ledgered": ledger.get("verdict") == "ok",
            "projectionDirty": ppl.projection_is_dirty(root),
            "unitId": unit_id,
            "nonBlocking": True,
            "outboxEventId": ledger.get("outboxEventId"),
        }
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
    return {"verdict": "ok", "action": "store-put-gap", "disposition": "accept", "unitId": unit_id}

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
    from planning_visibility import resolve_emission_destination

    destination = resolve_emission_destination("reconciler-output")
    return redact(reason, destination=destination)


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


def _verify_override_recurrence_path(root: Path, signature: str) -> Path:
    return pp.git_root(root) / VERIFY_OVERRIDE_RECURRENCE_REL / f"{signature}.json"


def record_verify_override_recurrence(
    root: Path,
    *,
    signature: str,
    unit_id: str,
) -> int:
    """Increment visible recurrence counter for an existing verify-override gap (PRD 094 R8)."""
    path = _verify_override_recurrence_path(root, signature)
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = 1
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                prior = int(doc.get("recurrence") or 1)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            prior = 1
    current = prior + 1
    payload = {
        "signature": signature,
        "unitId": unit_id,
        "recurrence": current,
        "updatedAt": utc_now(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return current


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
    import harness_isolation_lint as hil

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
        recurrence = record_verify_override_recurrence(
            root,
            signature=signature,
            unit_id=existing,
        )
        return {
            "action": "reused",
            "unitId": existing,
            "signature": signature,
            "deduped": True,
            "recurrence": recurrence,
        }
    refusal = hil.refuse_live_planning_store_write("capture_verify_override")
    if refusal:
        return {**refusal, "action": "refused"}
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


def capture_external_intake(
    root: Path,
    *,
    signal_id: str,
    title: str,
    payload: str | None = None,
    outcome: str = "brief",
    issue_id: str | None = None,
    gap_unit_id: str | None = None,
    comment: str | None = None,
    signal_class: str = "feedback",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Feedback handoff to external-intake store verbs — no nested orchestrators (PRD 280 R4/R5/R7)."""
    from workflow_extensions import require_extension

    disabled = require_extension("externalIntake", root=root)
    if disabled is not None:
        return {**disabled, "action": "capture-external-intake"}

    from planning_external_intake import EXTERNAL_INTAKE_OUTCOMES
    from planning_store_facade import external_intake_run_pipeline, external_intake_txn, load_workflow_config

    normalized_outcome = str(outcome or "brief").strip().lower()
    if normalized_outcome not in EXTERNAL_INTAKE_OUTCOMES:
        return {
            "verdict": "fail",
            "action": "capture-external-intake",
            "error": "invalid-outcome",
            "allowed": sorted(EXTERNAL_INTAKE_OUTCOMES),
        }

    cfg = load_workflow_config(root)
    redacted_payload = redact_override_reason(payload or title)
    reporter_comment = comment or redacted_payload

    receive = external_intake_txn(
        root,
        cfg,
        verb="external-intake-receive",
        signal_id=signal_id,
        title=title,
        signal_class=signal_class,
        dry_run=dry_run,
    )
    if receive.get("verdict") != "ok":
        return {"verdict": "fail", "action": "capture-external-intake", "step": "receive", **receive}

    active_issue_id = issue_id or str(receive.get("issueId") or "")
    if not active_issue_id:
        return {"verdict": "fail", "action": "capture-external-intake", "error": "missing-issue-id"}

    pipeline_through = "actionability" if normalized_outcome == "brief" else "verify"
    pipeline = external_intake_run_pipeline(
        root,
        cfg,
        issue_id=active_issue_id,
        duplicate=normalized_outcome == "closure",
        through=pipeline_through,
        dry_run=dry_run,
    )
    if pipeline.get("verdict") != "ok":
        return {"verdict": "fail", "action": "capture-external-intake", "step": "pipeline", **pipeline}

    if normalized_outcome == "brief":
        if not gap_unit_id:
            dirs = pp.load_planning_dirs(root)
            gap_unit_id, _body_path = allocate_gap_unit_id(root, title, lambda uid: gap_body_rel(dirs, uid))
        terminal = external_intake_txn(
            root,
            cfg,
            verb="external-intake-promote",
            issue_id=active_issue_id,
            gap_unit_id=gap_unit_id,
            comment=reporter_comment,
            dry_run=dry_run,
        )
    elif normalized_outcome == "question":
        terminal = external_intake_txn(
            root,
            cfg,
            verb="external-intake-ask-reporter",
            issue_id=active_issue_id,
            comment=reporter_comment,
            dry_run=dry_run,
        )
    else:
        terminal = external_intake_txn(
            root,
            cfg,
            verb="external-intake-close",
            issue_id=active_issue_id,
            comment=reporter_comment,
            dry_run=dry_run,
        )

    if terminal.get("verdict") != "ok":
        return {"verdict": "fail", "action": "capture-external-intake", "step": "terminal", **terminal}

    return {
        "verdict": "pass",
        "action": "capture-external-intake",
        "signalId": signal_id,
        "issueId": active_issue_id,
        "outcome": normalized_outcome,
        "gapUnitId": gap_unit_id,
        "pipeline": pipeline,
        "terminal": terminal,
        "orchestratorBoundary": "store-verbs-only",
    }


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


def retro_gap_capture_config(root: Path) -> dict[str, Any]:
    """``retrospective.gapCapture`` settings (PRD 275 R10/R22), defaulting to disabled."""
    retrospective = ps.load_workflow_config(root).get("retrospective") or {}
    cfg = retrospective.get("gapCapture") or {}
    max_captures = cfg.get("maxCapturesPerRun")
    if not isinstance(max_captures, int) or max_captures < 0:
        max_captures = DEFAULT_RETRO_MAX_CAPTURES
    return {
        "enabled": cfg.get("enabled") is True,
        "maxCapturesPerRun": max_captures,
    }


def retro_item_dedup_key(run_id: str, item_id: str) -> str:
    return f"retro:{run_id}:{item_id}"


def retro_item_signal_id(run_id: str, item_id: str) -> str:
    return retro_item_dedup_key(run_id, item_id)


def retro_item_digest(item: dict[str, Any]) -> str:
    """Deterministic per-item digest for digest-bound human confirm (PRD 275 R23)."""
    related = item.get("relatedFiles")
    if not isinstance(related, list):
        related = []
    canonical = {
        "extendsPriorPr": bool(item.get("extendsPriorPr")),
        "itemId": str(item.get("itemId") or ""),
        "kind": str(item.get("kind") or ""),
        "newScope": bool(item.get("newScope")),
        "prdRef": str(item.get("prdRef") or ""),
        "relatedFiles": sorted(str(path) for path in related),
        "summary": str(item.get("summary") or ""),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def redact_retro_summary(summary: str) -> str:
    from memory_redact import redact
    from planning_visibility import resolve_emission_destination

    destination = resolve_emission_destination("reconciler-output")
    return redact(summary, destination=destination)


def retro_gap_route_path(root: Path, signal_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._:-]+", "_", signal_id)
    return pp.git_root(root) / RETRO_GAP_ROUTE_REL / f"{safe}.json"


def record_retro_gap_route(
    root: Path,
    *,
    signal_id: str,
    dedup_key: str,
    action: str,
    digest: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Durable route record for retro gap lifecycle audit/resume (PRD 275 R11/R18)."""
    path = retro_gap_route_path(root, signal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "action": action,
        "dedupKey": dedup_key,
        "digest": digest,
        "recordedAt": utc_now(),
        "signalId": signal_id,
    }
    if extra:
        record.update(extra)
    history: list[dict[str, Any]] = []
    if path.is_file():
        try:
            prior = writer.load_store(path)
            if isinstance(prior.get("history"), list):
                history = [entry for entry in prior["history"] if isinstance(entry, dict)]
            elif isinstance(prior, dict) and prior.get("action"):
                history = [prior]
        except Exception:
            history = []
    history.append(record)
    path.write_text(
        json.dumps({"history": history, "signalId": signal_id}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rel = str(path.resolve().relative_to(pp.git_root(root).resolve()))
    return {"path": rel, "signalId": signal_id}


def capture_retro_painful(
    root: Path,
    retro_output: dict[str, Any],
    *,
    unattended: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Emit ``kind:painful`` retro items into the gap draft inbox only (PRD 275 R8/R21).

    Well/change items are excluded. Drafts are redacted; materialization is never
    performed here. ``unattended`` callers may only draft — mint is always refused.
    """
    _ = unattended
    cfg = retro_gap_capture_config(root)
    if not cfg["enabled"]:
        return {
            "verdict": "skipped",
            "reason": "retrospective.gapCapture.enabled is false (default)",
        }
    run_id = str(retro_output.get("runId") or "unknown")
    items = retro_output.get("items")
    if not isinstance(items, list):
        items = []
    max_captures = int(cfg["maxCapturesPerRun"])
    drafted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    painful_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind != RETRO_GAP_KIND:
            skipped.append(
                {
                    "itemId": item.get("itemId"),
                    "kind": kind or None,
                    "reason": "kind-excluded",
                }
            )
            continue
        if painful_count >= max_captures:
            overflow.append(
                {
                    "itemId": item.get("itemId"),
                    "reason": "cap-reached",
                }
            )
            continue
        item_id = str(item.get("itemId") or f"item-{painful_count + 1}")
        signal_id = retro_item_signal_id(run_id, item_id)
        dedup_key = retro_item_dedup_key(run_id, item_id)
        digest = retro_item_digest(item)
        summary = redact_retro_summary(str(item.get("summary") or item_id))
        title = summary[:120] if summary else item_id
        draft_path = gap_draft_inbox_path(root, signal_id)
        if draft_path.is_file():
            existing = writer.load_store(draft_path)
            drafted.append(
                {
                    "action": "reused-draft",
                    "dedupKey": dedup_key,
                    "digest": digest,
                    "signalId": signal_id,
                    "status": existing.get("status", "draft"),
                }
            )
            painful_count += 1
            continue
        payload = {
            "dedupKey": dedup_key,
            "digest": digest,
            "itemId": item_id,
            "kind": RETRO_GAP_KIND,
            "route": "gap-capture",
            "runId": run_id,
            "sourceClass": "retro",
            "summary": summary,
        }
        if not dry_run:
            put_gap_draft(root, signal_id=signal_id, title=title, payload=payload)
            record_retro_gap_route(
                root,
                signal_id=signal_id,
                dedup_key=dedup_key,
                action="draft",
                digest=digest,
            )
        drafted.append(
            {
                "action": "draft-inbox",
                "dedupKey": dedup_key,
                "digest": digest,
                "path": str(
                    gap_draft_inbox_path(root, signal_id).resolve().relative_to(pp.git_root(root).resolve())
                ),
                "signalId": signal_id,
            }
        )
        painful_count += 1
    result: dict[str, Any] = {
        "drafted": drafted,
        "maxCapturesPerRun": max_captures,
        "overflow": overflow,
        "skipped": skipped,
        "verdict": "pass",
    }
    if overflow:
        result["operatorMessage"] = (
            f"{len(overflow)} painful retro item(s) omitted — "
            f"retrospective.gapCapture.maxCapturesPerRun is {max_captures}"
        )
    return result


def confirm_retro_gap_draft(
    root: Path,
    *,
    signal_id: str,
    digest: str,
) -> dict[str, Any]:
    """Persist digest-bound human ack before materialization (PRD 275 R9/R23)."""
    draft = load_gap_draft(root, signal_id)
    expected = str(draft.get("digest") or "")
    if not expected or digest != expected:
        fail(
            "digest-mismatch",
            halt="retro-gap-digest-mismatch",
            signalId=signal_id,
            expectedDigest=expected or None,
        )
    if draft.get("status") == "materialized":
        return {
            "idempotent": True,
            "signalId": signal_id,
            "status": "materialized",
            "unitId": draft.get("materializedUnitId"),
        }
    if draft.get("status") == "confirmed" and draft.get("confirmedDigest") == digest:
        return {"digest": digest, "idempotent": True, "signalId": signal_id, "status": "confirmed"}
    draft["status"] = "confirmed"
    draft["confirmedAt"] = utc_now()
    draft["confirmedDigest"] = digest
    path = gap_draft_inbox_path(root, signal_id)
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_retro_gap_route(
        root,
        signal_id=signal_id,
        dedup_key=str(draft.get("dedupKey") or ""),
        action="confirmed",
        digest=digest,
    )
    return {"digest": digest, "signalId": signal_id, "status": "confirmed"}


def materialize_retro_gap_draft(
    root: Path,
    *,
    signal_id: str,
    digest: str,
    problem: str | None = None,
    context: str | None = None,
    unattended: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Materialize a confirmed retro gap draft; fail closed without persisted ack."""
    if unattended:
        fail("unattended-materialize-refused", halt="retro-gap-unattended-mint")
    draft = load_gap_draft(root, signal_id)
    if draft.get("status") == "materialized":
        return {
            "idempotent": True,
            "signalId": signal_id,
            "status": "materialized",
            "unitId": draft.get("materializedUnitId"),
        }
    if draft.get("status") != "confirmed":
        fail(
            "materialize requires persisted human ack",
            halt="retro-gap-ack-required",
            signalId=signal_id,
            status=draft.get("status"),
        )
    confirmed_digest = str(draft.get("confirmedDigest") or draft.get("digest") or "")
    if digest != confirmed_digest:
        fail(
            "digest-bound confirm required",
            halt="retro-gap-digest-mismatch",
            signalId=signal_id,
        )
    title = str(draft.get("title") or signal_id)
    summary = str(draft.get("summary") or title)
    out = materialize_gap_draft(
        root,
        signal_id=signal_id,
        problem=problem or title,
        context=context or f"_Retro painful item (digest {digest})._\n\n{summary}",
        dry_run=dry_run,
    )
    if not dry_run:
        record_retro_gap_route(
            root,
            signal_id=signal_id,
            dedup_key=str(draft.get("dedupKey") or ""),
            action="materialized",
            digest=digest,
            extra={"unitId": out.get("unitId")},
        )
    return {**out, "digest": digest, "status": "materialized"}


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



# PRD 066 R22 / PRD 068 R6 — absorb linkage
PRD_066_UNIT_ID = "066-prd-linear-planning-store-provider-and-operator-projection"
PRD_066_NUMBER = "066"
GAP_079_UNIT_ID = "gap-079-add-linear-as-a-new-planning-store-issue-trackin"
GAP_079_PLANNING_ISSUE_REF = "planning#267"
ABSORB_LINKAGE_MAX_RETRIES = 3


def gap_absorb_target_match(candidate: str, gap_unit_id: str) -> bool:
    """True when ``candidate`` names the same gap unit as ``gap_unit_id`` (prefix-safe)."""
    cand = candidate.strip()
    if not cand or not gap_unit_id:
        return False
    if cand == gap_unit_id:
        return True
    cand_base = cand.rstrip("-")
    gap_base = gap_unit_id.rstrip("-")
    if gap_unit_id.startswith(cand_base + "-") or cand.startswith(gap_base + "-"):
        return True
    m_c = re.match(r"^gap-(\d+)$", cand)
    m_g = re.match(r"^gap-(\d+)", gap_unit_id)
    if m_c and m_g and m_c.group(1) == m_g.group(1):
        return True
    return False


def _gap_matches_absorb_target(candidate: str, gap_unit_id: str) -> bool:
    return gap_absorb_target_match(candidate, gap_unit_id)


def _parse_absorbs_frontmatter(raw: str) -> list[str]:
    return ps._parse_absorbs_targets(raw or "")


class AbsorbLinkageRevisionConflict(Exception):
    """Revision-conflict during absorb-linkage put (PRD 094 R6)."""

    def __init__(self, **detail: Any) -> None:
        self.detail = detail
        super().__init__("revision-conflict")


def _absorb_target_present(targets: list[str], gap_unit_id: str) -> bool:
    return any(gap_absorb_target_match(item, gap_unit_id) for item in targets)


def _canonicalize_absorb_targets(targets: list[str]) -> list[str]:
    """Alias-normalized dedupe preserving first-seen order (PRD 094 R4)."""
    out: list[str] = []
    for candidate in targets:
        candidate = candidate.strip()
        if not candidate or _absorb_target_present(out, candidate):
            continue
        out.append(candidate)
    return out


def _absorb_sets_semantically_equal(left: list[str], right: list[str]) -> bool:
    left_norm = _canonicalize_absorb_targets(left)
    right_norm = _canonicalize_absorb_targets(right)
    if len(left_norm) != len(right_norm):
        return False
    return all(_absorb_target_present(right_norm, item) for item in left_norm)


def _collect_absorb_targets_from_content(content: str) -> list[str]:
    """Collect absorb targets from YAML frontmatter and sw-edges (PRD 094 R3/R4)."""
    from planning_canonical import parse_edges_block
    from planning_migrate_issue_store import parse_frontmatter_fields

    targets: list[str] = []
    fm = parse_frontmatter_fields(content)
    for item in _parse_absorbs_frontmatter(fm.get("absorbs", "")):
        targets = _canonicalize_absorb_targets(targets + [item])
    edges = parse_edges_block(content)
    if edges:
        for edge in edges.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            rel = str(edge.get("rel") or edge.get("relationship") or "").strip().lower()
            if rel != "absorbs":
                continue
            target = str(edge.get("target") or "").strip()
            if target:
                targets = _canonicalize_absorb_targets(targets + [target])
    return targets


def _apply_absorb_targets_to_content(content: str, absorb_targets: list[str]) -> str:
    """Merge absorbs into canonical frontmatter and durable sw-edges (PRD 094 R3).

    Hybrid operator bodies often lack YAML ``---`` frontmatter; when no
    ``sw-edges`` fence exists yet, create one so absorb linkage is discoverable
    by closeout (``discover_absorbed_units_anchored``).
    """
    from gap_backlog import update_frontmatter_field
    from planning_canonical import (
        SW_EDGES_FENCE,
        build_edges_block,
        merge_absorbs_into_edge_list,
        parse_edges_block,
        strip_markers_and_edges,
    )
    from planning_migrate_issue_store import parse_frontmatter_fields

    targets = _canonicalize_absorb_targets(absorb_targets)
    new_content = content
    fm = parse_frontmatter_fields(content)
    if fm or content.startswith("---"):
        new_content = update_frontmatter_field(
            new_content,
            "absorbs",
            "[" + ", ".join(targets) + "]",
        )
    edges_block = parse_edges_block(content)
    if edges_block is not None:
        edges = list(edges_block.get("edges") or [])
        native = list(edges_block.get("native") or [])
        merged_edges = merge_absorbs_into_edge_list(edges, targets)
        body_without_edges = strip_markers_and_edges(new_content)
        new_content = body_without_edges.rstrip() + "\n\n" + build_edges_block(merged_edges, native)
    else:
        merged_edges = merge_absorbs_into_edge_list([], targets)
        # Preserve hybrid markers/body; only drop a stale fence if present under
        # a non-standard parse miss, then append the durable absorbs block.
        without_fence = SW_EDGES_FENCE.sub("", new_content)
        new_content = without_fence.rstrip() + "\n\n" + build_edges_block(merged_edges, [])
    return new_content


def _merge_prd_absorbs_frontmatter(content: str, gap_unit_id: str) -> tuple[str, bool]:
    """Hybrid-safe absorb merge with semantic ``changed`` (PRD 094 R3/R4)."""
    before = _collect_absorb_targets_from_content(content)
    if _absorb_target_present(before, gap_unit_id):
        return content, False
    after = _canonicalize_absorb_targets(before + [gap_unit_id])
    if _absorb_sets_semantically_equal(before, after):
        return content, False
    applied = _apply_absorb_targets_to_content(content, after)
    if applied == content:
        return content, False
    return applied, True


def _remerge_prd_absorbs(content: str, gap_unit_ids: list[str]) -> tuple[str, bool]:
    updated = content
    changed_any = False
    for gap_unit_id in gap_unit_ids:
        updated, changed = _merge_prd_absorbs_frontmatter(updated, gap_unit_id)
        changed_any = changed_any or changed
    return updated, changed_any


def _backend_put_capture_conflict(
    backend: Any,
    unit_id: str,
    body_path: str,
    content: str,
) -> ps.StoreResult:
    """Issue-store put that surfaces revision-conflict instead of exiting (PRD 094 R6)."""
    conflict: dict[str, Any] = {}

    original_fail = ps.fail

    def _capturing_fail(error: str, exit_code: int = 2, **extra: Any) -> None:
        code = str(extra.get("code") or error or "").strip()
        if code == "revision-conflict" or error == "revision-conflict":
            conflict.update(extra)
            conflict["error"] = error
            raise AbsorbLinkageRevisionConflict(**conflict)
        original_fail(error, exit_code, **extra)

    ps.fail = _capturing_fail  # type: ignore[method-assign]
    try:
        return backend.put(unit_id, body_path, content)
    finally:
        ps.fail = original_fail  # type: ignore[method-assign]


def _put_absorb_linkage_unit(
    backend: Any,
    unit_id: str,
    body_path: str,
    content: str,
    *,
    remerge: Callable[[str], tuple[str, bool]] | None = None,
) -> ps.StoreResult | dict[str, Any]:
    """Put with refetch+remerge on revision-conflict (PRD 094 R6)."""
    current = content
    for attempt in range(ABSORB_LINKAGE_MAX_RETRIES):
        try:
            result = _backend_put_capture_conflict(backend, unit_id, body_path, current)
        except AbsorbLinkageRevisionConflict as exc:
            if attempt + 1 >= ABSORB_LINKAGE_MAX_RETRIES:
                return {
                    "verdict": "fail",
                    "error": "revision-conflict-retry-exhausted",
                    "unitId": unit_id,
                    "detail": exc.detail,
                }
            refetch = backend.get(unit_id, body_path)
            if refetch.verdict != "ok" or not refetch.content:
                return {
                    "verdict": "fail",
                    "error": "refetch-failed-after-conflict",
                    "unitId": unit_id,
                }
            if remerge is not None:
                current, _ = remerge(refetch.content)
            else:
                current = refetch.content
            continue
        if result.verdict in ("ok", "deferred"):
            return result
        reason = str(result.reason or "")
        if reason == "revision-conflict" and attempt + 1 < ABSORB_LINKAGE_MAX_RETRIES:
            refetch = backend.get(unit_id, body_path)
            if refetch.verdict != "ok" or not refetch.content:
                return {
                    "verdict": "fail",
                    "error": "refetch-failed-after-conflict",
                    "unitId": unit_id,
                }
            if remerge is not None:
                current, _ = remerge(refetch.content)
            else:
                current = refetch.content
            continue
        return result
    return {
        "verdict": "fail",
        "error": "put-retry-exhausted",
        "unitId": unit_id,
    }


def _merge_gap_absorb_schedule(
    content: str,
    *,
    prd_unit_id: str,
    prd_number: str,
    planning_issue: str,
) -> tuple[str, bool]:
    from gap_backlog import schedule_label, update_frontmatter_field
    from planning_migrate_issue_store import parse_frontmatter_fields

    schedule = schedule_label(prd_number)
    fm = parse_frontmatter_fields(content)
    changed = False
    new_content = content
    status = str(fm.get("status") or "open").strip().lower()
    if status == "open":
        new_content = update_frontmatter_field(new_content, "status", "scheduled")
        changed = True
    if str(fm.get("schedule") or "").strip() != schedule:
        new_content = update_frontmatter_field(new_content, "schedule", schedule)
        changed = True
    if str(fm.get("absorbed-by") or fm.get("absorbed_by") or "").strip() != prd_unit_id:
        new_content = update_frontmatter_field(new_content, "absorbed-by", prd_unit_id)
        changed = True
    related = str(fm.get("related") or "").strip()
    if planning_issue and planning_issue not in related:
        new_content = update_frontmatter_field(new_content, "related", planning_issue)
        changed = True
    return new_content, changed


def _resolve_frozen_prd_path(root: Path, prd_path: Path | None) -> Path:
    if prd_path is not None:
        return prd_path
    materialized = (
        root
        / ".cursor/planning-materialized/docs/prds/066-linear-planning-store-provider-and-operator-projection/066-prd-linear-planning-store-provider-and-operator-projection.md"
    )
    if materialized.is_file():
        return materialized
    return pp.git_root(root) / ps._default_body_path(PRD_066_UNIT_ID, "prd")




def _collect_absorb_gap_targets(
    root: Path,
    cfg: dict[str, Any],
    *,
    prd_unit_id: str,
    prd_content: str,
    gap_unit_ids: list[str] | None = None,
    planning_issues: list[str] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    """Resolve delivery-grade gap unit ids for absorb linkage (PRD 068 R6/R7)."""
    from planning_migrate_issue_store import parse_frontmatter_fields

    fm = parse_frontmatter_fields(prd_content)
    targets: list[str] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(gap_id: str) -> None:
        gap_id = gap_id.strip()
        if not gap_id or gap_id in seen:
            return
        seen.add(gap_id)
        targets.append(gap_id)

    for item in gap_unit_ids or []:
        if item and ("gap" in item or item.startswith("gap-")):
            _add(item)
    for item in _parse_absorbs_frontmatter(fm.get("absorbs", "")):
        if "gap" in item or item.startswith("gap-"):
            _add(item)

    for ref in planning_issues or ps.parse_planning_issues_refs(fm.get("planningIssues", "")):
        skip_meta: dict[str, str] = {}
        try:
            gap_id = ps.resolve_planning_issue_ref_to_gap(
                root, cfg, ref, skip_meta=skip_meta
            )
        except ps.PlanningIssueRefResolutionError as exc:
            return [], [{"ref": exc.ref, "reason": exc.error, **exc.detail}]
        if not gap_id:
            reason = skip_meta.get("reason", "planning-issue-unresolved")
            entry: dict[str, str] = {"ref": ref, "reason": reason}
            for key, value in skip_meta.items():
                if key != "reason" and value:
                    entry[key] = value
            skipped.append(entry)
            continue
        if ps.gap_has_absorb_provenance(root, cfg, gap_id, prd_unit_id, fm):
            _add(gap_id)
        else:
            skipped.append({"ref": ref, "unitId": gap_id, "reason": "planning-issue-no-provenance"})
    return targets, skipped


def record_absorb_linkage(
    root: Path,
    *,
    prd_unit_id: str,
    prd_number: str | None = None,
    gap_unit_ids: list[str] | None = None,
    planning_issues: list[str] | None = None,
    planning_issue: str | None = None,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generic freeze-time absorb linkage: absorbs + schedule + absorbed-by (PRD 068 R6)."""
    cfg = ps.load_workflow_config(root)
    prd_num = prd_number or ps._prd_number_from_unit_id(prd_unit_id) or ""
    prd_body_path = ps._default_body_path(prd_unit_id, "prd")
    resolved_prd = prd_path
    if resolved_prd is None:
        materialized = root / ".cursor/planning-materialized"
        if materialized.is_dir():
            for candidate in materialized.rglob(f"{prd_unit_id}.md"):
                resolved_prd = candidate
                break
    if resolved_prd is None:
        resolved_prd = pp.git_root(root) / prd_body_path

    try:
        from planning_migrate_issue_store import (
            issue_store_effective,
            refresh_gap_backlog_projection,
            sync_gap_issue_labels,
        )
    except ImportError as exc:
        return {
            "verdict": "fail",
            "action": "record-absorb-linkage",
            "error": f"migration-engine-unavailable: {exc}",
        }

    if not issue_store_effective(root, cfg):
        return {"verdict": "skipped", "action": "record-absorb-linkage", "reason": "not-issue-store"}

    backend = ps.get_backend(root, cfg, override="issue-store")
    prd_fetch = backend.get(prd_unit_id, prd_body_path)
    prd_content = prd_fetch.content if prd_fetch.verdict == "ok" and prd_fetch.content else None
    if not prd_content:
        return {
            "verdict": "fail",
            "action": "record-absorb-linkage",
            "error": "frozen-prd-missing",
            "prdUnitId": prd_unit_id,
        }

    issue_refs = list(planning_issues or [])
    if planning_issue and planning_issue not in issue_refs:
        issue_refs.append(planning_issue)
    gap_targets, skipped = _collect_absorb_gap_targets(
        root,
        cfg,
        prd_unit_id=prd_unit_id,
        prd_content=prd_content,
        gap_unit_ids=gap_unit_ids,
        planning_issues=issue_refs or None,
    )
    provider_errors = [
        item
        for item in skipped
        if item.get("reason") in {
            "issue-capability-error",
            "issue-budget-exhausted",
            "lifecycle-tombstone",
            "issue-transferred",
            "issue-provider-error",
            "invalid-project-key",
            "artifact-type-conflict",
        }
    ]
    if provider_errors:
        first = provider_errors[0]
        return {
            "verdict": "fail",
            "action": "record-absorb-linkage",
            "error": str(first.get("reason") or "planning-issue-resolution-failed"),
            "prdUnitId": prd_unit_id,
            "planningIssueRef": first.get("ref"),
            "skipped": skipped,
        }
    if not gap_targets:
        return {
            "verdict": "skipped",
            "action": "record-absorb-linkage",
            "reason": "no-absorb-targets",
            "skipped": skipped,
        }

    if dry_run:
        return {
            "verdict": "ok",
            "action": "record-absorb-linkage",
            "dryRun": True,
            "prdUnitId": prd_unit_id,
            "gapUnitIds": gap_targets,
            "skipped": skipped,
        }

    results: dict[str, Any] = {
        "prdUnitId": prd_unit_id,
        "gapUnitIds": gap_targets,
        "updates": {},
        "skipped": skipped,
    }
    prd_updated, prd_changed_any = _remerge_prd_absorbs(prd_content, gap_targets)

    gap_schedules: list[dict[str, Any]] = []
    for gap_unit_id in gap_targets:
        gap_body_path = ps._default_body_path(gap_unit_id, "gap")
        gap_fetch = backend.get(gap_unit_id, gap_body_path)
        gap_content = gap_fetch.content if gap_fetch.verdict == "ok" and gap_fetch.content else None
        if not gap_content:
            return {
                "verdict": "fail",
                "action": "record-absorb-linkage",
                "error": "gap-unit-missing",
                "gapUnitId": gap_unit_id,
            }
        issue_ref = planning_issue or ""
        if not issue_ref:
            for ref in issue_refs:
                resolved = ps.resolve_planning_issue_ref_to_gap(root, cfg, ref)
                if resolved == gap_unit_id:
                    issue_ref = ref if ref.startswith("planning#") else f"planning#{ref.lstrip('#')}"
                    break
        gap_schedules.append(
            {
                "gapUnitId": gap_unit_id,
                "bodyPath": gap_body_path,
                "issueRef": issue_ref,
            }
        )

    if prd_changed_any:
        prd_put = _put_absorb_linkage_unit(
            backend,
            prd_unit_id,
            prd_body_path,
            prd_updated,
            remerge=lambda body: _remerge_prd_absorbs(body, gap_targets),
        )
        if isinstance(prd_put, dict):
            return {
                "verdict": "fail",
                "action": "record-absorb-linkage",
                "error": prd_put.get("error", "prd-put-failed"),
                "prdUnitId": prd_unit_id,
                "detail": prd_put,
            }
        if prd_put.verdict not in ("ok", "deferred"):
            return {
                "verdict": "fail",
                "action": "record-absorb-linkage",
                "error": "prd-put-failed",
                "reason": prd_put.reason,
            }
        results["updates"]["prd"] = {"changed": True, "hash": prd_put.hash}
    else:
        results["updates"]["prd"] = {"changed": False}

    for schedule in gap_schedules:
        gap_unit_id = str(schedule["gapUnitId"])
        gap_body_path = str(schedule["bodyPath"])
        issue_ref = str(schedule["issueRef"])
        gap_fetch = backend.get(gap_unit_id, gap_body_path)
        gap_content = gap_fetch.content if gap_fetch.verdict == "ok" and gap_fetch.content else None
        if not gap_content:
            return {
                "verdict": "fail",
                "action": "record-absorb-linkage",
                "error": "gap-unit-missing",
                "gapUnitId": gap_unit_id,
            }

        def _remerge_gap(body: str, *, _issue_ref: str = issue_ref) -> tuple[str, bool]:
            return _merge_gap_absorb_schedule(
                body,
                prd_unit_id=prd_unit_id,
                prd_number=prd_num,
                planning_issue=_issue_ref,
            )

        gap_updated, gap_changed = _remerge_gap(gap_content)
        if not gap_changed:
            results["updates"].setdefault("gaps", {})[gap_unit_id] = {"changed": False}
            continue
        gap_put = _put_absorb_linkage_unit(
            backend,
            gap_unit_id,
            gap_body_path,
            gap_updated,
            remerge=_remerge_gap,
        )
        if isinstance(gap_put, dict):
            return {
                "verdict": "fail",
                "action": "record-absorb-linkage",
                "error": gap_put.get("error", "gap-put-failed"),
                "gapUnitId": gap_unit_id,
                "detail": gap_put,
            }
        if gap_put.verdict not in ("ok", "deferred"):
            return {
                "verdict": "fail",
                "action": "record-absorb-linkage",
                "error": "gap-put-failed",
                "gapUnitId": gap_unit_id,
                "reason": gap_put.reason,
            }
        results["updates"].setdefault("gaps", {})[gap_unit_id] = {"changed": True}
        gap_fetch_after = backend.get(gap_unit_id, gap_body_path)
        if gap_fetch_after.verdict == "ok" and gap_fetch_after.content:
            sync_gap_issue_labels(root, gap_unit_id, gap_fetch_after.content, cfg)

    refresh_gap_backlog_projection(root, cfg, apply=True)
    return {"verdict": "ok", "action": "record-absorb-linkage", **results}


def record_absorb_linkage_066(
    root: Path,
    *,
    prd_path: Path | None = None,
    tasks_path: Path | None = None,
    gap_unit_id: str = GAP_079_UNIT_ID,
    planning_issue: str = GAP_079_PLANNING_ISSUE_REF,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 066 → gap-079 absorb linkage (delegates to generic R6 helper)."""
    _ = tasks_path
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_066_UNIT_ID,
        prd_number=PRD_066_NUMBER,
        gap_unit_ids=[gap_unit_id],
        planning_issue=planning_issue,
        prd_path=prd_path,
        dry_run=dry_run,
    )
    if out.get("verdict") == "ok" and not dry_run:
        out = {**out, "gapUnitId": gap_unit_id, "planningIssue": planning_issue}
    return {**out, "action": "record-absorb-linkage-066"}


# PRD 072 R10 — absorb close-out (#458/#459/#468–#474)
PRD_072_UNIT_ID = "072-prd-post-070-deliver-hygiene"
PRD_072_NUMBER = "072"
PRD_072_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-167-remove-docs-decisions-from-the-public-shipwright",
    "gap-168-clarify-agents-md-vs-memory-provider-rules-thin-",
    "gap-170-workflow-config-json-widen-globs-forces-permanen",
    "gap-171-verify-watchdog-exhausted-must-not-block-merge-q",
    "gap-172-sw-deliver-verify-harness-fails-on-live-orch-pri",
    "gap-173-deliver-bookkeeping-must-not-bump-version-txt-wh",
    "gap-174-long-post-merge-verify-remediation-must-not-stal",
    "gap-175-close-memory-prework-gate-shell-bypass-pretoolus",
    "gap-176-conductor-skill-near-500-line-ceiling-carve-head",
)
PRD_072_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (
    458,
    459,
    468,
    469,
    470,
    471,
    472,
    473,
    474,
)


def _match_expected_absorb_gap(discovered: set[str], expected: str) -> bool:
    return any(gap_absorb_target_match(item, expected) for item in discovered)


def verify_absorb_closeout_072(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 072 close-out discovers all nine anchored gaps (R10)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_072_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-072",
            "error": snap.get("error"),
            "prdUnitId": PRD_072_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_072_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    return {
        "verdict": "ok" if not missing else "fail",
        "action": "verify-absorb-closeout-072",
        "prdUnitId": PRD_072_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "skipped": list(snap.get("skipped") or []),
        "planningIssues": [str(n) for n in PRD_072_PLANNING_ISSUE_NUMBERS],
    }


def record_absorb_linkage_072(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 072 absorb linkage for all nine delivery gaps (R10)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_072_UNIT_ID,
        prd_number=PRD_072_NUMBER,
        gap_unit_ids=list(PRD_072_ABSORB_GAP_UNITS),
        planning_issues=[f"planning#{num}" for num in PRD_072_PLANNING_ISSUE_NUMBERS],
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-072"}


# PRD 073 R12 — absorb close-out (#481–#485)
PRD_073_UNIT_ID = "073-prd-plugin-consumability-and-deliver-hygiene"
PRD_073_NUMBER = "073"
PRD_073_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-177-consumer-repo-scripts-pollution-missing-plugin-c",
    "gap-178-local-verify-manifest-must-forward-entry-args-in",
    "gap-179-resolve-model-tier-must-emit-cursor-task-allowli",
    "gap-180-merge-enqueue-must-reload-state-before-persist-c",
    "gap-181-phase-provision-must-parse-last-json-object-from",
)
PRD_073_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (
    481,
    482,
    483,
    484,
    485,
)


def verify_absorb_closeout_073(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 073 close-out discovers all five anchored gaps (R12)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_073_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-073",
            "error": snap.get("error"),
            "prdUnitId": PRD_073_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_073_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    return {
        "verdict": "ok" if not missing else "fail",
        "action": "verify-absorb-closeout-073",
        "prdUnitId": PRD_073_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "skipped": list(snap.get("skipped") or []),
        "planningIssues": [str(n) for n in PRD_073_PLANNING_ISSUE_NUMBERS],
    }


def record_absorb_linkage_073(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 073 absorb linkage for all five delivery gaps (R12)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_073_UNIT_ID,
        prd_number=PRD_073_NUMBER,
        gap_unit_ids=list(PRD_073_ABSORB_GAP_UNITS),
        planning_issues=[f"planning#{num}" for num in PRD_073_PLANNING_ISSUE_NUMBERS],
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-073"}


# PRD 325 R15 — absorb close-out (#331–#338)
PRD_325_UNIT_ID = "prd-325-deliver-finalize-consumer-resilience"
PRD_325_NUMBER = "325"
PRD_325_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-331-merge-detection-finalize-recovery-under-pr-number",
    "gap-332-closeout-prefers-run-scoped-state",
    "gap-333-blast-radius-clear-on-green-merged-phases",
    "gap-334-publish-surface-audit-under-in-repo-public",
    "gap-335-ship-loop-resolution-and-provisioning-consumer",
    "gap-336-orchestrator-primary-scripts-hash-divergence",
    "gap-337-docs-currency-gate-soft-skip-consumer",
    "gap-338-docs-worktree-bases-on-fetched-remote-tip",
)
PRD_325_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (331, 332, 333, 334, 335, 336, 337, 338)


def verify_absorb_closeout_325(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 325 close-out discovers all eight anchored gaps (R15)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_325_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-325",
            "error": snap.get("error"),
            "prdUnitId": PRD_325_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_325_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    return {
        "verdict": "ok" if not missing else "fail",
        "action": "verify-absorb-closeout-325",
        "prdUnitId": PRD_325_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "skipped": list(snap.get("skipped") or []),
        "planningIssues": [str(n) for n in PRD_325_PLANNING_ISSUE_NUMBERS],
    }


def record_absorb_linkage_325(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 325 absorb linkage for all eight delivery gaps (R15)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_325_UNIT_ID,
        prd_number=PRD_325_NUMBER,
        gap_unit_ids=list(PRD_325_ABSORB_GAP_UNITS),
        planning_issues=[f"planning#{num}" for num in PRD_325_PLANNING_ISSUE_NUMBERS],
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-325"}


# PRD 326 R19 — absorb close-out (gaps 311–314, 319, 320, 322 / planning #747–#750, #755, #756, #758)
PRD_326_UNIT_ID = "326-prd-workflow-quality-platform"
PRD_326_NUMBER = "326"
PRD_326_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-311-architecture-doctrine-and-design-quality-model-c",
    "gap-312-first-class-research-and-prototype-evidence-node",
    "gap-313-agent-instruction-compiler-linter-for-workflow-a",
    "gap-314-reviewer-evidence-harvesting-and-bounded-reviewe",
    "gap-319-fault-injection-and-state-machine-testing-framew",
    "gap-320-intent-aware-merge-conflict-resolution-via-prove",
    "gap-322-repro-first-debugging-invariant-for-sw-debug",
)
PRD_326_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (
    747,
    748,
    749,
    750,
    755,
    756,
    758,
)


def verify_absorb_closeout_326(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 326 close-out discovers all seven anchored gaps (R19)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_326_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-326",
            "error": snap.get("error"),
            "prdUnitId": PRD_326_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_326_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    return {
        "verdict": "ok" if not missing else "fail",
        "action": "verify-absorb-closeout-326",
        "prdUnitId": PRD_326_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "skipped": list(snap.get("skipped") or []),
        "planningIssues": [str(n) for n in PRD_326_PLANNING_ISSUE_NUMBERS],
    }


def record_absorb_linkage_326(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 326 absorb linkage for all seven delivery gaps (R19)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_326_UNIT_ID,
        prd_number=PRD_326_NUMBER,
        gap_unit_ids=list(PRD_326_ABSORB_GAP_UNITS),
        planning_issues=[f"planning#{num}" for num in PRD_326_PLANNING_ISSUE_NUMBERS],
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-326"}


# PRD 327 R15 — absorb close-out (gap-078 Notion planning-store provider)
PRD_327_UNIT_ID = "prd-327-notion-planning-store-provider"
PRD_327_NUMBER = "327"
PRD_327_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-078-add-notion-as-a-new-planning-store-issue-trackin",
)
GAP_078_UNIT_ID = PRD_327_ABSORB_GAP_UNITS[0]


def verify_absorb_closeout_327(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 327 close-out discovers anchored gap-078 (R15)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_327_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-327",
            "error": snap.get("error"),
            "prdUnitId": PRD_327_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_327_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    return {
        "verdict": "ok" if not missing else "fail",
        "action": "verify-absorb-closeout-327",
        "prdUnitId": PRD_327_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "skipped": list(snap.get("skipped") or []),
        "gapUnitIds": list(PRD_327_ABSORB_GAP_UNITS),
    }


def record_absorb_linkage_327(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 327 → gap-078 absorb linkage (R15)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_327_UNIT_ID,
        prd_number=PRD_327_NUMBER,
        gap_unit_ids=list(PRD_327_ABSORB_GAP_UNITS),
        prd_path=prd_path,
        dry_run=dry_run,
    )
    if out.get("verdict") == "ok" and not dry_run:
        out = {**out, "gapUnitId": GAP_078_UNIT_ID}
    return {**out, "action": "record-absorb-linkage-327"}


# PRD 330 R7 — absorb close-out (#849, #846, #866, #884, #850)
PRD_330_UNIT_ID = "330-prd-truth-hygiene-and-project-doctrine"
PRD_330_NUMBER = "330"
PRD_330_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-369-fix-documentation-default-truth-drift-provenance",
    "gap-365-separate-shipwright-doctrine-from-consumer-proje",
    "gap-388-clarify-relationship-between-projectdoctrine-and",
    "gap-406-complete-architecture-doctrine-beyond-shipwright",
    "gap-371-brownfield-projectbaseline-v1-synthesis-on-init-",
)
PRD_330_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (
    849,
    846,
    866,
    884,
    850,
)


def verify_absorb_closeout_330(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 330 close-out discovers all five anchored gaps (R7)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_330_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-330",
            "error": snap.get("error"),
            "prdUnitId": PRD_330_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_330_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    duplicate_targets = [
        gap_id
        for gap_id in PRD_330_ABSORB_GAP_UNITS
        if sum(1 for item in discovered if gap_absorb_target_match(item, gap_id)) > 1
    ]
    return {
        "verdict": "ok" if not missing and not duplicate_targets else "fail",
        "action": "verify-absorb-closeout-330",
        "prdUnitId": PRD_330_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "duplicateTargets": duplicate_targets,
        "skipped": list(snap.get("skipped") or []),
        "planningIssues": [str(n) for n in PRD_330_PLANNING_ISSUE_NUMBERS],
    }


def record_absorb_linkage_330(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 330 absorb linkage for all five delivery gaps (R7)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_330_UNIT_ID,
        prd_number=PRD_330_NUMBER,
        gap_unit_ids=list(PRD_330_ABSORB_GAP_UNITS),
        planning_issues=[f"planning#{num}" for num in PRD_330_PLANNING_ISSUE_NUMBERS],
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-330"}


# PRD 332 R9 — absorb close-out (gaps #864, #865, #847, #867, #854)
PRD_332_UNIT_ID = "332-prd-project-intelligence-triage-and-capability-promotion"
PRD_332_NUMBER = "332"
PRD_332_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-386-connect-codebase-history-decision-intelligence-t",
    "gap-387-define-and-implement-triageevidence-v1",
    "gap-367-generalize-evidence-backed-capabilitypromotion-b",
    "gap-389-add-evidence-freshness-and-invalidation-envelope",
    "gap-376-complete-context-compression-rollout-via-measure",
)
PRD_332_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (864, 865, 847, 867, 854)


def verify_absorb_closeout_332(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 332 close-out discovers all five anchored gaps (R9)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_332_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-332",
            "error": snap.get("error"),
            "prdUnitId": PRD_332_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_332_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    duplicate_targets = [
        gap_id
        for gap_id in PRD_332_ABSORB_GAP_UNITS
        if sum(1 for item in discovered if gap_absorb_target_match(item, gap_id)) > 1
    ]
    return {
        "verdict": "ok" if not missing and not duplicate_targets else "fail",
        "action": "verify-absorb-closeout-332",
        "prdUnitId": PRD_332_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "duplicateTargets": duplicate_targets,
        "skipped": list(snap.get("skipped") or []),
        "planningIssues": [str(n) for n in PRD_332_PLANNING_ISSUE_NUMBERS],
    }


def record_absorb_linkage_332(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 332 absorb linkage for all five delivery gaps (R9)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_332_UNIT_ID,
        prd_number=PRD_332_NUMBER,
        gap_unit_ids=list(PRD_332_ABSORB_GAP_UNITS),
        planning_issues=[f"planning#{num}" for num in PRD_332_PLANNING_ISSUE_NUMBERS],
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-332"}


# PRD 333 R12 — absorb close-out (gaps #869, #852, #868, #883, #879, #880, #881, #882, #873, #875)
PRD_333_UNIT_ID = "333-prd-eval-corpus-handoff-and-platform-providers"
PRD_333_NUMBER = "333"
PRD_333_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-391-establish-external-consumer-repository-evaluatio",
    "gap-373-strengthen-semantic-parity-conformance-across-pl",
    "gap-390-finish-general-handoffbundle-runtime-integration",
    "gap-405-close-handoffbundle-context-switch-stub-remainin",
    "gap-401-automated-upstream-provenance-analysis",
    "gap-402-gitlab-planning-store-provider",
    "gap-403-remote-execution-provider",
    "gap-404-workflowpackage-marketplace-registry",
    "gap-395-track-updated-enhancement-ranking-from-v2-5-0-re",
    "gap-397-follow-suggested-release-sequence-v2-5-1-truth-v",
)
PRD_333_PLANNING_ISSUE_NUMBERS: tuple[int, ...] = (
    869,
    852,
    868,
    883,
    879,
    880,
    881,
    882,
    873,
    875,
)


def verify_absorb_closeout_333(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 333 close-out discovers all ten anchored gaps (R12)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_333_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-333",
            "error": snap.get("error"),
            "prdUnitId": PRD_333_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_333_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    duplicate_targets = [
        gap_id
        for gap_id in PRD_333_ABSORB_GAP_UNITS
        if sum(1 for item in discovered if gap_absorb_target_match(item, gap_id)) > 1
    ]
    return {
        "verdict": "ok" if not missing and not duplicate_targets else "fail",
        "action": "verify-absorb-closeout-333",
        "prdUnitId": PRD_333_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "duplicateTargets": duplicate_targets,
        "skipped": list(snap.get("skipped") or []),
        "planningIssues": [str(n) for n in PRD_333_PLANNING_ISSUE_NUMBERS],
    }


def record_absorb_linkage_333(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 333 absorb linkage for all ten delivery gaps (R12)."""
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_333_UNIT_ID,
        prd_number=PRD_333_NUMBER,
        gap_unit_ids=list(PRD_333_ABSORB_GAP_UNITS),
        planning_issues=[f"planning#{num}" for num in PRD_333_PLANNING_ISSUE_NUMBERS],
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-333"}


# PRD 337 R6/R11 — bundle closeout for seventeen workflow-runtime gaps
PRD_337_UNIT_ID = "337-prd-workflow-runtime-autonomy-lifecycle"
PRD_337_NUMBER = "337"
PRD_337_ANOMALOUS_SHORT_GAP_TARGETS: tuple[str, ...] = (
    "gap-135",
    "gap-136",
    "gap-137",
)
PRD_337_ABSORB_GAP_UNITS: tuple[str, ...] = (
    "gap-135-deliver-autonomy-dispatch-ship-depends-on-chat-t",
    "gap-136-deliver-run-entry-hardening-bare-main-entry-pre-",
    "gap-137-autonomy-acceptance-gate-define-zero-interaction",
    "gap-355-add-sw-explore-as-first-class-pre-planning-works",
    "gap-357-sw-explore-first-release-must-include-full-entry",
    "gap-407-finalize-completion-living-docs-gap-resolve-exha",
    "gap-408-blind-python3-m-sw-generate-all-in-phase-trees-c",
    "gap-409-terminal-pr-prepare-blocked-completed-pending-me",
    "gap-410-pr-delivery-map-for-terminal-pr-lived-only-under",
    "gap-411-resume-friction-stacked-ambiguous-nonterminal-ru",
    "gap-412-auto-run-sw-retrospective-post-merge-during-deli",
    "gap-413-when-retrospective-gapcapture-enabled-true-auto-",
    "gap-414-retro-compound-must-scope-learning-candidates-by",
    "gap-415-terminal-gapcapture-must-not-mint-plugin-frictio",
    "gap-416-retro-gapcapture-must-fork-plugin-self-to-meta-s",
    "gap-430-phase-gap-check-provenance-and-status-integrity-",
    "gap-431-contended-shared-docs-need-plan-time-serialize-p",
)


def reconcile_absorbed_gap_lifecycle_states(
    root: Path,
    cfg: dict[str, Any],
    *,
    gap_unit_ids: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Normalize anomalous short gap-135/136/137 targets before absorb linkage (PRD 337 R6/R11).

    Uses existing short-gap canonicalization only — does not alter PRD 339-owned list-form
    ``absorbs`` projection logic.
    """
    from planning_store_facade import _canonicalize_short_gap_absorb_targets

    seeds = set(gap_unit_ids or PRD_337_ABSORB_GAP_UNITS)
    seeds.update(set(PRD_337_ANOMALOUS_SHORT_GAP_TARGETS) & seeds)
    normalized, skipped = _canonicalize_short_gap_absorb_targets(
        root, cfg, seeds, fail_closed=True
    )
    reconciled_shorts = [
        short
        for short in PRD_337_ANOMALOUS_SHORT_GAP_TARGETS
        if short in seeds
        and not any(gap_absorb_target_match(short, item) for item in normalized)
        and any(
            gap_absorb_target_match(item, expected)
            for item in normalized
            for expected in PRD_337_ABSORB_GAP_UNITS
            if gap_absorb_target_match(short, expected) or short in expected
        )
    ]
    missing = [
        gap_id
        for gap_id in PRD_337_ABSORB_GAP_UNITS
        if not any(gap_absorb_target_match(item, gap_id) for item in normalized)
    ]
    return {
        "verdict": "ok" if not missing else "fail",
        "action": "reconcile-absorbed-gap-lifecycle",
        "prdUnitId": PRD_337_UNIT_ID,
        "normalized": sorted(normalized),
        "reconciledShorts": reconciled_shorts,
        "missing": missing,
        "skipped": skipped,
        "expectedCount": len(PRD_337_ABSORB_GAP_UNITS),
    }


def verify_absorb_closeout_337(
    root: Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify PRD 337 close-out discovers all seventeen anchored gaps (R6/R11)."""
    resolved_cfg = cfg if cfg is not None else ps.load_workflow_config(root)
    reconcile = reconcile_absorbed_gap_lifecycle_states(root, resolved_cfg)
    if reconcile.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-337",
            "error": "lifecycle-reconcile-failed",
            "prdUnitId": PRD_337_UNIT_ID,
            "reconcile": reconcile,
        }
    snap = ps.resolve_delivery_linked_units(root, resolved_cfg, PRD_337_UNIT_ID)
    if snap.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "action": "verify-absorb-closeout-337",
            "error": snap.get("error"),
            "prdUnitId": PRD_337_UNIT_ID,
        }

    gap_ids = [
        item["unitId"]
        for item in snap.get("snapshot", [])
        if item.get("artifactType") == "gap"
    ]
    discovered = set(gap_ids)
    missing = [
        gap_id
        for gap_id in PRD_337_ABSORB_GAP_UNITS
        if not _match_expected_absorb_gap(discovered, gap_id)
    ]
    duplicate_targets = [
        gap_id
        for gap_id in PRD_337_ABSORB_GAP_UNITS
        if sum(1 for item in discovered if gap_absorb_target_match(item, gap_id)) > 1
    ]
    return {
        "verdict": "ok" if not missing and not duplicate_targets else "fail",
        "action": "verify-absorb-closeout-337",
        "prdUnitId": PRD_337_UNIT_ID,
        "discoveredCount": len(discovered),
        "discovered": sorted(discovered),
        "missing": missing,
        "duplicateTargets": duplicate_targets,
        "skipped": list(snap.get("skipped") or []),
        "reconcile": reconcile,
    }


def record_absorb_linkage_337(
    root: Path,
    *,
    prd_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record PRD 337 absorb linkage for all seventeen delivery gaps (R6/R11)."""
    resolved_cfg = ps.load_workflow_config(root)
    reconcile = reconcile_absorbed_gap_lifecycle_states(root, resolved_cfg)
    if reconcile.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "action": "record-absorb-linkage-337",
            "error": "lifecycle-reconcile-failed",
            "prdUnitId": PRD_337_UNIT_ID,
            "reconcile": reconcile,
        }
    out = record_absorb_linkage(
        root,
        prd_unit_id=PRD_337_UNIT_ID,
        prd_number=PRD_337_NUMBER,
        gap_unit_ids=list(PRD_337_ABSORB_GAP_UNITS),
        prd_path=prd_path,
        dry_run=dry_run,
    )
    return {**out, "action": "record-absorb-linkage-337", "reconcile": reconcile}


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
        elif tok == "--prd-path" and i + 1 < len(rest):
            out["prd_path"] = rest[i + 1]
            i += 2
        elif tok == "--tasks-path" and i + 1 < len(rest):
            out["tasks_path"] = rest[i + 1]
            i += 2
        elif tok == "--gap-unit-id" and i + 1 < len(rest):
            out["gap_unit_id"] = rest[i + 1]
            i += 2
        elif tok == "--planning-issue" and i + 1 < len(rest):
            out["planning_issue"] = rest[i + 1]
            i += 2
        elif tok == "--retro-json" and i + 1 < len(rest):
            out["retro_json"] = rest[i + 1]
            i += 2
        elif tok == "--digest" and i + 1 < len(rest):
            out["digest"] = rest[i + 1]
            i += 2
        elif tok == "--outcome" and i + 1 < len(rest):
            out["outcome"] = rest[i + 1]
            i += 2
        elif tok == "--issue-id" and i + 1 < len(rest):
            out["issue_id"] = rest[i + 1]
            i += 2
        elif tok == "--comment" and i + 1 < len(rest):
            out["comment"] = rest[i + 1]
            i += 2
        elif tok == "--payload" and i + 1 < len(rest):
            out["payload"] = rest[i + 1]
            i += 2
        elif tok == "--signal-class" and i + 1 < len(rest):
            out["signal_class"] = rest[i + 1]
            i += 2
        elif tok == "--unattended":
            out["unattended"] = True
            i += 1
        else:
            i += 1
    return out


def route_converge_findings(
    root: Path,
    findings: list[dict[str, Any]],
    *,
    unit_id: str | None = None,
    unit_dir: str | None = None,
    dry_run: bool = False,
    auto_fix: bool = False,
    auto_amend: bool = False,
) -> dict[str, Any]:
    """Route converge findings through gap-capture + amendment (PRD 342 R46).

    Findings reach human disposition via the existing gap-capture draft inbox and
    amendment proposals. This path never silently auto-fixes code and never
    auto-amends a frozen artifact — ``auto_fix`` / ``auto_amend`` are refused.
    """
    if auto_fix or auto_amend:
        return {
            "verdict": "refused",
            "reason": "converge-findings-must-not-auto-fix-or-auto-amend",
            "autoFixApplied": False,
            "autoAmendApplied": False,
            "routed": [],
            "awaitingHumanDisposition": True,
            "unitId": unit_id,
            "unitDir": unit_dir,
        }

    routed: list[dict[str, Any]] = []
    for index, raw in enumerate(findings or []):
        if not isinstance(raw, dict):
            continue
        reason = str(raw.get("reason") or "converge-finding")
        role = str(raw.get("role") or "")
        path = str(raw.get("path") or raw.get("ref") or "")
        title_bits = [part for part in ("Converge finding", role, reason) if part]
        title = " — ".join(title_bits)[:180]
        signal_id = str(
            raw.get("signalId")
            or raw.get("signal_id")
            or f"converge:{unit_id or 'unit'}:{reason}:{index}"
        )
        touches_frozen = bool(raw.get("frozenArtifact")) or reason in {
            "declared-bundle-asset-missing",
            "frozen-artifact-drift",
        }
        # Always stage a gap-capture draft for human disposition (never authoritative mint).
        if dry_run:
            gap_result = {
                "signalId": signal_id,
                "action": "draft-inbox",
                "title": title,
                "deduped": False,
                "dryRun": True,
            }
        else:
            gap_result = put_gap_draft(
                root,
                signal_id=signal_id,
                title=title,
                payload={
                    "source": "converge",
                    "unitId": unit_id,
                    "unitDir": unit_dir,
                    "finding": raw,
                    "stub": True,
                    "awaitingHumanDisposition": True,
                },
            )
            gap_result = {
                "signalId": signal_id,
                "action": "draft-inbox",
                "deduped": False,
                **gap_result,
            }

        amendment: dict[str, Any] | None = None
        if touches_frozen:
            amendment = {
                "route": "amendment",
                "status": "awaiting-human-disposition",
                "autoAmendApplied": False,
                "reason": "frozen-artifact-requires-human-amendment",
                "finding": raw,
                "unitId": unit_id,
            }

        routed.append(
            {
                "signalId": signal_id,
                "title": title,
                "gapCapture": gap_result,
                "amendment": amendment,
                "autoFixApplied": False,
                "autoAmendApplied": False,
            }
        )

    return {
        "verdict": "pass",
        "routed": routed,
        "autoFixApplied": False,
        "autoAmendApplied": False,
        "awaitingHumanDisposition": True,
        "unitId": unit_id,
        "unitDir": unit_dir,
        "findingCount": len(routed),
    }



def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail(
            "usage: planning_gap_capture.py <repo-root> "
"<capture|capture-external-intake|confirm|materialize|materialize-draft|draft-inbox-list|validate-enrichment|capture-verify-override|retro-capture|retro-confirm|retro-materialize|record-absorb-linkage|record-absorb-linkage-327|record-absorb-linkage-330|record-absorb-linkage-332|record-absorb-linkage-333|verify-absorb-closeout-072|verify-absorb-closeout-073|verify-absorb-closeout-325|verify-absorb-closeout-326|verify-absorb-closeout-327|verify-absorb-closeout-330|verify-absorb-closeout-332|verify-absorb-closeout-333> [options]"
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

    if command == "capture-external-intake":
        signal_id = flags.get("signal_id")
        title = flags.get("title")
        if not signal_id or not title:
            fail("--signal-id and --title required for capture-external-intake")
        out = capture_external_intake(
            root,
            signal_id=signal_id,
            title=title,
            payload=flags.get("payload"),
            outcome=str(flags.get("outcome") or "brief"),
            issue_id=flags.get("issue_id"),
            gap_unit_id=flags.get("unit_id"),
            comment=flags.get("comment"),
            signal_class=str(flags.get("signal_class") or "feedback"),
            dry_run=bool(flags.get("dry_run")),
        )
        emit(out, 0 if out.get("verdict") == "pass" else 20)

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

    if command == "retro-capture":
        retro_json = flags.get("retro_json")
        if not retro_json:
            fail("--retro-json required for retro-capture")
        retro_output = json.loads(retro_json)
        if not isinstance(retro_output, dict):
            fail("retro-capture requires JSON object")
        out = capture_retro_painful(
            root,
            retro_output,
            unattended=bool(flags.get("unattended")),
            dry_run=bool(flags.get("dry_run")),
        )
        emit(out, 0 if out.get("verdict") in {"pass", "skipped"} else 20)
        return

    if command == "retro-confirm":
        signal_id = flags.get("signal_id")
        digest = flags.get("digest")
        if not signal_id or not digest:
            fail("--signal-id and --digest required for retro-confirm")
        out = confirm_retro_gap_draft(root, signal_id=signal_id, digest=digest)
        emit({"verdict": "pass", "action": "retro-confirm", **out})
        return

    if command == "retro-materialize":
        signal_id = flags.get("signal_id")
        digest = flags.get("digest")
        if not signal_id or not digest:
            fail("--signal-id and --digest required for retro-materialize")
        out = materialize_retro_gap_draft(
            root,
            signal_id=signal_id,
            digest=digest,
            problem=flags.get("problem"),
            context=flags.get("context"),
            unattended=bool(flags.get("unattended")),
            dry_run=bool(flags.get("dry_run")),
        )
        emit({"verdict": "pass", **out})
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

    if command == "record-absorb-linkage":
        prd_path = Path(flags["prd_path"]).resolve() if flags.get("prd_path") else None
        prd_unit = str(flags.get("prd_unit_id") or flags.get("unit_id") or PRD_066_UNIT_ID)
        prd_number = str(flags.get("prd_number") or "")
        gap_ids = flags.get("gap_unit_ids")
        if isinstance(gap_ids, str):
            gap_ids = [g.strip() for g in gap_ids.split(",") if g.strip()]
        if prd_unit == PRD_072_UNIT_ID:
            out = record_absorb_linkage_072(
                root,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        elif prd_unit == PRD_073_UNIT_ID:
            out = record_absorb_linkage_073(
                root,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        elif prd_unit == PRD_325_UNIT_ID:
            out = record_absorb_linkage_325(
                root,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        elif prd_unit == PRD_326_UNIT_ID:
            out = record_absorb_linkage_326(
                root,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        elif prd_unit == PRD_327_UNIT_ID:
            out = record_absorb_linkage_327(
                root,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        elif prd_unit == PRD_332_UNIT_ID:
            out = record_absorb_linkage_332(
                root,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        elif prd_unit == PRD_333_UNIT_ID:
            out = record_absorb_linkage_333(
                root,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        elif prd_unit == PRD_066_UNIT_ID and not flags.get("prd_unit_id") and not flags.get("unit_id"):
            tasks_path = Path(flags["tasks_path"]).resolve() if flags.get("tasks_path") else None
            out = record_absorb_linkage_066(
                root,
                prd_path=prd_path,
                tasks_path=tasks_path,
                gap_unit_id=str(flags.get("gap_unit_id") or GAP_079_UNIT_ID),
                planning_issue=str(flags.get("planning_issue") or GAP_079_PLANNING_ISSUE_REF),
                dry_run=bool(flags.get("dry_run")),
            )
        else:
            out = record_absorb_linkage(
                root,
                prd_unit_id=prd_unit,
                prd_number=prd_number or None,
                gap_unit_ids=gap_ids,
                planning_issue=str(flags.get("planning_issue") or "") or None,
                prd_path=prd_path,
                dry_run=bool(flags.get("dry_run")),
            )
        emit(out, 0 if out.get("verdict") in {"ok", "skipped"} else 20)

    if command == "record-absorb-linkage-327":
        prd_path = Path(flags["prd_path"]).resolve() if flags.get("prd_path") else None
        out = record_absorb_linkage_327(
            root,
            prd_path=prd_path,
            dry_run=bool(flags.get("dry_run")),
        )
        emit(out, 0 if out.get("verdict") in {"ok", "skipped"} else 20)

    if command == "record-absorb-linkage-330":
        prd_path = Path(flags["prd_path"]).resolve() if flags.get("prd_path") else None
        out = record_absorb_linkage_330(
            root,
            prd_path=prd_path,
            dry_run=bool(flags.get("dry_run")),
        )
        emit(out, 0 if out.get("verdict") in {"ok", "skipped"} else 20)

    if command == "record-absorb-linkage-332":
        prd_path = Path(flags["prd_path"]).resolve() if flags.get("prd_path") else None
        out = record_absorb_linkage_332(
            root,
            prd_path=prd_path,
            dry_run=bool(flags.get("dry_run")),
        )
        emit(out, 0 if out.get("verdict") in {"ok", "skipped"} else 20)

    if command == "record-absorb-linkage-333":
        prd_path = Path(flags["prd_path"]).resolve() if flags.get("prd_path") else None
        out = record_absorb_linkage_333(
            root,
            prd_path=prd_path,
            dry_run=bool(flags.get("dry_run")),
        )
        emit(out, 0 if out.get("verdict") in {"ok", "skipped"} else 20)

    if command == "verify-absorb-closeout-072":
        out = verify_absorb_closeout_072(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-073":
        out = verify_absorb_closeout_073(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-325":
        out = verify_absorb_closeout_325(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-326":
        out = verify_absorb_closeout_326(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-327":
        out = verify_absorb_closeout_327(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-330":
        out = verify_absorb_closeout_330(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-332":
        out = verify_absorb_closeout_332(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-333":
        out = verify_absorb_closeout_333(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "verify-absorb-closeout-337":
        out = verify_absorb_closeout_337(root)
        emit(out, 0 if out.get("verdict") == "ok" else 20)

    if command == "prd339-cross-prd-gate":
        from prd339_cross_prd_gate import prd339_absorb_acceptance_milestone

        out = prd339_absorb_acceptance_milestone(root)
        emit(out, 0 if out.get("verdict") == "ready" else 20)

    fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
