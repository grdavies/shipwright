#!/usr/bin/env python3
"""PRD 082 phase 7 — refusal ledger operator CLI (R26)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config
from memory_redact import redact
import planning_ledger_store as pls
import planning_refusal_ledger as prl
import planning_visibility as pv

RECORD_SCRIPT = (SCRIPT_DIR / "planning_refusal_ledger.py").resolve()
CLI_SCRIPT = (SCRIPT_DIR / "planning_refusal_ledger_cli.py").resolve()
EXPORT_SCHEMA_VERSION = 1


def resolve_recorded_destination_tier(entry: dict[str, Any]) -> str:
    """Infer the destination tier applied when the refusal was recorded."""
    _ = entry.get("destinationPolicyId"), entry.get("destinationPolicyVersion")
    return pv.resolve_emission_destination("store-get")


def redact_entry_for_display(entry: dict[str, Any], *, destination_tier: str | None = None) -> dict[str, Any]:
    tier = destination_tier or resolve_recorded_destination_tier(entry)
    body = str(entry.get("redactedBody") or "")
    try:
        display_body = redact(body, destination=tier)
    except ValueError:
        display_body = "[redacted:invalid-tier]"
    out = {k: v for k, v in entry.items() if k not in {"redactedBody", "digest"}}
    out["displayBody"] = display_body
    out["displayDestinationTier"] = tier
    return out


def list_entries_display(root: Path, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    entries = prl.list_refusals(root, cfg)
    return [redact_entry_for_display(entry) for entry in entries]


def show_entry(
    root: Path,
    entry_id: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    ledger_dir = pls.resolve_ledger_path(root, cfg)
    entry_root = pls.entries_dir(ledger_dir)
    entry = pls.load_entry(entry_root, entry_id)
    if entry is None:
        for candidate in prl.list_refusals(root, cfg):
            if candidate.get("entryId") == entry_id or candidate.get("idempotencyKey") == entry_id:
                entry = candidate
                break
    if entry is None:
        return {
            "verdict": "fail",
            "action": "show",
            "error": "entry-not-found",
            "entryId": entry_id,
        }
    return {
        "verdict": "ok",
        "action": "show",
        "entry": redact_entry_for_display(entry),
    }


def compute_export_idempotency_key(entries: list[dict[str, Any]]) -> str:
    keys = sorted(str(entry.get("idempotencyKey") or entry.get("entryId") or "") for entry in entries)
    canonical = "\n".join(keys)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_export_script(root: Path, entries: list[dict[str, Any]]) -> str:
    export_key = compute_export_idempotency_key(entries)
    lines = [
        "#!/usr/bin/env bash",
        "# refusal-ledger-export — operator-runnable record commands only; does not replay refused writes.",
        f"# exportSchemaVersion: {EXPORT_SCHEMA_VERSION}",
        f"# exportIdempotencyKey: {export_key}",
        f"# entryCount: {len(entries)}",
        "set -euo pipefail",
        "",
    ]
    for entry in entries:
        key = str(entry.get("idempotencyKey") or entry.get("entryId") or "")
        unit_id = shlex.quote(str(entry.get("unitId") or ""))
        operation = shlex.quote(str(entry.get("operation") or ""))
        authority_state = shlex.quote(str(entry.get("authorityState") or ""))
        authority_reason = entry.get("authorityReason")
        reason_flag = (
            f" --authority-reason {shlex.quote(str(authority_reason))}"
            if authority_reason is not None
            else ""
        )
        policy_id = shlex.quote(str(entry.get("destinationPolicyId") or ""))
        policy_version = shlex.quote(str(entry.get("destinationPolicyVersion") or ""))
        body = str(entry.get("redactedBody") or "")
        body_path = f".cursor/sw-refusal-ledger/export-bodies/{key}.txt"
        rel_body_dir = (root / ".cursor/sw-refusal-ledger/export-bodies").relative_to(root)
        record_cmd = (
            f"{shlex.quote(sys.executable)} {shlex.quote(str(RECORD_SCRIPT))}"
            f" --root {shlex.quote(str(root))} record"
            f" --unit-id {unit_id} --operation {operation}"
            f" --body-file {shlex.quote(body_path)}"
            f" --authority-state {authority_state}{reason_flag}"
            f" --destination-policy-id {policy_id}"
            f" --destination-policy-version {policy_version}"
        )
        show_cmd = (
            f"{shlex.quote(sys.executable)} {shlex.quote(str(CLI_SCRIPT))}"
            f" --root {shlex.quote(str(root))} show {shlex.quote(key)}"
        )
        lines.extend(
            [
                f"# idempotencyKey: {key}",
                f"mkdir -p {shlex.quote(str(rel_body_dir))}",
                f"cat > {shlex.quote(body_path)} <<'SW_REFUSAL_BODY_EOF'",
                body,
                "SW_REFUSAL_BODY_EOF",
                f"if ! {show_cmd} 2>/dev/null | grep -q '\"verdict\": \"ok\"'; then",
                f"  {record_cmd}",
                "fi",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def export_entries(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    entries = prl.list_refusals(root, cfg)
    script = build_export_script(root, entries)
    export_key = compute_export_idempotency_key(entries)
    return {
        "verdict": "ok",
        "action": "export",
        "exportIdempotencyKey": export_key,
        "entryCount": len(entries),
        "script": script,
        "replayRefusedWrites": False,
    }


def purge_entries(
    root: Path,
    *,
    entry_ids: list[str] | None = None,
    all_entries: bool = False,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    ledger_dir = pls.resolve_ledger_path(root, cfg)
    contract = pls.verify_ledger_path_contract(root, ledger_dir)
    if contract.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "action": "purge",
            "error": "ledger-path-contract",
            "contract": contract,
        }
    if all_entries:
        purged = pls.purge_all_entries(ledger_dir, reason="purge")
    elif entry_ids:
        purged = pls.purge_entries(ledger_dir, entry_ids, reason="purge")
    else:
        return {
            "verdict": "fail",
            "action": "purge",
            "error": "missing-target",
            "hint": "pass --entry-id and/or --all",
        }
    return {
        "verdict": "ok",
        "action": "purge",
        "purged": purged.get("purged") or [],
        "remaining": len(prl.list_refusals(root, cfg)),
        "journalPath": str(pls.eviction_journal_path(ledger_dir)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planning refusal ledger CLI (PRD 082 R26)")
    parser.add_argument("--root", type=Path, default=SCRIPT_DIR.parent)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List refusal entries with tier-redacted bodies")

    show = sub.add_parser("show", help="Show one refusal entry")
    show.add_argument("entry_id", help="entryId or idempotencyKey")

    export = sub.add_parser("export", help="Export operator-runnable record commands")
    export.add_argument("--out", type=Path, default=None, help="Write script to file (stdout if omitted)")

    purge = sub.add_parser("purge", help="Purge refusal entries (journaled)")
    purge.add_argument("--entry-id", action="append", default=[], dest="entry_ids")
    purge.add_argument("--all", action="store_true", help="Purge every ledger entry")

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "list":
        payload = {"verdict": "ok", "action": "list", "entries": list_entries_display(root)}
    elif args.command == "show":
        payload = show_entry(root, args.entry_id)
    elif args.command == "export":
        payload = export_entries(root)
        if payload.get("verdict") == "ok" and args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(payload["script"], encoding="utf-8")
            payload = {k: v for k, v in payload.items() if k != "script"}
            payload["out"] = str(args.out)
    else:
        payload = purge_entries(
            root,
            entry_ids=list(args.entry_ids or []),
            all_entries=bool(args.all),
        )

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("verdict") == "ok" else 20


if __name__ == "__main__":
    raise SystemExit(main())
