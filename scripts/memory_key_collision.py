#!/usr/bin/env python3
"""Identity-keyed on-disk paths and alias-collision checks (PRD 082 R31).

On-disk layout follows the stable identity key, not permalink aliases. When
permalink-derived paths must remain for compatibility, write-time alias-collision
checks fail closed and existing collisions are reported for migration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_import_resolve import extract_aliases, extract_stable_id


class KeyCollisionError(Exception):
  def __init__(self, message: str, *, cause: str = "error") -> None:
    super().__init__(message)
    self.cause = cause


@dataclass(frozen=True)
class CollisionReport:
  identity_key: str
  permalink: str
  path: str
  other_identity: str | None = None


def identity_key(record: dict[str, Any]) -> str:
  """Canonical on-disk identity — stable record id, not a permalink alias."""
  return extract_stable_id(record)


def _safe_segment(value: str) -> str:
  return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "note"


def identity_disk_relpath(category: str, stable_id: str) -> str:
  """Filesystem relpath segment keyed by stable identity, not permalink alias."""
  folder = "rules" if category == "rule" else _safe_segment(category or "learning")
  safe_id = _safe_segment(stable_id)
  if category == "rule":
    return f"{safe_id}.md"
  return f"{folder}/{safe_id}.md"


def permalink_disk_relpath(category: str, permalink: str) -> str:
  """Legacy permalink-derived path (used only for collision scanning)."""
  folder = "rules" if category == "rule" else _safe_segment(category or "learning")
  safe = _safe_segment(permalink.replace("/", "_"))
  if category == "rule":
    return f"{safe}.md"
  return f"{folder}/{safe}.md"


def assert_no_alias_collision(
  alias_index: dict[str, str],
  record: dict[str, Any],
  *,
  canonical_id: str,
) -> None:
  """Fail closed when a permalink/title alias already maps to a different identity."""
  for alias in extract_aliases(record):
    if alias == canonical_id:
      continue
    existing = alias_index.get(alias)
    if existing and existing != canonical_id:
      raise KeyCollisionError(
        f"alias collision on write: {alias!r} -> {existing!r}, refused {canonical_id!r}",
        cause="alias-collision",
      )
    alias_index[alias] = canonical_id


def build_alias_index(records: list[dict[str, Any]]) -> dict[str, str]:
  index: dict[str, str] = {}
  for record in records:
    cid = identity_key(record)
    assert_no_alias_collision(index, record, canonical_id=cid)
  return index


def scan_permalink_path_collisions(
  project_path: Path,
  *,
  list_notes_fn: Any,
  note_path_fn: Any,
  memories_directory: str = "memories",
  rules_directory: str = "rules",
) -> list[CollisionReport]:
  """Report existing records whose permalink path would differ from identity path."""
  reports: list[CollisionReport] = []
  records = list_notes_fn(
    project_path,
    include_rules=True,
    memories_directory=memories_directory,
    rules_directory=rules_directory,
  )
  for record in records:
    cid = identity_key(record)
    fields = dict(record.get("fields") or {})
    permalink = str(fields.get("permalink") or record.get("id") or cid)
    category = str(record.get("category") or "learning")
    identity_rel = identity_disk_relpath(category, cid)
    permalink_rel = permalink_disk_relpath(category, permalink)
    if identity_rel == permalink_rel:
      continue
    identity_path = note_path_fn(
      project_path,
      category,
      cid,
      memories_directory=memories_directory,
      rules_directory=rules_directory,
    )
    permalink_path = note_path_fn(
      project_path,
      category,
      permalink,
      memories_directory=memories_directory,
      rules_directory=rules_directory,
    )
    if identity_path.resolve() != permalink_path.resolve():
      reports.append(
        CollisionReport(
          identity_key=cid,
          permalink=permalink,
          path=str(identity_path),
          other_identity=permalink if permalink != cid else None,
        )
      )
  return reports
