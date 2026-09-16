# Claude to Gemini CLI Converter

`migrate_skills.py` adapts one Claude-style plugin category at a time for a
Gemini CLI workspace.

It performs two operations:

- For each immediate subdirectory of `<plugin>/skills/`, it validates the
  `SKILL.md` name and creates a same-named symbolic link under
  `<workspace>/.gemini/skills/` without modifying the source skill.
- For each top-level Markdown file in `<plugin>/commands/`, it writes a Gemini
  CLI TOML command under
  `<workspace>/.gemini/commands/<category>/`.

The workspace is the current working directory, not the directory containing
the script. Run it from the Gemini workspace you want to modify:

```bash
uv run /path/to/Claude_plugin_converter/to_gemini_cli/migrate_skills.py \
  /path/to/claude-plugin/category
```

The converter requires Python 3.10 or newer and has no third-party Python
dependencies. `uv` supplies the interpreter for the commands in this guide.

For a category directory named `legal`, a command such as
`commands/brief.md` becomes `.gemini/commands/legal/brief.toml` and is invoked
as `/legal:brief`.

## Safety and limitations

- Each skill must contain a `SKILL.md` whose `name` uses lowercase letters,
  numbers, and single hyphens, is at most 64 characters, and matches the source
  directory name. Invalid skills stop the migration with an actionable error.
- Skills keep their existing names; category namespacing applies only to
  commands. If two categories contain the same skill name, migrate them into
  separate workspaces or rename one source skill. The converter refuses to
  replace a same-named destination owned by another skill.
- Re-running overwrites generated commands, but it does not remove generated
  commands whose source Markdown files were deleted.
- Symbolic links make this workflow suitable for macOS and Linux. Windows use
  requires a filesystem and permissions configuration that supports symbolic
  links.

## Tests

The converter and its tests use only the Python standard library:

```bash
uv run --python 3.12 python -m unittest discover -s tests -v
```

See the [migration guide](./MIGRATION_GUIDE.md) for the source layout, exact
side effects, verification steps, and update behavior.
