# worktree-helper

`worktree-helper` is a single-file Python utility for managing `git worktree` without having to remember the syntax. It uses only the Python standard library.

The executable itself is named `worktree`. It supports:

- A keyboard-driven TUI when launched with no flags
- Full CLI flags for headless or repeatable automation
- Copy/paste command hints after normal actions (except raw-path output)
- Folder browsing for repo and target selection
- Branch browsing for existing branches and new branch creation

## Why this exists

Git worktrees are useful, but the command surface is not memorable:

- `git worktree add ...`
- `git worktree remove ...`
- `git worktree prune ...`
- `git worktree repair ...`
- branch rules around existing checkouts
- detached vs new-branch flows

This utility wraps those flows in a friendlier interface and prints a reusable CLI command after each normal action.

## Features

- `create`
- `delete`
- `list`
- `status`
- `prune`
- `open`
- `cd` helper
- `lock`
- `unlock`
- `move`
- `repair`
- `doctor`

## Requirements

- Python 3.9+
- Git on `PATH`
- A real terminal with Python's `curses` module for the TUI mode
- macOS or a system with `xdg-open` for the `open` action

No third-party Python packages are required.

## Install

The tool is intentionally portable. The main script is:

- [`worktree`](./worktree)

Make it executable and put it somewhere on your `PATH`, for example `~/Library/Scripts`:

```zsh
chmod +x worktree
cp worktree ~/Library/Scripts/worktree
```

Or symlink it during development:

```zsh
ln -sf "$PWD/worktree" ~/Library/Scripts/worktree
```

## State Storage

The tool stores lightweight history only:

- `~/.worktree-helper/state.json`

That file is used for recent repo and target-folder suggestions in the TUI. It is safe to delete.

## Quick Start

Launch the interactive TUI:

```zsh
worktree
```

Create a new worktree without the wizard:

```zsh
worktree --create \
  --repo ~/src/myapp \
  --new-branch feature/auth \
  --from main \
  --path ~/worktrees/myapp-auth
```

Delete a worktree:

```zsh
worktree --delete \
  --repo ~/src/myapp \
  --worktree ~/worktrees/myapp-auth
```

See the repo family status:

```zsh
worktree --status --repo ~/src/myapp
```

Preview prune:

```zsh
worktree --prune --repo ~/src/myapp --dry-run
```

## Help Text

The built-in help is meant to stand on its own:

```zsh
worktree --help
worktree -h
```

It includes:

- every action flag
- create-mode options
- common examples
- scripting examples

## TUI Behavior

When you run `worktree` with no action flags, it opens a keyboard-first terminal UI.

Typical behavior:

- Arrow keys or `j` / `k` move through lists
- `Enter` selects
- typing filters long lists
- `q` or `Esc` backs out
- inside nested prompts, `Esc` returns to the previous picker before leaving the wizard
- after a TUI action runs, the result stays in the TUI and then returns you to the top menu
- path/name prompts support replace-on-type so you do not have to erase the suggested value first

The wizard can:

- detect the current repository
- browse to another repository
- browse parent folders for new worktrees
- let you type a full path when that is faster
- browse existing local branches
- create new branches from a selected base ref
- create reset branches or detached worktrees

## Command Reference

### Launch Modes

```zsh
worktree
worktree --help
worktree --version
```

### Core Actions

```zsh
worktree --create
worktree --delete
worktree --list
worktree --status
worktree --prune
worktree --open
worktree --cd
worktree --lock
worktree --unlock
worktree --move
worktree --repair
worktree --doctor
```

### Common Flags

```zsh
--repo PATH
--path PATH
--worktree PATH
--new-path PATH
--yes
--force
--verbose
--no-color
```

### Create Modes

Use exactly one of these working modes for non-interactive create. `--from` is optional; Git uses its normal default start point when it is omitted.

```zsh
--branch NAME
--new-branch NAME [--from REF]
--reset-branch NAME [--from REF]
--detach [--from REF]
```

Other create-related flags:

```zsh
--no-checkout
--lock-on-create
--lock-reason TEXT
```

The `--orphan` option appears in version 0.1.0's CLI and TUI, but its current validation conflicts with the required `--new-branch` or `--reset-branch` option. Orphan creation therefore does not currently complete; use `git worktree add --orphan` directly until that implementation is fixed.

### Prune Flags

```zsh
--dry-run
--expire now
--expire 3.days.ago
```

### Repair Flags

Repeat `--repair-path` when you need to repair multiple paths:

```zsh
worktree --repair --repo ~/src/myapp --repair-path ~/moved/worktree-a --repair-path ~/moved/worktree-b
```

## CD Helper

Like every CLI utility, `worktree` cannot change the parent shell's current directory directly.

It provides two useful modes:

Print a copy/paste shell command:

```zsh
worktree --cd --repo ~/src/myapp --worktree ~/worktrees/myapp-auth
```

Print just the raw path for scripting:

```zsh
worktree --cd --repo ~/src/myapp --worktree ~/worktrees/myapp-auth --raw-path
```

If you want a real shell helper:

```zsh
function cwt() { eval "$(worktree --cd "$@")"; }
```

Then:

```zsh
cwt --repo ~/src/myapp --worktree ~/worktrees/myapp-auth
```

## Notes About Git Worktree Behavior

- An existing local branch usually cannot be checked out in more than one worktree at the same time.
- Creating a new branch for a new worktree is the safest default for feature work.
- `prune` cleans stale metadata, not live worktree directories.
- `repair` is for cases where paths were moved manually outside Git.
- The main working tree cannot be removed with `git worktree remove`.
