# Claude to Gemini CLI Converter

Utilities to migrate Claude-style plugins (like those found in `knowledge-work-plugins`) into native Gemini CLI Skills and Slash Commands.

## Tools

- `migrate_skills.py`: A Python script that:
    - Creates symbolic links for skills to ensure they stay updated with the source.
    - Converts Markdown-based commands into Gemini CLI TOML files.
    - Prefixes skills and commands with the plugin category name for better organization.

## Usage

See the [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) for detailed instructions on how to use these tools.

### Quick Start

```bash
python migrate_skills.py path/to/claude/plugin/category
```

Example:
```bash
python migrate_skills.py knowledge-work-plugins/legal
```
