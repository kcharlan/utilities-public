from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from md_autotax_core import ConfigError, generate_qif_content, load_config, load_tax_table, write_qif


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def synthetic_config(table_path: Path) -> dict:
    return {
        "tax_table": str(table_path),
        "qif": {
            "federal": {
                "payee": "SYNTHETIC-FED-PAYEE",
                "memo": "SYNTHETIC-FED-MEMO",
                "expense_category": "SYNTHETIC:FED-EXPENSE",
                "transfer_account": "SYNTHETIC-FED-TRANSFER",
            },
            "state": {
                "payee": "SYNTHETIC-STATE-PAYEE",
                "memo": "SYNTHETIC-STATE-MEMO",
                "expense_category": "SYNTHETIC:STATE-EXPENSE",
                "transfer_account": "SYNTHETIC-STATE-TRANSFER",
            },
        },
    }


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.table = self.root / "private-table.csv"
        self.table.write_text(
            "Monthly Gross Income,Federal Monthly Tax,State Monthly Tax\n"
            "111111.11,22222.22,3333.33\n",
            encoding="utf-8",
        )
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(synthetic_config(self.table)), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_config_is_external_and_permissions_are_hardened(self) -> None:
        os.chmod(self.root, 0o755)
        os.chmod(self.config_path, 0o644)
        config = load_config(self.config_path)
        self.assertEqual(config["tax_table"], str(self.table))
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.config_path.stat().st_mode & 0o777, 0o600)

    def test_config_symlink_is_rejected(self) -> None:
        target = self.root / "target.json"
        self.config_path.rename(target)
        self.config_path.symlink_to(target)
        with self.assertRaisesRegex(ConfigError, "not a symlink"):
            load_config(self.config_path)

    def test_qif_control_characters_are_rejected(self) -> None:
        config = synthetic_config(self.table)
        config["qif"]["state"]["payee"] = "bad\nLInjected"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "control character"):
            load_config(self.config_path)

    def test_table_and_qif_generation_use_only_configured_labels(self) -> None:
        frame, error = load_tax_table(self.table)
        self.assertIsNone(error)
        row = frame.iloc[0]
        config = load_config(self.config_path)
        content = generate_qif_content(
            datetime(2031, 2, 3), row["FederalTax"], row["StateTax"], config
        )
        self.assertEqual(content.count("\n^"), 4)
        self.assertIn("PSYNTHETIC-STATE-PAYEE", content)
        self.assertIn("L[SYNTHETIC-STATE-TRANSFER]", content)
        self.assertIn("D02/03/31", content)

    def test_atomic_writer_creates_private_file(self) -> None:
        output = self.root / "nested" / "result.qif"
        write_qif(output, "SYNTHETIC")
        self.assertEqual(output.read_text(encoding="utf-8"), "SYNTHETIC")
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_cli_uses_private_config_and_table(self) -> None:
        output_dir = self.root / "out"
        result = subprocess.run(
            [
                os.fspath(Path(os.sys.executable)),
                os.fspath(PROJECT_ROOT / "tax_qif_generator_grouped.py"),
                "--income",
                "111111.11",
                "--date",
                "02/03/2031",
                "--config",
                os.fspath(self.config_path),
                "--output-dir",
                os.fspath(output_dir),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = output_dir / "tax_entries_2031-02-03.qif"
        self.assertIn("PSYNTHETIC-FED-PAYEE", output.read_text(encoding="utf-8"))

    def test_public_project_has_no_operational_tax_table_or_jurisdiction_label(self) -> None:
        self.assertFalse((PROJECT_ROOT / "Tax-table.csv").exists())
        public_files = [
            PROJECT_ROOT / "app.py",
            PROJECT_ROOT / "md_autotax_core.py",
            PROJECT_ROOT / "tax_qif_generator_grouped.py",
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "config.example.json",
        ]
        joined = "\n".join(path.read_text(encoding="utf-8") for path in public_files)
        private_marker = "G" + "A State"
        self.assertNotIn(private_marker, joined)


if __name__ == "__main__":
    unittest.main()
