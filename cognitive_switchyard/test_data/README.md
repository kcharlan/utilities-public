# Test Data: Intake Files for End-to-End Pipeline Testing

These intake files are designed to test the full cognitive_switchyard pipeline
against THIS repository. All file references point to `cognitive_switchyard/`
source files.

## Files

- `001_reorder_topbar_setup_first.md` — Simple UI reorder task (~10 min scope).
  Touches `html_template.py` only. Tests basic planning + execution flow.
- `002_auto_generate_intake_claude_md.md` — Multi-file feature (~30 min scope).
  Touches `config.py`, `state.py`, `server.py`. Tests planning with
  cross-file scope analysis and resolution.
- `NEXT_SEQUENCE` — Sequence counter (value: 3).

## Usage

Copy intake files to a session's `intake/` directory before starting:

```bash
# With the server running (COGNITIVE_SWITCHYARD_NO_BROWSER=1 to skip browser):
COGNITIVE_SWITCHYARD_NO_BROWSER=1 ./switchyard serve

# Then via API:
curl -X POST http://localhost:8100/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"id":"test-run","name":"Test Run","pack":"claude-code","config":{"environment":{"COGNITIVE_SWITCHYARD_REPO_ROOT":"/path/to/repo"}}}'

# Copy intake files:
cp test_data/001_*.md test_data/002_*.md ~/.cognitive_switchyard/sessions/test-run/intake/

# Start the session:
curl -X POST http://localhost:8100/api/sessions/test-run/start
```
