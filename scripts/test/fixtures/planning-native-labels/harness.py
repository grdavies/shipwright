#!/usr/bin/env python3
"""Provider-native labels + human-readable titles fixture (PRD 057 R11).

Proves, fully offline and deterministically (fixture issues store, no
network):

1. **Zero: minimal frontmatter promotes only the required labels** — a doc
   with just `type`/`unit-id` produces exactly the type + unit-id labels,
   nothing extra.
2. **Many: full frontmatter promotes every structural key** — `status`,
   `topic`, `visibility`, and multi-value `depends`/`absorbs`/`amends`
   edges all get a provider-native label projection, percent-encoded the
   same way `sw:source:*`/`sw:gap-schedule:*` already are.
3. **Boundaries: edge-label cardinality is capped, human titles are
   bracket-free and length-bounded** — `edge_labels_for` never emits more
   than `MAX_EDGE_LABELS_PER_RELATION` labels for one relation, and
   `human_readable_title` prefers frontmatter `title:`, then the doc's
   first H1, then a bracket-free `type: unit-id` fallback (never the
   legacy `[project] type:unit-id` prefix).
4. **Interfaces: label-first / body-fallback dual read on both provider
   clients** — `planning_github_client._record_from_issue` and
   `planning_jira_client._record_from_issue` prefer a provider-native
   label over a (deliberately conflicting) body marker when the label is
   present, and fall back to the body marker for a label-less (pre-R11)
   payload.
5. **The standard write path produces native labels + a human title** —
   `IssueStoreBackend.put`/`get` round-trip content byte-exact while the
   underlying fixture-store issue carries a bracket-free human title and
   the full structural label set.
6. **Exceptions: read-time backfill promotes a legacy issue** — an issue
   created directly against the fixture store with pre-R11 labels (no
   `sw:unit:*`) gets that label backfilled the first time it is resolved
   through `IssueStoreBackend.get`, without disturbing its content.

No network, no live GitHub/Jira required (`SW_ISSUES_FIXTURE=1`).

ZOMBIES: Zero (minimal frontmatter) · Many (full frontmatter, multi-value
edges) · Boundaries (edge-label cap, title precedence/length) · Interfaces
(GitHub + Jira label-first/body-fallback) · Exceptions (legacy backfill).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

os.environ.setdefault("SW_ISSUES_FIXTURE", "1")

from planning_canonical import (  # noqa: E402
    MAX_EDGE_LABELS_PER_RELATION,
    compose_issue_body,
    edge_labels_for,
    human_readable_title,
    project_label,
    status_label,
    structural_labels_from_content,
    topic_label,
    type_label,
    unit_id_label,
    visibility_label,
)


def check_zero_minimal_frontmatter_labels() -> dict:
    content = "---\ntype: prd\nunit-id: 001-minimal\n---\n\nBody only, no H1.\n"
    labels = structural_labels_from_content(content)
    expected = {type_label("prd"), unit_id_label("001-minimal")}
    ok = set(labels) == expected
    return {
        "name": "zero-minimal-frontmatter-labels",
        "ok": ok,
        "detail": f"labels={labels} expected={sorted(expected)}",
    }


def check_many_full_frontmatter_labels() -> dict:
    # `planning_index_gen.parse_frontmatter` is a line-based parser (not a
    # real YAML parser): multi-value keys use the inline flow-list syntax
    # `key: [a, b]`, not a YAML block list.
    content = (
        "---\n"
        "type: prd\n"
        "unit-id: 002-full\n"
        "status: proposed\n"
        "topic: planning store hardening\n"
        "visibility: public\n"
        "depends: [001-a, 001-b]\n"
        "absorbs: 000-legacy\n"
        "amends: 000-prior\n"
        "---\n\n# Full Frontmatter Unit\n\nBody.\n"
    )
    labels = set(structural_labels_from_content(content))
    expected = {
        type_label("prd"),
        unit_id_label("002-full"),
        status_label("proposed"),
        topic_label("planning store hardening"),
        visibility_label("public"),
        *edge_labels_for("depends", ["001-a", "001-b"]),
        *edge_labels_for("absorbs", ["000-legacy"]),
        *edge_labels_for("amends", ["000-prior"]),
    }
    # Percent-encoding is exercised by the topic (contains spaces), same
    # convention as `gap_schedule_label`/`source_tag_label`.
    encoded_topic = "sw:topic:planning%20store%20hardening"
    ok = labels == expected and encoded_topic in labels
    return {
        "name": "many-full-frontmatter-labels",
        "ok": ok,
        "detail": f"labels={sorted(labels)}",
    }


def check_boundary_edge_cap_and_title_precedence() -> dict:
    many_targets = [f"unit-{i}" for i in range(30)]
    capped = edge_labels_for("depends", many_targets)
    cap_ok = len(capped) == MAX_EDGE_LABELS_PER_RELATION

    frontmatter_title = human_readable_title(
        "---\ntype: prd\nunit-id: x\ntitle: Explicit Title\n---\n\n# Heading Ignored\n\nBody.\n",
        "prd",
        "x",
    )
    heading_title = human_readable_title(
        "---\ntype: prd\nunit-id: x\n---\n\n# Doc Heading\n\nBody.\n", "prd", "x"
    )
    fallback_title = human_readable_title("---\ntype: prd\nunit-id: x\n---\n\nNo heading.\n", "prd", "x")
    long_title = human_readable_title(f"# {'A' * 400}", "prd", "x")

    ok = (
        cap_ok
        and frontmatter_title == "Explicit Title"
        and heading_title == "Doc Heading"
        and fallback_title == "prd: x"
        and not fallback_title.startswith("[")
        and len(long_title) == 250
    )
    return {
        "name": "boundary-edge-cap-and-title-precedence",
        "ok": ok,
        "detail": (
            f"capped={len(capped)} frontmatterTitle={frontmatter_title!r} "
            f"headingTitle={heading_title!r} fallbackTitle={fallback_title!r} longTitleLen={len(long_title)}"
        ),
    }


def check_github_client_label_first_with_body_fallback() -> dict:
    import planning_github_client as ghc

    body_conflict = compose_issue_body("proj", "gap", "body-unit-id", "# Doc\n\nBody text.")
    payload_label_wins = {
        "number": 1,
        "title": "A human title",
        "body": body_conflict,
        "state": "open",
        "updated_at": "2026-01-01T00:00:00Z",
        "labels": [
            {"name": project_label("proj")},
            {"name": type_label("prd")},
            {"name": unit_id_label("label-unit-id")},
        ],
    }
    record_label = ghc._record_from_issue(payload_label_wins, project_key="proj")
    label_wins = record_label.unit_id == "label-unit-id" and record_label.artifact_type == "prd"

    body_legacy = compose_issue_body("proj", "gap", "legacy-unit-id", "# Legacy\n\nBody text.")
    payload_legacy = {
        "number": 2,
        "title": "[proj] gap:legacy-unit-id",
        "body": body_legacy,
        "state": "open",
        "updated_at": "2026-01-01T00:00:00Z",
        "labels": [{"name": project_label("proj")}],
    }
    record_legacy = ghc._record_from_issue(payload_legacy, project_key="proj")
    body_fallback = record_legacy.unit_id == "legacy-unit-id" and record_legacy.artifact_type == "gap"

    ok = label_wins and body_fallback
    return {
        "name": "github-client-label-first-with-body-fallback",
        "ok": ok,
        "detail": (
            f"labelWins(unit={record_label.unit_id},type={record_label.artifact_type}) "
            f"bodyFallback(unit={record_legacy.unit_id},type={record_legacy.artifact_type})"
        ),
    }


def check_jira_client_label_first_with_body_fallback() -> dict:
    import planning_jira_client as jc

    def _fields(summary: str, body: str, labels: list[str]) -> dict:
        return {
            "summary": summary,
            "description": body,
            "labels": labels,
            "status": {"statusCategory": {"key": "new"}},
            "updated": "2026-01-01T00:00:00.000+0000",
        }

    body_conflict = compose_issue_body("proj", "gap", "body-unit-id", "# Doc\n\nBody text.")
    payload_label_wins = {
        "key": "PROJ-1",
        "fields": _fields(
            "A human title",
            body_conflict,
            [type_label("prd"), unit_id_label("label-unit-id")],
        ),
    }
    record_label = jc._record_from_issue(payload_label_wins, flavor="dc")
    label_wins = record_label.unit_id == "label-unit-id" and record_label.artifact_type == "prd"

    body_legacy = compose_issue_body("proj", "gap", "legacy-unit-id", "# Legacy\n\nBody text.")
    payload_legacy = {
        "key": "PROJ-2",
        "fields": _fields("[proj] gap:legacy-unit-id", body_legacy, []),
    }
    record_legacy = jc._record_from_issue(payload_legacy, flavor="dc")
    body_fallback = record_legacy.unit_id == "legacy-unit-id" and record_legacy.artifact_type == "gap"

    ok = label_wins and body_fallback
    return {
        "name": "jira-client-label-first-with-body-fallback",
        "ok": ok,
        "detail": (
            f"labelWins(unit={record_label.unit_id},type={record_label.artifact_type}) "
            f"bodyFallback(unit={record_legacy.unit_id},type={record_legacy.artifact_type})"
        ),
    }


def _fixture_root(tmp: str) -> Path:
    root = Path(tmp)
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "native-labels-fixture",
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


def check_standard_write_path_produces_native_labels() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore

    content = (
        "---\n"
        "type: prd\n"
        "unit-id: 057-native-labels-demo\n"
        "status: proposed\n"
        "topic: native-labels\n"
        "depends: [001-foo, 002-bar]\n"
        "visibility: public\n"
        "---\n\n# Native label demo unit\n\nBody prose."
    )
    body_path = "docs/prds/057-native-labels-demo/057-native-labels-demo.md"
    with tempfile.TemporaryDirectory() as tmp:
        root = _fixture_root(tmp)
        cfg = json.loads((root / ".cursor/workflow.config.json").read_text())
        backend = ps.get_backend(root, cfg)
        put_result = backend.put("057-native-labels-demo", body_path, content)
        got = backend.get("057-native-labels-demo", body_path)
        store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
        record = next(iter(store._issues.values()))
    expected_labels = {
        project_label("native-labels-fixture"),
        type_label("prd"),
        unit_id_label("057-native-labels-demo"),
        status_label("proposed"),
        topic_label("native-labels"),
        visibility_label("public"),
        *edge_labels_for("depends", ["001-foo", "002-bar"]),
    }
    ok = (
        put_result.verdict == "ok"
        and got.content == content
        and record.title == "Native label demo unit"
        and not record.title.startswith("[")
        and set(record.labels) == expected_labels
    )
    return {
        "name": "standard-write-path-produces-native-labels",
        "ok": ok,
        "detail": (
            f"title={record.title!r} exactMatch={got.content == content} "
            f"labels={sorted(record.labels)} expected={sorted(expected_labels)}"
        ),
    }


def check_backfill_promotes_legacy_issue_labels() -> dict:
    import planning_store as ps
    from issues_lib import FixtureIssuesStore, fixture_store_path

    legacy_content = "---\ntype: prd\nunit-id: 999-legacy\nstatus: proposed\n---\n\n# Legacy Unit\n\nBody."
    body_path = "docs/prds/999-legacy/999-legacy.md"
    with tempfile.TemporaryDirectory() as tmp:
        root = _fixture_root(tmp)
        legacy_body = compose_issue_body("native-labels-fixture", "prd", "999-legacy", legacy_content)
        store = FixtureIssuesStore(fixture_store_path(root))
        store.create(
            title="[native-labels-fixture] prd:999-legacy",
            body=legacy_body,
            labels=[project_label("native-labels-fixture"), type_label("prd")],
            project_key="native-labels-fixture",
            artifact_type="prd",
            unit_id="999-legacy",
        )
        cfg = json.loads((root / ".cursor/workflow.config.json").read_text())
        backend = ps.get_backend(root, cfg)
        got = backend.get("999-legacy", body_path)
        reloaded = FixtureIssuesStore(fixture_store_path(root))
        record = next(iter(reloaded._issues.values()))
    ok = (
        got.verdict == "ok"
        and got.content == legacy_content
        and unit_id_label("999-legacy") in record.labels
    )
    return {
        "name": "backfill-promotes-legacy-issue-labels",
        "ok": ok,
        "detail": f"getVerdict={got.verdict} contentMatch={got.content == legacy_content} labels={sorted(record.labels)}",
    }


def main() -> int:
    checks = [
        check_zero_minimal_frontmatter_labels(),
        check_many_full_frontmatter_labels(),
        check_boundary_edge_cap_and_title_precedence(),
        check_github_client_label_first_with_body_fallback(),
        check_jira_client_label_first_with_body_fallback(),
        check_standard_write_path_produces_native_labels(),
        check_backfill_promotes_legacy_issue_labels(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-native-labels",
        "rid": "R11",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
