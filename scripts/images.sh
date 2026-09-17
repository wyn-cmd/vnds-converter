#!/bin/bash
# Convert images into the two forms VNDS needs.
#
# background: the DS screen is 256x192, so backgrounds are forced onto exactly
#   that. Stretching is the default because it fills the screen. Pass --fit to
#   keep the aspect ratio and pad with black instead.
# foreground: sprites are scaled to a fixed height, 180 by default, keeping their
#   aspect ratio. 180 leaves a little room inside the 192 pixel screen so a
#   sprite is not clipped at the top and bottom.
#
# Both modes write PNG, and both refuse to silently overwrite a PNG that a
# different source image already produced.
#
# Usage: images.sh [--mode background|foreground] [--height N] [--fit]
#                  [--dry-run] SOURCE_DIR [OUTPUT_DIR]

source "$(dirname "$0")/../lib/common.sh"

mode="background"
height=180
fit=0
dry_run=0
source_dir=""
output_dir=""

while [ $# -gt 0 ]; do
    case "$1" in
        -m|--mode)       mode="${2:-}"; shift ;;
        --height)        height="${2:-}"; shift ;;
        --fit)           fit=1 ;;
        -n|--dry-run)    dry_run=1 ;;
        -h|--help)       usage_from_header "$0"; exit 0 ;;
        -*)              die "unknown option: $1" ;;
        *)               if [ -z "$source_dir" ]; then source_dir="$1"; else output_dir="$1"; fi ;;
    esac
    shift
done

case "$mode" in
    background|foreground) ;;
    *) die "--mode must be background or foreground, got '$mode'" ;;
esac

[ -n "$source_dir" ] || die "usage: $(basename "$0") --mode background|foreground SOURCE_DIR [OUTPUT_DIR]"
[ -d "$source_dir" ] || die "'$source_dir' is not a directory"

if [ -z "$output_dir" ]; then
    output_dir="$source_dir/converted"
fi

case "$height" in
    ''|*[!0-9]*) die "--height must be a number, got '$height'" ;;
esac

image_command=$(image_tool)
if [ "$dry_run" -eq 0 ]; then
    mkdir -p -- "$output_dir"
fi

converted=0
skipped=0
conflicts=0

while IFS= read -r -d '' path; do
    base=$(basename -- "$path")
    name="${base%.*}"
    target="$output_dir/$name.png"

    # A PNG in the source set is already a candidate for output, so converting it
    # onto itself is pointless and can destroy the original.
    if [ "$path" = "$target" ]; then
        skipped=$((skipped + 1))
        continue
    fi

    if [ -e "$target" ]; then
        log "conflict: '$name.png' already exists, skipping '$base'"
        conflicts=$((conflicts + 1))
        continue
    fi

    if [ "$mode" = "background" ]; then
        if [ "$fit" -eq 1 ]; then
            # Scale to fit inside the screen, then centre on a black canvas.
            geometry=(-resize 256x192 -background black -gravity center -extent 256x192)
        else
            # The trailing ! forces the exact size and ignores the aspect ratio.
            geometry=(-resize '256x192!')
        fi
    else
        geometry=(-resize "x$height")
    fi

    if [ "$dry_run" -eq 1 ]; then
        log "would convert: $base -> $name.png"
        converted=$((converted + 1))
        continue
    fi

    # -background none keeps sprite transparency, -strip drops metadata that the
    # DS has no use for.
    "$image_command" "$path" -background none "${geometry[@]}" -strip "$target"
    log "converted: $base -> $name.png"
    converted=$((converted + 1))
done < <(find "$source_dir" -maxdepth 1 -type f \
    \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.gif' \
    -o -iname '*.bmp' -o -iname '*.tiff' -o -iname '*.webp' -o -iname '*.pnm' \
    -o -iname '*.heic' \) -print0)

log "$mode: converted $converted image(s), skipped $skipped, $conflicts conflict(s) into $output_dir"
[ "$conflicts" -eq 0 ]
