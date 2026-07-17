"""Regression tests for the background sampler heartbeat in the execute script.

The background sampler in the claude-code execute script (lines 59–103) emits
##PROGRESS## detail lines when NDJSON output appears. When the subprocess
produces no new output (e.g. during long-running pytest or compilation), the
sampler previously emitted nothing — allowing the orchestrator's idle timer
to fire and kill the worker.

Fix (plan 002): an `else` branch was added so the sampler emits a heartbeat
line when the line count is unchanged:

    else
      echo "##PROGRESS## $TASK_ID | Detail: Working... (no new output)"
    fi

These tests verify:
  1. The heartbeat line is emitted when the NDJSON file is static.
  2. The heartbeat is NOT emitted on the iteration where new output appears
     (the `if` branch fires instead and emits real detail).
"""
from __future__ import annotations

import subprocess
import textwrap
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared sampler loop snippet
# ---------------------------------------------------------------------------

# This shell fragment is extracted from lines 59–103 of the execute script.
# It is self-contained: the caller sets TASK_ID, CLAUDE_OUTPUT_FILE, and
# SAMPLER_STOP_FILE as environment variables before sourcing it.
# We keep a copy here (rather than sourcing the full execute script) so the
# test is not coupled to the full script's setup/teardown machinery.
_SAMPLER_SNIPPET = textwrap.dedent("""\
    _LAST_LINE_COUNT=0
    while [ ! -f "$SAMPLER_STOP_FILE" ]; do
      _i=0
      while [ "$_i" -lt 6 ] && [ ! -f "$SAMPLER_STOP_FILE" ]; do
        sleep 0.5
        _i=$((_i + 1))
      done
      [ -f "$SAMPLER_STOP_FILE" ] && break
      [ -f "$CLAUDE_OUTPUT_FILE" ] || continue
      _CURRENT_COUNT=$(wc -l < "$CLAUDE_OUTPUT_FILE" 2>/dev/null | tr -d ' ' || echo 0)
      if [ "$_CURRENT_COUNT" -gt "$_LAST_LINE_COUNT" ] 2>/dev/null; then
        _LAST_LINE=$(tail -1 "$CLAUDE_OUTPUT_FILE" 2>/dev/null || true)
        if [ -n "$_LAST_LINE" ]; then
          _DETAIL=$(printf '%s' "$_LAST_LINE" | python3 -c "
import sys, json
try:
    obj = json.load(sys.stdin)
    t = obj.get('type', '')
    if t == 'system':
        print('CLI initialized')
    elif t == 'assistant':
        content = obj.get('message', {}).get('content', [])
        tools = [b['name'] for b in content if isinstance(b, dict) and b.get('type') == 'tool_use']
        if tools:
            print(('Using: ' + ', '.join(tools[:4]))[:80])
        else:
            texts = [b['text'] for b in content if isinstance(b, dict) and b.get('type') == 'text' and b.get('text', '').strip()]
            if texts:
                print(texts[-1].strip().split('\\n')[0][:80])
    elif t == 'result':
        r = obj.get('result', '')
        if r:
            print(('Completed: ' + r.strip().split('\\n')[0])[:80])
except Exception:
    pass
" 2>/dev/null || true)
          if [ -n "$_DETAIL" ]; then
            echo "##PROGRESS## $TASK_ID | Detail: $_DETAIL"
          fi
        fi
        _LAST_LINE_COUNT=$_CURRENT_COUNT
      else
        echo "##PROGRESS## $TASK_ID | Detail: Working... (no new output)"
      fi
    done
""")


def _run_sampler(
    tmp_path: Path,
    ndjson_content: str,
    run_seconds: float = 4.5,
    task_id: str = "test-001",
) -> list[str]:
    """Run the sampler snippet in a subprocess for `run_seconds`, then stop it.

    The caller supplies the initial content of the NDJSON file. The file is
    not modified during the run (simulating a static output file).

    Returns the captured stdout lines.
    """
    output_file = tmp_path / "output.ndjson"
    stop_file = tmp_path / "sampler_stop"
    output_file.write_text(ndjson_content, encoding="utf-8")

    script = textwrap.dedent(f"""\
        #!/bin/sh
        set -eu
        export TASK_ID={task_id!r}
        export CLAUDE_OUTPUT_FILE={str(output_file)!r}
        export SAMPLER_STOP_FILE={str(stop_file)!r}
        {_SAMPLER_SNIPPET}
    """)

    proc = subprocess.Popen(
        ["sh", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Let the sampler run for the specified duration then touch the stop-file.
    time.sleep(run_seconds)
    stop_file.touch()

    try:
        stdout, _ = proc.communicate(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()

    return [line for line in stdout.splitlines() if line.strip()]


class TestSamplerHeartbeat:
    """Regression tests for the heartbeat else branch (plan 002)."""

    def test_heartbeat_emitted_when_no_new_output(self, tmp_path: Path) -> None:
        """Heartbeat line is emitted when the NDJSON file does not grow.

        Regression: before plan 002 the sampler produced no output when idle,
        allowing the orchestrator idle timer to kill the worker.
        """
        # Empty file — simulates Claude subprocess that hasn't written anything yet
        lines = _run_sampler(tmp_path, ndjson_content="", run_seconds=4.5)

        heartbeat_lines = [
            l for l in lines if "Working... (no new output)" in l
        ]
        assert heartbeat_lines, (
            "Expected at least one heartbeat line but got none.\n"
            f"All output lines: {lines!r}"
        )

        # Verify format: "##PROGRESS## test-001 | Detail: Working... (no new output)"
        for hb in heartbeat_lines:
            assert hb.startswith("##PROGRESS## test-001 | Detail: Working... (no new output)"), (
                f"Heartbeat line has unexpected format: {hb!r}"
            )

    def test_heartbeat_format_contains_task_id(self, tmp_path: Path) -> None:
        """Heartbeat line must embed the correct task ID."""
        lines = _run_sampler(
            tmp_path,
            ndjson_content="",
            run_seconds=4.5,
            task_id="my-task-007",
        )
        heartbeat_lines = [l for l in lines if "Working... (no new output)" in l]
        assert heartbeat_lines, "No heartbeat lines produced"
        for hb in heartbeat_lines:
            assert "my-task-007" in hb, f"Task ID missing from heartbeat: {hb!r}"

    def test_if_branch_fires_on_new_output_not_heartbeat(self, tmp_path: Path) -> None:
        """When new content is present from iteration 1, the if branch fires.

        The NDJSON file is pre-populated with a system line so _LAST_LINE_COUNT
        starts at 0 and _CURRENT_COUNT = 1 on the first sample. The if branch
        should fire and emit 'CLI initialized'; the heartbeat should NOT appear
        on that same iteration.

        Note: after the first iteration _LAST_LINE_COUNT catches up to 1, so
        subsequent iterations enter the else/heartbeat branch. The assertion is
        therefore that the very first ##PROGRESS## line is 'CLI initialized',
        not the heartbeat.
        """
        system_line = '{"type":"system","subtype":"init","session_id":"abc"}\n'
        lines = _run_sampler(tmp_path, ndjson_content=system_line, run_seconds=4.5)

        progress_lines = [l for l in lines if l.startswith("##PROGRESS##")]
        assert progress_lines, "No ##PROGRESS## lines produced at all"

        first = progress_lines[0]
        assert "CLI initialized" in first, (
            f"Expected first ##PROGRESS## line to contain 'CLI initialized' "
            f"(from if branch), got: {first!r}"
        )
