#!/bin/bash
# Shared helpers for the vnds-converter scripts. Sourced, never executed.

set -euo pipefail

# Everything human readable goes to stderr, so a script can still be used in a
# pipeline without conversation mixing into the data.
log() {
    printf '%s\n' "$*" >&2
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

# Check for a tool up front with an install hint, rather than dying halfway
# through a batch with a bare "command not found".
need() {
    local command_name="$1" hint="${2:-}"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        if [ -n "$hint" ]; then
            die "$command_name is required ($hint)"
        fi
        die "$command_name is required"
    fi
}

# ImageMagick 7 ships "magick", Debian and older builds ship "convert".
image_tool() {
    if command -v magick >/dev/null 2>&1; then
        printf 'magick'
    elif command -v convert >/dev/null 2>&1; then
        printf 'convert'
    else
        die "ImageMagick is required (apt install imagemagick)"
    fi
}

# Print the comment header of a script as its help text.
usage_from_header() {
    sed -n '2,20p' "$1" | sed -n '/^#/p' | sed 's/^#\{1,\} \{0,1\}//'
}
