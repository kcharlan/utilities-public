import os
import sys
import shutil
import re

def migrate(source_category_path):
    """
    Migrates skills and commands from a Claude-style plugin directory to Gemini CLI.
    """
    if not os.path.isdir(source_category_path):
        print(f"Error: {source_category_path} is not a directory.")
        return

    # 1. Setup paths
    category_name = os.path.basename(source_category_path.rstrip(os.sep))
    gemini_dir = os.path.join(os.getcwd(), '.gemini')
    skills_dest = os.path.join(gemini_dir, 'skills')
    commands_dest = os.path.join(gemini_dir, 'commands', category_name)

    os.makedirs(skills_dest, exist_ok=True)
    os.makedirs(commands_dest, exist_ok=True)

    print(f"\n🚀 Migrating plugin: {category_name}")
    print(f"----------------------------------")

    # 2. Migrate Skills (Symbolic Links)
    source_skills_dir = os.path.join(source_category_path, 'skills')
    if os.path.exists(source_skills_dir):
        for skill_name in os.listdir(source_skills_dir):
            src_skill = os.path.join(source_skills_dir, skill_name)
            if not os.path.isdir(src_skill): 
                continue
            
            # Use a colon prefix for grouping, similar to commands
            prefixed_name = f"{category_name}:{skill_name}"
            dest_skill = os.path.join(skills_dest, prefixed_name)
            
            # 2a. Update the name in SKILL.md to match the prefixed name
            # This ensures they are grouped correctly in 'gemini skills list'
            skill_md_path = os.path.join(src_skill, 'SKILL.md')
            if os.path.exists(skill_md_path):
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    md_content = f.read()
                
                # Update the name field in frontmatter
                new_md_content = re.sub(r'^(name:\s*).*$', f'\\1{prefixed_name}', md_content, flags=re.MULTILINE)
                if new_md_content != md_content:
                    with open(skill_md_path, 'w', encoding='utf-8') as f:
                        f.write(new_md_content)
                    print(f"  [Skill]   Updated name in source: {prefixed_name}")

            # 2b. Clean up old non-prefixed link if it exists
            old_dest_skill = os.path.join(skills_dest, skill_name)
            if os.path.islink(old_dest_skill):
                os.unlink(old_dest_skill)
            
            # 2c. Create/update the new symlink
            if os.path.islink(dest_skill):
                os.unlink(dest_skill)
            elif os.path.exists(dest_skill):
                shutil.rmtree(dest_skill)
            
            os.symlink(os.path.abspath(src_skill), dest_skill)
            print(f"  [Skill]   Linked: {prefixed_name}")

    # 3. Migrate Commands (Markdown -> TOML)
    source_commands_dir = os.path.join(source_category_path, 'commands')
    if os.path.exists(source_commands_dir):
        for cmd_file in os.listdir(source_commands_dir):
            if not cmd_file.endswith('.md'): 
                continue
            
            src_path = os.path.join(source_commands_dir, cmd_file)
            cmd_name = cmd_file.replace('.md', '')
            dest_path = os.path.join(commands_dest, f"{cmd_name}.toml")

            with open(src_path, 'r', encoding='utf-8') as f:
                content = f.read()

            description = f"{category_name.capitalize()} command: {cmd_name}"
            prompt_body = content
            
            frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if frontmatter_match:
                fm_content = frontmatter_match.group(1)
                desc_match = re.search(r'^description:\s*(.*)$', fm_content, re.MULTILINE)
                if desc_match:
                    description = desc_match.group(1).strip().strip('"')
                prompt_body = content[frontmatter_match.end():].strip()

            escaped_desc = description.replace('"', '\\"')
            
            with open(dest_path, 'w', encoding='utf-8') as f:
                f.write(f'description = "{escaped_desc}"\n')
                f.write(f'prompt = """\n{prompt_body}\n"""\n')
            
            print(f"  [Command] Created: /{category_name}:{cmd_name}")

    print(f"----------------------------------")
    print(f"Done! Run 'gemini skills list' to see your new skills.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python migrate_skills.py <path_to_plugin_subdirectory>")
        sys.exit(1)
    migrate(sys.argv[1])
