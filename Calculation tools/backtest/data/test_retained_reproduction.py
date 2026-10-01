"""Real retained-input integration. Missing prerequisites are fatal, never skips.

The two explicit invented modules form the synthetic subset; full discovery
also runs this selected-current-bundle reproduction. No observations are fixtures.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RetainedReproductionTests(unittest.TestCase):
    def test_selected_bundle_reproduces_exact_pair_from_both_retained_inputs(self):
        self.assertNotEqual(sys.prefix, sys.base_prefix, "Use the documented external ready venv")
        project = Path(__file__).resolve().parent.parent
        bridge = project / "tests/helpers/retained-reproduction.cjs"
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

        def verified():
            result = subprocess.run(
                ["node", str(bridge), "--python", sys.executable],
                cwd=project, env=env, capture_output=True, timeout=90,
            )
            self.assertEqual(result.returncode, 0,
                             "Retained reproduction prerequisites failed; run npm run setup:data "
                             "and prepare the documented compatible external venv. "
                             "No setup or acquisition runs from tests.")
            return json.loads(result.stdout)

        admitted = verified()
        self.assertEqual({source["id"] for source in admitted["inputs"]}, {"shiller", "damodaran"})
        root = Path(admitted["root"])
        expected = {name: (root / name).read_bytes() for name in admitted["pairHashes"]}
        for name, content in expected.items():
            self.assertEqual(hashlib.sha256(content).hexdigest(), admitted["pairHashes"][name],
                             "Independently verified expected pair changed before capture")

        watched = [Path(source["path"]) for source in admitted["inputs"]]
        watched.extend(root.rglob("*"))
        watched.append(Path(admitted["dataHome"]) / "current.json")

        def snapshot():
            result = {}
            for file in watched:
                if file.exists() and file.is_file():
                    info = file.stat()
                    result[str(file)] = (info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns,
                                         hashlib.sha256(file.read_bytes()).hexdigest())
                elif not file.exists():
                    result[str(file)] = None
            return result

        before = snapshot()
        sources = {source["id"]: source["path"] for source in admitted["inputs"]}
        parent = os.environ.get("MARKET_ATLAS_TEST_TMPDIR") or tempfile.gettempdir()
        # Node preflight above validates the external temporary parent before writes.
        with tempfile.TemporaryDirectory(prefix="market-atlas retained reproduction ", dir=parent) as temporary:
            os.chmod(temporary, 0o700)
            output = Path(temporary) / "compiled pair"
            result = subprocess.run(
                [sys.executable, "-B", str(project / "data/compile_market_data.py"),
                 "--shiller", sources["shiller"], "--damodaran", sources["damodaran"],
                 "--output-dir", str(output), "--end-year", "2025",
                 "--generated-date", admitted["generatedDate"]],
                cwd=project, env=env, capture_output=True, timeout=300,
            )
            self.assertEqual(result.returncode, 0,
                             "Retained-input compiler child failed; no output values are printed")
            self.assertEqual({p.name for p in output.iterdir()}, set(expected))
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for name, content in expected.items():
                emitted = output / name
                self.assertEqual(emitted.stat().st_mode & 0o777, 0o600)
                # assertTrue avoids embedding historical observations in unittest failures.
                self.assertTrue(emitted.read_bytes() == content, "Reproduced pair bytes differ")
                self.assertEqual(hashlib.sha256(emitted.read_bytes()).hexdigest(),
                                 admitted["pairHashes"][name], "Reproduced pair hash differs")
        self.assertEqual(snapshot(), before, "Inputs, selector or selected generation mutated")
        self.assertEqual(verified(), admitted, "Read-only verified identities changed")


if __name__ == "__main__":
    unittest.main()
