#!/usr/bin/env python3
"""Thin Notion REST client (PRD 327 R2) + LCD verbs (R10)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import issues_broker
import issues_http
from credentials.model import Resolution, ResolvedToken
from host_lib import load_workflow_config
from planning_canonical import (
    BODY_SIZE_LIMIT,
    FROZEN_LABEL,
    MARKER_ARTIFACT_TYPE,
    MARKER_PROJECT_KEY,
    MARKER_UNIT_ID,
    SOURCE_REMOVED_LABEL,
    CommentRecord,
    artifact_type_from_labels,
    build_freeze_record_body,
    canonical_hash,
    chunk_body_if_needed,
    compute_etag,
    parse_body_marker,
    project_label,
    reassemble_body,
    rewrite_chunk_manifest_ids,
    type_label,
    unit_id_from_labels,
)
from planning_notion_canonical import (
    NOTION_BLOCK_APPEND_LIMIT,
    NOTION_RICH_TEXT_CHAR_LIMIT,
    blocks_to_markdown,
    markdown_to_blocks,
    paginate_blocks,
    split_rich_text_chunks,
)

LIVE_CLIENT = True
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_TITLE_PROPERTY = "Name"
DEFAULT_STATUS_PROPERTY = "Status"
DEFAULT_PROJECT_PROPERTY = "Project"
ADAPTER_VERBS = (
    "create",
    "get",
    "update",
    "add_comment",
    "set_labels",
    "lock",
    "search",
)
LIFECYCLE_HOOKS = (
    "mark_tombstone",
    "mark_transferred",
    "mark_archived_project",
    "mark_type_converted",
    "mark_key_changed",
)
LOCK_CAPABILITY = "degraded"
NATIVE_ISSUE_LOCK = False
SEARCH_PAGE_SIZE = 100
NOTION_LABEL_DEGRADATION_LADDER = ("multi_select", "select", "customField")
DEFAULT_PARENT_RELATION_PROPERTY = "Parent"
SW_LABEL_MARKERS = frozenset({
    "sw:prd",
    "sw:brainstorm",
    "sw:gap",
    "sw:task",
    FROZEN_LABEL,
})
_LABEL_DEGRADED_EMITTED = False
_HIERARCHY_DEGRADED_EMITTED = False
_RELATION_DEGRADED_EMITTED = False
_COMMENT_MUTATION_DEGRADED_EMITTED = False


class NotionClientError(Exception):
    def __init__(self, message: str, *, code: str = "notion-client-error") -> None:
        super().__init__(message)
        self.code = code


class NotionDatabaseConfigError(NotionClientError):
    pass


def _issues_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    issues = store.get("issues")
    return issues if isinstance(issues, dict) else {}


def resolve_token_env(cfg: dict[str, Any]) -> str:
    raw = _issues_section(cfg).get("tokenEnv")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "ISSUES_NOTION_TOKEN"


def resolve_title_property(cfg: dict[str, Any]) -> str:
    issues = _issues_section(cfg)
    raw = issues.get("notionTitleProperty")
    return raw.strip() if isinstance(raw, str) and raw.strip() else DEFAULT_TITLE_PROPERTY


def resolve_status_property(cfg: dict[str, Any]) -> str:
    issues = _issues_section(cfg)
    raw = issues.get("notionStatusProperty")
    return raw.strip() if isinstance(raw, str) and raw.strip() else DEFAULT_STATUS_PROPERTY


def resolve_project_property(cfg: dict[str, Any]) -> str:
    issues = _issues_section(cfg)
    raw = issues.get("notionProjectProperty")
    return raw.strip() if isinstance(raw, str) and raw.strip() else DEFAULT_PROJECT_PROPERTY


def resolve_label_property(cfg: dict[str, Any]) -> str:
    issues = _issues_section(cfg)
    raw = issues.get("notionLabelProperty")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return resolve_project_property(cfg)


def resolve_parent_relation_property(cfg: dict[str, Any]) -> str:
    issues = _issues_section(cfg)
    raw = issues.get("notionParentRelationProperty")
    return raw.strip() if isinstance(raw, str) and raw.strip() else DEFAULT_PARENT_RELATION_PROPERTY


def resolve_label_custom_field(cfg: dict[str, Any]) -> str | None:
    issues = _issues_section(cfg)
    raw = issues.get("labelCustomField")
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def resolve_label_surface_config(cfg: dict[str, Any]) -> str | None:
    issues = _issues_section(cfg)
    raw = issues.get("labelSurface")
    if isinstance(raw, str) and raw.strip().lower() in NOTION_LABEL_DEGRADATION_LADDER:
        return raw.strip().lower()
    return None


def _emit_operator_notice(
    notice: str,
    message: str,
    *,
    flag: str,
) -> None:
    global _LABEL_DEGRADED_EMITTED, _HIERARCHY_DEGRADED_EMITTED, _RELATION_DEGRADED_EMITTED, _COMMENT_MUTATION_DEGRADED_EMITTED
    emitted = {
        "label": _LABEL_DEGRADED_EMITTED,
        "hierarchy": _HIERARCHY_DEGRADED_EMITTED,
        "relation": _RELATION_DEGRADED_EMITTED,
        "comment": _COMMENT_MUTATION_DEGRADED_EMITTED,
    }
    if emitted.get(flag):
        return
    if flag == "label":
        _LABEL_DEGRADED_EMITTED = True
    elif flag == "hierarchy":
        _HIERARCHY_DEGRADED_EMITTED = True
    elif flag == "relation":
        _RELATION_DEGRADED_EMITTED = True
    elif flag == "comment":
        _COMMENT_MUTATION_DEGRADED_EMITTED = True
    payload = {"verdict": "notice", "notice": notice, "message": message}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def label_ladder_info(cfg: dict[str, Any], *, surface: str | None = None) -> dict[str, Any]:
    rung = surface or resolve_label_surface_config(cfg) or "multi_select"
    return {
        "ladder": list(NOTION_LABEL_DEGRADATION_LADDER),
        "surface": rung,
        "labelProperty": resolve_label_property(cfg),
        "bodyMarkerAuthoritative": True,
    }


def comment_mutation_capability() -> dict[str, Any]:
    return {
        "capability": "degraded",
        "update": False,
        "delete": False,
        "amendVia": "append-marked-comment",
        "notes": (
            "Notion exposes comment create/read only; update/delete amendments append "
            "a new marked comment and the facade reports comment mutation as degraded."
        ),
    }


def overflow_chunk_policy() -> dict[str, Any]:
    return {
        "provider": "notion",
        "bodySizeLimitBytes": BODY_SIZE_LIMIT,
        "richTextCharLimit": NOTION_RICH_TEXT_CHAR_LIMIT,
        "blockAppendLimit": NOTION_BLOCK_APPEND_LIMIT,
        "chunkMarker": "sw-chunk-overflow",
        "chunkVia": "planning_notion_canonical.chunk_body_for_notion",
        "notes": (
            "Bodies respect 2000-char rich_text and 100-block append caps; overflow uses "
            "<!-- sw-chunk-manifest --> plus <!-- sw-chunk-overflow --> comments."
        ),
    }


NOTION_PROVIDER_DOC_REL = Path("core/providers/issues/notion.md")
NOTION_DOCS_GATE_MARKERS: tuple[str, ...] = (
    "## Configuration keys",
    "## Auth headers",
    "Notion-Version",
    "2022-06-28",
    "## Capability flags",
    "## LCD verb mapping",
    "## Label degradation ladder",
    "issue-lock",
    "commentMutation",
    "## Body overflow",
    "## Rate limit",
    "## Promotion gates",
)
NOTION_PROMOTION_GATE_FIXTURES_REL = Path("scripts/test/fixtures/planning-notion-promotion")
NOTION_PROMOTION_GATES: tuple[str, ...] = ("docs-gate",)


def resolve_notion_provider_doc(root: Path) -> Path:
    candidate = (root / NOTION_PROVIDER_DOC_REL).resolve()
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"missing notion provider doc: {NOTION_PROVIDER_DOC_REL}")


def notion_provider_doc_text(root: Path) -> str:
    return resolve_notion_provider_doc(root).read_text(encoding="utf-8")


def _doc_marker_gate(
    doc: str,
    markers: tuple[str, ...],
    *,
    gate: str,
) -> dict[str, Any]:
    missing = [marker for marker in markers if marker not in doc]
    if missing:
        return {
            "verdict": "fail",
            "gate": gate,
            "error": "missing-doc-markers",
            "missing": missing,
        }
    return {"verdict": "ok", "gate": gate, "markerCount": len(markers)}


def docs_gate(root: Path) -> dict[str, Any]:
    """R12 — adapter spec completeness gate before notion promotion."""
    try:
        doc = notion_provider_doc_text(root)
    except FileNotFoundError:
        return {
            "verdict": "fail",
            "gate": "docs-gate",
            "error": "missing-provider-doc",
            "missing": [str(NOTION_PROVIDER_DOC_REL)],
        }
    return _doc_marker_gate(doc, NOTION_DOCS_GATE_MARKERS, gate="docs-gate")


def notion_promotion_gate_fixture_path(root: Path, gate: str) -> Path:
    return (root / NOTION_PROMOTION_GATE_FIXTURES_REL / f"{gate}.ok.json").resolve()


def load_notion_promotion_gate_fixture(root: Path, gate: str) -> dict[str, Any]:
    path = notion_promotion_gate_fixture_path(root, gate)
    if not path.is_file():
        return {
            "verdict": "fail",
            "gate": gate,
            "error": "missing-promotion-gate-fixture",
            "fixturePath": str(path),
        }
    return json.loads(path.read_text(encoding="utf-8"))


def notion_promotion_gate_evidence(root: Path) -> dict[str, Any]:
    recorded: dict[str, Any] = {}
    live: dict[str, Any] = {}
    for gate in NOTION_PROMOTION_GATES:
        recorded[gate] = load_notion_promotion_gate_fixture(root, gate)
        live[gate] = docs_gate(root)
    failures: list[dict[str, str]] = []
    for gate in NOTION_PROMOTION_GATES:
        if recorded[gate].get("verdict") != "ok":
            failures.append({"gate": gate, "phase": "recorded", "verdict": str(recorded[gate].get("verdict"))})
        if live[gate].get("verdict") != "ok":
            failures.append({"gate": gate, "phase": "live", "verdict": str(live[gate].get("verdict"))})
    return {
        "verdict": "ok" if not failures else "fail",
        "action": "notion-promotion-gate-evidence",
        "gates": list(NOTION_PROMOTION_GATES),
        "fixtureDir": str(NOTION_PROMOTION_GATE_FIXTURES_REL),
        "recorded": recorded,
        "live": live,
        "failures": failures,
    }


def resolve_database_ids(cfg: dict[str, Any]) -> list[str]:
    issues = _issues_section(cfg)
    ids: list[str] = []
    single = issues.get("notionDatabaseId")
    if isinstance(single, str) and single.strip():
        ids.append(single.strip())
    database_map = issues.get("databaseMap")
    if isinstance(database_map, dict):
        for value in database_map.values():
            if isinstance(value, str) and value.strip():
                ids.append(value.strip())
    return sorted(set(ids))


def notion_headers(token: str) -> dict[str, str]:
    value = token.strip()
    auth = value if value.lower().startswith("bearer ") else f"Bearer {value}"
    return {
        "Authorization": auth,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "shipwright-notion-client",
    }


def _redact(text: str, token: str) -> str:
    if not token:
        return text
    return text.replace(token, "[REDACTED]")


def _allowed_hosts() -> set[str]:
    return issues_broker.merge_allowed_hosts(
        issues_broker.hosts_from_urls(NOTION_API_BASE),
        {"api.notion.com"},
    )


def notion_request(
    root: Path,
    cfg: dict[str, Any],
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    credential: Resolution | ResolvedToken | None = None,
) -> tuple[int, dict[str, str], str]:
    from planning_store_facade import resolve_issues_credential

    if token is not None and token.strip():
        auth_token = token.strip()
    else:
        resolved = credential
        if resolved is None:
            resolved = resolve_issues_credential(
                root,
                issues_provider="notion",
                destination_endpoint=NOTION_API_BASE,
                cfg=cfg,
            )
        try:
            auth_token = issues_broker.require_token(resolved)
        except issues_broker.IssuesBrokerError as exc:
            raise NotionClientError(str(exc), code="missing-token") from exc

    extra = issues_broker.strip_auth_headers(notion_headers(auth_token))
    bearer = auth_token[7:].strip() if auth_token.lower().startswith("bearer ") else auth_token
    url = f"{NOTION_API_BASE}{path}"
    try:
        bound = issues_broker.prepare_bound_headers(
            url=url,
            allowed_hosts=_allowed_hosts(),
            bearer_token=bearer,
            extra_headers=extra,
            method=method,
        )
    except issues_broker.IssuesBrokerError as exc:
        raise NotionClientError(str(exc), code=exc.code) from exc

    try:
        status, resp_headers, body = issues_http.http_request(
            method,
            url,
            bound,
            payload,
            root=root,
            issues_provider="notion",
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        raise NotionClientError(_redact(str(exc), auth_token), code="transport-error") from None
    return status, {str(k).lower(): str(v) for k, v in (resp_headers or {}).items()}, body


def _json_response(status: int, body: str, *, token: str = "") -> dict[str, Any]:
    if status >= 400:
        raise NotionClientError(
            _redact(f"Notion HTTP {status}: {body[:300]}", token),
            code="http-error",
        )
    if not body.strip():
        return {}
    data = json.loads(body)
    if not isinstance(data, dict):
        raise NotionClientError("unexpected Notion payload", code="invalid-payload")
    return data


def probe_token(root: Path, cfg: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    """Verify integration token resolves (R4). Missing token → missing-token advisory shape."""
    token_env = resolve_token_env(cfg)
    if token is None and not token_env:
        return {"verdict": "fail", "error": "missing-token-env", "provider": "notion"}
    if token is None:
        from host_lib import token_present

        if not token_present(token_env):
            return {
                "verdict": "fail",
                "error": "missing-token",
                "provider": "notion",
                "tokenEnv": token_env,
                "message": f"Set {token_env} for Notion issue-store access (value never logged).",
            }
    if use_fixture_probe_mode():
        return {
            "verdict": "ok",
            "provider": "notion",
            "fixtureProbe": True,
            "tokenEnv": token_env,
        }
    try:
        status, _, body = notion_request(root, cfg, "GET", "/users/me", token=token)
        data = _json_response(status, body, token=token or "")
        return {
            "verdict": "ok",
            "provider": "notion",
            "userId": str(data.get("id") or ""),
            "tokenEnv": token_env,
        }
    except NotionClientError as exc:
        return {"verdict": "fail", "error": exc.code, "message": str(exc), "provider": "notion"}


def _property_type(schema: dict[str, Any], name: str) -> str:
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    entry = props.get(name)
    if isinstance(entry, dict):
        return str(entry.get("type") or "")
    return ""


def _validate_database_schema(
    schema: dict[str, Any],
    *,
    title_property: str,
    status_property: str,
    project_property: str,
    label_property: str,
    parent_relation_property: str,
    label_custom_field: str | None,
) -> tuple[list[str], str, bool]:
    errors: list[str] = []
    title_type = _property_type(schema, title_property)
    if title_type != "title":
        errors.append(f"title-property-wrong-type:{title_property}:{title_type or 'missing'}")
    status_type = _property_type(schema, status_property)
    if status_type not in {"status", "select"}:
        errors.append(f"status-property-wrong-type:{status_property}:{status_type or 'missing'}")

    label_surface = "multi_select"
    label_type = _property_type(schema, label_property)
    if label_type == "multi_select":
        label_surface = "multi_select"
    elif label_type == "select":
        label_surface = "select"
    elif label_custom_field:
        custom_type = _property_type(schema, label_custom_field)
        if custom_type in {"rich_text", "multi_select", "select"}:
            label_surface = "customField"
        else:
            errors.append(
                f"label-custom-field-wrong-type:{label_custom_field}:{custom_type or 'missing'}"
            )
    else:
        errors.append(
            f"label-property-wrong-type:{label_property}:{label_type or 'missing'}"
        )

    relation_type = _property_type(schema, parent_relation_property)
    relation_capable = relation_type == "relation"
    return errors, label_surface, relation_capable


def probe_database(root: Path, cfg: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    """Fail-closed database scope probe (R4)."""
    token_probe = probe_token(root, cfg, token=token)
    if token_probe.get("verdict") != "ok":
        return token_probe

    database_ids = resolve_database_ids(cfg)
    if not database_ids:
        return {
            "verdict": "fail",
            "error": "missing-database-id",
            "message": "planning.store.issues requires notionDatabaseId or databaseMap",
            "provider": "notion",
        }

    title_property = resolve_title_property(cfg)
    status_property = resolve_status_property(cfg)
    project_property = resolve_project_property(cfg)
    label_property = resolve_label_property(cfg)
    parent_relation_property = resolve_parent_relation_property(cfg)
    label_custom_field = resolve_label_custom_field(cfg)

    if use_fixture_probe_mode():
        label_surface = resolve_label_surface_config(cfg) or "multi_select"
        return {
            "verdict": "ok",
            "provider": "notion",
            "fixtureProbe": True,
            "databases": database_ids,
            "titleProperty": title_property,
            "statusProperty": status_property,
            "projectProperty": project_property,
            "labelProperty": label_property,
            "labelSurface": label_surface,
            "parentRelationProperty": parent_relation_property,
            "labelLadder": list(NOTION_LABEL_DEGRADATION_LADDER),
            "bodyMarkerAuthoritative": True,
            "relationCapable": True,
        }

    failures: list[dict[str, Any]] = []
    checked: list[str] = []
    checked_label_surface = resolve_label_surface_config(cfg) or "multi_select"
    checked_relation_capable = False
    for database_id in database_ids:
        try:
            status, _, body = notion_request(
                root,
                cfg,
                "GET",
                f"/databases/{database_id}",
                token=token,
            )
            if status in {401, 403, 404}:
                failures.append(
                    {
                        "databaseId": database_id,
                        "error": "notion-database-scope-refused",
                        "httpStatus": status,
                    }
                )
                continue
            schema = _json_response(status, body, token=token or "")
            prop_errors, label_surface, relation_capable = _validate_database_schema(
                schema,
                title_property=title_property,
                status_property=status_property,
                project_property=project_property,
                label_property=label_property,
                parent_relation_property=parent_relation_property,
                label_custom_field=label_custom_field,
            )
            if prop_errors:
                failures.append(
                    {
                        "databaseId": database_id,
                        "error": "notion-database-scope-refused",
                        "propertyErrors": prop_errors,
                    }
                )
                continue
            checked.append(database_id)
            checked_label_surface = label_surface
            checked_relation_capable = relation_capable
        except NotionClientError as exc:
            failures.append(
                {"databaseId": database_id, "error": exc.code, "message": str(exc)}
            )

    if failures:
        return {
            "verdict": "fail",
            "error": "notion-database-scope-refused",
            "provider": "notion",
            "failures": failures,
            "checked": checked,
        }
    return {
        "verdict": "ok",
        "provider": "notion",
        "databases": checked,
        "titleProperty": title_property,
        "statusProperty": status_property,
        "projectProperty": project_property,
        "labelProperty": label_property,
        "labelSurface": checked_label_surface,
        "parentRelationProperty": parent_relation_property,
        "labelLadder": list(NOTION_LABEL_DEGRADATION_LADDER),
        "bodyMarkerAuthoritative": True,
        "relationCapable": checked_relation_capable,
    }


def use_fixture_probe_mode() -> bool:
    return os.environ.get("SW_ISSUES_FIXTURE", "").strip() in {"1", "true", "yes"} or (
        os.environ.get("SW_NOTION_PROBE_FIXTURE", "").strip() in {"1", "true", "yes"}
    )


def lock_capability() -> dict[str, Any]:
    return {
        "capability": LOCK_CAPABILITY,
        "native": NATIVE_ISSUE_LOCK,
        "mechanism": "hash-authoritative",
        "frozenLabel": FROZEN_LABEL,
        "notes": (
            "Notion has no native conversation lock. Freeze immutability is "
            "hash-authoritative via sw:frozen + sw-freeze-record (tamper-evidence on read)."
        ),
    }


def prepare_body_with_overflow(
    body: str,
    comments: list[CommentRecord] | None = None,
) -> tuple[str, list[CommentRecord]]:
    return chunk_body_if_needed(body, list(comments or []), provider="notion")


def _strip_block_object(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        cleaned = {k: v for k, v in block.items() if k != "object"}
        block_type = str(cleaned.get("type") or "")
        payload = cleaned.get(block_type)
        if isinstance(payload, dict) and isinstance(payload.get("children"), list):
            payload = dict(payload)
            payload["children"] = _strip_block_object(payload["children"])
            cleaned[block_type] = payload
        out.append(cleaned)
    return out


def _title_property_value(title: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": title}}]}


def _status_property_value(state: str, *, status_property: str) -> dict[str, Any]:
    name = "Done" if state == "closed" else "In progress"
    prop_type = "status"
    return {status_property: {prop_type: {"name": name}}}


def _rich_text_payload(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content}}]


def _parse_comment(raw: dict[str, Any]) -> CommentRecord:
    rich_text = raw.get("rich_text")
    parts: list[str] = []
    if isinstance(rich_text, list):
        for item in rich_text:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), dict):
                parts.append(str(item["text"].get("content") or ""))
    body = "".join(parts)
    markers: list[str] = []
    for marker in (
        "sw-freeze-record",
        "sw-chunk-overflow",
        "sw-memory-pointer",
        "lifecycle:source-removed",
        "sw-comment-amendment",
    ):
        if f"<!-- {marker} -->" in body or f"<!--{marker}-->" in body:
            markers.append(marker)
    return CommentRecord(
        id=str(raw.get("id") or ""),
        body=body,
        created_at=str(raw.get("created_time") or ""),
        markers=markers,
    )


def _label_property_payload(
    labels: list[str],
    *,
    property_name: str,
    surface: str,
    custom_field: str | None,
) -> dict[str, Any]:
    unique = sorted({label for label in labels if label})
    if surface == "multi_select":
        return {property_name: {"multi_select": [{"name": label} for label in unique]}}
    if surface == "select":
        primary = next(iter(unique), "")
        return {property_name: {"select": {"name": primary} if primary else None}}
    field_name = custom_field or property_name
    joined = ", ".join(unique)
    return {field_name: {"rich_text": _rich_text_payload(joined)}}


def _labels_from_property(
    properties: dict[str, Any],
    *,
    property_name: str,
    surface: str,
    custom_field: str | None,
) -> list[str]:
    field_name = custom_field if surface == "customField" and custom_field else property_name
    prop = properties.get(field_name)
    if not isinstance(prop, dict):
        return []
    if surface == "multi_select":
        options = prop.get("multi_select")
        if isinstance(options, list):
            return sorted(
                {
                    str(item.get("name") or "")
                    for item in options
                    if isinstance(item, dict) and item.get("name")
                }
            )
        return []
    if surface == "select":
        select = prop.get("select")
        if isinstance(select, dict) and select.get("name"):
            return [str(select.get("name") or "")]
        return []
    rich_text = prop.get("rich_text")
    if isinstance(rich_text, list):
        joined = "".join(
            str(item.get("text", {}).get("content") or "")
            for item in rich_text
            if isinstance(item, dict) and isinstance(item.get("text"), dict)
        )
        return [part.strip() for part in joined.split(",") if part.strip()]
    return []


def _project_property_value(labels: list[str], *, project_property: str) -> dict[str, Any]:
    return {
        project_property: {
            "multi_select": [{"name": label} for label in sorted(set(labels)) if label],
        }
    }


def _labels_from_properties(properties: dict[str, Any], project_property: str) -> list[str]:
    prop = properties.get(project_property)
    if not isinstance(prop, dict):
        return []
    options = prop.get("multi_select")
    if not isinstance(options, list):
        return []
    return sorted(
        {str(item.get("name") or "") for item in options if isinstance(item, dict) and item.get("name")}
    )


def _title_from_properties(properties: dict[str, Any], title_property: str) -> str:
    prop = properties.get(title_property)
    if not isinstance(prop, dict):
        return ""
    title_items = prop.get("title")
    if not isinstance(title_items, list):
        return ""
    parts: list[str] = []
    for item in title_items:
        if isinstance(item, dict):
            text = item.get("text") if isinstance(item.get("text"), dict) else {}
            parts.append(str(text.get("content") or ""))
    return "".join(parts)


def _state_from_properties(properties: dict[str, Any], status_property: str) -> str:
    prop = properties.get(status_property)
    if not isinstance(prop, dict):
        return "open"
    status = prop.get("status")
    if isinstance(status, dict):
        name = str(status.get("name") or "").lower()
        if name in {"done", "closed", "complete", "completed"}:
            return "closed"
    select = prop.get("select")
    if isinstance(select, dict):
        name = str(select.get("name") or "").lower()
        if name in {"done", "closed", "complete", "completed"}:
            return "closed"
    return "open"


def _record_from_page(
    page: dict[str, Any],
    *,
    body: str,
    project_key: str = "",
    comments: list[CommentRecord] | None = None,
    label_property: str = DEFAULT_PROJECT_PROPERTY,
    label_surface: str = "multi_select",
    label_custom_field: str | None = None,
) -> Any:
    from issues_lib import IssueRecord

    properties = page.get("properties") if isinstance(page.get("properties"), dict) else {}
    title_property = DEFAULT_TITLE_PROPERTY
    status_property = DEFAULT_STATUS_PROPERTY
    labels = _labels_from_property(
        properties,
        property_name=label_property,
        surface=label_surface,
        custom_field=label_custom_field,
    )
    title = _title_from_properties(properties, title_property)
    state = _state_from_properties(properties, status_property)
    updated = str(page.get("last_edited_time") or "")
    page_id = str(page.get("id") or "")
    artifact_type = (
        artifact_type_from_labels(labels) or parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
    )
    unit_id = unit_id_from_labels(labels) or parse_body_marker(body, MARKER_UNIT_ID) or ""
    locked = FROZEN_LABEL in labels
    record = IssueRecord(
        id=page_id,
        number=0,
        title=title,
        body=body,
        state=state,
        labels=labels,
        comments=list(comments or []),
        locked=locked,
        updated_at=updated,
        project_key=project_key or parse_body_marker(body, MARKER_PROJECT_KEY) or "",
        artifact_type=artifact_type,
        unit_id=unit_id,
    )
    record.etag = compute_etag(updated, body, title, labels)
    return record


class NotionIssuesClient:
    """Duck-typed LCD issues adapter matching FixtureIssuesStore verbs (R10)."""

    LOCK_CAPABILITY = LOCK_CAPABILITY
    NATIVE_ISSUE_LOCK = NATIVE_ISSUE_LOCK

    def __init__(
        self,
        root: Path,
        *,
        cfg: dict[str, Any] | None = None,
        fixture_store: Any | None = None,
        token: str | None = None,
        credential: Resolution | ResolvedToken | None = None,
    ) -> None:
        from issues_lib import get_fixture_store, use_fixture_mode
        from planning_store_facade import resolve_issues_credential

        self.root = Path(root)
        self.cfg = cfg if cfg is not None else load_workflow_config(self.root)
        store = self.cfg.get("planning", {}).get("store", {})
        store = store if isinstance(store, dict) else {}
        raw_key = store.get("projectKey")
        self.project_key = raw_key.strip() if isinstance(raw_key, str) else ""
        self.title_property = resolve_title_property(self.cfg)
        self.status_property = resolve_status_property(self.cfg)
        self.project_property = resolve_project_property(self.cfg)
        self.label_property = resolve_label_property(self.cfg)
        self.parent_relation_property = resolve_parent_relation_property(self.cfg)
        self.label_custom_field = resolve_label_custom_field(self.cfg)
        configured_surface = resolve_label_surface_config(self.cfg)
        self.label_surface = configured_surface or "multi_select"
        self.relation_capable = True
        self._token = token
        self._credential = credential
        self._default_database_id = resolve_database_ids(self.cfg)[0] if resolve_database_ids(self.cfg) else ""

        if fixture_store is not None:
            self._fixture = fixture_store
        elif use_fixture_mode():
            self._fixture = get_fixture_store(self.root)
        else:
            self._fixture = None

        if self._fixture is None:
            if token is not None and token.strip():
                self._token = token.strip()
            else:
                resolved = (
                    credential
                    if credential is not None
                    else resolve_issues_credential(
                        self.root,
                        issues_provider="notion",
                        destination_endpoint=NOTION_API_BASE,
                        cfg=self.cfg,
                    )
                )
                self._credential = resolved
                try:
                    self._token = issues_broker.require_token(resolved)
                except issues_broker.IssuesBrokerError as exc:
                    raise NotionClientError(str(exc), code="missing-token") from exc

    def lock_capability(self) -> dict[str, Any]:
        return lock_capability()

    def comment_mutation_capability(self) -> dict[str, Any]:
        return comment_mutation_capability()

    def label_ladder_info(self) -> dict[str, Any]:
        return label_ladder_info(self.cfg, surface=self.label_surface)

    def hierarchy_capable(self) -> bool:
        return self.relation_capable

    def _resolve_label_surface(self) -> str:
        if self._fixture is not None:
            return self.label_surface
        if use_fixture_probe_mode():
            return self.label_surface
        probe = probe_database(self.root, self.cfg, token=self._token)
        if probe.get("verdict") == "ok":
            surface = probe.get("labelSurface")
            if isinstance(surface, str) and surface in NOTION_LABEL_DEGRADATION_LADDER:
                if surface != "multi_select" and self.label_surface == "multi_select":
                    _emit_operator_notice(
                        "notion-label-surface-degraded",
                        f"Notion label surface degraded to {surface!r}; body marker remains authoritative",
                        flag="label",
                    )
                self.label_surface = surface
            relation_capable = probe.get("relationCapable")
            if isinstance(relation_capable, bool):
                self.relation_capable = relation_capable
        return self.label_surface

    def _label_patch(self, labels: list[str]) -> dict[str, Any]:
        surface = self._resolve_label_surface()
        if surface == "multi_select":
            return _label_property_payload(
                labels,
                property_name=self.label_property,
                surface=surface,
                custom_field=self.label_custom_field,
            )
        if surface == "select":
            if self.label_surface != "select":
                _emit_operator_notice(
                    "notion-label-surface-degraded",
                    "Notion label surface degraded to select; body marker remains authoritative",
                    flag="label",
                )
            return _label_property_payload(
                labels,
                property_name=self.label_property,
                surface="select",
                custom_field=self.label_custom_field,
            )
        if self.label_custom_field:
            if self.label_surface != "customField":
                _emit_operator_notice(
                    "notion-label-surface-degraded",
                    "Notion label surface degraded to labelCustomField; body marker remains authoritative",
                    flag="label",
                )
            return _label_property_payload(
                labels,
                property_name=self.label_property,
                surface="customField",
                custom_field=self.label_custom_field,
            )
        raise NotionClientError(
            "all Notion label ladder rungs denied",
            code="notion-label-ladder-exhausted",
        )

    def _append_block_children(self, block_id: str, blocks: list[dict[str, Any]]) -> None:
        for batch in paginate_blocks(blocks):
            status, _, resp = notion_request(
                self.root,
                self.cfg,
                "PATCH",
                f"/blocks/{block_id}/children",
                payload={"children": batch},
                token=self._token,
                credential=self._credential,
            )
            _json_response(status, resp, token=self._token or "")

    def _list_comments(self, block_id: str) -> list[CommentRecord]:
        comments: list[CommentRecord] = []
        cursor = ""
        while True:
            path = f"/comments?block_id={block_id}&page_size={SEARCH_PAGE_SIZE}"
            if cursor:
                path += f"&start_cursor={cursor}"
            status, _, body = notion_request(
                self.root,
                self.cfg,
                "GET",
                path,
                token=self._token,
                credential=self._credential,
            )
            data = _json_response(status, body, token=self._token or "")
            results = data.get("results")
            if isinstance(results, list):
                comments.extend(
                    [_parse_comment(item) for item in results if isinstance(item, dict)]
                )
            if not data.get("has_more"):
                break
            cursor = str(data.get("next_cursor") or "")
            if not cursor:
                break
        comments.sort(key=lambda c: (c.created_at, c.id))
        return comments

    def _post_overflow_comments(
        self,
        issue_id: str,
        extra: list[CommentRecord],
        *,
        base_count: int,
    ) -> list[str]:
        posted: list[str] = []
        for comment in extra[base_count:]:
            created = self.add_comment(issue_id, comment.body, markers=list(comment.markers))
            posted.append(created.id)
        return posted

    def _record_from_current(
        self,
        page: dict[str, Any],
        *,
        body_md: str,
        comments: list[CommentRecord],
    ) -> Any:
        return _record_from_page(
            page,
            body=body_md,
            project_key=self.project_key,
            comments=comments,
            label_property=self.label_property,
            label_surface=self.label_surface,
            label_custom_field=self.label_custom_field,
        )

    def _fetch_block_children(self, block_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor = ""
        while True:
            path = f"/blocks/{block_id}/children?page_size={SEARCH_PAGE_SIZE}"
            if cursor:
                path += f"&start_cursor={cursor}"
            status, _, body = notion_request(
                self.root,
                self.cfg,
                "GET",
                path,
                token=self._token,
                credential=self._credential,
            )
            data = _json_response(status, body, token=self._token or "")
            results = data.get("results")
            if isinstance(results, list):
                blocks.extend([b for b in results if isinstance(b, dict)])
            if not data.get("has_more"):
                break
            cursor = str(data.get("next_cursor") or "")
            if not cursor:
                break
        return blocks

    def _page_body(self, page_id: str) -> str:
        blocks = self._fetch_block_children(page_id)
        return blocks_to_markdown(blocks)

    def create(
        self,
        *,
        title: str,
        body: str,
        labels: list[str],
        project_key: str,
        artifact_type: str,
        unit_id: str,
        native_links: list[dict[str, Any]] | None = None,
    ) -> Any:
        if self._fixture is not None:
            return self._fixture.create(
                title=title,
                body=body,
                labels=labels,
                project_key=project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
                native_links=native_links,
            )
        del artifact_type, unit_id, native_links
        if not self._default_database_id:
            raise NotionDatabaseConfigError(
                "notionDatabaseId or databaseMap required",
                code="missing-database-id",
            )
        head, extra = prepare_body_with_overflow(body, [])
        merged = sorted(set(labels) | {project_label(project_key)})
        first_batch_blocks = _strip_block_object(markdown_to_blocks(head))
        initial_children = first_batch_blocks[:NOTION_BLOCK_APPEND_LIMIT]
        properties: dict[str, Any] = {
            self.title_property: _title_property_value(title),
            **_status_property_value("open", status_property=self.status_property),
            **self._label_patch(merged),
        }
        payload = {
            "parent": {"database_id": self._default_database_id},
            "properties": properties,
            "children": initial_children,
        }
        status, _, resp = notion_request(
            self.root,
            self.cfg,
            "POST",
            "/pages",
            payload=payload,
            token=self._token,
            credential=self._credential,
        )
        page = _json_response(status, resp, token=self._token or "")
        page_id = str(page.get("id") or "")
        remaining_blocks = first_batch_blocks[NOTION_BLOCK_APPEND_LIMIT:]
        if remaining_blocks:
            self._append_block_children(page_id, remaining_blocks)
        posted = self._post_overflow_comments(page_id, extra, base_count=0)
        if posted:
            head = rewrite_chunk_manifest_ids(head, posted)
            manifest_blocks = _strip_block_object(markdown_to_blocks(head))
            if manifest_blocks:
                self._append_block_children(page_id, manifest_blocks[:1])
        return self.get(page_id)

    def get(self, issue_id: str) -> Any:
        if self._fixture is not None:
            return self._fixture.get(issue_id)
        status, _, body = notion_request(
            self.root,
            self.cfg,
            "GET",
            f"/pages/{issue_id}",
            token=self._token,
            credential=self._credential,
        )
        page = _json_response(status, body, token=self._token or "")
        body_blocks = self._fetch_block_children(issue_id)
        body_md = blocks_to_markdown(body_blocks)
        comments = self._list_comments(issue_id)
        full_body = reassemble_body(body_md, comments)
        return self._record_from_current(page, body_md=full_body, comments=comments)

    def update(
        self,
        issue_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
        native_links: list[dict[str, Any]] | None = None,
        if_match: str | None = None,
        allow_locked: bool = False,
    ) -> Any:
        from issues_lib import IssueRevisionConflict

        if self._fixture is not None:
            return self._fixture.update(
                issue_id,
                title=title,
                body=body,
                state=state,
                labels=labels,
                native_links=native_links,
                if_match=if_match,
                allow_locked=allow_locked,
            )
        del native_links
        current = self.get(issue_id)
        if if_match and current.etag != if_match:
            raise IssueRevisionConflict(
                "etag-conflict",
                expected=if_match,
                actual=current.etag,
            )
        if current.locked and not allow_locked:
            raise IssueRevisionConflict("issue-locked")
        patch_props: dict[str, Any] = {}
        if title is not None:
            patch_props[self.title_property] = _title_property_value(title)
        if labels is not None:
            patch_props.update(self._label_patch(labels))
        if state is not None:
            patch_props.update(
                _status_property_value(state, status_property=self.status_property)
            )
        if patch_props:
            status, _, resp = notion_request(
                self.root,
                self.cfg,
                "PATCH",
                f"/pages/{issue_id}",
                payload={"properties": patch_props},
                token=self._token,
                credential=self._credential,
            )
            _json_response(status, resp, token=self._token or "")
        if body is not None:
            head, extra = prepare_body_with_overflow(body, list(current.comments))
            blocks = _strip_block_object(markdown_to_blocks(head))
            first_batch = blocks[:NOTION_BLOCK_APPEND_LIMIT]
            if first_batch:
                self._append_block_children(issue_id, first_batch)
            if len(blocks) > NOTION_BLOCK_APPEND_LIMIT:
                self._append_block_children(issue_id, blocks[NOTION_BLOCK_APPEND_LIMIT:])
            posted = self._post_overflow_comments(issue_id, extra, base_count=len(current.comments))
            if posted:
                head = rewrite_chunk_manifest_ids(head, posted)
                manifest_blocks = _strip_block_object(markdown_to_blocks(head))
                if manifest_blocks:
                    self._append_block_children(issue_id, manifest_blocks[:1])
        return self.get(issue_id)

    def add_comment(
        self, issue_id: str, body: str, *, markers: list[str] | None = None
    ) -> CommentRecord:
        if self._fixture is not None:
            return self._fixture.add_comment(issue_id, body, markers=markers)
        marker_prefix = ""
        if markers:
            marker_prefix = "".join(f"<!-- {marker} -->\n" for marker in markers)
        full_body = f"{marker_prefix}{body}" if marker_prefix else body
        chunks = split_rich_text_chunks(full_body)
        created: CommentRecord | None = None
        for chunk in chunks:
            payload = {
                "parent": {"page_id": issue_id},
                "rich_text": _rich_text_payload(chunk),
            }
            status, _, resp = notion_request(
                self.root,
                self.cfg,
                "POST",
                "/comments",
                payload=payload,
                token=self._token,
                credential=self._credential,
            )
            data = _json_response(status, resp, token=self._token or "")
            created = CommentRecord(
                id=str(data.get("id") or ""),
                body=full_body,
                created_at=str(data.get("created_time") or ""),
                markers=list(markers or []),
            )
        if created is None:
            raise NotionClientError("comment create returned no payload", code="comment-failed")
        return created

    def amend_comment(
        self,
        issue_id: str,
        comment_id: str,
        body: str,
        *,
        markers: list[str] | None = None,
    ) -> CommentRecord:
        """Append amendment comment — Notion has no comment update (R11)."""
        del comment_id
        amendment_markers = list(markers or []) + ["sw-comment-amendment"]
        _emit_operator_notice(
            "notion-comment-mutation-degraded",
            "Notion comment update unavailable; amendment appended as new marked comment",
            flag="comment",
        )
        return self.add_comment(issue_id, body, markers=amendment_markers)

    def delete_comment(self, issue_id: str, comment_id: str) -> None:
        """Notion has no comment delete — append tombstone amendment (R11)."""
        del comment_id
        _emit_operator_notice(
            "notion-comment-mutation-degraded",
            "Notion comment delete unavailable; tombstone appended as new marked comment",
            flag="comment",
        )
        self.add_comment(
            issue_id,
            "<!-- sw-comment-amendment -->\n(comment delete requested; native delete unavailable)",
            markers=["sw-comment-amendment"],
        )

    def set_labels(
        self, issue_id: str, labels: list[str], *, if_match: str | None = None
    ) -> Any:
        return self.update(issue_id, labels=labels, if_match=if_match, allow_locked=True)

    def lock(self, issue_id: str, *, if_match: str | None = None) -> Any:
        from issues_lib import IssueRevisionConflict

        if self._fixture is not None:
            record = self._fixture.get(issue_id)
            if if_match and record.etag != if_match:
                raise IssueRevisionConflict(
                    "etag-conflict",
                    expected=if_match,
                    actual=record.etag,
                )
            if FROZEN_LABEL not in record.labels:
                record = self._fixture.update(
                    issue_id,
                    labels=sorted(set(record.labels) | {FROZEN_LABEL}),
                    if_match=record.etag,
                    allow_locked=True,
                )
            freeze_hash = canonical_hash(
                snapshot_from_fixture_record(record)
            )
            self._fixture.add_comment(
                issue_id,
                build_freeze_record_body(freeze_hash),
                markers=["sw-freeze-record"],
            )
            return self._fixture.lock(issue_id, if_match=record.etag)

        record = self.get(issue_id)
        if if_match and record.etag != if_match:
            raise IssueRevisionConflict(
                "etag-conflict",
                expected=if_match,
                actual=record.etag,
            )
        if FROZEN_LABEL not in record.labels:
            record = self.update(
                issue_id,
                labels=sorted(set(record.labels) | {FROZEN_LABEL}),
                if_match=record.etag,
                allow_locked=True,
            )
        freeze_hash = canonical_hash(snapshot_from_fixture_record(record))
        self.add_comment(
            issue_id,
            build_freeze_record_body(freeze_hash),
            markers=["sw-freeze-record"],
        )
        record.locked = True
        return record

    def search(
        self,
        *,
        project_key: str,
        artifact_type: str | None = None,
        unit_id: str | None = None,
        labels: list[str] | None = None,
    ) -> list[Any]:
        if self._fixture is not None:
            return self._fixture.search(
                project_key=project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
                labels=labels,
            )
        if not self._default_database_id:
            return []
        wanted = [project_label(project_key)]
        if artifact_type:
            wanted.append(type_label(artifact_type))
        if labels:
            wanted.extend(labels)
        filter_obj: dict[str, Any] = {
            "property": self.project_property,
            "multi_select": {"contains": project_label(project_key)},
        }
        results: list[Any] = []
        cursor = ""
        while True:
            payload: dict[str, Any] = {
                "page_size": SEARCH_PAGE_SIZE,
                "filter": filter_obj,
            }
            if cursor:
                payload["start_cursor"] = cursor
            status, _, body = notion_request(
                self.root,
                self.cfg,
                "POST",
                f"/databases/{self._default_database_id}/query",
                payload=payload,
                token=self._token,
                credential=self._credential,
            )
            data = _json_response(status, body, token=self._token or "")
            pages = data.get("results")
            if isinstance(pages, list):
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    page_id = str(page.get("id") or "")
                    if not page_id:
                        continue
                    record = self.get(page_id)
                    if SOURCE_REMOVED_LABEL in record.labels:
                        continue
                    if unit_id and record.unit_id != unit_id:
                        continue
                    if artifact_type and record.artifact_type != artifact_type:
                        continue
                    if labels and not all(label in record.labels for label in labels):
                        continue
                    results.append(record)
            if not data.get("has_more"):
                break
            cursor = str(data.get("next_cursor") or "")
            if not cursor:
                break
        results.sort(key=lambda r: r.number)
        return results

    def epic_create(
        self,
        *,
        title: str,
        body: str,
        labels: list[str],
        project_key: str,
        artifact_type: str,
        unit_id: str,
    ) -> Any:
        return self.create(
            title=title,
            body=body,
            labels=labels,
            project_key=project_key,
            artifact_type=artifact_type,
            unit_id=unit_id,
        )

    def sub_issue_create(
        self,
        *,
        title: str,
        body: str,
        labels: list[str],
        project_key: str,
        artifact_type: str,
        unit_id: str,
        parent_issue_id: str | None = None,
    ) -> Any:
        child = self.create(
            title=title,
            body=body,
            labels=labels,
            project_key=project_key,
            artifact_type=artifact_type,
            unit_id=unit_id,
        )
        if parent_issue_id:
            return self.sub_issue_link(parent_issue_id, child.id)
        return child

    def sub_issue_link(self, parent_issue_id: str, child_issue_id: str) -> Any:
        if not self.relation_capable:
            if self._fixture is not None:
                return self._checkbox_fallback_on_epic(parent_issue_id, child_issue_id)
            _emit_operator_notice(
                "notion-hierarchy-relation-degraded",
                "Notion parent relation unavailable; degrading to checkbox/body-encoded phases",
                flag="relation",
            )
            return self._checkbox_fallback_on_epic(parent_issue_id, child_issue_id)
        if self._fixture is not None:
            link = {"type": "sub-issue-of", "target": parent_issue_id}
            record = self._fixture.get(child_issue_id)
            links = list(record.native_links)
            if link not in links:
                links.append(link)
            return self._fixture.update(child_issue_id, native_links=links, allow_locked=True)
        patch_props = {
            self.parent_relation_property: {
                "relation": [{"id": parent_issue_id}],
            }
        }
        try:
            status, _, resp = notion_request(
                self.root,
                self.cfg,
                "PATCH",
                f"/pages/{child_issue_id}",
                payload={"properties": patch_props},
                token=self._token,
                credential=self._credential,
            )
            _json_response(status, resp, token=self._token or "")
        except NotionClientError:
            self.relation_capable = False
            _emit_operator_notice(
                "notion-hierarchy-relation-degraded",
                "Notion parent relation write denied; degrading to checkbox/body-encoded phases",
                flag="relation",
            )
            return self._checkbox_fallback_on_epic(parent_issue_id, child_issue_id)
        return self.get(child_issue_id)

    def _checkbox_fallback_on_epic(self, parent_issue_id: str, child_issue_id: str) -> Any:
        parent = self.get(parent_issue_id)
        child = self.get(child_issue_id)
        checkbox_line = f"- [ ] Phase child: {child.unit_id or child_issue_id}"
        block = f"\n{checkbox_line}\n"
        if checkbox_line not in parent.body:
            new_body = f"{parent.body.rstrip()}\n{checkbox_line}\n"
            return self.update(parent_issue_id, body=new_body, if_match=parent.etag, allow_locked=True)
        return child

    def hierarchy_capability(self) -> dict[str, Any]:
        if self.relation_capable:
            return {
                "verdict": "ok",
                "mode": "epic-sub-issue",
                "provider": "notion",
                "notice": None,
            }
        _emit_operator_notice(
            "notion-hierarchy-degraded",
            "hierarchy verbs absent for notion; degrading to checkbox/body-encoded phase list",
            flag="hierarchy",
        )
        return {
            "verdict": "ok",
            "mode": "checkbox",
            "provider": "notion",
            "notice": (
                "hierarchy verbs absent for notion; degrading to checkbox/body-encoded phase list "
                "— deliver continues"
            ),
        }

    def mark_tombstone(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_tombstone(issue_id)
            return
        record = self.get(issue_id)
        labels = sorted(set(record.labels) | {SOURCE_REMOVED_LABEL})
        self.update(
            issue_id,
            labels=labels,
            state="closed",
            if_match=record.etag,
            allow_locked=True,
        )
        self.add_comment(
            issue_id,
            "<!-- lifecycle:source-removed -->\nIssue content migrated to in-repo files.",
            markers=["lifecycle:source-removed"],
        )

    def mark_transferred(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_transferred(issue_id)
            return
        raise NotionClientError(
            "mark_transferred requires fixture harness on Notion live path",
            code="lifecycle-fixture-only",
        )

    def mark_archived_project(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_archived_project(issue_id)
            return
        raise NotionClientError(
            "mark_archived_project requires fixture harness on Notion live path",
            code="lifecycle-fixture-only",
        )

    def mark_type_converted(self, issue_id: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_type_converted(issue_id)
            return
        raise NotionClientError(
            "mark_type_converted requires fixture harness on Notion live path",
            code="lifecycle-fixture-only",
        )

    def mark_key_changed(self, issue_id: str, new_key: str) -> None:
        if self._fixture is not None:
            self._fixture.mark_key_changed(issue_id, new_key)
            return
        raise NotionClientError(
            "mark_key_changed requires fixture harness on Notion live path",
            code="lifecycle-fixture-only",
        )


def snapshot_from_fixture_record(record: Any) -> Any:
    from planning_canonical import IssueSnapshot

    return IssueSnapshot(
        title=record.title,
        body=record.body,
        state=record.state,
        labels=list(record.labels),
        comments=list(record.comments),
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "usage: planning_notion_client.py <root> <probe-token|probe-database|lock-capability|comment-mutation-capability|overflow-policy|label-ladder|docs-gate|promotion-gate-evidence>",
                }
            )
        )
        raise SystemExit(2)
    root = Path(args[0]).resolve()
    cfg = load_workflow_config(root)
    cmd = args[1]
    if cmd == "probe-token":
        print(json.dumps(probe_token(root, cfg), indent=2))
    elif cmd == "probe-database":
        print(json.dumps(probe_database(root, cfg), indent=2))
    elif cmd == "lock-capability":
        print(json.dumps(lock_capability(), indent=2))
    elif cmd == "comment-mutation-capability":
        print(json.dumps(comment_mutation_capability(), indent=2))
    elif cmd == "overflow-policy":
        print(json.dumps(overflow_chunk_policy(), indent=2))
    elif cmd == "label-ladder":
        print(json.dumps(label_ladder_info(cfg), indent=2))
    elif cmd == "docs-gate":
        print(json.dumps(docs_gate(root), indent=2))
    elif cmd == "promotion-gate-evidence":
        print(json.dumps(notion_promotion_gate_evidence(root), indent=2))
    else:
        print(json.dumps({"verdict": "fail", "error": f"unknown command: {cmd}"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
