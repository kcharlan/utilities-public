#!/bin/bash
set -euo pipefail

TOOL_NAME="apple-health-extract"
PROJECT_DIR_ENV_NAME="APPLE_HEALTH_EXTRACT_PROJECT_DIR"
RUNTIME_HOME_ENV_NAME="APPLE_HEALTH_EXTRACT_HOME"
EXPECTED_SCRIPT="extract_workout_stats.py"

usage() {
    cat <<'EOF'
Usage: run.sh [--check] [extractor arguments...]

Launch the Apple Health workout extractor from its project environment.

Project directory resolution, in priority order:
  1. APPLE_HEALTH_EXTRACT_PROJECT_DIR
  2. The directory containing this wrapper, when it contains the project
  3. First line of ${APPLE_HEALTH_EXTRACT_HOME:-~/.apple-health-extract}/project-dir

Options:
  --check   Validate configuration and required files without running extraction.
  -h, --help
            Show this help without creating local configuration.

The project-dir file is plain text containing one absolute path. It is never
sourced or evaluated as shell code.
EOF
}

fail() {
    printf '%s: ERROR: %s\n' "$TOOL_NAME" "$*" >&2
    exit 2
}

runtime_home() {
    if [[ -n "${APPLE_HEALTH_EXTRACT_HOME:-}" ]]; then
        printf '%s\n' "$APPLE_HEALTH_EXTRACT_HOME"
        return
    fi
    [[ -n "${HOME:-}" ]] || fail "HOME is not set; set $RUNTIME_HOME_ENV_NAME explicitly."
    printf '%s/.apple-health-extract\n' "$HOME"
}

read_project_dir_file() {
    local config_file="$1"
    local candidate=""
    local line=""
    local line_count=0

    while IFS= read -r line || [[ -n "$line" ]]; do
        line_count=$((line_count + 1))
        (( line_count == 1 )) || fail "$config_file must contain exactly one line."
        candidate="$line"
    done < "$config_file"

    [[ $line_count -eq 1 && -n "$candidate" ]] || fail \
        "$config_file is empty; write the absolute apple-health-extract project path on its only line."
    printf '%s\n' "$candidate"
}

create_empty_config() {
    local home_dir="$1"
    local config_file="$2"

    mkdir -p "$home_dir" || fail "could not create runtime directory $home_dir."
    chmod 700 "$home_dir" || fail "could not secure runtime directory $home_dir."
    if [[ ! -e "$config_file" ]]; then
        (umask 077; : > "$config_file") || fail "could not create $config_file."
    fi
    fail "created empty local config $config_file; write the absolute project path on its only line, then retry."
}

resolve_project_dir() {
    local wrapper_dir="$1"
    local home_dir=""
    local config_file=""
    local config_source="$PROJECT_DIR_ENV_NAME"
    local candidate=""

    if [[ -n "${APPLE_HEALTH_EXTRACT_PROJECT_DIR:-}" ]]; then
        candidate="$APPLE_HEALTH_EXTRACT_PROJECT_DIR"
    elif [[ -f "$wrapper_dir/$EXPECTED_SCRIPT" ]]; then
        candidate="$wrapper_dir"
        config_source="colocated wrapper"
    else
        home_dir="$(runtime_home)"
        config_file="$home_dir/project-dir"
        config_source="$config_file"
        if [[ -f "$config_file" ]]; then
            chmod 700 "$home_dir" || fail "could not secure runtime directory $home_dir."
            chmod 600 "$config_file" || fail "could not secure local config $config_file."
            candidate="$(read_project_dir_file "$config_file")"
        else
            create_empty_config "$home_dir" "$config_file"
        fi
    fi

    case "$candidate" in
        /*) ;;
        *) fail "$config_source must contain an absolute path, not: $candidate" ;;
    esac
    [[ -d "$candidate" ]] || fail "configured project directory does not exist: $candidate"
    candidate="$(cd "$candidate" && pwd -P)"
    [[ -f "$candidate/$EXPECTED_SCRIPT" ]] || fail \
        "configured project directory is missing $EXPECTED_SCRIPT: $candidate"
    [[ -x "$candidate/venv/bin/python" ]] || fail \
        "project environment is missing executable venv/bin/python: $candidate"
    printf '%s\n' "$candidate"
}

check_only=false
case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    --check)
        check_only=true
        shift
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PROJECT_DIR="$(resolve_project_dir "$SCRIPT_DIR")"

if [[ "$check_only" == true ]]; then
    [[ $# -eq 0 ]] || fail "--check does not accept extractor arguments."
    printf '%s: configuration OK (%s)\n' "$TOOL_NAME" "$PROJECT_DIR"
    exit 0
fi

cd "$PROJECT_DIR"
exec "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/$EXPECTED_SCRIPT" "$@"
