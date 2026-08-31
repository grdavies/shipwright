#!/usr/bin/env python3
"""PRD 337 R17/R19/R20 — redacted retro gap capture with destination routing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_gap_capture as pgc
from retro_candidates import (
    FRICTION_PLUGIN_SELF,
    FRICTION_PRODUCT,
    POSTURE_CONSUMER,
    classify_friction_scope,
    resolve_repo_posture,
    select_learning_candidates,
)

DESTINATION_CONSUMER_INBOX = "consumer-inbox"
DESTINATION_META_SHIPWRIGHT = "meta-shipwright"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def route_destination(friction_scope: str) -> str:
    """Fork painful items by destination (PRD 337 R20)."""
    if friction_scope == FRICTION_PLUGIN_SELF:
        return DESTINATION_META_SHIPWRIGHT
    return DESTINATION_CONSUMER_INBOX


def consumer_rejects_plugin_friction(root: Path, friction_scope: str) -> bool:
    """Consumer planning stores reject plugin-self friction (PRD 337 R19)."""
    return resolve_repo_posture(root) == POSTURE_CONSUMER and friction_scope == FRICTION_PLUGIN_SELF


def verify_item_digest(item: dict[str, Any], *, expected: str | None = None) -> str:
    digest = pgc.retro_item_digest(item)
    if expected is not None and expected != digest:
        fail(
            "digest-mismatch",
            halt="retro-gap-digest-mismatch",
            itemId=item.get("itemId"),
            expectedDigest=expected,
            actualDigest=digest,
        )
    return digest


def _auto_materialize_product_gap(
    root: Path,
    *,
    signal_id: str,
    digest: str,
    title: str,
    summary: str,
    run_id: str,
    item_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    draft_path = pgc.gap_draft_inbox_path(root, signal_id)
    if draft_path.is_file():
        existing = pgc.load_gap_draft(root, signal_id)
        if existing.get("status") == "materialized":
            return {
                "action": "reused-materialized",
                "destination": DESTINATION_CONSUMER_INBOX,
                "digest": digest,
                "idempotent": True,
                "signalId": signal_id,
                "unitId": existing.get("materializedUnitId"),
            }
    payload = {
        "dedupKey": pgc.retro_item_dedup_key(run_id, item_id),
        "destination": DESTINATION_CONSUMER_INBOX,
        "digest": digest,
        "frictionScope": FRICTION_PRODUCT,
        "itemId": item_id,
        "kind": pgc.RETRO_GAP_KIND,
        "route": "gap-capture",
        "runId": run_id,
        "sourceClass": "retro",
        "summary": summary,
    }
    if not dry_run:
        pgc.put_gap_draft(root, signal_id=signal_id, title=title, payload=payload)
        pgc.confirm_retro_gap_draft(root, signal_id=signal_id, digest=digest)
        out = pgc.materialize_retro_gap_draft(
            root,
            signal_id=signal_id,
            digest=digest,
            problem=title,
            context=f"_Retro painful item (digest {digest})._\n\n{summary}",
            dry_run=False,
        )
        pgc.record_retro_gap_route(
            root,
            signal_id=signal_id,
            dedup_key=str(payload["dedupKey"]),
            action="auto-materialized",
            digest=digest,
            extra={"destination": DESTINATION_CONSUMER_INBOX, "unitId": out.get("unitId")},
        )
        return {
            "action": "auto-materialized",
            "destination": DESTINATION_CONSUMER_INBOX,
            "digest": digest,
            "signalId": signal_id,
            "unitId": out.get("unitId"),
        }
    return {
        "action": "would-auto-materialize",
        "destination": DESTINATION_CONSUMER_INBOX,
        "digest": digest,
        "signalId": signal_id,
    }


def _auto_materialize_meta_gap(
    root: Path,
    *,
    signal_id: str,
    digest: str,
    title: str,
    summary: str,
    run_id: str,
    item_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    inbox_path = pgc.meta_inbox_path(root, signal_id)
    if inbox_path.is_file():
        existing = pgc.load_meta_draft(root, signal_id)
        if existing.get("status") == "materialized":
            return {
                "action": "reused-materialized",
                "destination": DESTINATION_META_SHIPWRIGHT,
                "digest": digest,
                "gapClass": "plugin-self",
                "idempotent": True,
                "signalId": signal_id,
                "unitId": existing.get("materializedUnitId"),
            }
    if not dry_run:
        pgc.capture_meta_draft(root, signal_id=signal_id, title=title, summary=summary)
        pgc.confirm_meta_draft(root, signal_id=signal_id)
        out = pgc.materialize_meta_gap(root, signal_id=signal_id, title=title, dry_run=False)
        pgc.record_retro_gap_route(
            root,
            signal_id=signal_id,
            dedup_key=pgc.retro_item_dedup_key(run_id, item_id),
            action="auto-materialized",
            digest=digest,
            extra={
                "destination": DESTINATION_META_SHIPWRIGHT,
                "gapClass": "plugin-self",
                "unitId": out.get("unitId"),
            },
        )
        return {
            "action": "auto-materialized",
            "destination": DESTINATION_META_SHIPWRIGHT,
            "digest": digest,
            "gapClass": "plugin-self",
            "signalId": signal_id,
            "unitId": out.get("unitId"),
        }
    return {
        "action": "would-auto-materialize",
        "destination": DESTINATION_META_SHIPWRIGHT,
        "digest": digest,
        "gapClass": "plugin-self",
        "signalId": signal_id,
    }


def capture_retro_gaps(
    root: Path,
    retro_output: dict[str, Any],
    *,
    dry_run: bool = False,
    digest_by_item_id: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Auto-materialize digest-bound painful retro items when enabled (PRD 337 R17)."""
    cfg = pgc.retro_gap_capture_config(root)
    if not cfg["enabled"]:
        return {
            "verdict": "skipped",
            "reason": "retrospective.gapCapture.enabled is false (default)",
        }

    posture = resolve_repo_posture(root)
    run_id = str(retro_output.get("runId") or "unknown")
    items = retro_output.get("items")
    if not isinstance(items, list):
        items = []

    selection = select_learning_candidates(items, posture=posture)
    posture_excluded_ids = {str(row.get("itemId") or "") for row in selection["excluded"]}
    max_captures = int(cfg["maxCapturesPerRun"])
    materialized: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    digest_map = digest_by_item_id or {}
    painful_count = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind != pgc.RETRO_GAP_KIND:
            skipped.append({"itemId": item.get("itemId"), "kind": kind or None, "reason": "kind-excluded"})
            continue
        item_id = str(item.get("itemId") or f"item-{painful_count + 1}")
        friction_scope = classify_friction_scope(item)
        if consumer_rejects_plugin_friction(root, friction_scope):
            rejected.append(
                {
                    "destination": route_destination(friction_scope),
                    "frictionScope": friction_scope,
                    "itemId": item_id,
                    "reason": "consumer-plugin-friction-rejected",
                }
            )
            continue
        if item_id in posture_excluded_ids:
            rejected.append(
                {
                    "itemId": item_id,
                    "reason": "posture-excluded",
                }
            )
            continue

        if painful_count >= max_captures:
            overflow.append({"itemId": item_id, "reason": "cap-reached"})
            continue

        expected_digest = digest_map.get(item_id)
        digest = verify_item_digest(item, expected=expected_digest)

        summary = pgc.redact_retro_summary(str(item.get("summary") or item_id))
        title = summary[:120] if summary else item_id
        signal_id = pgc.retro_item_signal_id(run_id, item_id)
        destination = route_destination(friction_scope)
        if destination == DESTINATION_META_SHIPWRIGHT:
            out = _auto_materialize_meta_gap(
                root,
                signal_id=signal_id,
                digest=digest,
                title=title,
                summary=summary,
                run_id=run_id,
                item_id=item_id,
                dry_run=dry_run,
            )
        else:
            out = _auto_materialize_product_gap(
                root,
                signal_id=signal_id,
                digest=digest,
                title=title,
                summary=summary,
                run_id=run_id,
                item_id=item_id,
                dry_run=dry_run,
            )
        materialized.append({**out, "frictionScope": friction_scope, "itemId": item_id})
        painful_count += 1

    result: dict[str, Any] = {
        "learningCandidates": selection,
        "materialized": materialized,
        "maxCapturesPerRun": max_captures,
        "overflow": overflow,
        "posture": posture,
        "rejected": rejected,
        "skipped": skipped,
        "verdict": "pass",
    }
    if overflow:
        result["operatorMessage"] = (
            f"{len(overflow)} painful retro item(s) omitted — "
            f"retrospective.gapCapture.maxCapturesPerRun is {max_captures}"
        )
    return result


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(description="PRD 337 retro gap capture routing")
    parser.add_argument("repo_root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="Auto-materialize enabled retro painful gaps")
    capture.add_argument("--retro-json", required=True)
    capture.add_argument("--dry-run", action="store_true")

    parsed = parser.parse_args(args)
    root = parsed.repo_root.resolve()
    if parsed.command == "capture":
        retro_output = json.loads(Path(parsed.retro_json).read_text(encoding="utf-8"))
        if not isinstance(retro_output, dict):
            fail("retro-json must be an object")
        emit(capture_retro_gaps(root, retro_output, dry_run=bool(parsed.dry_run)))


if __name__ == "__main__":
    main()
