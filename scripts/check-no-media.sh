#!/bin/bash
# Fail if any media or other non source file has found its way into the repo.
#
# This project ships scripts and instructions only. The games it was written for
# belong to their authors, and none of their art, audio, fonts or save files can
# be redistributed from here. Run this before every commit, and in the test
# suite, so a stray asset cannot ride along by accident.
#
# Usage: scripts/check-no-media.sh

set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)

# Extensions that must never appear in this repository.
media_pattern='\.(png|jpg|jpeg|gif|bmp|webp|tif|tiff|heic|pnm|ico|svg|mp3|wav|ogg|oga|m4a|aac|flac|opus|wma|aiff|aif|mp4|mkv|avi|mov|webm|ttf|otf|woff|woff2|hex|bin|rom|nds|sav|dsv|pk5|pk4|bnk|zip|7z|rar|pyc|rpyc|scr)$'

found=0
while IFS= read -r -d '' path; do
    case "$path" in
        */.git/*) continue ;;
        # Python build output is gitignored and shows up merely from running the
        # converter or its tests. Flagging it would fail this check for a reason
        # that has nothing to do with what must not be published.
        */__pycache__/*) continue ;;
    esac
    if printf '%s' "$path" | grep -qiE "$media_pattern"; then
        printf 'media or binary in the repo: %s\n' "${path#"$root"/}"
        found=$((found + 1))
    fi
done < <(find "$root" -type f -print0)

# The .scr extension is handled above, but say it separately because it is the
# output format rather than an input, and a converted script is still not ours.
if [ "$found" -gt 0 ]; then
    printf '\n%d file(s) that must not be published. Remove them before committing.\n' "$found"
    exit 1
fi

printf 'no media in the repo, only source and docs\n'
