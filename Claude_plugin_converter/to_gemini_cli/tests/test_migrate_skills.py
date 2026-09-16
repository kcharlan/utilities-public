"""Regression tests for the Gemini CLI converter."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "migrate_skills.py"


class ConverterTests(unittest.TestCase):
    def run_converter(self, workspace: Path, category: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(category)],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )

    def make_skill(self, category: Path, directory_name: str, metadata_name: str) -> Path:
        skill_dir = category / "skills" / directory_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {metadata_name}\n"
            "description: Synthetic skill used only by tests.\n"
            "---\n\n"
            "# Synthetic Skill\n",
            encoding="utf-8",
        )
        return skill_dir

    def test_preserves_source_links_compliant_skill_and_escapes_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            category = root / "legal"
            workspace.mkdir()
            skill_dir = self.make_skill(category, "contract-review", "contract-review")
            original_skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            commands = category / "commands"
            commands.mkdir()
            prompt = 'Use the literal delimiter """ without breaking TOML.'
            (commands / "brief.md").write_text(
                "---\n"
                'description: "Create a synthetic brief"\n'
                "---\n\n"
                f"{prompt}\n",
                encoding="utf-8",
            )

            result = self.run_converter(workspace, category)

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(
                (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
                original_skill,
            )
            link = workspace / ".gemini" / "skills" / "contract-review"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), skill_dir.resolve())
            self.assertFalse((workspace / ".gemini" / "skills" / "legal:contract-review").exists())

            command = tomllib.loads(
                (workspace / ".gemini" / "commands" / "legal" / "brief.toml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(command["description"], "Create a synthetic brief")
            self.assertEqual(command["prompt"], prompt)

    def test_rejects_destination_collision_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            category = root / "legal"
            workspace.mkdir()
            self.make_skill(category, "contract-review", "contract-review")
            destination = workspace / ".gemini" / "skills" / "contract-review"
            destination.mkdir(parents=True)
            marker = destination / "KEEP.txt"
            marker.write_text("synthetic existing content\n", encoding="utf-8")

            result = self.run_converter(workspace, category)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination already exists", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "synthetic existing content\n")

    def test_rejects_noncompliant_skill_metadata_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            category = root / "legal"
            workspace.mkdir()
            skill_dir = self.make_skill(category, "contract-review", "different-name")
            original_skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

            result = self.run_converter(workspace, category)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must match its directory name", result.stderr)
            self.assertEqual(
                (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
                original_skill,
            )
            self.assertFalse((workspace / ".gemini" / "skills" / "contract-review").exists())


if __name__ == "__main__":
    unittest.main()
