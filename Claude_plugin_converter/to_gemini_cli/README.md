# Claude to Gemini CLI Converter

`migrate_skills.py` adapts one Claude-style plugin category at a time for a
Gemini CLI workspace.

It performs two operations:

- For each immediate subdirectory of `<plugin>/skills/`, it creates a symbolic
  link under `<workspace>/.gemini/skills/`.
- For each top-level Markdown file in `<plugin>/commands/`, it writes a Gemini
  CLI TOML command under
  `<workspace>/.gemini/commands/<category>/`.

The workspace is the current working directory, not the directory containing
the script. Run it from the Gemini workspace you want to modify:

```bash
uv run /path/to/Claude_plugin_converter/to_gemini_cli/migrate_skills.py \
  /path/to/claude-plugin/category
```

For a category directory named `legal`, a command such as
`commands/brief.md` becomes `.gemini/commands/legal/brief.toml` and is invoked
as `/legal:brief`.

## Important limitations

- The script rewrites each source `SKILL.md` `name:` field and creates the
  destination skill directory as `<category>:<skill>`. Current Agent Skills
  names are expected to use lowercase letters, numbers, and hyphens and to
  match the directory name, so these colon-prefixed skills are not compatible
  with the current format.
- The script replaces an existing destination skill directory or link with the
  same prefixed name.
- Re-running overwrites generated commands, but it does not remove generated
  commands whose source Markdown files were deleted.
- Command bodies containing a TOML triple-double-quote delimiter (`"""`) are
  not escaped and require manual correction in the generated file.
- Symbolic links make this workflow suitable for macOS and Linux. The
  colon-prefixed destination names also prevent the skill-linking behavior from
  working on Windows.

See the [migration guide](./MIGRATION_GUIDE.md) for the source layout, exact
side effects, verification steps, and update behavior.
