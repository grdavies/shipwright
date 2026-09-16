#!/usr/bin/env python3
"""Isolated live Linear facade pilot gate (PRD 357 R13 / TR10)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from credentials.model import Resolution, ResolutionState, ResolvedToken
from credentials.resolver import RepositoryContext, resolve
from credentials.selector_store import SelectorEntry, load_selector_store
from planning_canonical import reassemble_body
from planning_linear_canonical import linear_markdown_canonical

GRAPHQL_URL = "https://api.linear.app/graphql"
PILOT_MARKER = "sw:live-facade-pilot"
RECEIPT_GATE = "live-facade-pilot-phase-1-merge-gate"
RECEIPT_VERSION = 1

RECEIPT_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "verdict",
        "gate",
        "ops",
        "canonicalIdentityHash",
        "descriptionBytes",
        "commentBytesMax",
        "chunkCount",
        "overscopedKeyCheck",
        "scopeCheck",
        "credentialBlocked",
        "blockedCause",
    }
)

_FORBIDDEN_RECEIPT_PATTERNS = (
    re.compile(r"lin_api_[A-Za-z0-9]+", re.I),
    re.compile(r"https?://[^\s]*linear\.app", re.I),
    re.compile(r"\bmutation\b", re.I),
    re.compile(r"\bquery\b", re.I),
    re.compile(r'"data"\s*:', re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+", re.I),
)

ISSUE_DELETE_MUTATION = """
mutation IssueDelete($id: String!) {
  issueDelete(id: $id) { success }
}
""".strip()


def _pilot_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    issues = store.get("issues") if isinstance(store.get("issues"), dict) else {}
    pilot = issues.get("liveFacadePilot")
    return pilot if isinstance(pilot, dict) else {}


def live_facade_pilot_synthetic_body(root: Path) -> str:
    """Sanitized chunked body from the public fixture corpus (R16)."""
    fixture = (
        root
        / "scripts/test/fixtures/planning-linear-chunk/fixtures/multi-chunk.json"
    )
    if not fixture.is_file():
        return (
            "# Live facade pilot\n\n"
            + ("synthetic paragraph line.\n\n" * 4000)
        )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    body = str(data.get("body") or "")
    if not body.strip():
        raise ValueError("empty synthetic pilot body")
    return body


def _strip_pilot_marker(markdown: str) -> str:
    return re.sub(
        rf"<!--\s*{re.escape(PILOT_MARKER)}\s*-->\s*",
        "",
        markdown,
        count=1,
    )


def canonical_identity_hash(markdown: str) -> str:
    canonical = linear_markdown_canonical(_strip_pilot_marker(markdown))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_live_facade_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if receipt leaks secrets, GraphQL, or Linear URLs (TR10)."""
    extra = set(receipt) - RECEIPT_TOP_LEVEL_KEYS
    if extra:
        return {
            "verdict": "fail",
            "error": "receipt-extra-keys",
            "keys": sorted(extra),
        }
    blob = json.dumps(receipt, sort_keys=True)
    for pattern in _FORBIDDEN_RECEIPT_PATTERNS:
        if pattern.search(blob):
            return {
                "verdict": "fail",
                "error": "receipt-forbidden-content",
                "pattern": pattern.pattern,
            }
    return {"verdict": "ok"}


def _pilot_broker_context(pilot: dict[str, Any]) -> tuple[str, str, str] | str:
    """Return (remote, repo_slug, project_id) from the consumer pin, or an error code."""
    project_id = str(pilot.get("projectId") or "").strip()
    if not project_id:
        return "missing-pilot-project-id"
    repo_slug = str(pilot.get("repoSlug") or "").strip()
    remote = str(pilot.get("remote") or "").strip()
    if not remote and repo_slug:
        remote = f"https://github.com/{repo_slug}.git"
    if not repo_slug and remote:
        from host_lib import parse_owner_repo

        parsed = parse_owner_repo(remote)
        repo_slug = f"{parsed[0]}/{parsed[1]}" if parsed else ""
    if not repo_slug or not remote:
        return "missing-pilot-repo-scope"
    return remote, repo_slug, project_id


def _linear_cfg_for_pilot(cfg: dict[str, Any], pilot: dict[str, Any], cred_ref: str) -> dict[str, Any]:
    linear_cfg = json.loads(json.dumps(cfg))
    store = linear_cfg.setdefault("planning", {}).setdefault("store", {})
    store["issuesProvider"] = "linear"
    issues = store.setdefault("issues", {})
    if not isinstance(issues, dict):
        issues = {}
        store["issues"] = issues
    issues["credentialRef"] = cred_ref
    team_key = str(pilot.get("teamKey") or issues.get("teamKey") or "").strip()
    if team_key:
        issues["teamKey"] = team_key
    team_id = str(pilot.get("teamId") or issues.get("teamId") or "").strip()
    if team_id:
        issues["teamId"] = team_id
    return linear_cfg


def _resolve_pilot_credential(
    root: Path,
    cfg: dict[str, Any],
    pilot: dict[str, Any],
) -> tuple[Resolution | None, str | None]:
    from credentials.model import CredentialRef
    from host_lib import load_workflow_config

    resolved_cfg = cfg if cfg is not None else load_workflow_config(root)
    issues = (
        (resolved_cfg.get("planning") or {}).get("store") or {}
    ).get("issues") or {}
    cred_ref = pilot.get("credentialRef") or issues.get("credentialRef")
    if not isinstance(cred_ref, str) or not cred_ref.strip():
        return None, "missing-credential-ref"
    scoped = _pilot_broker_context(pilot)
    if isinstance(scoped, str):
        return None, scoped
    remote_url, repo_slug, project_id_str = scoped
    resolution = resolve(
        CredentialRef(cred_ref.strip()),
        provider="linear",
        purpose="planning",
        context=RepositoryContext(
            remote=remote_url,
            repo_slug=repo_slug,
            project_id=project_id_str,
            destination_endpoint=GRAPHQL_URL,
            adapter_id="linear",
        ),
    )
    if resolution.state != ResolutionState.RESOLVED:
        reason = getattr(resolution, "reason", None) or "credential-unresolved"
        return resolution, str(reason)
    return resolution, None


def _selector_entry_for_ref(ref: str) -> SelectorEntry | None:
    try:
        doc = load_selector_store()
    except Exception:  # noqa: BLE001
        return None
    entry = doc.entries.get(ref)
    return entry if isinstance(entry, SelectorEntry) else None


def _validate_pilot_scope(
    pilot: dict[str, Any],
    *,
    credential_ref: str,
) -> dict[str, Any]:
    project_id = str(pilot.get("projectId") or "").strip()
    if not project_id:
        return {
            "verdict": "fail",
            "error": "missing-pilot-project-id",
            "message": "planning.store.issues.liveFacadePilot.projectId is required",
        }
    entry = _selector_entry_for_ref(credential_ref)
    if entry is None:
        return {
            "verdict": "fail",
            "error": "selector-entry-missing",
            "credentialRef": credential_ref,
        }
    allowed_projects = tuple(entry.allowed_project_ids)
    if project_id not in allowed_projects:
        return {
            "verdict": "fail",
            "error": "pilot-project-out-of-scope",
            "projectId": project_id,
            "allowedProjectIds": list(allowed_projects),
        }
    allowed_endpoints = {item.strip().lower() for item in entry.allowed_endpoints if item.strip()}
    if GRAPHQL_URL.lower() not in allowed_endpoints and not any(
        "api.linear.app" in ep for ep in allowed_endpoints
    ):
        return {
            "verdict": "fail",
            "error": "pilot-endpoint-out-of-scope",
            "allowedEndpoints": list(entry.allowed_endpoints),
        }
    return {
        "verdict": "ok",
        "projectId": project_id,
        "allowedProjectIds": list(allowed_projects),
        "allowedEndpoints": list(entry.allowed_endpoints),
    }


def _materialize_facade_body(record: Any) -> str:
    return reassemble_body(str(record.body or ""), list(record.comments or []))


def _refetched_canonical(record: Any) -> str:
    materialized = _materialize_facade_body(record)
    return linear_markdown_canonical(materialized)


def _comment_byte_max(record: Any) -> int:
    sizes = [len(str(c.body or "").encode("utf-8")) for c in (record.comments or [])]
    return max(sizes) if sizes else 0


def live_facade_pilot_gate(
    root: Path,
    cfg: dict[str, Any],
    *,
    receipt_path: Path | None = None,
    skip_live: bool = False,
) -> dict[str, Any]:
    """Run create/read/update/materialize against live Linear (broker-only)."""
    from host_lib import load_workflow_config
    from issues_broker import require_token
    from planning_linear_client import (
        LinearClientError,
        LinearIssuesClient,
        graphql,
        probe_team_scope,
    )

    root = Path(root).resolve()
    cfg = cfg if cfg is not None else load_workflow_config(root)
    pilot = _pilot_section(cfg)
    issues = (
        (cfg.get("planning") or {}).get("store") or {}
    ).get("issues") or {}
    cred_ref = str(pilot.get("credentialRef") or issues.get("credentialRef") or "").strip()

    base_receipt: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "gate": RECEIPT_GATE,
        "credentialBlocked": False,
        "blockedCause": None,
    }

    scope = _validate_pilot_scope(pilot, credential_ref=cred_ref) if cred_ref else {
        "verdict": "fail",
        "error": "missing-credential-ref",
    }
    if scope.get("verdict") != "ok":
        out = {
            **base_receipt,
            "verdict": "blocked",
            "blockedCause": f"live-facade-pilot:{scope.get('error')}",
            "scopeCheck": scope,
            "ops": [],
        }
        if receipt_path:
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        return out

    resolution, cred_err = _resolve_pilot_credential(root, cfg, pilot)
    if cred_err or resolution is None or resolution.state != ResolutionState.RESOLVED:
        cause = cred_err or "credential-unresolved"
        out = {
            **base_receipt,
            "verdict": "blocked",
            "credentialBlocked": True,
            "blockedCause": f"live-facade-pilot:{cause}",
            "scopeCheck": scope,
            "ops": [],
        }
        if receipt_path:
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        return out

    if skip_live:
        out = {
            **base_receipt,
            "verdict": "ok",
            "scopeCheck": scope,
            "ops": ["dry-run"],
            "canonicalIdentityHash": "",
            "descriptionBytes": 0,
            "commentBytesMax": 0,
            "chunkCount": 0,
            "overscopedKeyCheck": "skipped",
        }
        validation = validate_live_facade_receipt(out)
        if validation.get("verdict") != "ok":
            out["verdict"] = "fail"
            out["blockedCause"] = validation.get("error")
        return out

    token = require_token(resolution)
    linear_cfg = _linear_cfg_for_pilot(cfg, pilot, cred_ref)
    team_probe = probe_team_scope(root, linear_cfg, token=token)
    overscoped = False
    if team_probe.get("verdict") != "ok":
        if team_probe.get("error") == "overscoped-key":
            overscoped = True
        else:
            out = {
                **base_receipt,
                "verdict": "blocked",
                "blockedCause": f"live-facade-pilot:{team_probe.get('error')}",
                "scopeCheck": scope,
                "overscopedKeyCheck": team_probe,
                "ops": [],
            }
            if receipt_path:
                receipt_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
            return out

    project_key = str(
        ((linear_cfg.get("planning") or {}).get("store") or {}).get("projectKey") or "shipwright-pilot"
    )

    client = LinearIssuesClient(
        root,
        cfg=linear_cfg,
        token=token,
        credential=resolution,
    )

    synthetic = live_facade_pilot_synthetic_body(root)
    ops: list[str] = []
    issue_id = ""
    receipt: dict[str, Any] = base_receipt
    try:
        created = client.create(
            title="[sw-pilot] live facade receipt",
            body=f"<!-- {PILOT_MARKER} -->\n\n{synthetic}",
            labels=[project_key, "sw:pilot", "artifact:gap"],
            project_key=project_key,
            artifact_type="gap",
            unit_id="live-facade-pilot",
        )
        ops.append("create")
        issue_id = str(created.id)
        after_create = client.get(issue_id)
        ops.append("read")
        materialized_create = _materialize_facade_body(after_create)
        if canonical_identity_hash(materialized_create) != canonical_identity_hash(synthetic):
            raise LinearClientError(
                "live identity mismatch after create",
                code="canonical-identity-mismatch",
            )
        updated_synthetic = f"{synthetic}\n\n## pilot-update\n\nminor sanitized edit."
        updated_body = f"<!-- {PILOT_MARKER} -->\n\n{updated_synthetic}"
        client.update(issue_id, body=updated_body, if_match=after_create.etag)
        ops.append("update")
        after_update = client.get(issue_id)
        ops.append("read")
        materialized = _materialize_facade_body(after_update)
        ops.append("materialize")
        if canonical_identity_hash(materialized) != canonical_identity_hash(updated_synthetic):
            raise LinearClientError(
                "live identity mismatch after update",
                code="canonical-identity-mismatch",
            )
        chunk_count = len([c for c in after_update.comments if "sw-chunk-overflow" in c.body])
        receipt = {
            **base_receipt,
            "verdict": "ok",
            "ops": ops,
            "canonicalIdentityHash": canonical_identity_hash(materialized),
            "descriptionBytes": len(str(after_update.body or "").encode("utf-8")),
            "commentBytesMax": _comment_byte_max(after_update),
            "chunkCount": chunk_count,
            "overscopedKeyCheck": "fail" if overscoped else "ok",
            "scopeCheck": {"verdict": "ok", "projectId": scope.get("projectId")},
        }
        if overscoped:
            receipt["verdict"] = "fail"
            receipt["blockedCause"] = "live-facade-pilot:overscoped-key"
        validation = validate_live_facade_receipt(receipt)
        if validation.get("verdict") != "ok":
            receipt["verdict"] = "fail"
            receipt["blockedCause"] = validation.get("error")
    except LinearClientError as exc:
        receipt = {
            **base_receipt,
            "verdict": "fail",
            "blockedCause": f"live-facade-pilot:{exc.code}",
            "scopeCheck": scope,
            "ops": ops,
        }
    finally:
        if issue_id:
            try:
                client.mark_tombstone(issue_id)
                ops.append("tombstone")
            except Exception:  # noqa: BLE001
                try:
                    graphql(
                        root,
                        linear_cfg,
                        query=ISSUE_DELETE_MUTATION,
                        variables={"id": issue_id},
                        token=token,
                        credential=resolution,
                    )
                    ops.append("delete")
                except Exception:  # noqa: BLE001
                    pass

    if receipt_path:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
