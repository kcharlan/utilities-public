# Migrating Claude-Style Plugins to Gemini CLI

This guide documents the behavior of `migrate_skills.py`, which processes one
Claude-style plugin category and writes project-level Gemini CLI files into the
current working directory.

## Before you run it

The script expects a source layout like this:

```text
legal/
├── skills/
│   └── contract-review/
│       └── SKILL.md
└── commands/
    └── brief.md
```

Only immediate child directories of `skills/` and top-level `.md` files in
`commands/` are processed. Either source directory may be absent.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) with Python 3.10 or newer for the runtime.
- Gemini CLI installed and configured.
- A local Claude-style plugin directory.

Run the converter only after reviewing these side effects:

- The category name is the source directory's basename (`legal` in the
  example).
- The script validates each source `SKILL.md` but never modifies it.
- A valid source skill is linked as `.gemini/skills/<skill>`.
- A same-named destination is reused only when it already links to that exact
  source. Any other file, directory, or link is preserved and stops migration.
- A legacy `.gemini/skills/<category>:<skill>` link is removed only when it
  points to the same source skill now linked under its compliant name.
- Existing generated command files with matching names are overwritten.
- Obsolete generated command files are not pruned.

### Skill-format compatibility

Current Agent Skills names contain only lowercase letters, numbers, and single
hyphens, are at most 64 characters, and match their directory names. The
converter enforces those rules and links the original directory without
rewriting its metadata. Gemini CLI also provides `gemini skills link` for
linking one compliant skill manually.

Skill names are global within a workspace, so the converter does not prepend
the plugin category. A collision stops safely instead of deleting or replacing
the existing destination. Commands are different: Gemini CLI intentionally
derives `/category:command` names from subdirectories under
`.gemini/commands/`, so command category namespacing remains valid.

## Run the converter

Change to the root of the Gemini workspace that should receive the `.gemini/`
directory, then run the script with an absolute or correctly resolved relative
source path:

```bash
cd /path/to/gemini-workspace
uv run /path/to/Claude_plugin_converter/to_gemini_cli/migrate_skills.py \
  /path/to/claude-plugin/legal
```

For the sample layout, the script attempts to produce:

```text
.gemini/
├── skills/
│   └── contract-review -> /absolute/path/to/legal/skills/contract-review
└── commands/
    └── legal/
        └── brief.toml
```

The generated command uses the source Markdown body as its `prompt`. If the
Markdown starts with YAML frontmatter and contains a one-line `description:`,
that description is used; otherwise the script generates a description from
the category and filename. Description and prompt values are escaped as TOML
basic strings, including embedded quotes and newlines.

## Verify in Gemini CLI

Start an interactive Gemini CLI session in the workspace:

```bash
gemini
```

Then use the interactive commands:

```text
/skills reload
/skills list
/commands reload
/commands list
```

`activate_skill` is an agent tool, not a command users invoke manually. Ask
Gemini to perform a task matching a valid skill's description; Gemini decides
whether to request activation.

Generated commands are invoked directly. For example:

```text
/legal:brief
```

## Keeping generated files updated

- Content changes within a linked skill are visible through the symbolic link;
  re-running is not necessary for those files.
- Re-run the converter after adding or changing command Markdown files. It
  overwrites the corresponding TOML files.
- If a source command is renamed or deleted, manually remove its old TOML file
  from `.gemini/commands/<category>/`.
- Re-run `/skills reload` or `/commands reload` in an active Gemini session
  after changing the corresponding files.
