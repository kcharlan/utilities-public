"""External-output/acquisition contracts; all row fixtures are invented."""
import argparse
import io
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from test_compile_market_data import compiler


def native_xattr(*args):
    return subprocess.check_output(["/usr/bin/xattr", *map(str, args)]).rstrip(b"\n")


class ExternalCompilerTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "native macOS metadata preservation")
    def test_existing_attributes_are_accepted_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp).resolve() / "invented output"
            output.mkdir(mode=0o755)
            target = output / "market-data.js"
            target.write_bytes(b"invented original output")
            target.chmod(0o644)
            attribute = "com.example.market-atlas-invented"
            native_xattr("-w", attribute, "invented metadata", target)
            self.assertEqual(compiler.validate_output_dir(output), output)
            self.assertEqual(target.read_bytes(), b"invented original output")
            self.assertEqual(native_xattr("-p", attribute, target), b"invented metadata")

    def test_manual_hardlinked_workbook_is_read_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "invented-workbook.xls"
            source.write_bytes(b"invented workbook bytes")
            os.link(source, root / "invented-alias.xls")
            with mock.patch.object(compiler, "validate_workbook"), mock.patch.object(compiler, "open_source") as opener:
                self.assertEqual(compiler.acquire_source("Shiller", compiler.SHILLER_URL, str(source), False), source)
            opener.assert_not_called()
            self.assertEqual(source.read_bytes(), b"invented workbook bytes")

    def test_cli_requires_output_and_pins_selected_end_year(self):
        with mock.patch.object(compiler.sys, "argv", ["compiler"]), mock.patch.object(compiler.sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                compiler.parse_args()
        with mock.patch.object(compiler.sys, "argv", ["compiler", "--output-dir", "/synthetic/output"]):
            args = compiler.parse_args()
        self.assertEqual(args.output_dir, "/synthetic/output")
        self.assertEqual(args.end_year, 2025)

    def test_acquire_only_finishes_before_any_transform_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            args = argparse.Namespace(output_dir=str(root), damodaran=None, shiller=None,
                                      refresh=False, end_year=2025, generated_date="2026-10-01",
                                      acquire_only=True)
            with (mock.patch.object(compiler, "parse_args", return_value=args),
                  mock.patch.object(compiler, "acquire_source", side_effect=[root / "invented-d.xls", root / "invented-s.xls"]) as acquire,
                  mock.patch.object(compiler, "parse_damodaran", side_effect=AssertionError("transform must not run")) as parse,
                  mock.patch.object(compiler, "emit") as emit,
                  mock.patch.object(compiler.sys, "stdout", io.StringIO()),
                  mock.patch.object(compiler.sys, "stderr", io.StringIO())):
                self.assertEqual(compiler.main(), 0)
            self.assertEqual(acquire.call_count, 2)
            parse.assert_not_called()
            emit.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_cli_explicitly_supports_acquisition_without_compilation(self):
        with mock.patch.object(compiler.sys, "argv", ["compiler", "--output-dir", "/invented/output", "--acquire-only"]):
            self.assertTrue(compiler.parse_args().acquire_only)

    def test_acquire_only_validates_manual_sources_and_preserves_existing_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            inputs = {name: root / (name + ".xls") for name in ("damodaran", "shiller")}
            pair = {name: b"invented previous output " + name.encode()
                    for name in ("market-data.js", "market-data.csv")}
            for name, content in pair.items():
                (root / name).write_bytes(content)
                (root / name).chmod(0o600)
            for path in inputs.values():
                path.write_bytes(b"invented read-only manual source")
                path.chmod(0o644)
            argv = ["compiler", "--acquire-only", "--output-dir", str(root),
                    "--damodaran", str(inputs["damodaran"]), "--shiller", str(inputs["shiller"])]
            with (mock.patch.object(compiler.sys, "argv", argv),
                  mock.patch.object(compiler, "validate_workbook") as validate,
                  mock.patch.object(compiler, "open_source") as opener,
                  mock.patch.object(compiler, "parse_damodaran") as parse,
                  mock.patch.object(compiler, "emit") as emit,
                  mock.patch.object(compiler.sys, "stdout", io.StringIO())):
                self.assertEqual(compiler.main(), 0)
            self.assertEqual(validate.call_args_list, [mock.call("Damodaran", inputs["damodaran"]),
                                                       mock.call("Shiller", inputs["shiller"])])
            opener.assert_not_called()
            parse.assert_not_called()
            emit.assert_not_called()
            for name, content in pair.items():
                self.assertEqual((root / name).read_bytes(), content)
            for path in inputs.values():
                self.assertEqual(path.read_bytes(), b"invented read-only manual source")
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_acquire_only_partial_acquisition_failure_never_changes_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            pair = {name: b"invented old paired output " + name.encode()
                    for name in ("market-data.js", "market-data.csv")}
            for name, content in pair.items():
                (root / name).write_bytes(content)
                (root / name).chmod(0o600)
            acquired = root / "invented-successful-input.xls"
            acquired.write_bytes(b"invented first acquisition")
            acquired.chmod(0o600)
            args = argparse.Namespace(output_dir=str(root), damodaran=None, shiller=None,
                                      refresh=False, acquire_only=True)
            with (mock.patch.object(compiler, "parse_args", return_value=args),
                  mock.patch.object(compiler, "acquire_source", side_effect=[acquired, RuntimeError("invented second acquisition failure")]),
                  mock.patch.object(compiler, "parse_damodaran") as parse,
                  mock.patch.object(compiler, "emit") as emit,
                  mock.patch.object(compiler.sys, "stderr", io.StringIO())):
                self.assertEqual(compiler.main(), 1)
            parse.assert_not_called()
            emit.assert_not_called()
            self.assertEqual(acquired.read_bytes(), b"invented first acquisition")
            for name, content in pair.items():
                self.assertEqual((root / name).read_bytes(), content)

    def test_selected_end_year_rejects_unsupported_or_missing_years(self):
        rows = [{"year": year} for year in range(1872, 2027)]
        self.assertEqual(len(compiler.select_output_rows(rows, 2025)), 154)
        for year in (2024, 2026, True):
            with self.subTest(year=year), self.assertRaisesRegex(ValueError, "end year"):
                compiler.select_output_rows(rows, year)
        with self.assertRaisesRegex(ValueError, "end year"):
            compiler.select_output_rows(rows[:-2], 2025)

    def test_output_rejects_repo_webroot_aliases_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            repo = root / "repo"
            webroot = root / "webroot"
            repo.mkdir(); webroot.mkdir()
            alias = root / "alias"
            alias.symlink_to(repo, target_is_directory=True)
            outside = root / "outside"
            outside.mkdir()
            external_alias = root / "external-alias"
            external_alias.symlink_to(outside, target_is_directory=True)
            with mock.patch.object(compiler, "REPOSITORY_ROOT", repo), mock.patch.object(compiler, "WEBROOT", webroot):
                for path in (repo / "data", webroot / "out", alias / "out", external_alias / "out",
                             external_alias / ".." / "new-output"):
                    with self.subTest(path=path.name), self.assertRaises(ValueError):
                        compiler.validate_output_dir(path)
                self.assertEqual(compiler.validate_output_dir(outside / "space output"), outside / "space output")

    def test_output_refuses_symlink_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            output = root / "output"
            output.mkdir(mode=0o700)
            (output / "market-data.js").symlink_to(root / "unrelated")
            with self.assertRaisesRegex(ValueError, "regular"):
                compiler.validate_output_dir(output)
            self.assertFalse((root / "unrelated").exists())

    def test_readable_output_and_cache_modes_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            output = root / "output"
            cache = root / "cache"
            output.mkdir(mode=0o700); cache.mkdir(mode=0o700)
            controlled = output / "market-data.js"
            cached = cache / "ie_data.xls"
            controlled.write_bytes(b"synthetic old output")
            cached.write_bytes(b"synthetic cached workbook")
            cached.chmod(0o600)
            for mode in (0o644, 0o700):
                os.chmod(controlled, mode)
                os.chmod(cached, mode)
                with self.subTest(mode=mode):
                    self.assertEqual(compiler.validate_output_dir(output), output)
                with (self.subTest(cacheMode=mode),
                      mock.patch.object(compiler, "CACHE", cache),
                      mock.patch.object(compiler, "validate_workbook"),
                      mock.patch.object(compiler, "open_source") as opener):
                    self.assertEqual(compiler.acquire_source("Shiller", compiler.SHILLER_URL, None, False), cached)
                opener.assert_not_called()
                self.assertEqual(controlled.stat().st_mode & 0o777, mode)
                self.assertEqual(cached.stat().st_mode & 0o777, mode)
            os.chmod(controlled, 0o600); os.chmod(cached, 0o600)
            self.assertEqual(compiler.validate_output_dir(output), output)
            with mock.patch.object(compiler, "CACHE", cache), mock.patch.object(compiler, "validate_workbook"):
                self.assertEqual(compiler.acquire_source("Shiller", compiler.SHILLER_URL, None, False), cached)

    def test_manual_read_only_input_need_not_have_controlled_file_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp).resolve() / "synthetic-manual.xls"
            source.write_bytes(b"synthetic manually supplied workbook")
            os.chmod(source, 0o644)
            with mock.patch.object(compiler, "validate_workbook"), mock.patch.object(compiler, "open_source") as opener:
                self.assertEqual(compiler.acquire_source("Shiller", compiler.SHILLER_URL, str(source), False), source)
            self.assertEqual(source.stat().st_mode & 0o777, 0o644)
            opener.assert_not_called()

    def test_explicit_output_is_private_and_date_reproduction_is_exact(self):
        rows = [{"year": 1928, "stock_tr": 0.1, "bond10_tr": 0.02, "tbill_tr": 0.03,
                 "cpi_change": 0.04, "quality": "ok"}]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp).resolve() / "synthetic output"
            compiler.emit(rows, "2026-08-20", output)
            first = {p.name: p.read_bytes() for p in output.iterdir()}
            compiler.emit(rows, "2026-08-20", output)
            self.assertEqual(first, {p.name: p.read_bytes() for p in output.iterdir()})
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir()))

    def test_full_controls_run_before_output_selection(self):
        rows = [{"year": year} for year in range(1872, 2027)]
        args = argparse.Namespace(damodaran=None, shiller=None, refresh=False,
                                  generated_date="2026-08-20", output_dir="/synthetic/output", end_year=2025)
        order = []
        with (mock.patch.object(compiler, "parse_args", return_value=args),
              mock.patch.object(compiler, "validate_output_dir", return_value=Path(args.output_dir)),
              mock.patch.object(compiler, "acquire_source", side_effect=[Path("d.xls"), Path("s.xls")]),
              mock.patch.object(compiler, "parse_damodaran", return_value=({2026: {}}, None)),
              mock.patch.object(compiler, "parse_shiller", return_value={}),
              mock.patch.object(compiler, "verify_damodaran_anchor", side_effect=lambda *_: order.append("anchor")),
              mock.patch.object(compiler, "reconcile", side_effect=lambda *_: order.append("reconcile")),
              mock.patch.object(compiler, "splice", return_value=rows),
              mock.patch.object(compiler, "select_output_rows", side_effect=lambda rows, year: (order.append("select") or rows[:-1])),
              mock.patch.object(compiler, "emit") as emit,
              mock.patch.object(compiler.sys, "stdout", io.StringIO())):
            self.assertEqual(compiler.main(), 0)
        self.assertEqual(order, ["anchor", "reconcile", "select"])
        emit.assert_called_once_with(rows[:-1], "2026-08-20", Path(args.output_dir))

    def test_redirects_are_https_and_source_confined_before_opening(self):
        handler = compiler.OfficialRedirectHandler("Shiller")
        request = urllib.request.Request(compiler.SHILLER_URL)
        for target in ("http://img1.wsimg.com/data.xls", "https://example.invalid/data.xls",
                       "https://user:password@img1.wsimg.com/data.xls"):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "endpoint"):
                handler.redirect_request(request, None, 302, "Found", {}, target)
        redirected = handler.redirect_request(request, None, 302, "Found", {}, "https://img1.wsimg.com/approved.xls")
        self.assertEqual(redirected.full_url, "https://img1.wsimg.com/approved.xls")
        for url in ("http://pages.stern.nyu.edu/data.xls", "https://example.invalid/data.xls"):
            with self.assertRaisesRegex(ValueError, "endpoint"):
                compiler.validate_source_url("Damodaran", url)

    def test_shiller_cache_name_ignores_download_query(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp).resolve()
            cached = cache / "ie_data.xls"
            cached.write_bytes(b"invented legacy cache")
            cached.chmod(0o600)
            with mock.patch.object(compiler, "CACHE", cache), mock.patch.object(compiler, "validate_workbook"):
                self.assertEqual(compiler.acquire_source("Shiller", compiler.SHILLER_URL, None, False), cached)

    def test_cache_inside_forbidden_tree_fails_before_network_or_mkdir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            repo = root / "repo"
            repo.mkdir()
            cache = repo / "cache"
            with (mock.patch.object(compiler, "REPOSITORY_ROOT", repo),
                  mock.patch.object(compiler, "CACHE", cache),
                  mock.patch.object(compiler, "open_source") as opener):
                with self.assertRaisesRegex(ValueError, "outside"):
                    compiler.acquire_source("Shiller", compiler.SHILLER_URL, None, False)
            opener.assert_not_called()
            self.assertFalse(cache.exists())

    def test_configured_webroot_alias_is_forbidden(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            serving = root / "custom-serving"
            serving.mkdir()
            alias = root / "alias"
            alias.symlink_to(serving)
            with mock.patch.object(compiler, "CONFIGURED_WEBROOT", alias):
                with self.assertRaisesRegex(ValueError, "outside"):
                    compiler.validate_output_dir(serving / "output")

    def test_standalone_private_copy_cannot_emit_into_its_source_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "standalone-source"
            source.mkdir(mode=0o700)
            with mock.patch.object(compiler, "REPOSITORY_ROOT", None), mock.patch.object(compiler, "SOURCE_ROOT", source):
                with self.assertRaisesRegex(ValueError, "outside"):
                    compiler.validate_output_dir(source / "candidate")
                self.assertEqual(compiler.validate_output_dir(root / "candidate"), root / "candidate")

    def test_manual_symlink_is_not_followed_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            original = root / "synthetic-original.xls"
            original.write_bytes(b"invented workbook bytes")
            alias = root / "source.xls"
            alias.symlink_to(original)
            with mock.patch.object(compiler, "open_source") as opener:
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    compiler.acquire_source("Shiller", compiler.SHILLER_URL, str(alias), False)
            opener.assert_not_called()
            self.assertEqual(original.read_bytes(), b"invented workbook bytes")

    def test_existing_directory_modes_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp).resolve() / "ordinary output"
            output.mkdir(mode=0o755)
            os.chmod(output, 0o755)
            self.assertEqual(compiler.validate_output_dir(output), output)
            os.chmod(output, 0o777)
            self.assertEqual(compiler.validate_output_dir(output / "new-child"), output / "new-child")
            self.assertEqual(output.stat().st_mode & 0o777, 0o777)

    def test_network_opener_uses_confined_handler_and_bounded_timeout(self):
        request = urllib.request.Request(compiler.DAMODARAN_URL)
        with mock.patch.object(compiler.urllib.request, "build_opener") as build:
            compiler.open_source("Damodaran", request)
        self.assertIsInstance(build.call_args.args[0], compiler.OfficialRedirectHandler)
        build.return_value.open.assert_called_once_with(request, timeout=60)

    def test_failed_rollback_retains_last_good_backup_for_manual_recovery(self):
        rows = [{"year": 1928, "stock_tr": 0.1, "bond10_tr": 0.02, "tbill_tr": 0.03,
                 "cpi_change": 0.04, "quality": "ok"}]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp).resolve()
            js = output / "market-data.js"
            csv = output / "market-data.csv"
            js.write_text("synthetic old js"); csv.write_text("synthetic old csv")
            js.chmod(0o600); csv.chmod(0o600)
            replace = os.replace
            failed = False
            def fail_promotion_and_rollback(source, destination):
                nonlocal failed
                if Path(destination) == csv and not failed:
                    failed = True
                    raise OSError("injected promotion failure")
                if Path(destination) == js and failed:
                    raise OSError("injected rollback failure")
                replace(source, destination)
            with mock.patch.object(compiler.os, "replace", side_effect=fail_promotion_and_rollback):
                with self.assertRaisesRegex(RuntimeError, "rollback also failed"):
                    compiler.emit(rows, "2026-08-20", output)
            retained = [p for p in output.iterdir() if p.name not in (js.name, csv.name)]
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0].read_text(), "synthetic old js")
            self.assertEqual(retained[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(csv.read_text(), "synthetic old csv")

    def test_partial_second_backup_copy_cleans_owned_files_without_changing_pair(self):
        rows = [{"year": 1928, "stock_tr": 0.1, "bond10_tr": 0.02, "tbill_tr": 0.03,
                 "cpi_change": 0.04, "quality": "ok"}]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp).resolve()
            originals = {"market-data.js": b"synthetic old js", "market-data.csv": b"synthetic old csv"}
            for name, value in originals.items():
                file = output / name
                file.write_bytes(value); file.chmod(0o600)
            copy = compiler.shutil.copyfile
            calls = 0
            def partial_second_copy(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    Path(destination).write_bytes(b"synthetic partial backup")
                    raise OSError("injected second backup copy failure")
                return copy(source, destination)
            with mock.patch.object(compiler.shutil, "copyfile", side_effect=partial_second_copy):
                with self.assertRaisesRegex(OSError, "injected second backup copy failure"):
                    compiler.emit(rows, "2026-08-20", output)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, originals)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir()))

    def test_partial_candidate_write_cleans_owned_files_without_changing_pair(self):
        rows = [{"year": 1928, "stock_tr": 0.1, "bond10_tr": 0.02, "tbill_tr": 0.03,
                 "cpi_change": 0.04, "quality": "ok"}]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp).resolve()
            originals = {"market-data.js": b"synthetic old js", "market-data.csv": b"synthetic old csv"}
            for name, value in originals.items():
                file = output / name
                file.write_bytes(value); file.chmod(0o600)
            create = compiler.tempfile.NamedTemporaryFile
            calls = 0
            def candidate_file(*args, **kwargs):
                nonlocal calls
                handle = create(*args, **kwargs)
                calls += 1
                if calls == 2:
                    write = handle.write
                    def partial_write(contents):
                        write(contents[:10])
                        raise OSError("injected second candidate write failure")
                    handle.write = partial_write
                return handle
            with mock.patch.object(compiler.tempfile, "NamedTemporaryFile", side_effect=candidate_file):
                with self.assertRaisesRegex(OSError, "injected second candidate write failure"):
                    compiler.emit(rows, "2026-08-20", output)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, originals)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir()))


if __name__ == "__main__":
    unittest.main()
