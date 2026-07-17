import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


DOCPIPE_PATH = Path(__file__).resolve().parents[1] / "docpipe"


def load_docpipe_module():
    return load_launcher(DOCPIPE_PATH)


def make_args(input_path: Path, out_dir: Path, strict: bool):
    return argparse.Namespace(
        command="convert",
        input=str(input_path),
        out=str(out_dir),
        images=False,
        format="md+json",
        max_page_images=50,
        xlsx_max_cells=2_000_000,
        strict=strict,
        verbose=False,
    )


def make_result(module, src: str, src_type: str, warnings=None):
    return module.ConversionResult(
        source_path=src,
        source_type=src_type,
        sha256="testsha",
        converted_at="2026-02-19T00:00:00+00:00",
        converter_version=module.VERSION,
        segments=[module.Segment(id="p1", type="page", index=1, text="hello")],
        warnings=warnings or [],
    )


def test_parser_supports_strict_flag():
    module = load_docpipe_module()
    parser = module.build_parser()
    args = parser.parse_args(["convert", "--input", "in.html", "--out", "out", "--strict"])
    assert args.strict is True


def test_run_convert_strict_fails_when_warnings(monkeypatch, tmp_path):
    module = load_docpipe_module()
    input_path = tmp_path / "sample.html"
    input_path.write_text("<h1>x</h1>", encoding="utf-8")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(module, "detect_file_type", lambda _: "html")
    monkeypatch.setattr(
        module,
        "convert_html",
        lambda *_args, **_kwargs: make_result(module, str(input_path), "html", warnings=["degraded"]),
    )

    rc = module.run_convert(make_args(input_path, out_dir, strict=True))

    assert rc == 2
    assert not (out_dir / "sample.opencode.md").exists()
    assert not (out_dir / "sample.opencode.json").exists()


def test_run_convert_non_strict_writes_outputs_with_warnings(monkeypatch, tmp_path):
    module = load_docpipe_module()
    input_path = tmp_path / "sample.html"
    input_path.write_text("<h1>x</h1>", encoding="utf-8")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(module, "detect_file_type", lambda _: "html")
    monkeypatch.setattr(
        module,
        "convert_html",
        lambda *_args, **_kwargs: make_result(module, str(input_path), "html", warnings=["degraded"]),
    )

    rc = module.run_convert(make_args(input_path, out_dir, strict=False))

    assert rc == 0
    assert (out_dir / "sample.opencode.md").exists()
    assert (out_dir / "sample.opencode.json").exists()


def test_run_convert_strict_succeeds_without_warnings(monkeypatch, tmp_path):
    module = load_docpipe_module()
    input_path = tmp_path / "sample.html"
    input_path.write_text("<h1>x</h1>", encoding="utf-8")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(module, "detect_file_type", lambda _: "html")
    monkeypatch.setattr(
        module,
        "convert_html",
        lambda *_args, **_kwargs: make_result(module, str(input_path), "html", warnings=[]),
    )

    rc = module.run_convert(make_args(input_path, out_dir, strict=True))

    assert rc == 0
    assert (out_dir / "sample.opencode.md").exists()
    assert (out_dir / "sample.opencode.json").exists()
