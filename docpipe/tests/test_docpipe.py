import argparse
import json
import sys
from pathlib import Path

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher
from tools.check_uv_headers import extract_pep723


DOCPIPE_PATH = Path(__file__).resolve().parents[1] / "docpipe"


def test_readability_dependency_excludes_unsupported_09():
    metadata = extract_pep723(DOCPIPE_PATH.read_text(encoding="utf-8"))
    requirements = [Requirement(item) for item in metadata["dependencies"]]
    readability = next(item for item in requirements if item.name == "readability-lxml")
    assert "0.8.4.1" in readability.specifier
    assert "0.9" not in readability.specifier


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


def test_docx_content_control_text_is_extracted(tmp_path):
    from docx import Document
    from docx.oxml import OxmlElement

    doc = Document()
    doc.add_paragraph("Synthetic plain paragraph")
    paragraph = doc.add_paragraph("Synthetic controlled text")._p
    control, content = OxmlElement("w:sdt"), OxmlElement("w:sdtContent")
    paragraph.addprevious(control)
    content.append(paragraph)
    control.append(content)
    source, out = tmp_path / "sample.docx", tmp_path / "out"
    doc.save(source)

    assert load_docpipe_module().run_convert(make_args(source, out, strict=True)) == 0
    result = json.loads((out / "sample.opencode.json").read_text())
    segment = next(segment for segment in result["segments"] if segment["id"] == "p1")
    assert segment["text"] == "Synthetic plain paragraph\nSynthetic controlled text"


def test_pptx_group_shape_text_is_extracted(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    group = slide.shapes.add_group_shape()
    textbox = group.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1))
    textbox.text = "Synthetic grouped text"
    source, out = tmp_path / "sample.pptx", tmp_path / "out"
    presentation.save(source)

    assert load_docpipe_module().run_convert(make_args(source, out, strict=True)) == 0
    result = json.loads((out / "sample.opencode.json").read_text())
    segment = next(segment for segment in result["segments"] if segment["id"] == "s1")
    assert "Synthetic grouped text" in segment["text"]


def test_docx_heading_and_table_are_converted(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_heading("Synthetic Heading", level=1)
    doc.add_paragraph("Synthetic body")
    table = doc.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, (("H1", "H2"), ("a", "b"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    source, out = tmp_path / "sample.docx", tmp_path / "out"
    doc.save(source)

    assert load_docpipe_module().run_convert(make_args(source, out, strict=False)) == 0
    result = json.loads((out / "sample.opencode.json").read_text())
    segment = result["segments"][0]
    assert "## Synthetic Heading" in segment["text"]
    assert "Synthetic body" in segment["text"]
    assert segment["tables"][0]["csv"] == "H1,H2\r\na,b\r\n"


def test_pptx_title_body_table_and_notes_are_converted(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Synthetic Slide"
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text = "Synthetic body"
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    for row, values in zip(table.rows, (("H1", "H2"), ("a", "b"))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    slide.notes_slide.notes_text_frame.text = "Synthetic notes"
    source, out = tmp_path / "sample.pptx", tmp_path / "out"
    presentation.save(source)

    assert load_docpipe_module().run_convert(make_args(source, out, strict=False)) == 0
    result = json.loads((out / "sample.opencode.json").read_text())
    segment = next(item for item in result["segments"] if item["id"] == "s1")
    assert "Synthetic Slide" in segment["text"]
    assert "Synthetic body" in segment["text"]
    assert "**Speaker Notes:** Synthetic notes" in segment["text"]
    assert segment["tables"][0]["id"] == "s1_t1"
    assert segment["tables"][0]["csv"] == "H1,H2\r\na,b\r\n"


def test_xlsx_trims_trailing_rows_and_columns_but_keeps_inner_blanks(tmp_path):
    import openpyxl

    workbook = openpyxl.Workbook()
    alpha = workbook.active
    alpha.title = "Alpha"
    alpha.append(("name", "qty", "note"))
    alpha.append(("widget", None, "fake"))
    alpha["E6"].number_format = "0.00"
    workbook.create_sheet("Beta")["A1"] = "only"
    source, out = tmp_path / "sample.xlsx", tmp_path / "out"
    workbook.save(source)

    assert load_docpipe_module().run_convert(make_args(source, out, strict=False)) == 0
    result = json.loads((out / "sample.opencode.json").read_text())
    assert len(result["segments"]) == 2
    alpha, beta = result["segments"]
    assert alpha["text"].startswith("Sheet: Alpha (2 rows x 3 cols)")
    assert alpha["tables"][0]["csv"] == "name,qty,note\r\nwidget,,fake\r\n"
    assert beta["tables"][0]["csv"] == "only\r\n"


def test_html_heading_and_table_are_converted(tmp_path):
    source, out = tmp_path / "sample.html", tmp_path / "out"
    sentence = "Synthetic paragraph content describes an invented document for conversion."
    source.write_text(
        "<html><body><div><h1>Synthetic Page</h1><p>" + sentence * 5 + "</p>"
        "<table><caption>Synthetic data table for this invented document</caption>"
        "<tr><th>H1</th><th>H2</th></tr><tr><td>a</td><td>b</td></tr></table>"
        "<p>" + sentence * 5 + "</p></div></body></html>", encoding="utf-8"
    )

    assert load_docpipe_module().run_convert(make_args(source, out, strict=False)) == 0
    result = json.loads((out / "sample.opencode.json").read_text())
    segment = result["segments"][0]
    assert sentence in segment["text"]
    assert segment["tables"][0]["csv"] == "H1,H2\r\na,b\r\n"


def test_html_plain_text_fallback_warns_and_strict_rejects(monkeypatch, tmp_path):
    module = load_docpipe_module()
    sentence = "Synthetic paragraph content describes an invented document for conversion."
    source, out = tmp_path / "sample.html", tmp_path / "out"
    source.write_text("<html><body><p>" + sentence * 5 + "</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(module, "md_convert", lambda *args, **kwargs: "")
    monkeypatch.setattr(module, "HAS_PANDOC", False)

    result = module.convert_html(str(source), "sample", str(out))
    assert sentence in result.segments[0].text
    assert "HTML to Markdown conversion degraded: plain text only." in result.warnings
    assert module.run_convert(make_args(source, out, strict=True)) == 2
    assert not (out / "sample.opencode.md").exists()


def test_pdf_page_images_are_capped(monkeypatch, tmp_path):
    module = load_docpipe_module()
    monkeypatch.setattr(module, "HAS_PDFTOTEXT", True)
    monkeypatch.setattr(module, "HAS_PDFTOPPM", True)

    def run(cmd, timeout):
        if cmd[0] == "pdftotext":
            Path(cmd[-1]).write_text("one\x0ctwo")
        else:
            Path(cmd[-1] + "-1.png").write_bytes(b"synthetic first page")
            Path(cmd[-1] + "-2.png").write_bytes(b"synthetic second page")

    monkeypatch.setattr(module, "run_cmd", run)
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"synthetic")
    result = module.convert_pdf(str(source), "sample", str(tmp_path), True, 1)
    assert [segment.id for segment in result.segments if segment.assets] == ["p1"]
    assert sum(len(segment.assets) for segment in result.segments) == 1
    assert any("capped at 1" in warning for warning in result.warnings)
    assert [path.name for path in (tmp_path / "sample.assets").iterdir()] == ["page-001.png"]


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
    out = tmp_path / 'out'
    assert module.main(['convert', '--input', str(source), '--out', str(out),
                        '--strict', '--xlsx-max-cells', '1']) == 2
    assert not (out / 'sample.opencode.md').exists()
    assert not (out / 'sample.opencode.json').exists()
