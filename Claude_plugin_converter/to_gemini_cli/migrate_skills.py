"""Convert Claude-style plugin skills and commands for Gemini CLI."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SKILL_NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class MigrationError(Exception):
    """Raised when migration would produce invalid or destructive output."""


def read_skill_name(skill_file: Path) -> str:
    """Return a skill's frontmatter name after validating its basic structure."""
    content = skill_file.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", content, re.DOTALL)
    if not frontmatter:
        raise MigrationError(f"{skill_file} must begin with YAML frontmatter")

    name_match = re.search(r"^name:\s*([^\n]+?)\s*$", frontmatter.group(1), re.MULTILINE)
    if not name_match:
        raise MigrationError(f"{skill_file} frontmatter is missing a name field")

    name = name_match.group(1).strip().strip('"\'')
    if len(name) > 64 or not SKILL_NAME_PATTERN.fullmatch(name):
        raise MigrationError(
            f"{skill_file} name must be 1-64 lowercase letters, numbers, or single hyphens"
        )
    if name != skill_file.parent.name:
        raise MigrationError(
            f"{skill_file} name {name!r} must match its directory name "
            f"{skill_file.parent.name!r}"
        )
    return name


def link_skill(source_skill: Path, skills_destination: Path, category_name: str) -> None:
    """Create one spec-compliant workspace link without modifying its source."""
    skill_file = source_skill / "SKILL.md"
    if not skill_file.is_file():
        raise MigrationError(f"skill directory is missing SKILL.md: {source_skill}")

    skill_name = read_skill_name(skill_file)
    destination = skills_destination / skill_name
    source_resolved = source_skill.resolve()

    if destination.is_symlink():
        if destination.resolve() != source_resolved:
            raise MigrationError(
                f"destination already exists and points elsewhere: {destination}"
            )
    elif destination.exists():
        raise MigrationError(f"destination already exists: {destination}")
    else:
        destination.symlink_to(source_resolved, target_is_directory=True)

    # Remove only the legacy link created by older converter releases, and
    # only when it points to this same source skill. Never delete a directory
    # or a link owned by another skill.
    legacy_destination = skills_destination / f"{category_name}:{skill_name}"
    if legacy_destination.is_symlink() and legacy_destination.resolve() == source_resolved:
        legacy_destination.unlink()

    print(f"  [Skill]   Linked: {skill_name}")


def command_parts(content: str, category_name: str, command_name: str) -> tuple[str, str]:
    """Extract a command description and prompt body from Markdown."""
    description = f"{category_name.capitalize()} command: {command_name}"
    prompt_body = content

    frontmatter = re.match(r"\A---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if frontmatter:
        description_match = re.search(
            r"^description:\s*(.*)$", frontmatter.group(1), re.MULTILINE
        )
        if description_match:
            description = description_match.group(1).strip().strip('"\'')
        prompt_body = content[frontmatter.end() :].strip()

    return description, prompt_body


def migrate(source_category_path: str | Path) -> None:
    """Migrate one Claude-style plugin category into the current workspace."""
    source_category = Path(source_category_path).expanduser()
    if not source_category.is_dir():
        raise MigrationError(f"{source_category} is not a directory")
    source_category = source_category.resolve()

    category_name = source_category.name
    gemini_directory = Path.cwd() / ".gemini"
    skills_destination = gemini_directory / "skills"
    commands_destination = gemini_directory / "commands" / category_name
    skills_destination.mkdir(parents=True, exist_ok=True)
    commands_destination.mkdir(parents=True, exist_ok=True)

    print(f"\nMigrating plugin: {category_name}")
    print("----------------------------------")

    source_skills = source_category / "skills"
    if source_skills.is_dir():
        for source_skill in sorted(source_skills.iterdir()):
            if source_skill.is_dir():
                link_skill(source_skill, skills_destination, category_name)

    source_commands = source_category / "commands"
    if source_commands.is_dir():
        for source_command in sorted(source_commands.glob("*.md")):
            command_name = source_command.stem
            destination = commands_destination / f"{command_name}.toml"
            description, prompt = command_parts(
                source_command.read_text(encoding="utf-8"), category_name, command_name
            )
            destination.write_text(
                f"description = {json.dumps(description, ensure_ascii=False)}\n"
                f"prompt = {json.dumps(prompt, ensure_ascii=False)}\n",
                encoding="utf-8",
            )
            print(f"  [Command] Created: /{category_name}:{command_name}")

    print("----------------------------------")
    print("Done! Run '/skills reload' and '/commands reload' in Gemini CLI.")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: uv run migrate_skills.py <path_to_plugin_subdirectory>", file=sys.stderr)
        return 2
    try:
        migrate(sys.argv[1])
    except (MigrationError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
