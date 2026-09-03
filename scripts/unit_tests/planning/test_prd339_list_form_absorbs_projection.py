"""PRD 339 R37 — list-form absorbs projection equivalent to string form."""

from __future__ import annotations

import planning_canonical as pc


def _list_form() -> str:
    return (
        "---\n"
        "id: demo-prd\n"
        "type: prd\n"
        "status: proposed\n"
        "absorbs:\n"
        "  - gap-423-operator-body-projection-drops-yaml-list-form-ab\n"
        "  - gap-429-issue-store-put-must-refuse-sw-unit-id-marker-re\n"
        "---\n"
        "# Demo\n"
    )


def _string_form() -> str:
    return (
        "---\n"
        "id: demo-prd\n"
        "type: prd\n"
        "status: proposed\n"
        "absorbs: gap-423-operator-body-projection-drops-yaml-list-form-ab, "
        "gap-429-issue-store-put-must-refuse-sw-unit-id-marker-re\n"
        "---\n"
        "# Demo\n"
    )


def test_r37_list_form_absorbs_projection_equivalent() -> None:
    """R37 — YAML list-form and comma-string absorbs project to the same edges/labels."""
    list_body = _list_form()
    str_body = _string_form()

    list_fm, _ = pc.split_frontmatter(list_body)
    str_fm, _ = pc.split_frontmatter(str_body)
    assert list_fm is not None and str_fm is not None
    assert pc.parse_absorbs_targets(list_fm.get("absorbs")) == pc.parse_absorbs_targets(
        str_fm.get("absorbs")
    )

    list_labels = sorted(label for label in pc.structural_labels_from_content(list_body) if "absorbs" in label)
    str_labels = sorted(label for label in pc.structural_labels_from_content(str_body) if "absorbs" in label)
    assert list_labels == str_labels
    assert len(list_labels) == 2

    list_store = pc.operator_body_from_canonical(list_body)
    str_store = pc.operator_body_from_canonical(str_body)
    _, list_edges, _ = pc.resolve_put_edge_projection(
        store_content=list_store,
        canonical_content=list_body,
        existing_body=None,
        existing_native_links=None,
    )
    _, str_edges, _ = pc.resolve_put_edge_projection(
        store_content=str_store,
        canonical_content=str_body,
        existing_body=None,
        existing_native_links=None,
    )
    assert list_edges == str_edges
    assert list_edges is not None
    assert {edge["target"] for edge in list_edges} == {
        "gap-423-operator-body-projection-drops-yaml-list-form-ab",
        "gap-429-issue-store-put-must-refuse-sw-unit-id-marker-re",
    }
