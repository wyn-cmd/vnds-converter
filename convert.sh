#!/bin/bash
# Run the whole conversion for one game: images, audio, then filename cleanup.
#
# The stages run in this order on purpose. Images and audio are converted from
# your source folders into the game folder, and only then are spaces stripped
# from the results, so the finished tree is DS ready and you never lose track of
# which file is which while converting.
#
# What this does not do: it will not write your VNDS script, and it will not
# create the font, icon or thumbnail. Those come from your own game.
#
# Usage: convert.sh [options] GAME_DIR
#
#   --background DIR        images to force onto the 256x192 screen
#   --foreground DIR        sprite images to scale to a fixed height
#   --sound DIR             audio to turn into MP3
#   --title NAME            write info.txt as title=NAME when it is missing
#   --foreground-height N   sprite height, default 180
#   --bitrate B             MP3 bitrate, default 192k
#   --fit                   letterbox backgrounds instead of stretching them
#   --keep-names            do not strip spaces from the produced filenames
#   --dry-run               show what would happen, change nothing
#   -h, --help              this text
#
# Example:
#   convert.sh --title "Deers and Deckards" \
#       --background ~/work/backgrounds --foreground ~/work/sprites \
#       --sound ~/work/audio ~/vnds-games/deers

source "$(dirname "$0")/lib/common.sh"

background_src=""
foreground_src=""
sound_src=""
title=""
foreground_height=180
bitrate="192k"
fit=0
keep_names=0
dry_run=0
game_dir=""

while [ $# -gt 0 ]; do
    case "$1" in
        --background)         background_src="${2:-}"; shift ;;
        --foreground)         foreground_src="${2:-}"; shift ;;
        --sound)              sound_src="${2:-}"; shift ;;
        --title)              title="${2:-}"; shift ;;
        --foreground-height)  foreground_height="${2:-}"; shift ;;
        --bitrate)            bitrate="${2:-}"; shift ;;
        --fit)                fit=1 ;;
        --keep-names)         keep_names=1 ;;
        -n|--dry-run)         dry_run=1 ;;
        -h|--help)            usage_from_header "$0"; exit 0 ;;
        -*)                   die "unknown option: $1" ;;
        *)                    game_dir="$1" ;;
    esac
    shift
done

[ -n "$game_dir" ] || die "usage: $(basename "$0") [options] GAME_DIR"
[ -n "$background_src$foreground_src$sound_src" ] || die "give at least one of --background, --foreground or --sound"

for source_dir in "$background_src" "$foreground_src" "$sound_src"; do
    [ -z "$source_dir" ] && continue
    [ -d "$source_dir" ] || die "'$source_dir' is not a directory"
done

here=$(cd "$(dirname "$0")" && pwd)

dry_args=()
[ "$dry_run" -eq 1 ] && dry_args=(--dry-run)

failed=0
run_stage() {
    local label="$1"
    shift
    log ""
    log "== $label"
    # Inside an if, a non-zero status is caught instead of ending the script, so
    # one bad stage does not hide the state of the others.
    if "$@"; then
        return 0
    fi
    log "   stage reported a problem: $label"
    failed=$((failed + 1))
}

if [ "$dry_run" -eq 0 ]; then
    mkdir -p -- "$game_dir/background" "$game_dir/foreground" "$game_dir/sound"
fi

if [ -n "$background_src" ]; then
    run_stage "backgrounds onto 256x192" \
        "$here/scripts/images.sh" --mode background "${dry_args[@]+"${dry_args[@]}"}" \
        ${fit:+--fit} "$background_src" "$game_dir/background"
fi

if [ -n "$foreground_src" ]; then
    run_stage "sprites scaled to height $foreground_height" \
        "$here/scripts/images.sh" --mode foreground --height "$foreground_height" \
        "${dry_args[@]+"${dry_args[@]}"}" "$foreground_src" "$game_dir/foreground"
fi

if [ -n "$sound_src" ]; then
    run_stage "audio converted for the DS" \
        "$here/scripts/audio.sh" --bitrate "$bitrate" "${dry_args[@]+"${dry_args[@]}"}" \
        "$sound_src" "$game_dir/sound"
fi

if [ "$keep_names" -eq 0 ]; then
    for produced in background foreground sound; do
        [ -d "$game_dir/$produced" ] || continue
        run_stage "stripping spaces from $produced/" \
            "$here/scripts/rename.sh" "${dry_args[@]+"${dry_args[@]}"}" "$game_dir/$produced"
    done
fi

if [ -n "$title" ] && [ ! -e "$game_dir/info.txt" ]; then
    if [ "$dry_run" -eq 1 ]; then
        log ""
        log "would write info.txt as title=$title"
    else
        printf 'title=%s\n' "$title" > "$game_dir/info.txt"
        log ""
        log "wrote $game_dir/info.txt"
    fi
fi

log ""
log "game folder: $game_dir"
log "still needed: script/, default.ttf, icon.png, thumbnail.png"
if [ "$failed" -gt 0 ]; then
    log "$failed stage(s) reported a problem"
    exit 1
fi
log "all stages finished"
