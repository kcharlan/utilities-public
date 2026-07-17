#!/bin/bash

# ==============================================================================
# CLI Harness - Boilerplate for robust shell scripts
# ==============================================================================

# Strict mode:
# -e: Exit immediately if a command exits with a non-zero status.
# -u: Treat unset variables as an error.
# -o pipefail: Pipeline returns the status of the last command to exit with non-zero.
set -euo pipefail

# ------------------------------------------------------------------------------
# Configuration & Defaults
# ------------------------------------------------------------------------------
SCRIPT_NAME=$(basename "$0")
VERSION="0.1.0"

# Default flags
VERBOSE=false
DRY_RUN=false

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

# Print error message to stderr and exit
die() {
    echo "Error: $1" >&2
    exit 1
}

# Print log message if verbose mode is on
log() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "[INFO] $1"
    fi
}

# Check if a command exists on the system
require_tool() {
    local tool="$1"
    if ! command -v "$tool" &> /dev/null; then
        die "Required tool '$tool' is not installed or not in PATH."
    fi
}

# ------------------------------------------------------------------------------
# Usage
# ------------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $SCRIPT_NAME [OPTIONS] [TARGET_DIR]

Description of the script goes here.

Options:
  -h, --help       Show this help message and exit
  -v, --verbose    Enable verbose logging
  -n, --dry-run    Show what would happen without making changes
      --version    Show script version

Examples:
  $SCRIPT_NAME --verbose .
  $SCRIPT_NAME --dry-run /path/to/files

EOF
}

# ------------------------------------------------------------------------------
# Argument Parsing
# ------------------------------------------------------------------------------
parse_args() {
    # Initialize custom variables here
    # MY_CUSTOM_VAR=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                usage
                exit 0
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -n|--dry-run)
                DRY_RUN=true
                shift
                ;;
            --version)
                echo "$SCRIPT_NAME $VERSION"
                exit 0
                ;;
            # Example of a flag with an argument
            # -c|--custom)
            #     MY_CUSTOM_VAR="$2"
            #     shift 2
            #     ;;
            -*)
                die "Unknown option: $1"
                ;;
            *)
                # Assuming positional argument is the target directory
                if [[ -z "${TARGET_DIR:-}" ]]; then
                    TARGET_DIR="$1"
                else
                    die "Multiple target directories specified (first: $TARGET_DIR, second: $1)."
                fi
                shift
                ;;
        case_end
        # Note: 'case_end' is just a label for reading, standard is 'esac'.
        # I am using 'esac' below.
        esac
    done

    # Set default target if not provided
    TARGET_DIR="${TARGET_DIR:-.}"
}

# ------------------------------------------------------------------------------
# Main Execution
# ------------------------------------------------------------------------------
main() {
    parse_args "$@"

    log "Starting $SCRIPT_NAME..."
    log "Target Directory: $TARGET_DIR"

    # 1. Check Dependencies
    # require_tool "some_tool"

    # 2. Validation
    if [[ ! -d "$TARGET_DIR" ]]; then
        die "Directory not found: $TARGET_DIR"
    fi

    # Pattern: Safe Temporary Files
    # local tmp_file
    # tmp_file=$(mktemp) || die "Could not create temp file."
    # # Use double quotes in trap to expand variable immediately (prevents unbound var error on exit)
    # trap "rm -f \"$tmp_file\"" EXIT

    # 3. Core Logic
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY-RUN] Would execute main logic on $TARGET_DIR"
    else
        # Actual implementation goes here
        echo "Doing work..."
    fi

    log "Done."
}

# Invoke main with all arguments
main "$@"
