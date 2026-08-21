#!/usr/bin/env python3
"""Planning store package CLI (PRD 082 phase 14 / R27)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_store_facade as _facade

# Bind facade symbols (including _optional/_require) for the extracted main body.
for _name in dir(_facade):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_facade, _name)
del _name

def main() -> None:
    parser = argparse.ArgumentParser(description="Planning store interface (PRD 034 + PRD 043)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "resolve-backend",
        "list-backends",
        "list-facade",
        "lint-facade-imports",
        "lint-projection-mutations",
        "operator-projection-contract",
        "linear-projection-schema",
        "comments-relations-schema",
        "issues-provider-registration",
        "resolve-issues",
        "resolve-store-location",
        "probe-issues-token",
        "probe-jira-init",
        "bitbucket-issue-store-guidance",
        "validate-project-key",
        "put",
        "get",
        "exists",
        "materialize",
        "materialize-from-store",
        "validate-local-synced",
        "canonical-hash",
        "freeze",
        "verify-frozen-hash",
        "link-brainstorm-prd",
        "mark-issue-tombstone",
        "mark-issue-transferred",
        "clear-issue-fixture",
        "close-delivery-units",
        "doctor",
        "cleanup",
        "progress-update",
        "external-intake-txn",
        "external-intake-pipeline",
        "migrate-orphan-phase-issues",
        "projection-refresh",
        "probe-projection",
        "write-back-gap-prereqs",
        "resolve-absorbed-gaps-061",
        "verify-absorb-linkage-066",
    ):
        sub.add_parser(name)
    args, rest = parser.parse_known_args()
    root = git_root(Path(args.root).resolve())
    cfg = load_workflow_config(root)
    if args.command == "list-facade":
        emit(facade_surface())
    elif args.command == "lint-facade-imports":
        scope = _optional(rest, "--path")
        result = lint_facade_imports(root, scope=scope)
        emit(result, 0 if result.get("verdict") == "pass" else 20)
    elif args.command == "lint-projection-mutations":
        scope = _optional(rest, "--path")
        result = lint_projection_mutations(root, scope=scope)
        emit(result, 0 if result.get("verdict") == "pass" else 20)
    elif args.command == "operator-projection-contract":
        emit(operator_projection_contract())
    elif args.command == "linear-projection-schema":
        emit(linear_projection_schema_contract())
    elif args.command == "comments-relations-schema":
        emit(comments_relations_schema_contract())
    elif args.command == "issues-provider-registration":
        emit(issues_provider_registration_footprint())
    elif args.command == "resolve-backend":

        override = _optional(rest, "--backend")
        emit(resolve_effective_backend(root, cfg, override=override))
    elif args.command == "list-backends":
        emit({
            "verdict": "ok",
            "default": DEFAULT_BACKEND,
            "shipped": sorted(SHIPPED_BACKENDS),
            "deferred": sorted(DEFERRED_BACKENDS),
            "issuesProviders": sorted(ISSUES_PROVIDERS),
            "interface": ["put", "get", "exists", "materialize"],
        })
    elif args.command == "resolve-issues":
        emit(resolve_issues_provider(cfg))
    elif args.command == "resolve-store-location":
        emit(resolve_store_location(root, cfg))
    elif args.command == "probe-issues-token":
        result = probe_issues_token(root, cfg)
        emit(result, 0 if result.get("verdict") == "ok" else 2)
    elif args.command == "probe-jira-init":
        issues = resolve_issues_provider(cfg)
        if issues.get("provider") != "jira":
            emit({"verdict": "ok", "skipped": True, "reason": "not-jira"})
        token_env = resolve_issues_token_env(cfg, "jira")
        if not token_env or not token_present(token_env):
            fail("missing-token", tokenEnv=token_env)
        from planning_jira_probe import probe_jira_init
        result = probe_jira_init(cfg, os.environ.get(token_env, ""), root)
        emit(result, 0 if result.get("verdict") == "ok" else 2)
    elif args.command == "bitbucket-issue-store-guidance":
        guidance = bitbucket_issue_store_guidance(root, cfg)
        if guidance:
            emit(guidance)
        emit({"verdict": "ok", "skipped": True, "reason": "not-bitbucket-or-issues-configured"})
    elif args.command == "validate-project-key":
        register = "--register" in rest
        result = validate_project_key(root, cfg, register=register)
        emit(result, 0 if result.get("verdict") == "ok" else 2)
    elif args.command == "put":
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"), operation="write")
        result = backend.put(_require(rest, "--unit-id"), _require(rest, "--body-path"), _require(rest, "--content"), content_class=_optional(rest, "--content-class"))
        emit(result.as_dict())
    elif args.command == "get":
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        result = backend.get(_require(rest, "--unit-id"), _require(rest, "--body-path"))
        emit(result.as_dict(), 0 if result.verdict in {"ok", "degraded"} else 2)
    elif args.command == "exists":
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        emit(backend.exists(_require(rest, "--unit-id"), _require(rest, "--body-path")).as_dict())
    elif args.command == "materialize":
        unit_id = _require(rest, "--unit-id")
        body_path = _require(rest, "--body-path")
        dest = Path(_require(rest, "--dest"))
        if "--resync" in rest:
            result = materialize_with_resync(root, unit_id, body_path, dest)
            exit_code = 0 if result.get("verdict") == "ok" else 1
            emit(result, exit_code)
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        result = backend.materialize(unit_id, body_path, dest)
        emit(result.as_dict(), 0 if result.verdict == "ok" else 2)
    elif args.command == "materialize-from-store":
        units_file = _optional(rest, "--units-file")
        units_raw = _optional(rest, "--units-json")
        if units_file:
            units = json.loads(Path(units_file).read_text(encoding="utf-8"))
        elif units_raw:
            units = json.loads(units_raw)
        else:
            units = []
        result = materialize_from_store(root, cfg, units)
        emit(result, 0 if result.get("verdict") == "ok" else 2)

    elif args.command == "canonical-hash":
        from planning_canonical import CommentRecord, IssueSnapshot, canonical_form, canonical_hash as ch
        fixture_path = Path(_require(rest, "--fixture"))
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        comments = [CommentRecord(**c) for c in data.get("comments", [])]
        snap = IssueSnapshot(
            title=data["title"],
            body=data["body"],
            state=data.get("state", "open"),
            labels=list(data.get("labels", [])),
            comments=comments,
        )
        emit({"verdict": "ok", "canonical": canonical_form(snap), "hash": ch(snap)})

    elif args.command == "freeze":
        backend = get_backend(root, cfg, override="issue-store")
        if not isinstance(backend, IssueStoreBackend):
            fail("issue-store backend required")
        distill = "--no-distill" not in rest
        emit(backend.freeze(_require(rest, "--unit-id"), _require(rest, "--body-path"), distill=distill))
    elif args.command == "verify-frozen-hash":
        backend = get_backend(root, cfg, override="issue-store")
        if not isinstance(backend, IssueStoreBackend):
            fail("issue-store backend required")
        result = backend.verify_frozen_hash(_require(rest, "--unit-id"), _require(rest, "--body-path"))
        emit(result)
    elif args.command == "mark-issue-tombstone":
        client = IssuesClient(root, resolve_issues_provider(cfg).get("provider", "none"))
        client.mark_tombstone(_require(rest, "--issue-id"))
        emit({"verdict": "ok"})
    elif args.command == "mark-issue-transferred":
        client = IssuesClient(root, resolve_issues_provider(cfg).get("provider", "none"))
        client.mark_transferred(_require(rest, "--issue-id"))
        emit({"verdict": "ok"})
    elif args.command == "link-brainstorm-prd":
        backend = get_backend(root, cfg, override="issue-store")
        if not isinstance(backend, IssueStoreBackend):
            fail("issue-store backend required")
        emit(backend.link_brainstorm_to_prd(_require(rest, "--brainstorm-unit"), _require(rest, "--prd-unit")))
    elif args.command == "clear-issue-fixture":
        from issues_lib import get_fixture_store
        get_fixture_store(root).clear()
        emit({"verdict": "ok"})
    elif args.command == "validate-local-synced":
        raw = _require(rest, "--path")
        allowlist_raw = _optional(rest, "--allowlist")
        allowlist = [p.strip() for p in allowlist_raw.split(",") if p.strip()] if allowlist_raw else None
        store = store_section(cfg)
        local = store.get("localSynced")
        if isinstance(local, dict) and not allowlist:
            cfg_allow = local.get("allowlist")
            if isinstance(cfg_allow, list):
                allowlist = [str(x) for x in cfg_allow]
        result = validate_local_synced_path(Path(os.path.expanduser(raw)), allowlist=allowlist)
        emit(result, 0 if result["verdict"] == "ok" else 2)
    elif args.command == "close-delivery-units":
        dry_run = "--dry-run" in rest
        result = close_delivery_units(root, cfg, _require(rest, "--prd-unit"), dry_run=dry_run)
        emit(result, 0 if result.get("verdict") in {"ready", "dry-run"} else 2)
    elif args.command == "projection-refresh":
        from planning_github_projects_v2 import refresh_projection, sample_projection_items

        dry_run = "--dry-run" in rest
        result = refresh_projection(root, cfg, dry_run=dry_run, items=sample_projection_items(root, cfg))
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "probe-projection":
        from planning_github_projects_v2 import projection_health

        result = projection_health(root, cfg)
        emit(result)
    elif args.command == "write-back-gap-prereqs":
        dry_run = "--dry-run" in rest
        result = write_back_gap_prereqs_061(root, cfg, dry_run=dry_run)
        emit(result, 0 if result.get("verdict") in {"ok", "skipped"} else 20)
    elif args.command == "resolve-absorbed-gaps-061":
        dry_run = "--dry-run" in rest
        force = "--force" in rest
        unit_id = _optional(rest, "--unit-id")
        result = resolve_absorbed_gaps_061(root, cfg, dry_run=dry_run, force=force, unit_id=unit_id)
        emit(result, 0 if result.get("verdict") in {"ok", "skipped"} else 20)
    elif args.command == "audit-closure-completeness":
        prd_unit = _require(rest, "--prd-unit")
        result = audit_closure_completeness(root, cfg, prd_unit)
        emit(result, 0 if result.get("verdict") == "ready" else 20)

    elif args.command == "verify-absorb-linkage-066":
        prd_unit = _optional(rest, "--prd-unit-id") or PRD_066_ABSORB_UNIT_ID
        gap_unit = _optional(rest, "--gap-unit-id") or GAP_079_ABSORB_UNIT_ID
        planning_issue = _optional(rest, "--planning-issue") or GAP_079_PLANNING_ISSUE_REF
        result = verify_absorb_linkage_066(
            root,
            cfg,
            prd_unit_id=prd_unit,
            gap_unit_id=gap_unit,
            planning_issue=planning_issue,
        )
        emit(result, 0 if result.get("verdict") in {"ok", "skipped"} else 20)
    elif args.command == "doctor":
        result = doctor(root, cfg)
        emit(result, 0 if result.get("verdict") == "pass" else 20)

    elif args.command == "progress-update":
        parent = _require(rest, "--parent-issue-id")
        phase_id = _require(rest, "--phase-id")
        action = _optional(rest, "--action") or "phase-done"
        provider = _optional(rest, "--provider")
        project_key = _optional(rest, "--project-key")
        task_list = _optional(rest, "--task-list")
        task_ref = _optional(rest, "--task-ref")
        checked_raw = _optional(rest, "--checked-phase-ids")
        checked = [x.strip() for x in checked_raw.split(",") if x.strip()] if checked_raw else None
        result = progress_update(
            root,
            parent_issue_id=parent,
            phase_id=phase_id,
            action=action,
            provider=provider,
            project_key=project_key,
            task_list=task_list,
            checked_phase_ids=checked,
            task_ref=task_ref,
        )
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "external-intake-txn":
        from workflow_extensions import require_extension

        disabled = require_extension("externalIntake", root=root, cfg=cfg)
        if disabled is not None:
            emit({**disabled, "action": "external-intake-txn"}, 20)
        verb = _require(rest, "--verb")
        result = external_intake_txn(
            root,
            cfg,
            verb=verb,
            issue_id=_optional(rest, "--issue-id"),
            signal_id=_optional(rest, "--signal-id"),
            title=_optional(rest, "--title"),
            signal_class=_optional(rest, "--signal-class") or "unknown",
            comment=_optional(rest, "--comment"),
            gap_unit_id=_optional(rest, "--gap-unit-id"),
            priority=_optional(rest, "--priority") or "medium",
            tier=_optional(rest, "--tier") or "build",
            gap_class=_optional(rest, "--gap-class") or "external",
            dry_run="--dry-run" in rest,
        )
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "external-intake-pipeline":
        from workflow_extensions import require_extension

        disabled = require_extension("externalIntake", root=root, cfg=cfg)
        if disabled is not None:
            emit({**disabled, "action": "external-intake-pipeline"}, 20)
        issue_id = _require(rest, "--issue-id")
        result = external_intake_run_pipeline(
            root,
            cfg,
            issue_id=issue_id,
            duplicate="--duplicate" in rest,
            dry_run="--dry-run" in rest,
        )
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "migrate-orphan-phase-issues":
        unit_id = _optional(rest, "--tasks-unit-id")
        dry_run = "--apply" not in rest
        result = migrate_orphan_phase_issues(root, cfg, tasks_unit_id=unit_id, dry_run=dry_run)
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "cleanup":
        apply = "--apply" in rest
        result = cleanup_separate_project_local_writes(root, cfg, apply=apply)
        emit(result, 0 if result.get("verdict") == "ok" else 20)




if __name__ == "__main__":
    main()
