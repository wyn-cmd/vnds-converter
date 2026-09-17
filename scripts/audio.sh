#!/bin/bash
# Convert audio into the MP3 that VNDS can decode.
#
# The DS build of VNDS wants MPEG-1 Layer 3 at 44100 Hz. Files that are already
# in that exact form are copied rather than re-encoded, because re-encoding an
# MP3 loses quality for nothing. Anything else, including MPEG-2 MP3s, VBR
# files, WAV, OGG and M4A, is converted.
#
# Embedded cover art is dropped with -vn: the DS cannot use it and it wastes
# space on the card. Source metadata is dropped for the same reason.
#
# Usage: audio.sh [--bitrate 192k] [--rate 44100] [--force]
#                 [--dry-run] SOURCE_DIR OUTPUT_DIR

source "$(dirname "$0")/../lib/common.sh"

bitrate="192k"
rate="44100"
force=0
dry_run=0
source_dir=""
output_dir=""

while [ $# -gt 0 ]; do
    case "$1" in
        --bitrate)  bitrate="${2:-}"; shift ;;
        --rate)     rate="${2:-}"; shift ;;
        -f|--force) force=1 ;;
        -n|--dry-run) dry_run=1 ;;
        -h|--help)  usage_from_header "$0"; exit 0 ;;
        -*)         die "unknown option: $1" ;;
        *)          if [ -z "$source_dir" ]; then source_dir="$1"; else output_dir="$1"; fi ;;
    esac
    shift
done

[ -n "$source_dir" ] || die "usage: $(basename "$0") [options] SOURCE_DIR OUTPUT_DIR"
[ -n "$output_dir" ] || die "usage: $(basename "$0") [options] SOURCE_DIR OUTPUT_DIR"
[ -d "$source_dir" ] || die "'$source_dir' is not a directory"

need ffmpeg "apt install ffmpeg"
need ffprobe "apt install ffmpeg"

if [ "$dry_run" -eq 0 ]; then
    mkdir -p -- "$output_dir"
fi

converted=0
copied=0
skipped=0
conflicts=0

# True when the file is already MPEG-1 Layer 3 at the wanted sample rate. An
# MPEG-2 file cannot reach 44100 Hz, so the sample rate is enough to tell them
# apart without parsing the frame header by hand.
is_ready_mp3() {
    local path="$1" probe codec sample_rate

    probe=$(ffprobe -v error -select_streams a:0 \
        -show_entries stream=codec_name,sample_rate -of default=noprint_wrappers=1 \
        -- "$path" 2>/dev/null) || return 1

    codec=$(printf '%s\n' "$probe" | sed -n 's/^codec_name=//p')
    sample_rate=$(printf '%s\n' "$probe" | sed -n 's/^sample_rate=//p')

    [ "$codec" = "mp3" ] && [ "$sample_rate" = "$rate" ]
}

while IFS= read -r -d '' path; do
    base=$(basename -- "$path")
    name="${base%.*}"
    target="$output_dir/$name.mp3"

    # Track whether the input is already an mp3. Note that "${base,,%.mp3}" does not
    # mean "lowercase, then strip the suffix": the pattern in ${var,,pattern} picks
    # which characters to lowercase, so it silently returns the name unchanged.
    is_mp3=0
    case "${base,,}" in
        *.mp3) is_mp3=1 ;;
        *.wav|*.ogg|*.oga|*.m4a|*.aac|*.flac|*.opus|*.wma|*.aiff|*.aif) ;;
        *)
            log "not audio, skipping: $base"
            skipped=$((skipped + 1))
            continue ;;
    esac

    if [ "$path" = "$target" ]; then
        skipped=$((skipped + 1))
        continue
    fi

    if [ -e "$target" ]; then
        log "conflict: '$name.mp3' already exists, skipping '$base'"
        conflicts=$((conflicts + 1))
        continue
    fi

    if [ "$force" -eq 0 ] && [ "$is_mp3" -eq 1 ] && is_ready_mp3 "$path"; then
        if [ "$dry_run" -eq 1 ]; then
            log "would copy: $base -> $name.mp3"
        else
            cp -- "$path" "$target"
            log "already MPEG-1 Layer 3 at ${rate} Hz, copied: $base"
        fi
        copied=$((copied + 1))
        continue
    fi

    if [ "$dry_run" -eq 1 ]; then
        log "would convert: $base -> $name.mp3"
        converted=$((converted + 1))
        continue
    fi

    ffmpeg -v error -nostdin -y -i "$path" \
        -vn -map_metadata -1 -c:a libmp3lame -b:a "$bitrate" -ar "$rate" \
        "$target"
    log "converted: $base -> $name.mp3"
    converted=$((converted + 1))
done < <(find "$source_dir" -maxdepth 1 -type f -print0)

log "audio: converted $converted, copied $copied, skipped $skipped, $conflicts conflict(s) into $output_dir"
[ "$conflicts" -eq 0 ]
