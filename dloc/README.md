# dloc (Daily Lines of Code)

`dloc` summarizes Git's reported insertions and deletions by author date. Despite
the name, it counts changed lines in tracked files rather than measuring the
number of source-code lines currently present in a repository.

## Features

- Reads commit statistics from the repository containing the current working
  directory.
- Aggregates insertions and deletions across all commits with the same author
  date.
- Writes a newest-first Markdown table to standard output.

## Requirements

- Python 3.9 or newer
- Git

The tool has no third-party Python dependencies.

## Usage

Run the script from within the Git repository you want to analyze:

```bash
cd /path/to/your/repo
/path/to/dloc/dloc
```

The script accepts no command-line options. Redirect its output to save the
table:

```bash
/path/to/dloc/dloc > daily_changes.md
```

Running it outside a Git repository prints a Git command error to standard
error and exits with a nonzero status.

### Example Output

| Date       | Added   | Removed | Net Change |
|------------|---------|---------|------------|
| 2024-05-20 |     150 |      20 |        130 |
| 2024-05-19 |      45 |      10 |         35 |

## Implementation Details

The tool parses:

```text
git log --pretty=format:%ad --date=short --shortstat
```

`Added` and `Removed` are the insertion and deletion totals reported by Git.
`Net Change` is `Added - Removed`. Binary-file changes and other changes for
which Git does not report line counts do not contribute to these totals.
