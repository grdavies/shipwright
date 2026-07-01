#!/usr/bin/env python3
"""Explicit no-op quality harness adapter (PRD 039 R3)."""
from __future__ import annotations

import json


def main() -> int:
    print(
        json.dumps(
            {
                "verdict": "none",
                "provider": "none",
                "skipped": True,
                "reason": "quality.provider is none",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
