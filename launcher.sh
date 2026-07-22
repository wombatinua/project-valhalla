#!/bin/sh

# Valhalla Photo Studio Web UI bootstrap.
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SERVER="$SCRIPT_DIR/server.py"
PYTHON_BIN=${PYTHON_BIN:-python3}

die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

ensure_dependency() {
    module=$1
    package=$2
    if "$PYTHON_BIN" -c "import $module" >/dev/null 2>&1; then
        return
    fi
    printf 'Installing required Python dependency: %s\n' "$package"
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        "$PYTHON_BIN" -m ensurepip --upgrade || die "Could not initialize pip"
    fi
    "$PYTHON_BIN" -m pip install "$package" || die "Could not install $package"
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python not found: $PYTHON_BIN"
[ -f "$SERVER" ] || die "Application not found: $SERVER"

ensure_dependency requests requests
ensure_dependency PIL Pillow
exec "$PYTHON_BIN" "$SERVER"
