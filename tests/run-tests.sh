#!/bin/bash
# Exercise the pipeline against throwaway fixtures and check the results with
# identify and ffprobe. Needs ffmpeg and ImageMagick, the same tools the
# converter needs, so a green run also proves the tools are usable here.
#
# Usage: tests/run-tests.sh

set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

pass=0
fail=0

ok() {
    printf 'ok   %s\n' "$1"
    pass=$((pass + 1))
}

bad() {
    printf 'FAIL %s\n' "$1"
    fail=$((fail + 1))
}

# check <label> <actual> <expected>
check() {
    if [ "$2" = "$3" ]; then
        ok "$1"
    else
        bad "$1 (expected '$3', got '$2')"
    fi
}

say() {
    printf '\n--- %s\n' "$1"
}

for tool in ffmpeg ffprobe identify convert; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'skipping: %s is not installed\n' "$tool"
        exit 0
    fi
done

say "building fixtures"
mkdir -p "$work/src/background" "$work/src/foreground" "$work/src/sound"

convert -size 400x300 xc:navy "$work/src/background/wide shot.png"
convert -size 300x300 xc:green "$work/src/background/square.jpg"
convert -size 100x400 xc:red "$work/src/foreground/hero sprite.png"
convert -size 50x50 xc:none "$work/src/foreground/small.gif"

# A real MPEG-1 Layer 3 file at 44100, which the audio stage should copy rather
# than re-encode.
ffmpeg -v error -f lavfi -i "sine=frequency=440:duration=1" \
    -ar 44100 -c:a libmp3lame -b:a 192k "$work/src/sound/ready.mp3"
# A WAV with a space in its name, the usual state of a real source folder.
ffmpeg -v error -f lavfi -i "sine=frequency=880:duration=1" \
    "$work/src/sound/voice line.wav"
# 22050 Hz means MPEG-2, which the DS cannot decode, so this must be converted.
ffmpeg -v error -f lavfi -i "sine=frequency=660:duration=1" \
    -ar 22050 -c:a libmp3lame "$work/src/sound/lowrate.mp3"
printf 'not audio\n' > "$work/src/sound/notes.txt"

say "a dry run changes nothing"
"$here/convert.sh" --dry-run --title "Test Game" \
    --background "$work/src/background" \
    --foreground "$work/src/foreground" \
    --sound "$work/src/sound" "$work/game" >"$work/dry.log" 2>&1 || true
if [ -e "$work/game" ]; then
    bad "dry run created the game folder"
else
    ok "dry run created nothing"
fi
check "dry run left the sources alone" \
    "$(find "$work/src" -type f | wc -l)" "8"

say "full conversion"
if "$here/convert.sh" --title "Test Game" \
    --background "$work/src/background" \
    --foreground "$work/src/foreground" \
    --sound "$work/src/sound" "$work/game" >"$work/run.log" 2>&1; then
    ok "convert.sh finished cleanly"
else
    bad "convert.sh exited non zero"
    sed 's/^/     /' "$work/run.log"
fi

check "background forced to the screen size" \
    "$(identify -format '%wx%h' "$work/game/background/wideshot.png")" "256x192"
check "jpg background handled too" \
    "$(identify -format '%wx%h' "$work/game/background/square.png")" "256x192"
check "sprite scaled to the default height" \
    "$(identify -format '%h' "$work/game/foreground/herosprite.png")" "180"
check "sprite aspect ratio kept at 1:4" \
    "$(identify -format '%wx%h' "$work/game/foreground/herosprite.png")" "45x180"
check "small sprite scaled up to the same height" \
    "$(identify -format '%wx%h' "$work/game/foreground/small.png")" "180x180"

check "wav became mp3" \
    "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 "$work/game/sound/voiceline.mp3")" "mp3"
check "wav conversion resampled to 44100" \
    "$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$work/game/sound/voiceline.mp3")" "44100"
check "mpeg-2 mp3 was brought up to 44100" \
    "$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$work/game/sound/lowrate.mp3")" "44100"

if cmp -s "$work/src/sound/ready.mp3" "$work/game/sound/ready.mp3"; then
    ok "a ready mp3 was copied byte for byte"
else
    bad "a ready mp3 was re-encoded when it did not need to be"
fi

if cmp -s "$work/src/sound/lowrate.mp3" "$work/game/sound/lowrate.mp3"; then
    bad "the mpeg-2 file was copied instead of converted"
else
    ok "the mpeg-2 file was genuinely converted"
fi

if [ -e "$work/game/sound/notes.txt" ]; then
    bad "a non audio file ended up in sound/"
else
    ok "a non audio file was skipped"
fi

say "names, metadata and layout"
check "info.txt written from the title" \
    "$(cat "$work/game/info.txt")" "title=Test Game"
check "no spaces left anywhere in the game folder" \
    "$(find "$work/game" -name '* *' | wc -l)" "0"
check "the three asset folders exist" \
    "$(find "$work/game" -mindepth 1 -maxdepth 1 -type d | wc -l)" "3"

say "name collisions are refused, not silently overwritten"
mkdir -p "$work/collide"
convert -size 10x10 xc:white "$work/collide/dupe.png"
convert -size 20x20 xc:black "$work/collide/dupe.jpg"
if "$here/scripts/images.sh" --mode background \
    "$work/collide" "$work/collide-out" >"$work/collide.log" 2>&1; then
    bad "two sources mapping to one name should not exit cleanly"
else
    ok "the collision was reported as a failure"
fi
if grep -q "conflict" "$work/collide.log"; then
    ok "the collision was explained"
else
    bad "the collision was not explained"
fi
if [ -e "$work/collide-out/dupe.png" ]; then
    ok "the first file still produced its output"
else
    bad "neither file produced output"
fi

say "the rename stage"
mkdir -p "$work/names"
touch "$work/names/one two three.png" "$work/names/simple.png"
"$here/scripts/rename.sh" --dry-run "$work/names" >"$work/rename-dry.log" 2>&1
if [ -e "$work/names/one two three.png" ]; then
    ok "a rename dry run leaves the file in place"
else
    bad "a rename dry run moved the file"
fi
"$here/scripts/rename.sh" "$work/names" >"$work/rename.log" 2>&1
check "the real rename collapsed the spaces" \
    "$(ls "$work/names")" "onetwothree.png
simple.png"

say "the repository ships no media"
if "$here/scripts/check-no-media.sh" >"$work/media.log" 2>&1; then
    ok "no artwork, audio, font or save file has leaked in"
else
    bad "media found in the repo"
    sed 's/^/     /' "$work/media.log"
fi

say "the Ren'Py to VNDS script converter"
if command -v python3 >/dev/null 2>&1; then
    if python3 "$here/tests/test_renpy_to_vnds.py" >"$work/renpy.log" 2>&1; then
        passed=$(grep -c '\.\.\. ok' "$work/renpy.log" || true)
        ok "$passed converter tests passed"
    else
        bad "converter tests failed"
        tail -25 "$work/renpy.log" | sed 's/^/     /'
    fi
else
    printf 'skipping: python3 is not installed\n'
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
