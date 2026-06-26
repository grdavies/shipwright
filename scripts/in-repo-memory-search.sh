#!/usr/bin/env bash
# Deterministic keyword + frontmatter search for in-repo memory store.
# Emits JSON: {"results":[{"id":"...","summary":"..."}]}
set -euo pipefail

STORE=""
QUERY=""
CATEGORY=""
TAG=""
FILE_GLOB=""

usage() {
  echo "Usage: $0 --store DIR [--query TEXT] [--category CAT] [--tag TAG] [--file-glob GLOB]" >&2
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --store) STORE="${2:-}"; shift 2 ;;
    --query) QUERY="${2:-}"; shift 2 ;;
    --category) CATEGORY="${2:-}"; shift 2 ;;
    --tag) TAG="${2:-}"; shift 2 ;;
    --file-glob) FILE_GLOB="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[ -n "$STORE" ] || usage

MEMORIES="$STORE/memories"
RULES="$STORE/rules"

frontmatter_field() {
  local file="$1" field="$2"
  awk -v f="$field" '
    BEGIN { in_fm=0 }
    /^---$/ { in_fm++; next }
    in_fm==1 && $0 ~ "^" f ":" {
      sub("^" f ":[[:space:]]*", "")
      gsub(/^["'\''[]]|["'\'']]$/, "")
      print
      exit
    }
  ' "$file" 2>/dev/null || true
}

frontmatter_tags_contain() {
  local file="$1" want="$2"
  local tags
  tags=$(awk '
    BEGIN { in_fm=0 }
    /^---$/ { in_fm++; next }
    in_fm==1 && /^tags:/ {
      sub(/^tags:[[:space:]]*/, "")
      print
      exit
    }
  ' "$file" 2>/dev/null || true)
  echo "$tags" | grep -q "$want"
}

related_files_match() {
  local file="$1" glob="$2"
  local rf
  rf=$(awk '
    BEGIN { in_fm=0 }
    /^---$/ { in_fm++; next }
    in_fm==1 && /^relatedFiles:/ {
      sub(/^relatedFiles:[[:space:]]*/, "")
      print
      exit
    }
  ' "$file" 2>/dev/null || true)
  echo "$rf" | grep -qF "$glob"
}

body_summary() {
  local file="$1"
  awk 'BEGIN { past=0 } /^---$/ { past++; next } past>=2 && NF { print; exit }' "$file" | head -1
}

score_file() {
  local file="$1" id="$2" q="$3"
  local score=0
  local cat fm_cat
  fm_cat=$(frontmatter_field "$file" "category")
  if [ -n "$CATEGORY" ] && [ "$fm_cat" != "$CATEGORY" ]; then
    return 1
  fi
  if [ -n "$TAG" ] && ! frontmatter_tags_contain "$file" "$TAG"; then
    return 1
  fi
  if [ -n "$FILE_GLOB" ] && ! related_files_match "$file" "$FILE_GLOB"; then
    return 1
  fi
  if [ -n "$q" ]; then
    if grep -qiF "$q" "$file" 2>/dev/null; then
      score=$((score + 10))
    else
      return 1
    fi
  fi
  local summary
  summary=$(body_summary "$file")
  [ -n "$summary" ] || summary="$id"
  printf '%d\t%s\t%s\n' "$score" "$id" "$summary"
}

RESULTS=""
if [ -d "$MEMORIES" ]; then
  while IFS= read -r -d '' f; do
    id=$(basename "$f" .md)
    line=$(score_file "$f" "$id" "$QUERY" || true)
    [ -n "$line" ] && RESULTS="${RESULTS}${line}"$'\n'
  done < <(find "$MEMORIES" -maxdepth 1 -name '*.md' -print0 2>/dev/null | sort -z)
fi

# Rules excluded from general search unless category=rule
if [ "$CATEGORY" = "rule" ] && [ -d "$RULES" ]; then
  while IFS= read -r -d '' f; do
    id=$(basename "$f" .md)
    line=$(score_file "$f" "$id" "$QUERY" || true)
    [ -n "$line" ] && RESULTS="${RESULTS}${line}"$'\n'
  done < <(find "$RULES" -maxdepth 1 -name '*.md' -print0 2>/dev/null | sort -z)
fi

# Sort by score desc, then id asc (deterministic)
SORTED=$(printf '%s' "$RESULTS" | grep -v '^$' | sort -t$'\t' -k1,1nr -k2,2 || true)

JSON_ITEMS="[]"
if [ -n "$SORTED" ]; then
  JSON_ITEMS=$(printf '%s\n' "$SORTED" | while IFS=$'\t' read -r _sc id summary; do
    jq -n --arg id "$id" --arg summary "$summary" '{id:$id, summary:$summary}'
  done | jq -s '.')
fi

jq -n --argjson results "$JSON_ITEMS" '{results: $results}'
