#!/usr/bin/env bash
# Resolve plugin content root for workflow scripts (dist install, core authoring, legacy root).
sw_resolve_plugin_root() {
  local script_dir="${1:?script_dir required}"
  local parent
  parent="$(cd "$script_dir/.." && pwd)"
  if [ -d "$parent/providers" ] || [ -d "$parent/commands" ]; then
    printf '%s\n' "$parent"
    return 0
  fi
  if [ -d "$parent/core/providers" ]; then
    printf '%s\n' "$parent/core"
    return 0
  fi
  printf '%s\n' "$parent"
}
