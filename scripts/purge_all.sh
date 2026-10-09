#!/usr/bin/env bash
# Delete everything Creator Scout scraped or derived. Run it AFTER judging, never before: the data in
# the worktrees is input for workflows that may still be running.
#
#   scripts/purge_all.sh --dry-run   # list what would be deleted (path + size), delete nothing
#   scripts/purge_all.sh --yes       # delete it
#
# What it deletes, in this repo and in every git worktree of it (from `git worktree list`, not a glob):
#   data/cache  data/runs  data/llm  data/live-tests  data/live-run  data/live-subject  data/validation
# Nothing else: fixtures/, docs/ and the rest of data/ are never touched. It refuses to run when the
# script is not inside this repo, and refuses everything when data/ or a target is a symlink.
# It prints paths and sizes only, never file contents.

set -euo pipefail

usage() {
  sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

DRY=0
YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "purge_all: unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done
if [ "$DRY" -eq 1 ] && [ "$YES" -eq 1 ]; then
  echo "purge_all: give --dry-run or --yes, not both" >&2; exit 2
fi
if [ "$DRY" -eq 0 ] && [ "$YES" -eq 0 ]; then
  echo "purge_all: nothing done. Use --dry-run to list, --yes to delete." >&2; exit 2
fi

# ---------------------------------------------------------------------------------------- repo root
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
TOP=$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null || true)
if [ -n "$TOP" ]; then
  TOP=$(cd "$TOP" && pwd -P)
fi
if [ -z "$TOP" ] || [ "$TOP" != "$ROOT" ] || [ ! -f "$ROOT/scripts/validate_run.py" ]; then
  echo "purge_all: refusing: $ROOT is not the Creator Scout repo root (no git toplevel match or no scripts/validate_run.py)" >&2
  exit 1
fi

# ---------------------------------------------------------------------------------------- targets
NAMES="cache runs llm live-tests live-run live-subject validation"
TARGETS=()
REFUSED=0

add_worktree() {
  local wt="${1:?}"
  if [ ! -d "$wt" ]; then
    echo "skip: worktree $wt does not exist (prunable)" >&2
    return 0
  fi
  wt=$(cd "$wt" && pwd -P)
  case "$wt" in
    /|"") echo "purge_all: refusing odd worktree path '$wt'" >&2; REFUSED=1; return 0 ;;
  esac
  if [ -L "$wt/data" ]; then
    echo "purge_all: refusing: $wt/data is a symlink" >&2; REFUSED=1; return 0
  fi
  [ -d "$wt/data" ] || return 0
  local name t
  for name in $NAMES; do
    t="${wt:?}/data/${name:?}"
    if [ -L "$t" ]; then
      echo "purge_all: refusing: $t is a symlink" >&2; REFUSED=1; continue
    fi
    [ -e "$t" ] || continue
    case "$t" in
      "$wt"/data/cache|"$wt"/data/runs|"$wt"/data/llm|"$wt"/data/live-tests|"$wt"/data/live-run|"$wt"/data/live-subject|"$wt"/data/validation) ;;
      *) echo "purge_all: refusing: $t is not on the allow-list" >&2; REFUSED=1; continue ;;
    esac
    TARGETS+=("$t")
  done
}

WT_LIST=$(git -C "$ROOT" worktree list --porcelain)
while IFS= read -r line; do
  case "$line" in
    "worktree "*) add_worktree "${line#worktree }" ;;
  esac
done <<EOF
$WT_LIST
EOF

if [ "$REFUSED" -ne 0 ]; then
  echo "purge_all: refused, nothing deleted (see the lines above)" >&2
  exit 1
fi
if [ "${#TARGETS[@]}" -eq 0 ]; then
  echo "purge_all: nothing to delete"
  exit 0
fi

# ---------------------------------------------------------------------------------------- list / delete
if [ "$DRY" -eq 1 ]; then
  echo "Would delete (dry run, nothing deleted):"
else
  echo "Deleting:"
fi
for t in "${TARGETS[@]}"; do
  size=$(du -sh "$t" 2>/dev/null | cut -f1 || true)
  printf '  %6s  %s\n' "${size:-?}" "$t"
  if [ "$YES" -eq 1 ]; then
    rm -rf -- "${t:?}"
  fi
done
if [ "$DRY" -eq 1 ]; then
  echo "${#TARGETS[@]} path(s) would be deleted. Run with --yes to delete them."
else
  echo "${#TARGETS[@]} path(s) deleted."
fi
