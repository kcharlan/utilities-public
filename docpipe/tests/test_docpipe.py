import argparse
from importlib.metadata import version
import sys
from pathlib import Path

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher
from tools.check_uv_headers import extract_pep723


DOCPIPE_PATH = Path(__file__).resolve().parents[1] / "docpipe"


def test_readability_dependency_excludes_unsupported_09_and_resolves_in_range():
    metadata = extract_pep723(DOCPIPE_PATH.read_text(encoding="utf-8"))
    requirements = [Requirement(item) for item in metadata["dependencies"]]
    readability = next(item for item in requirements if item.name == "readability-lxml")
    assert "0.8.4.1" in readability.specifier
    assert "0.9" not in readability.specifier
    assert version("readability-lxml") in readability.specifier


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


def test_pdf_rerun_uses_only_new_page_images(monkeypatch, tmp_path):
    module = load_docpipe_module()
    assets = tmp_path / 'sample.assets'
    assets.mkdir()
    (assets / 'page-001.png').write_bytes(b'stale')
    monkeypatch.setattr(module, 'HAS_PDFTOTEXT', True)
    monkeypatch.setattr(module, 'HAS_PDFTOPPM', True)
    def run(cmd, timeout):
        if cmd[0] == 'pdftotext':
            Path(cmd[-1]).write_text('new page')
        else:
            Path(cmd[-1] + '-1.png').write_bytes(b'new')
    monkeypatch.setattr(module, 'run_cmd', run)
    source = tmp_path / 'synthetic.pdf'
    source.write_bytes(b'synthetic')
    result = module.convert_pdf(str(source), 'sample', str(tmp_path), True, 50)
    assert len(result.segments[0].assets) == 1
    assert (tmp_path / result.segments[0].assets[0].path).read_bytes() == b'new'


def test_xlsx_load_failure_returns_failure(monkeypatch, tmp_path):
    import zipfile
    module = load_docpipe_module()
    input_path = tmp_path / 'bad.xlsx'
    with zipfile.ZipFile(input_path, 'w') as archive:
        archive.writestr('synthetic.txt', 'not a workbook')
    attempted = []
    def fail_workbook(path, **kwargs):
        attempted.append(path)
        raise ValueError('synthetic workbook failure')
    monkeypatch.setattr(module.openpyxl, 'load_workbook', fail_workbook)
    result = module.run_convert(make_args(input_path, tmp_path / 'out', False))
    assert attempted == [str(input_path)]
    assert result != 0
    assert not (tmp_path / 'out' / 'bad.opencode.md').exists()
    assert not (tmp_path / 'out' / 'bad.opencode.json').exists()


def test_pdf_without_text_extractor_is_failure(monkeypatch, tmp_path):
    module = load_docpipe_module()
    monkeypatch.setattr(module, 'HAS_PDFTOTEXT', False)
    source = tmp_path / 'sample.pdf'
    source.write_bytes(b'synthetic')
    assert module.run_convert(make_args(source, tmp_path / 'out', False)) != 0


def test_invalid_docx_without_fallback_is_failure(monkeypatch, tmp_path):
    import zipfile
    module = load_docpipe_module()
    monkeypatch.setattr(module, 'HAS_PANDOC', False)
    source = tmp_path / 'sample.docx'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('synthetic.txt', 'not a document')
    attempted = []
    def fail_document(path):
        attempted.append(path)
        raise ValueError('synthetic parse failure')
    monkeypatch.setattr(module.docx, 'Document', fail_document)
    assert module.run_convert(make_args(source, tmp_path / 'out', False)) != 0
    assert attempted


def test_rejects_oversized_expanded_office_file(monkeypatch, tmp_path):
    import zipfile
    module = load_docpipe_module()
    monkeypatch.setattr(module, 'MAX_OFFICE_EXPANDED_BYTES', 32, raising=False)
    source = tmp_path / 'synthetic.docx'
    with zipfile.ZipFile(source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', b'x' * 64)
    monkeypatch.setattr(module, 'HAS_PANDOC', False)
    # A real parser would allocate expanded members before discovering malformed content.
    called = []
    monkeypatch.setattr(module.docx, 'Document', lambda path: called.append(path))
    assert module.run_convert(make_args(source, tmp_path / 'out', False)) != 0
    assert not called


def test_pdf_image_output_can_be_on_another_filesystem(monkeypatch, tmp_path):
    import errno
    module = load_docpipe_module()
    monkeypatch.setattr(module, 'HAS_PDFTOTEXT', True)
    monkeypatch.setattr(module, 'HAS_PDFTOPPM', True)
    def run(cmd, timeout):
        if cmd[0] == 'pdftotext':
            Path(cmd[-1]).write_text('page')
        else:
            Path(cmd[-1] + '-1.png').write_bytes(b'page image')
    monkeypatch.setattr(module, 'run_cmd', run)
    monkeypatch.setattr(Path, 'rename', lambda *args: (_ for _ in ()).throw(OSError(errno.EXDEV, 'cross-device')))
    source = tmp_path / 'sample.pdf'
    source.write_bytes(b'synthetic')
    result = module.convert_pdf(str(source), 'sample', str(tmp_path), True, 50)
    assert (tmp_path / result.segments[0].assets[0].path).read_bytes() == b'page image'


def test_strict_rejects_actual_xlsx_cell_limit_warning(tmp_path):
    import openpyxl
    module = load_docpipe_module()
    workbook = openpyxl.Workbook()
    workbook.active.append(['synthetic', 'cells'])
    source = tmp_path / 'sample.xlsx'
    workbook.save(source)
    args = make_args(source, tmp_path / 'out', True)
    args.xlsx_max_cells = 1
    assert module.run_convert(args) == 2
    assert not (tmp_path / 'out' / 'sample.opencode.md').exists()
