# Media Dater (`media-dater`)

Media Dater is a Bash wrapper around ExifTool that renames files from their
`CreateDate` metadata. The default output format is:

```text
IMG_YYYYMMDD_HHMMSS_XX.ext
```

ExifTool supplies the numeric copy counter when multiple files would otherwise
receive the same name.

## Requirements

- Bash and standard Unix command-line tools (`find`, `sed`, `xargs`, and
  `basename`)
- [ExifTool](https://exiftool.org/)

Install ExifTool on macOS with `brew install exiftool`, or on Debian/Ubuntu
with `sudo apt-get install libimage-exiftool-perl`.

## Installation

Copy or symlink the executable into a directory on `PATH`. For example:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/media-dater" ~/.local/bin/media-dater
```

Add `~/.local/bin` to `PATH` if it is not already present.

## Usage

```text
media-dater [OPTIONS] [TARGET_DIR]
```

If `TARGET_DIR` is omitted, the current directory is used.

| Option | Description |
| --- | --- |
| `-h`, `--help` | Show help and exit. |
| `-v`, `--verbose` | Show informational messages and files skipped as already named. |
| `-n`, `--dry-run` | Show the planned ExifTool command and up to five candidate paths without renaming files. |
| `-r`, `--recursive` | Include files below the target directory. |
| `-p`, `--prefix STRING` | Set the filename prefix (default: `IMG_`). |
| `-e`, `--ext LIST` | Limit discovery to a case-insensitive, comma-separated list of extensions such as `jpg,mov`. |
| `--version` | Print the version and exit. |

Examples:

```bash
# Preview candidates in the current directory.
media-dater --dry-run .

# Rename JPEG and PNG files below a directory.
media-dater --recursive --ext jpg,png ~/Pictures

# Use a custom prefix for MOV and MP4 files.
media-dater --prefix "VACATION_" --ext mov,mp4 ~/Movies/Trip
```

## Behavior and limitations

- Without `--ext`, discovery includes every non-hidden regular file, not just
  recognized image and video formats. Use `--ext` when the target contains
  unrelated files.
- ExifTool reads only `CreateDate`; the script does not fall back to other date
  tags or filesystem timestamps. Files without a usable `CreateDate` are left
  unchanged and ExifTool reports them.
- A file is skipped before metadata inspection when its name begins with the
  selected prefix followed by eight digits, an underscore, and six digits.
  This makes normal repeated runs idempotent, but any unrelated filename with
  that leading pattern is also skipped.
- `--dry-run` previews candidate files, not the exact destination name ExifTool
  will derive from each file's metadata.
- Spaces in paths are supported. Newlines in filenames are not, because
  candidate paths are passed to ExifTool in a line-oriented argument file.
- ExifTool performs the rename in one batch using `-@`; the temporary argument
  file is removed when the script exits.

## Implementation overview

The script builds a `find` command from the recursion and extension options,
reads its null-delimited output, filters names that already match the generated
format, and writes the remaining paths to a temporary argument file. It then
runs one ExifTool command equivalent to:

```bash
exiftool \
  '-filename<CreateDate' \
  -d "${PREFIX}%Y%m%d_%H%M%S_%%%-02.c.%%e" \
  -@ "$argfile"
```
