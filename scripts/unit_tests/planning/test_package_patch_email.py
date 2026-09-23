"""Complete Markdown patch references are package tokens, never line-wide exemptions."""
import pytest
from secret_scan import scan_text
from memory_redact import redact

PATCH = "patches/nitropack" + "@2.13.4.patch"
EMAIL = "person" + "@example.com"
PUBLIC_CONTACT = "i" + "@izs.me"


def emails(text):
    return [f for f in scan_text(text, allowlist={"lines": [], "paths": []}) if f.pattern == "EMAIL"]


def test_exact_frozen_amendment_reference_passes():
    assert not emails(f"- **R42**: declaration-only matcher patch at `{PATCH}`, metadata unchanged.")
    assert not emails(f"- `{PATCH}` — declaration-only corrections.")
    assert not emails(f"Candidate touches `{PATCH}` plus registration metadata.")
    assert not emails(f'"nitropack@2.13.4": "{PATCH}"')
    assert not emails(f"    path: {PATCH}")


@pytest.mark.parametrize("text", [
    f"`{PATCH}` {EMAIL}", f"{EMAIL} `{PATCH}`", f"`{PATCH}` `{EMAIL}`",
    f'"{PATCH}" {EMAIL}', f"path: {PATCH} {EMAIL}",
    f"`{PATCH}` nitropack" + "@2.13.4.patch",  # Same matched text outside the exempt span.
    "nitropack" + f"@2.13.4.patch `{PATCH}`",
])
def test_adjacent_email_still_denied(text):
    assert len(emails(text)) == 1


@pytest.mark.parametrize("text", [
    PATCH, f"`{PATCH}", f"{PATCH}`", f"``{PATCH}``", f"`{PATCH}.evil`",
    f"`{PATCH}/extra`", f"`other/{PATCH}`", f"\\`{PATCH}`",
    "`patches/nitropack" + "@2.13.patch`", "`patches/nitropack" + "@02.13.4.patch`",
    "`patches/nitropack" + "@example.com.patch`", f"`patches/{EMAIL}`",
])
def test_malformed_or_non_patch_email_tokens_remain_denied(text):
    assert emails(text)


def test_public_glob_contact_requires_exact_root_lockfile_line():
    notice = (
        "    deprecated: Old versions of glob are not supported, and contain widely "
        "publicized security vulnerabilities, which have been fixed in the current "
        "version. Please update. Support for old versions may be purchased "
        "(at exorbitant rates) by contacting " + PUBLIC_CONTACT
    )
    empty = {"lines": [], "paths": []}
    assert not scan_text(notice, allowlist=empty, path="pnpm-lock.yaml")
    assert emails(notice)
    assert scan_text(notice, allowlist=empty, path="nested/pnpm-lock.yaml")
    assert scan_text(notice + f" {EMAIL}", allowlist=empty, path="pnpm-lock.yaml")
    assert scan_text(notice.replace("glob", "another package"), allowlist=empty, path="pnpm-lock.yaml")


def test_existing_redactor_still_removes_real_email_next_to_reference():
    result = redact(f"`{PATCH}` {EMAIL}", destination="external")
    assert EMAIL not in result
    assert "[REDACTED:EMAIL]" in result
