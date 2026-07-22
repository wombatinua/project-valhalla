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

is_project_server() {
    process_id=$1
    process_dir="/proc/$process_id"
    [ -r "$process_dir/comm" ] && [ -r "$process_dir/cmdline" ] || return 1
    case "$(sed -n '1p' "$process_dir/comm" 2>/dev/null)" in
        python*) ;;
        *) return 1 ;;
    esac
    if tr '\000' '\n' < "$process_dir/cmdline" 2>/dev/null | grep -Fqx "$SERVER"; then
        return 0
    fi
    process_cwd=$(readlink -f "$process_dir/cwd" 2>/dev/null || true)
    [ "$process_cwd" = "$SCRIPT_DIR" ] || return 1
    tr '\000' '\n' < "$process_dir/cmdline" 2>/dev/null | grep -Fqx "server.py"
}

find_project_servers() {
    for process_dir in /proc/[0-9]*; do
        [ -d "$process_dir" ] || continue
        process_id=${process_dir##*/}
        [ "$process_id" = "$$" ] && continue
        if is_project_server "$process_id"; then
            printf '%s\n' "$process_id"
        fi
    done
}

stop_leftover_servers() {
    leftover_pids=$(find_project_servers)
    [ -n "$leftover_pids" ] || return 0

    printf 'Existing Valhalla server process%s found:\n' \
        "$([ "$(printf '%s\n' "$leftover_pids" | wc -l)" -eq 1 ] && printf '' || printf 'es')"
    for process_id in $leftover_pids; do
        ps -p "$process_id" -o pid=,etime=,args= 2>/dev/null || true
    done
    if [ ! -t 0 ]; then
        die "Cannot confirm stopping leftover server processes in a non-interactive session"
    fi
    printf 'Stop these processes before starting a new server? [y/N] '
    IFS= read -r reply
    case "$reply" in
        y|Y|yes|YES|Yes) ;;
        *) die "Startup cancelled; existing server processes were left running" ;;
    esac

    for process_id in $leftover_pids; do
        is_project_server "$process_id" && kill -TERM "$process_id" 2>/dev/null || true
    done
    attempts=0
    while [ "$attempts" -lt 20 ]; do
        survivors=""
        for process_id in $leftover_pids; do
            if is_project_server "$process_id"; then
                survivors="$survivors $process_id"
            fi
        done
        [ -z "$survivors" ] && return 0
        sleep 0.25
        attempts=$((attempts + 1))
    done
    printf 'Processes did not stop after 5 seconds; forcing shutdown.\n'
    for process_id in $survivors; do
        is_project_server "$process_id" && kill -KILL "$process_id" 2>/dev/null || true
    done
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python not found: $PYTHON_BIN"
[ -f "$SERVER" ] || die "Application not found: $SERVER"

stop_leftover_servers
ensure_dependency requests requests
ensure_dependency PIL Pillow
exec "$PYTHON_BIN" "$SERVER"
