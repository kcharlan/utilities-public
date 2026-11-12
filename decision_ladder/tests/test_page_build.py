def test_page_escapes_embedded_data(dl):
    page = dl.render_page({"name": "</script><b>synthetic</b>"}).decode()
    assert "</script><b>synthetic</b>" not in page
    assert "\\u003c/script>" in page
