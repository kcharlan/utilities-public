import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "routerview"


def load_module():
    return load_launcher(SCRIPT_PATH)


def test_chart_tooltip_includes_bucket_totals_for_additive_metrics():
    module = load_module()

    assert "function sumTooltipValues(items)" in module.HTML_TEMPLATE
    assert "const showTotals = metric!=='latency';" in module.HTML_TEMPLATE
    assert "const primaryTotal = sumTooltipValues(primary);" in module.HTML_TEMPLATE
    assert "const compTotal = sumTooltipValues(comp);" in module.HTML_TEMPLATE
    assert '<span className="font-medium text-slate-300">Total</span>' in module.HTML_TEMPLATE


def test_chart_tooltip_sorts_cost_rows_descending():
    module = load_module()

    assert "function sortTooltipItems(items, metric)" in module.HTML_TEMPLATE
    assert "if(metric!=='cost') return items;" in module.HTML_TEMPLATE
    assert "return [...items].sort((a,b)=>(Number(b?.value)||0)-(Number(a?.value)||0));" in module.HTML_TEMPLATE
    assert "const orderedPrimary = sortTooltipItems(primary, metric);" in module.HTML_TEMPLATE
    assert "const orderedComp = sortTooltipItems(comp, metric);" in module.HTML_TEMPLATE


def test_csv_import_triggers_dashboard_refresh():
    module = load_module()

    assert "function SettingsPanel({onClose,onImportComplete})" in module.HTML_TEMPLATE
    assert "fd.append('file',file);" in module.HTML_TEMPLATE
    # Client should no longer send a timezone with CSV uploads — OpenRouter
    # exports are UTC and are recovered from the gen-ID epoch server-side.
    assert "fd.append('tz'," not in module.HTML_TEMPLATE
    assert "if(d.status==='ok') onImportComplete?.();" in module.HTML_TEMPLATE
    assert "<SettingsPanel onClose={()=>setShowSettings(false)} onImportComplete={()=>{fetchData();fetchLog();}}/>" in module.HTML_TEMPLATE
    assert "/api/admin/rebuild-timestamps?confirm=true" in module.HTML_TEMPLATE


def test_frontend_removes_live_observability_controls():
    module = load_module()

    assert "Fetch from API" not in module.HTML_TEMPLATE
    assert "function SetupWizard(" not in module.HTML_TEMPLATE
    assert "new WebSocket(" not in module.HTML_TEMPLATE
    assert "wsConnected?'Live':'Disconnected'" not in module.HTML_TEMPLATE


def test_header_shows_selected_preset_with_resolved_range():
    module = load_module()

    assert "function formatResolvedRange(fromIso,toIso,tz)" in module.HTML_TEMPLATE
    assert "const activeRangeLabel = RANGE_OPTS.find(o=>o.v===timeRange)?.l||'Custom Range';" in module.HTML_TEMPLATE
    assert "const resolvedRange = summary?.from&&summary?.to ? formatResolvedRange(summary.from, summary.to, tz) : null;" in module.HTML_TEMPLATE
    assert "<Header" in module.HTML_TEMPLATE
    assert "summary={summary}" in module.HTML_TEMPLATE


def test_rebuild_timestamps_button_wired_in_settings_panel():
    module = load_module()

    # Exact rendered string. Uses a template literal so apostrophes do not break
    # the surrounding single-quoted JS context — regressing this to a single-
    # quoted string with a bare apostrophe produced a Babel syntax error that
    # blanked the UI.
    assert (
        "`Rebuild created_at for every generation from its gen-ID epoch? "
        "The database will be backed up to ~/.routerview/backups/ first.`"
    ) in module.HTML_TEMPLATE
    assert "setRebuilding(true);" in module.HTML_TEMPLATE
    assert ">{rebuilding?'Rebuilding...':'Rebuild Timestamps'}<" in module.HTML_TEMPLATE


def _first_arg_literal(source: str, start: int):
    """Walk the first argument to a call starting at ``start`` (which points at
    the character after the opening ``(``), assuming the argument is a JS
    string literal. Returns ``(kind, end_index, error)`` where ``kind`` is
    ``'single'``, ``'double'``, ``'backtick'``, or ``None``; ``end_index`` is
    the index of the character just past the closing quote; and ``error`` is
    a short description if the literal is unterminated.
    """
    i = start
    while i < len(source) and source[i] in " \t":
        i += 1
    if i >= len(source) or source[i] not in "'\"`":
        return None, i, None
    quote = source[i]
    kind = {"'": "single", '"': "double", "`": "backtick"}[quote]
    i += 1
    while i < len(source):
        c = source[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return kind, i + 1, None
        # Single- and double-quoted JS string literals may not contain a raw
        # newline. Template literals (backtick) may.
        if c == "\n" and quote != "`":
            return kind, i, "unterminated_before_newline"
        i += 1
    return kind, i, "unterminated_at_eof"


def test_alert_and_confirm_calls_have_balanced_string_literals():
    """Scan every ``confirm(...)`` / ``alert(...)`` call in the inline Babel
    script and verify its first argument, when a string literal, is both
    terminated AND followed by a valid post-expression token.

    This catches the bug where an unescaped apostrophe inside a single-quoted
    string (e.g. ``'generation's'``) closes the string early, leaving stray
    tokens (``s`` here) that break Babel parsing and blank the UI.
    """
    import re

    module = load_module()
    src = module.HTML_TEMPLATE
    problems = []
    for m in re.finditer(r"\b(confirm|alert)\(", src):
        kind, end_i, err = _first_arg_literal(src, m.end())
        line = src[: m.start()].count("\n") + 1
        if err:
            problems.append((line, m.group(1), kind, err))
            continue
        if kind is None:
            continue  # First arg wasn't a string literal; skip.
        j = end_i
        while j < len(src) and src[j] in " \t":
            j += 1
        # After the closing quote, the only valid continuations are:
        #   "," (another arg), ")" (end of call), "+" / "." / etc (expression
        #   operators). A letter/digit/underscore means an unescaped-apostrophe
        #   leaked a bare identifier into the source.
        if j < len(src) and (src[j].isalnum() or src[j] == "_"):
            problems.append((line, m.group(1), kind, f"stray_token_{src[j]!r}_after_close"))
    assert not problems, (
        "JS string literal issue in " + ", ".join(
            f"{n}()@L{l} ({k}: {e})" for l, n, k, e in problems
        )
    )
