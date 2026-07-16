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

clear_screen() {
    # Avoid escape sequences when output is redirected or used by automated tests.
    if [ -t 1 ]; then
        printf '\033[2J\033[H'
    fi
}

screen_header() {
    clear_screen
    printf 'Project Valhalla Prompt Composer\n'
    printf '%s\n\n' '---------------------------------'
    printf '%s\n\n' "$1"
}

ensure_requests() {
    if "$PYTHON_BIN" -c 'import requests' >/dev/null 2>&1; then
        return
    fi

    screen_header 'Dependency setup'
    printf 'Python package "requests" is missing for: %s\n' "$PYTHON_BIN"
    printf 'Installing it now with pip...\n\n'
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        printf 'pip is unavailable; bootstrapping it with ensurepip...\n\n'
        "$PYTHON_BIN" -m ensurepip --upgrade || \
            die "Could not initialize pip for $PYTHON_BIN"
    fi
    if ! "$PYTHON_BIN" -m pip install requests; then
        die "Could not install requests. Install it manually with: $PYTHON_BIN -m pip install requests"
    fi
    "$PYTHON_BIN" -c 'import requests' >/dev/null 2>&1 || \
        die "requests was installed but cannot be imported by $PYTHON_BIN"
    printf '\nDependency installed successfully.\n'
}

find_fzf() {
    if command -v fzf >/dev/null 2>&1; then
        command -v fzf
        return
    fi
    for candidate in \
        /home/linuxbrew/.linuxbrew/bin/fzf \
        /opt/homebrew/bin/fzf \
        /usr/local/bin/fzf
    do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
    return 1
}

find_brew() {
    if command -v brew >/dev/null 2>&1; then
        command -v brew
        return
    fi
    for candidate in \
        /home/linuxbrew/.linuxbrew/bin/brew \
        /opt/homebrew/bin/brew \
        /usr/local/bin/brew
    do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
    return 1
}

ensure_fzf() {
    FZF_BIN=$(find_fzf 2>/dev/null || true)
    if [ -n "$FZF_BIN" ]; then
        export FZF_BIN
        return
    fi

    BREW_BIN=$(find_brew 2>/dev/null || true)
    if [ -z "$BREW_BIN" ]; then
        return
    fi

    screen_header 'Optional TUI setup'
    printf 'Installing fzf with Homebrew for searchable Director menus...\n\n'
    if "$BREW_BIN" install fzf; then
        FZF_BIN=$(find_fzf 2>/dev/null || true)
        if [ -n "$FZF_BIN" ]; then
            export FZF_BIN
            printf '\nfzf installed successfully.\n'
        fi
    else
        printf '\nfzf installation failed; numbered Director menus will be used instead.\n'
    fi
}

read_value() {
    prompt=$1
    printf '%s' "$prompt"
    if ! IFS= read -r REPLY; then
        printf '\n'
        exit 1
    fi
}

fzf_choice() {
    prompt=$1
    default=$2
    shift 2
    if [ -z "${FZF_BIN:-}" ] || [ ! -t 0 ] || [ ! -t 1 ]; then
        return 1
    fi
    rows="0\t↩️ Default — $default\n"
    for pair in "$@"; do
        value=${pair%%|*}
        label=${pair#*|}
        rows="${rows}${value}\t${label}\n"
    done
    selected=$(printf '%b' "$rows" | "$FZF_BIN" \
        --height=85% --layout=reverse --border=rounded --info=inline \
        --delimiter='\t' --with-nth=2.. --prompt="$prompt › " \
        --header='Type to search • Enter select • Esc use default') || selected=
    if [ -z "$selected" ]; then
        REPLY=$default
    else
        REPLY=${selected%%	*}
        [ "$REPLY" = 0 ] && REPLY=$default
    fi
    return 0
}

using_fzf() {
    [ -n "${FZF_BIN:-}" ] && [ -t 0 ] && [ -t 1 ]
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
        read_value 'Inference seed [fixed for every image; blank = random per image]: '
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
    if fzf_choice 'Confirmation' y 'y|🚀 Launch now' 'n|❌ Cancel'; then
        case "$REPLY" in
            n) printf 'Cancelled.\n'; exit 0 ;;
            *) return ;;
        esac
    fi
    read_value 'Launch now? [Y/n]: '
    case "$REPLY" in
        n|N|no|NO|No) printf 'Cancelled.\n'; exit 0 ;;
        *) return ;;
    esac
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python executable not found: $PYTHON_BIN"
[ -f "$APP" ] || die "Application not found: $APP"
[ -f "$DATABASE" ] || die "Database not found: $DATABASE"
ensure_requests
ensure_fzf

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

screen_header 'Main menu'
printf '%s\n\n' "$SETTINGS_SUMMARY"
if ! using_fzf; then
    printf '%s\n' 'Choose an action:'
    printf '%s\n' '  1) Generate images'
    printf '%s\n' '  2) Dry run (prompts only)'
    printf '%s\n' '  3) Capture latest ComfyUI workflow'
    printf '%s\n' '  4) Show app help'
    printf '%s\n' '  5) Exit'
fi

if fzf_choice 'Main menu' 1 '1|🚀 Generate images' '2|🧪 Dry run (prompts only)' '3|📥 Capture latest ComfyUI workflow' '4|❓ Show app help' '5|🚪 Exit'; then
    selection=$REPLY
else
    while :; do
        read_value 'Selection [1]: '
        selection=${REPLY:-1}
        case "$selection" in 1|2|3|4|5) break ;; *) printf 'Choose 1, 2, 3, 4, or 5.\n' ;; esac
    done
fi
case "$selection" in
    1) COMMAND=generate ;;
    2) COMMAND=dry-run ;;
    3) COMMAND=capture ;;
    4) exec "$PYTHON_BIN" "$APP" --help ;;
    5) exit 0 ;;
esac

if [ "$COMMAND" = capture ]; then
    screen_header 'Capture ComfyUI workflow'
    if fzf_choice 'Capture workflow' n 'y|♻️ Replace existing workflow.json' 'n|↩️ Keep existing workflow.json'; then :; else
        read_value 'Replace workflow.json if it already exists? [y/N]: '
    fi
    FORCE_CAPTURE=false
    case "$REPLY" in
        y|Y|yes|YES|Yes) FORCE_CAPTURE=true ;;
    esac

    screen_header 'Confirm capture'
    printf 'Command: capture\n'
    printf 'Replace existing workflow: %s\n\n' "$FORCE_CAPTURE"
    confirm_launch

    set -- "$PYTHON_BIN" "$APP" capture
    if [ "$FORCE_CAPTURE" = true ]; then
        set -- "$@" --force
    fi
    exec "$@"
fi

screen_header 'Generation mode'
if ! using_fzf; then
    printf 'Choose generation mode:\n'
    printf '%s\n' '  1) Photoshoot (fixed model/outfit/location with progressive stages)'
    printf '%s\n' '  2) Random (independent scene for every image)'
fi
if fzf_choice 'Generation mode' 1 '1|📸 Photoshoot — connected SET and progression' '2|🎲 Random — independent scene per image'; then :; else
    while :; do read_value 'Mode [1]: '; case "${REPLY:-1}" in 1|2) break ;; *) printf 'Choose 1 or 2.\n' ;; esac; done
fi
case "${REPLY:-1}" in 1) MODE=photoshoot ;; 2) MODE=random ;; esac

screen_header 'Content mode'
if ! using_fzf; then
    printf '%s\n' '  1) Normal / progressive content'
    printf '%s\n' '  2) Full XXX from the first image'
fi
if fzf_choice 'Content mode' 1 '1|🎞️ Normal / progressive content' '2|🔞 Full XXX from the first image'; then :; else
    while :; do read_value 'Content [1]: '; case "${REPLY:-1}" in 1|2) break ;; *) printf 'Choose 1 or 2.\n' ;; esac; done
fi
case "${REPLY:-1}" in 1) XXX_ONLY=false ;; 2) XXX_ONLY=true ;; esac

screen_header "Director's Desk"
if ! using_fzf; then
    printf '%s\n' 'Would you like to review and direct the complete storyboard before launch?'
    printf '%s\n' '  1) Auto — trust the director and continue'
    printf '%s\n' '  2) Interactive — review, reroll, and edit individual shots'
fi
if fzf_choice "Director's Desk" 1 '1|🤖 Auto — trust the director and continue' '2|🎬 Interactive — review and edit storyboard'; then :; else
    while :; do read_value 'Storyboard [1]: '; case "${REPLY:-1}" in 1|2) break ;; *) printf 'Choose 1 or 2.\n' ;; esac; done
fi
case "${REPLY:-1}" in 1) REVIEW_STORYBOARD=false ;; 2) REVIEW_STORYBOARD=true ;; esac

PHOTOSHOOTS=1
screen_header 'Batch size'
if [ "$MODE" = photoshoot ]; then
    ask_photoshoot_count
fi
ask_count

screen_header 'Random seeds'
ask_optional_prompt_seed
ask_optional_inference_seed
NSFW_PERCENT=
PLATEAU_PERCENT=
if [ "$MODE" = photoshoot ] && [ "$XXX_ONLY" = false ]; then
    screen_header 'Photoshoot progression'
    printf 'The final percentage advances through topless, nude, and explicit stages.\n'
    printf 'The plateau is the final fully explicit part: rear views, close-ups, then masturbation.\n'
    printf 'Use 0 to disable the forced NSFW ending.\n'
    ask_nsfw_percent
    ask_plateau_percent
fi

screen_header 'Launch summary'
printf '%s\n' '--------------'
printf 'Command: %s\n' "$COMMAND"
printf 'Mode: %s\n' "$MODE"
if [ "$XXX_ONLY" = true ]; then
    printf 'Content: full XXX from the first image\n'
else
    printf 'Content: normal / progressive\n'
fi
if [ "$REVIEW_STORYBOARD" = true ]; then
    printf "Storyboard: interactive Director's Desk\n"
else
    printf 'Storyboard: automatic\n'
fi
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
if [ "$MODE" = photoshoot ] && [ "$XXX_ONLY" = false ]; then
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
if [ "$XXX_ONLY" = true ]; then
    set -- "$@" --xxx-only
fi
if [ "$REVIEW_STORYBOARD" = true ]; then
    set -- "$@" --review-storyboard
fi

clear_screen
exec "$@"
