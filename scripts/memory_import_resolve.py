#!/usr/bin/env python3
"""Two-pass interchange import id resolution (PRD 082 R31).

Pass 1 registers every record id before any supersedes edge is resolved so input
ordering cannot sever supersession chains. Pass 2 resolves supersedes targets to
canonical ids; an unresolvable target is a hard error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import memory_fingerprint as fp


class ImportResolveError(Exception):
  def __init__(self, message: str, *, cause: str = "error") -> None:
    super().__init__(message)
    self.cause = cause


@dataclass
class IdRegistry:
  """Maps aliases and provisional ids to canonical stable ids."""

  canonical: dict[str, str] = field(default_factory=dict)
  aliases: dict[str, str] = field(default_factory=dict)
  records: dict[str, dict[str, Any]] = field(default_factory=dict)

  def register(self, canonical_id: str, record: dict[str, Any]) -> None:
    cid = canonical_id.strip()
    if not cid:
      raise ImportResolveError("empty canonical id", cause="malformed")
    self.canonical[cid] = cid
    self.records[cid] = record
    for alias in extract_aliases(record):
      existing = self.aliases.get(alias)
      if existing and existing != cid:
        raise ImportResolveError(
          f"alias collision: {alias!r} maps to {existing!r} and {cid!r}",
          cause="alias-collision",
        )
      self.aliases[alias] = cid

  def resolve(self, ref: str) -> str:
    key = ref.strip()
    if not key:
      raise ImportResolveError("empty id reference", cause="malformed")
    if key in self.canonical:
      return self.canonical[key]
    if key in self.aliases:
      return self.aliases[key]
    raise ImportResolveError(f"unresolvable id reference: {key!r}", cause="unresolvable-supersedes")


def extract_stable_id(record: dict[str, Any]) -> str:
  fields = dict(record.get("fields") or {})
  for key in ("stableId", "id", "permalink"):
    value = record.get(key) if key != "permalink" else fields.get("permalink") or record.get("id")
    if isinstance(value, str) and value.strip():
      return value.strip()
  rid = record.get("id")
  if isinstance(rid, str) and rid.strip():
    return rid.strip()
  raise ImportResolveError("record missing stable id", cause="malformed")


def extract_aliases(record: dict[str, Any]) -> list[str]:
  fields = dict(record.get("fields") or {})
  out: list[str] = []
  seen: set[str] = set()

  def add(value: Any) -> None:
    if not isinstance(value, str):
      return
    text = value.strip()
    if not text or text in seen:
      return
    seen.add(text)
    out.append(text)

  add(record.get("stableId"))
  add(record.get("id"))
  add(fields.get("permalink"))
  add(fields.get("id"))
  add(fields.get("title"))
  return out


def extract_supersedes(record: dict[str, Any]) -> list[str]:
  fields = dict(record.get("fields") or {})
  raw = record.get("supersedes")
  if raw is None:
    raw = fields.get("supersedes")
  if not raw:
    return []
  if isinstance(raw, str):
    return [raw.strip()] if raw.strip() else []
  if isinstance(raw, list):
    return [str(x).strip() for x in raw if isinstance(x, str) and x.strip()]
  raise ImportResolveError("invalid supersedes field", cause="malformed")


def assign_ids_pass(records: list[dict[str, Any]]) -> IdRegistry:
  registry = IdRegistry()
  for record in records:
    canonical_id = extract_stable_id(record)
    registry.register(canonical_id, record)
  return registry


def resolve_supersedes_pass(
  records: list[dict[str, Any]],
  registry: IdRegistry,
) -> list[dict[str, Any]]:
  resolved: list[dict[str, Any]] = []
  for record in records:
    out = dict(record)
    fields = dict(out.get("fields") or {})
    targets = extract_supersedes(out)
    if not targets:
      resolved.append(out)
      continue
    canonical_targets: list[str] = []
    for target in targets:
      canonical_targets.append(registry.resolve(target))
    out["supersedes"] = canonical_targets
    fields["supersedes"] = canonical_targets
    out["fields"] = fields
    resolved.append(out)
  return resolved


def two_pass_import_resolve(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], IdRegistry]:
  """Register all ids, then resolve supersedes edges to canonical ids."""
  registry = assign_ids_pass(records)
  resolved = resolve_supersedes_pass(records, registry)
  return resolved, registry


def merge_identity_key(record: dict[str, Any]) -> str:
  """Fingerprint-stable identity key for merge deduplication."""
  return fp.note_fingerprint(record)
