from __future__ import annotations

from pathlib import Path

from cognitive_switchyard.html_template import render_app_html
from tools.testkit import assert_frontend_vendor_current, assert_launcher_compiles_cleanly, assert_offline_page_source


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_render_app_html_embeds_offline_frontend() -> None:
    html = render_app_html({"ok": True})
    assert_offline_page_source(html)
    assert_frontend_vendor_current(PROJECT_ROOT / "cognitive_switchyard" / "html_template.py")
    assert_launcher_compiles_cleanly(PROJECT_ROOT / "cognitive_switchyard" / "html_template.py")


def test_render_app_html_escapes_bootstrap_json_for_inline_use() -> None:
    html = render_app_html(
        {
            "danger": "</script><script>alert('xss')</script>",
            "ampersand": "A&B",
        }
    )

    assert "</script><script>alert('xss')</script>" not in html
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert('xss')\\u003c/script\\u003e" in html
    assert "A\\u0026B" in html


def test_render_app_html_uses_valid_single_brace_css_and_react_syntax() -> None:
    html = render_app_html({"ok": True})

    assert "body {" in html
    assert "const {useEffect, useLayoutEffect, useMemo, useRef, useState} = preactHooks;" in html
    assert "body {{" not in html
    assert "const {{ useEffect, useMemo, useRef, useState }} = React;" not in html
    assert "window.location.reload" not in html
