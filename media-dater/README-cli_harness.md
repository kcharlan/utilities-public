# CLI Harness (`cli_harness.sh`)

**CLI Harness** is a production-ready Bash boilerplate designed to standardize the creation of robust, user-friendly command-line tools. It handles the "boring" parts of script writing—argument parsing, error handling, and dependency checking—so you can focus on the core logic.

## User Guide (How to Use)

### 1. Copy the Template
Duplicate the harness to start a new tool.
```bash
cp cli_harness.sh my-new-tool
chmod +x my-new-tool
```

### 2. Configure Metadata
Open the file and update the top section variables:
```bash
SCRIPT_NAME="my-new-tool"
VERSION="0.1.0"
```

### 3. Implement Logic
Scroll down to the `main()` function. This is where your code lives.
*   **Dependencies:** Add `require_tool "git"` (or other tools) to ensure the environment is ready.
*   **Logic:** Replace the `echo "Doing work..."` line with your actual script logic.
*   **Variables:** Use `$TARGET_DIR`, `$VERBOSE`, and `$DRY_RUN` which are already pre-populated by the argument parser.

---

## Developer Guide

### Features available out-of-the-box

#### 1. Strict Mode
The script starts with `set -euo pipefail`. This ensures:
*   **Safety:** The script exits immediately if any command fails.
*   **Clarity:** Accessing undefined variables causes an error (prevents `rm -rf /$UNDEFINED_VAR`).
*   **Pipes:** Errors in a pipeline (e.g., `cmd1 | cmd2`) are caught.

#### 2. Standard Argument Parsing
The `parse_args` function automatically handles:
*   `-h / --help`: Displays usage instructions.
*   `-v / --verbose`: Sets `$VERBOSE=true`.
*   `-n / --dry-run`: Sets `$DRY_RUN=true`.
*   `--version`: Prints the version string.
*   Positional arguments (mapped to `$TARGET_DIR` by default).

#### 3. Helper Functions

| Function | Usage | Description |
| :--- | :--- | :--- |
| `die` | `die "Message"` | Prints the error to stderr and exits with status 1. |
| `log` | `log "Message"` | Prints an info message only if `--verbose` is active. |
| `require_tool` | `require_tool "curl"` | Checks if `curl` is in `$PATH`. Dies if missing. |

### extending the Argument Parser
To add a new flag (e.g., `--user`):

1.  **Define variable:** Initialize `USER_NAME=""` at the top of `parse_args`.
2.  **Add Case:** Add a new case block inside the `while` loop:
    ```bash
    -u|--user)
        if [[ -z "${2:-}" ]]; then die "Missing argument for --user"; fi
        USER_NAME="$2"
        shift 2
        ;;
    ```
3.  **Use it:** Access `$USER_NAME` in your `main` function.

### Best Practices

#### Temporary Files
If your script needs temporary files, use `mktemp` and `trap` for cleanup.
**Crucial:** When using `set -u` (strict mode), you must use **double quotes** in the trap command if the variable is local.

```bash
local tmp_file
tmp_file=$(mktemp)
# CORRECT: Expands $tmp_file immediately
trap "rm -f \"$tmp_file\"" EXIT

# INCORRECT: Tries to expand $tmp_file at exit (when it may no longer exist)
# trap 'rm -f "$tmp_file"' EXIT 
```
