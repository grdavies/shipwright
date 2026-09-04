"""Interview idempotency, credential scope, and init currency (PRD 342 R28/R29/R48)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from init_scripts_facade import (  # noqa: E402
    store_broker_reference,
    validate_broker_reference_scope,
)


def _load_sw_configure():
    path = SCRIPT_DIR / "sw-configure.py"
    spec = importlib.util.spec_from_file_location("sw_configure_idempotency", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sw_configure():
    return _load_sw_configure()


def test_second_run_proposes_deltas_only_without_preconsent_write(
    tmp_path: Path, sw_configure
) -> None:
    """R28 — already-configured repo proposes drift only; no write before consent."""
    first = sw_configure.apply_packaged_configure(tmp_path, accept_ci_stub=False)
    assert first["verdict"] == "pass"
    assert first.get("wrote") is True
    config_path = Path(first["configPath"])
    assert config_path.is_file()

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    stamp = cfg.setdefault("configuredWith", {})
    stamp["shipwrightVersion"] = "0.0.0-stale"
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    drifted = config_path.read_text(encoding="utf-8")
    drifted_mtime = config_path.stat().st_mtime_ns

    proposal = sw_configure.propose_configure_deltas(tmp_path)
    assert proposal["alreadyConfigured"] is True
    assert proposal["wrote"] is False
    assert proposal["written"] == []
    assert proposal["deltaCount"] >= 1
    assert any(
        row["path"] == "configuredWith.shipwrightVersion" for row in proposal["deltas"]
    )

    second = sw_configure.apply_packaged_configure(
        tmp_path, accept_ci_stub=False, confirm=False
    )
    assert second["verdict"] == "confirm-required"
    assert second.get("action") == "propose-deltas"
    assert second.get("wrote") is False
    assert second.get("written") == []
    assert second.get("deltaCount", 0) >= 1
    assert config_path.read_text(encoding="utf-8") == drifted
    assert config_path.stat().st_mtime_ns == drifted_mtime

    applied = sw_configure.apply_packaged_configure(
        tmp_path, accept_ci_stub=False, confirm=True
    )
    assert applied["verdict"] == "pass"
    assert applied.get("wrote") is True
    after = json.loads(config_path.read_text(encoding="utf-8"))
    assert after["configuredWith"]["shipwrightVersion"] != "0.0.0-stale"


def test_out_of_scope_broker_reference_fails_before_success() -> None:
    """R29 — credential material and out-of-scope refs fail before success."""
    material = store_broker_reference(
        credential_ref="github/work",
        project_id="demo",
        extra={"token": "sekrit-value-should-never-land"},
    )
    assert material["verdict"] == "fail"
    assert material["error"] == "credential-material-refused"
    assert material.get("fragment") is None

    secret_ref = store_broker_reference(
        credential_ref="ghp_notARealTokenButLooksLikeOne1234567890",
        project_id="demo",
    )
    assert secret_ref["verdict"] == "fail"
    assert secret_ref["error"] == "credential-material-refused"

    ok = store_broker_reference(
        credential_ref="github/work",
        project_id="demo-app",
    )
    assert ok["verdict"] == "pass"
    fragment = ok["fragment"]
    assert fragment["host"]["credentialRef"] == "github/work"
    assert fragment["projectId"] == "demo-app"
    assert "token" not in json.dumps(fragment)

    entry = {
        "backend": "environment",
        "provider": "github",
        "allowedRepos": ["acme/allowed"],
        "allowedProjectIds": ["demo-app"],
        "allowedEndpoints": ["https://api.github.com"],
    }
    refused = validate_broker_reference_scope(
        credential_ref="github/work",
        repo="acme/other",
        project_id="demo-app",
        endpoint="https://api.github.com",
        selector_entry=entry,
    )
    assert refused["verdict"] == "fail"
    assert refused["error"] == "out-of-scope-reference"
    assert "repo-out-of-scope" in refused["errors"]
    assert refused["inScope"] is False

    accepted = validate_broker_reference_scope(
        credential_ref="github/work",
        repo="acme/allowed",
        project_id="demo-app",
        endpoint="https://api.github.com",
        selector_entry=entry,
    )
    assert accepted["verdict"] == "pass"
    assert accepted["inScope"] is True


def test_documented_init_steps_match_code_seed(sw_configure) -> None:
    """R48 — documented initialization steps equal the code seed output."""
    steps = sw_configure.packaged_init_steps()
    assert len(steps) == 4
    docs = (REPO_ROOT / "docs/guides/getting-started.md").read_text(encoding="utf-8")
    # Canonical block: first four numbered steps under the default packaged path.
    default_section = docs.split("## Default: packaged install + single init", 1)[1].split(
        "### Self-check", 1
    )[0]
    numbered = re.findall(r"^\d+\.\s+(.+)$", default_section, flags=re.MULTILINE)
    assert numbered[:4] == steps
    for step in steps:
        assert step in docs

    config_docs = (REPO_ROOT / "docs/guides/configuration.md").read_text(encoding="utf-8")
    assert "### Interview priority tiering" in config_docs
    assert "Priority zero" in config_docs
    assert "Priority one" in config_docs
    assert "Priority two" in config_docs
    assert "allowedRepos" in config_docs
    assert "allowedProjectIds" in config_docs
    assert "allowedEndpoints" in config_docs
