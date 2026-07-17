#!/bin/sh

# Minimal bootstrap for the Python wizard.
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP="$SCRIPT_DIR/app.py"
PYTHON_BIN=${PYTHON_BIN:-python3}

die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

header() {
    if [ -t 1 ]; then
        printf '\033[2J\033[H'
    fi
    printf 'Project Valhalla\n\n%s\n\n' "$1"
}

find_tool() {
    name=$1
    shift
    if command -v "$name" >/dev/null 2>&1; then
        command -v "$name"
        return
    fi
    for candidate in "$@"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
    return 1
}

ensure_requests() {
    if "$PYTHON_BIN" -c 'import requests' >/dev/null 2>&1; then
        return
    fi
    header 'Installing requests'
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        "$PYTHON_BIN" -m ensurepip --upgrade || die "Could not initialize pip"
    fi
    "$PYTHON_BIN" -m pip install requests || die "Could not install requests"
}

ensure_fzf() {
    FZF_BIN=$(find_tool fzf \
        /home/linuxbrew/.linuxbrew/bin/fzf \
        /opt/homebrew/bin/fzf \
        /usr/local/bin/fzf 2>/dev/null || true)
    if [ -n "$FZF_BIN" ]; then
        export FZF_BIN
        return
    fi
    BREW_BIN=$(find_tool brew \
        /home/linuxbrew/.linuxbrew/bin/brew \
        /opt/homebrew/bin/brew 2>/dev/null || true)
    if [ -n "$BREW_BIN" ]; then
        header 'Installing FZF'
        "$BREW_BIN" install fzf || true
        FZF_BIN=$(find_tool fzf \
            /home/linuxbrew/.linuxbrew/bin/fzf \
            /opt/homebrew/bin/fzf \
            /usr/local/bin/fzf 2>/dev/null || true)
        if [ -n "$FZF_BIN" ]; then
            export FZF_BIN
        fi
    fi
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python not found: $PYTHON_BIN"
[ -f "$APP" ] || die "Application not found: $APP"

ensure_requests
ensure_fzf
exec "$PYTHON_BIN" "$APP" wizard
