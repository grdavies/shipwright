"""Named fixture rid-asterisk-linear-roundtrip (PRD 358 R7)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE_ID = "rid-asterisk-linear-roundtrip"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main() -> int:
    root = _repo_root()
    scripts = root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    import doc_format

    sample_path = Path(__file__).resolve().parent / "linear-requirements-snapshot.md"
    text = sample_path.read_text(encoding="utf-8")
    expected = {f"R{n}" for n in range(1, 17)}
    found = {rid for rid, _ in doc_format.extract_rd_bullets(text) if rid.startswith("R")}
    if found != expected:
        print(f"extract_rd_bullets missing ids: expected {sorted(expected)}, got {sorted(found)}")
        return 1

    hyphen = "## Requirements\n\n- **R1** Hyphen marker requirement one for linear roundtrip extraction.\n"
    asterisk = "## Requirements\n\n* **R1** Asterisk marker requirement one for linear roundtrip extraction.\n"
    for label, fragment in ("hyphen", hyphen), ("asterisk", asterisk):
        ids = [rid for rid, _ in doc_format.extract_rd_bullets(fragment)]
        if ids != ["R1"]:
            print(f"{label} R1 bullet parse failed: {ids}")
            return 1

    verdict, findings = doc_format.check_document(text, str(sample_path))
    if verdict != "pass":
        print(f"doc_format.check_document failed: {findings}")
        return 1

    normalized = doc_format.write_document(text)
    if normalized != text:
        print("write_document rewrote list markers on the Linear snapshot")
        return 1

    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "doc-format-normalize.py"),
            "--check",
            str(sample_path),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"doc-format-normalize --check failed: {proc.stderr or proc.stdout}")
        return 1

    rigor = subprocess.run(
        [
            sys.executable,
            str(scripts / "spec-rigor-check.py"),
            "--root",
            str(root),
            "--artifact",
            "prd",
            "--path",
            str(sample_path),
            "--tier",
            "standard",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if rigor.returncode != 0:
        print(f"spec-rigor-check failed: {rigor.stderr or rigor.stdout}")
        return 1
    payload = json.loads(rigor.stdout.strip().splitlines()[-1])
    if payload.get("verdict") != "pass":
        print(f"spec-rigor verdict not pass: {payload}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
