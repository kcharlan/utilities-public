# Guide: Migrating Knowledge Work Plugins to Gemini CLI

This guide explains how to convert specialized "Claude Skills" and plugins (like the ones found in `knowledge-work-plugins/`) into native **Gemini CLI Skills** and **Slash Commands**.

---

## How It Works

1.  **Skills (Symlinks):** The script creates symbolic links from your plugin's `skills/` folders to `.gemini/skills/`. This means if you update the source repository (e.g., via `git pull`), the skills in Gemini CLI are **instantly updated** without needing to run the script again.
2.  **Commands (TOML):** The script converts Markdown command files (e.g., `legal/commands/brief.md`) into Gemini CLI TOML files. This enables slash commands like `/legal:brief` directly in your chat.

---

## Prerequisites

- **Gemini CLI** installed and configured in your project.
- **Python 3** installed on your system.
- The `knowledge-work-plugins` repository cloned locally.

---

## Step-by-Step Migration

### 1. Run the Migration Script
Open your terminal in the root of your project and run the script against a specific plugin directory (e.g., `legal`):

```bash
python migrate_skills.py knowledge-work-plugins/legal
```

**What this does:**
- It looks into `knowledge-work-plugins/legal/skills/` and links every skill found there into `.gemini/skills/`.
- It looks into `knowledge-work-plugins/legal/commands/` and converts the Markdown files into `/legal:...` slash commands.

### 2. Verify Installation
After running the script, you can verify the skills are active:

```bash
gemini skills list
```

You should see skills like `legal:contract-review`, `legal:legal-risk-assessment`, etc., listed. This prefixing keeps your skills grouped by domain.

### 3. Use the Commands
You can now use the new slash commands in your Gemini CLI session:

- `/legal:brief`
- `/legal:review-contract`
- `/legal:triage-nda`

And activate the skills using their new prefixed names:
`activate_skill(name="legal:contract-review")`

---

## Keeping Things Updated

One of the best features of this setup is how it handles updates:

### If the Skills Repo Changes
If the authors of `knowledge-work-plugins` update the content of the `SKILL.md` files or the scripts inside the `skills/` folders:
1.  Navigate to the `knowledge-work-plugins` directory.
2.  Run `git pull`.
3.  **Done.** Since we used symbolic links, Gemini CLI will immediately start using the new content. You do **not** need to run the migration script again for skills.

### If New Commands are Added
If new `.md` files appear in the `commands/` directory:
1.  Run `git pull` in the plugins repo.
2.  Re-run the migration script:
    ```bash
    python migrate_skills.py knowledge-work-plugins/legal
    ```
    The script will detect new commands and update existing ones.

---

## Migrating Other Plugins
The script is flexible. To migrate the `bio-research` plugin, simply run:

```bash
python migrate_skills.py knowledge-work-plugins/bio-research
```

This will create a new set of commands under the `/bio-research:` namespace (e.g., `/bio-research:start`).
