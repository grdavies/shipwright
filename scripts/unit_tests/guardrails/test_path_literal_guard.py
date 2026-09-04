"""Fixtures for path_literal_guard (PRD 342 R11)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

import path_literal_guard as guard


INVENTORY = {
    "schemaVersion": 1,
    "description": "test inventory",
    "entries": [
        {
            "family": "configuration",
            "legacyPath": ".cursor/workflow.config.json",
            "newPath": ".shipwright/workflow.config.json",
            "accessor": "workflow_config_path",
            "notes": "test",
        },
        {
            "family": "run-state",
            "legacyPath": ".cursor/sw-deliver-runs",
            "newPath": ".shipwright/deliver-runs",
            "accessor": "deliver_runs_dir",
            "notes": "test",
        },
    ],
}


def _seed_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "core" / "sw-reference").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "core" / "scripts").mkdir(parents=True)
    (root / "core" / "sw-reference" / "state-root-inventory.json").write_text(
        json.dumps(INVENTORY, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def test_new_direct_reference_fails(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    (root / "scripts" / "offender.py").write_text(
        'PATH = ".cursor/sw-deliver-runs/foo"\n',
        encoding="utf-8",
    )
    # Empty ratchet → any literal is new.
    (root / "core" / "sw-reference" / "path-literal-ratchet.json").write_text(
        json.dumps({"schemaVersion": 1, "refs": []}) + "\n",
        encoding="utf-8",
    )
    payload = guard.evaluate(root)
    assert payload["verdict"] == "fail"
    assert payload["reason"] == "new-path-literal"
    assert payload["newRefCount"] == 1
    assert guard.main(["--root", str(root)]) == 20


def test_ratcheted_residual_literals_do_not_fire(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    literal = ".cursor/sw-deliver-runs/legacy"
    (root / "scripts" / "residual.py").write_text(
        f'PATH = "{literal}"\n',
        encoding="utf-8",
    )
    key = guard.site_key("scripts/residual.py", literal)
    (root / "core" / "sw-reference" / "path-literal-ratchet.json").write_text(
        json.dumps({"schemaVersion": 1, "refs": [key]}) + "\n",
        encoding="utf-8",
    )
    payload = guard.evaluate(root)
    assert payload["verdict"] == "pass"
    assert payload["newRefCount"] == 0
    assert guard.main(["--root", str(root)]) == 0


def test_mirror_pair_reports_once(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    body = 'PATH = ".cursor/workflow.config.json"\n'
    (root / "scripts" / "mirrored.py").write_text(body, encoding="utf-8")
    (root / "core" / "scripts" / "mirrored.py").write_text(body, encoding="utf-8")
    findings = guard.scan_repo(root)
    assert len(findings) == 1
    assert findings[0]["path"] == "scripts/mirrored.py"
    assert findings[0]["sourcePath"] == "scripts/mirrored.py"


@pytest.mark.parametrize(
    "fn_class,source",
    [
        (
            "runtime-fragments",
            textwrap.dedent(
                '''\
                prefix = ".cursor/"
                suffix = "sw-deliver-runs"
                path = prefix + suffix
                '''
            ),
        ),
        (
            "fstring-or-format",
            textwrap.dedent(
                '''\
                name = "sw-deliver-runs"
                path = f".cursor/{name}"
                other = ".cursor/{}".format(name)
                '''
            ),
        ),
        (
            "config-or-env",
            textwrap.dedent(
                '''\
                import os
                path = os.environ.get("SW_LEGACY_PATH", "")
                '''
            ),
        ),
        (
            "fixtures-and-generated",
            None,  # handled separately via path skip
        ),
    ],
)
def test_named_false_negative_class_not_detected(
    tmp_path: Path, fn_class: str, source: str | None
) -> None:
    root = _seed_root(tmp_path)
    if fn_class == "fixtures-and-generated":
        fixture = root / "scripts" / "unit_tests" / "fixtures" / "legacy.py"
        fixture.parent.mkdir(parents=True)
        fixture.write_text('PATH = ".cursor/sw-deliver-runs"\n', encoding="utf-8")
        findings = guard.scan_repo(root)
        assert findings == []
        assert fn_class in guard.FALSE_NEGATIVE_CLASSES
        return

    assert source is not None
    (root / "scripts" / "fn_case.py").write_text(source, encoding="utf-8")
    findings = guard.scan_repo(root)
    assert findings == [], f"{fn_class} unexpectedly detected: {findings}"
    assert fn_class in guard.FALSE_NEGATIVE_CLASSES
