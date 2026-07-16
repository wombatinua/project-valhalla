#!/bin/sh

# Interactive launcher for Project Valhalla Prompt Composer.
# POSIX sh is sufficient; no bash-specific features are used.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP="$SCRIPT_DIR/app.py"
DATABASE="$SCRIPT_DIR/database.json"
PYTHON_BIN=${PYTHON_BIN:-python3}

die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

read_value() {
    prompt=$1
    printf '%s' "$prompt"
    if ! IFS= read -r REPLY; then
        printf '\n'
        exit 1
    fi
}

is_integer() {
    value=$1
    case "$value" in
        -*) digits=${value#-} ;;
        *) digits=$value ;;
    esac
    case "$digits" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

ask_count() {
    while :; do
        if [ "$MODE" = photoshoot ]; then
            read_value 'Images per photoshoot [10]: '
        else
            read_value 'Random image count [10]: '
        fi
        COUNT=${REPLY:-10}
        case "$COUNT" in
            *[!0-9]*|'') printf 'Enter a positive whole number.\n' ;;
            *)
                if [ "$COUNT" -ge 1 ]; then
                    return
                fi
                printf 'Count must be at least 1.\n'
                ;;
        esac
    done
}

ask_photoshoot_count() {
    while :; do
        read_value 'Number of different photoshoots [1]: '
        PHOTOSHOOTS=${REPLY:-1}
        case "$PHOTOSHOOTS" in
            *[!0-9]*|'') printf 'Enter a positive whole number.\n' ;;
            *)
                if [ "$PHOTOSHOOTS" -ge 1 ]; then
                    return
                fi
                printf 'Number of photoshoots must be at least 1.\n'
                ;;
        esac
    done
}

ask_optional_prompt_seed() {
    while :; do
        read_value 'Prompt seed [blank = random]: '
        PROMPT_SEED=$REPLY
        if [ -z "$PROMPT_SEED" ] || is_integer "$PROMPT_SEED"; then
            return
        fi
        printf 'Enter a whole number or leave it blank.\n'
    done
}

ask_optional_inference_seed() {
    while :; do
        read_value 'Inference seed [blank = random for every image]: '
        INFERENCE_SEED=$REPLY
        if [ -z "$INFERENCE_SEED" ]; then
            return
        fi
        case "$INFERENCE_SEED" in
            *[!0-9]*) printf 'Enter a whole number from 0 to 18446744073709551615, or leave it blank.\n' ;;
            *)
                if "$PYTHON_BIN" -c 'import sys; n=int(sys.argv[1]); raise SystemExit(not 0 <= n < 2**64)' "$INFERENCE_SEED" 2>/dev/null; then
                    return
                fi
                printf 'Inference seed is outside the accepted range.\n'
                ;;
        esac
    done
}

ask_nsfw_percent() {
    while :; do
        read_value "NSFW final percentage [blank = database default: $DEFAULT_NSFW_PERCENT]: "
        NSFW_PERCENT=$REPLY
        if [ -z "$NSFW_PERCENT" ]; then
            return
        fi
        if "$PYTHON_BIN" -c 'import sys; n=float(sys.argv[1]); raise SystemExit(not 0 <= n <= 100)' "$NSFW_PERCENT" 2>/dev/null; then
            return
        fi
        printf 'Enter a number from 0 through 100, or leave it blank.\n'
    done
}

ask_plateau_percent() {
    while :; do
        read_value "Explicit plateau percentage [blank = database default: $DEFAULT_PLATEAU_PERCENT]: "
        PLATEAU_PERCENT=$REPLY
        if [ -z "$PLATEAU_PERCENT" ]; then
            candidate=$DEFAULT_PLATEAU_PERCENT
        else
            candidate=$PLATEAU_PERCENT
        fi
        if ! "$PYTHON_BIN" -c 'import sys; n=float(sys.argv[1]); raise SystemExit(not 0 <= n <= 100)' "$candidate" 2>/dev/null; then
            printf 'Enter a number from 0 through 100, or leave it blank.\n'
            continue
        fi
        effective_nsfw=${NSFW_PERCENT:-$DEFAULT_NSFW_PERCENT}
        if "$PYTHON_BIN" -c 'import sys; plateau=float(sys.argv[1]); nsfw=float(sys.argv[2]); raise SystemExit(plateau > nsfw)' "$candidate" "$effective_nsfw" 2>/dev/null; then
            return
        fi
        printf 'The plateau percentage cannot exceed the NSFW final percentage (%s).\n' "$effective_nsfw"
    done
}

confirm_launch() {
    read_value 'Launch now? [Y/n]: '
    case "$REPLY" in
        n|N|no|NO|No) printf 'Cancelled.\n'; exit 0 ;;
        *) return ;;
    esac
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python executable not found: $PYTHON_BIN"
[ -f "$APP" ] || die "Application not found: $APP"
[ -f "$DATABASE" ] || die "Database not found: $DATABASE"

SETTINGS_SUMMARY=$(
    "$PYTHON_BIN" -c '
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
d = json.loads(p.read_text(encoding="utf-8"))
s = d["settings"]
print("ComfyUI: {}".format(s["comfy_url"]))
print("Workflow: {}".format(s["workflow_file"]))
print("Output: {}".format(s["output_dir"]))
' "$DATABASE" 2>/dev/null
) || die "Could not read settings from database.json"

DEFAULT_NSFW_PERCENT=$(
    "$PYTHON_BIN" -c '
import json, pathlib, sys
d = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(d["settings"].get("photoshoot_progression", {}).get("nsfw_final_percent", 30))
' "$DATABASE" 2>/dev/null
) || die "Could not read the default NSFW percentage"

DEFAULT_PLATEAU_PERCENT=$(
    "$PYTHON_BIN" -c '
import json, pathlib, sys
d = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(d["settings"].get("photoshoot_progression", {}).get("explicit_plateau_percent", 0))
' "$DATABASE" 2>/dev/null
) || die "Could not read the default explicit plateau percentage"

printf '\nProject Valhalla Prompt Composer\n'
printf '%s\n' '---------------------------------'
printf '%s\n\n' "$SETTINGS_SUMMARY"
printf '%s\n' 'Choose an action:'
printf '%s\n' '  1) Generate images'
printf '%s\n' '  2) Dry run (prompts only)'
printf '%s\n' '  3) Capture latest ComfyUI workflow'
printf '%s\n' '  4) Show app help'
printf '%s\n' '  5) Exit'

while :; do
    read_value 'Selection [1]: '
    case "${REPLY:-1}" in
        1) COMMAND=generate; break ;;
        2) COMMAND=dry-run; break ;;
        3) COMMAND=capture; break ;;
        4) exec "$PYTHON_BIN" "$APP" --help ;;
        5) exit 0 ;;
        *) printf 'Choose 1, 2, 3, 4, or 5.\n' ;;
    esac
done

if [ "$COMMAND" = capture ]; then
    read_value 'Replace workflow.json if it already exists? [y/N]: '
    FORCE_CAPTURE=false
    case "$REPLY" in
        y|Y|yes|YES|Yes) FORCE_CAPTURE=true ;;
    esac

    printf '\nCommand: capture\n'
    printf 'Replace existing workflow: %s\n\n' "$FORCE_CAPTURE"
    confirm_launch

    set -- "$PYTHON_BIN" "$APP" capture
    if [ "$FORCE_CAPTURE" = true ]; then
        set -- "$@" --force
    fi
    exec "$@"
fi

printf '\nChoose generation mode:\n'
printf '%s\n' '  1) Photoshoot (fixed model/outfit/location with progressive stages)'
printf '%s\n' '  2) Random (independent scene for every image)'
while :; do
    read_value 'Mode [1]: '
    case "${REPLY:-1}" in
        1) MODE=photoshoot; break ;;
        2) MODE=random; break ;;
        *) printf 'Choose 1 or 2.\n' ;;
    esac
done

PHOTOSHOOTS=1
if [ "$MODE" = photoshoot ]; then
    ask_photoshoot_count
fi
ask_count
ask_optional_prompt_seed
ask_optional_inference_seed
NSFW_PERCENT=
PLATEAU_PERCENT=
if [ "$MODE" = photoshoot ]; then
    printf 'The final percentage advances through topless, nude, and explicit stages.\n'
    printf 'The plateau is the final fully explicit part: rear views, close-ups, then masturbation.\n'
    printf 'Use 0 to disable the forced NSFW ending.\n'
    ask_nsfw_percent
    ask_plateau_percent
fi

printf '\nLaunch summary\n'
printf '%s\n' '--------------'
printf 'Command: %s\n' "$COMMAND"
printf 'Mode: %s\n' "$MODE"
if [ "$MODE" = photoshoot ]; then
    printf 'Photoshoots: %s\n' "$PHOTOSHOOTS"
    printf 'Images per photoshoot: %s\n' "$COUNT"
    printf 'Total images: %s\n' "$((PHOTOSHOOTS * COUNT))"
else
    printf 'Count: %s\n' "$COUNT"
fi
if [ -n "$PROMPT_SEED" ]; then
    printf 'Prompt seed: %s\n' "$PROMPT_SEED"
else
    printf 'Prompt seed: random\n'
fi
if [ -n "$INFERENCE_SEED" ]; then
    printf 'Inference seed: %s (fixed for the batch)\n' "$INFERENCE_SEED"
else
    printf 'Inference seed: random for every image\n'
fi
if [ "$MODE" = photoshoot ]; then
    if [ -n "$NSFW_PERCENT" ]; then
        printf 'NSFW final percentage: %s (command override)\n' "$NSFW_PERCENT"
    else
        printf 'NSFW final percentage: %s (database default)\n' "$DEFAULT_NSFW_PERCENT"
    fi
    if [ -n "$PLATEAU_PERCENT" ]; then
        printf 'Explicit plateau percentage: %s (command override)\n' "$PLATEAU_PERCENT"
    else
        printf 'Explicit plateau percentage: %s (database default)\n' "$DEFAULT_PLATEAU_PERCENT"
    fi
fi
printf '\n'
confirm_launch

set -- "$PYTHON_BIN" "$APP" "$COMMAND" --mode "$MODE" --count "$COUNT"
if [ "$MODE" = photoshoot ]; then
    set -- "$@" --photoshoots "$PHOTOSHOOTS"
fi
if [ -n "$PROMPT_SEED" ]; then
    set -- "$@" --prompt-seed "$PROMPT_SEED"
fi
if [ -n "$INFERENCE_SEED" ]; then
    set -- "$@" --inference-seed "$INFERENCE_SEED"
fi
if [ -n "$NSFW_PERCENT" ]; then
    set -- "$@" --nsfw-percent "$NSFW_PERCENT"
fi
if [ -n "$PLATEAU_PERCENT" ]; then
    set -- "$@" --plateau-percent "$PLATEAU_PERCENT"
fi

printf '\n'
exec "$@"
