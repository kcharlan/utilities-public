# Media Dater (`media-dater`)

**Media Dater** is a robust command-line utility designed to organize image and video collections by renaming files according to their creation date. It wraps the powerful `exiftool` library in a safe, user-friendly interface.

## User Guide

### Features
*   **Automatic Date Extraction:** Reads the Create Date from EXIF/metadata.
*   **Idempotent:** Smartly skips files that have already been renamed to avoid processing them twice.
*   **Collision Handling:** Automatically adds a counter (e.g., `_00`, `_01`) if multiple photos were taken in the exact same second.
*   **Safety First:** Includes a `--dry-run` mode to preview changes before they happen.

### Prerequisites
*   **macOS/Linux**
*   **ExifTool**: This script requires `exiftool` to be installed.
    *   macOS: `brew install exiftool`
    *   Debian/Ubuntu: `sudo apt-get install libimage-exiftool-perl`

### Installation
Move the script to a directory in your `$PATH` (e.g., `/usr/local/bin` or `~/bin`) and ensure it is executable.

```bash
chmod +x media-dater
mv media-dater ~/bin/
```

### Usage
```bash
media-dater [OPTIONS] [TARGET_DIRECTORY]
```

#### Options
| Option | Description |
| :--- | :--- |
| `-h`, `--help` | Show the help message and exit. |
| `-n`, `--dry-run` | **Recommended:** Preview what would happen without renaming any files. |
| `-v`, `--verbose` | Enable detailed output (shows skipped files). |
| `-r`, `--recursive` | Process the target directory and all its subdirectories. |
| `-p`, `--prefix STR` | Set a custom prefix for the filenames (Default: `IMG_`). |
| `-e`, `--ext LIST` | Process only specific extensions (comma-separated, e.g., `jpg,mov`). |
| `--version` | Show the script version and exit. |

#### Examples

**1. Standard Run (Current Directory)**
Renames all files in the current folder to `IMG_YYYYMMDD_HHMMSS_XX.ext`.
```bash
media-dater .
```

**2. Preview Changes (Dry Run)**
See exactly what will be renamed without touching your files.
```bash
media-dater --dry-run ~/Downloads/Photos
```

**3. Organize Vacation Videos**
Renames only `.mov` and `.mp4` files recursively, starting with "HAAWAII_".
```bash
media-dater --recursive --prefix "HAWAII_" --ext mov,mp4 ~/Movies/Trip
```

---

## Developer Guide

### Architecture
The script follows a **Filter-Then-Execute** pipeline to ensure robustness and speed.

1.  **Discovery (`find`):** Uses the `find` command to locate potential files. It handles paths with spaces and special characters safely by using null delimiters (`-print0`).
2.  **Filtering (Bash Loop):** 
    *   Iterates through the found files.
    *   Checks filenames against a regex pattern (e.g., `^IMG_[0-9]{8}_...`).
    *   If a file matches the pattern, it is **skipped**.
    *   Valid files are written to a temporary "arguments file".
3.  **Execution (`exiftool`):** 
    *   If the arguments file is not empty, `exiftool` is invoked once in batch mode.
    *   It reads the file list from the temporary file (`-@ argfile`).
    *   This prevents "Argument list too long" errors and reduces process overhead.

### Key Variables
*   `PREFIX`: Defaults to `IMG_`. Adjusted via `-p`.
*   `EXTENSIONS`: Comma-separated list used to build the `find` command parameters.
*   `TARGET_DIR`: The root directory for the operation.

### Extending
To add new metadata tags (e.g., Model Name or ISO), modify the `exiftool` command in the `main` function:

```bash
# Existing
-d "${PREFIX}%Y%m%d_%H%M%S_%%%-02.c.%%e"

# Modified to include Camera Model
-d "${PREFIX}%Y%m%d_%H%M%S_\${Model;}_%%%-02.c.%%e"
```
