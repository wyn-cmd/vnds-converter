#!/bin/bash
# Strip spaces out of filenames.
#
# VNDS references assets by name from its script files, and a space in a name is
# the most common reason a converted game loads a blank screen, so the pipeline
# renames assets before anything else touches them.
#
# Usage: rename.sh [--recursive] [--dry-run] DIRECTORY

source "$(dirname "$0")/../lib/common.sh"

recursive=0
dry_run=0
target=""

while [ $# -gt 0 ]; do
    case "$1" in
        -r|--recursive) recursive=1 ;;
        -n|--dry-run)   dry_run=1 ;;
        -h|--help)      usage_from_header "$0"; exit 0 ;;
        -*)             die "unknown option: $1" ;;
        *)              target="$1" ;;
    esac
    shift
done

[ -n "$target" ] || die "usage: $(basename "$0") [--recursive] [--dry-run] DIRECTORY"
[ -d "$target" ] || die "'$target' is not a directory"

renamed=0
conflicts=0

# -print0 paired with read -d '' keeps names containing spaces or newlines in one
# piece. The original find pipe also ran the loop in a subshell, which threw the
# counters away.
while IFS= read -r -d '' path; do
    base=$(basename -- "$path")
    new_base=${base// /}
    [ "$base" = "$new_base" ] && continue

    parent=$(dirname -- "$path")
    new_path="$parent/$new_base"

    # Two different files can collapse onto one name, for example "my art.png"
    # and "myart.png". Overwriting one silently would corrupt the game.
    if [ -e "$new_path" ]; then
        log "conflict: '$new_base' already exists, leaving '$base' alone"
        conflicts=$((conflicts + 1))
        continue
    fi

    if [ "$dry_run" -eq 1 ]; then
        log "would rename: $base -> $new_base"
    else
        mv -- "$path" "$new_path"
        log "renamed: $base -> $new_base"
    fi
    renamed=$((renamed + 1))
done < <(if [ "$recursive" -eq 1 ]; then find "$target" -depth -print0; else find "$target" -maxdepth 1 -print0; fi)

log "renamed $renamed file(s), $conflicts conflict(s)"
[ "$conflicts" -eq 0 ]
