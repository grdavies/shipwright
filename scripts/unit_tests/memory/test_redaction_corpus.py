"""PRD 082 R32 — modern token corpus fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_redact_allowlist as allowlist  # noqa: E402
import memory_redact_patterns as patterns  # noqa: E402
import memory_redaction_provenance as prov  # noqa: E402


@pytest.mark.parametrize("destination", sorted(allowlist.DESTINATION_VALUES))
@pytest.mark.parametrize("name,sample", sorted(patterns.CORPUS_SAMPLES.items()))
def test_modern_token_removed_for_every_destination(name: str, sample: str, destination: str) -> None:
    body = f"prefix {sample} suffix"
    redacted, record = allowlist.redact_document(body, destination=destination)
    assert sample not in redacted
    assert "REDACTED" in redacted
    assert record["patternSetVersion"] == patterns.pattern_set_version()
    assert record["destinationTierApplied"] == destination
    assert record["substitutionCount"] >= 1


def test_pattern_set_version_recorded_on_provenance_record() -> None:
    secret = patterns.CORPUS_SAMPLES["GITHUB_PAT"]
    _, record = allowlist.redact_document(secret, destination="external")
    provenance = prov.build_applied_redaction_record(
        destination_tier="external",
        text=secret,
    )
    assert provenance["patternSetVersion"]
    assert record["patternSetVersion"] == patterns.pattern_set_version()


def test_representative_modern_patterns_have_samples() -> None:
    assert patterns.CORPUS_SAMPLES
    for name in patterns.CORPUS_SAMPLES:
        assert any(p.name == name for p in patterns.MODERN_PATTERNS)
