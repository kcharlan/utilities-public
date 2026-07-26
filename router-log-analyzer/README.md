# Router Log Analyzer

`router_log_analyze.py` is a standalone NETGEAR router log analyzer with persistent SQLite-backed learning. It ingests PDF or UTF-8 plain-text log exports, tracks known devices and behavioral baselines over time, and reports:

- unknown or blocked-device activity
- DHCP and overall event-volume anomalies
- new, rare, or unusually timed event types
- changes in device and cluster behavior
- confirmed or probable internet-reset incidents

The current parser expects NETGEAR-style timestamps and square-bracketed event labels. See [Future Multi-Vendor Support](FUTURE_MULTI_VENDOR_SUPPORT.md) for the proposed parser boundary; that work is not implemented.

## Quick Start

The utility is intentionally portable. The main script is `router_log_analyze.py`.

After validating the repository version, copy it into a user-selected executable directory on `PATH`. The destination depends on the operating system and local conventions; common choices include `~/.local/bin`, `~/bin`, or a user scripts directory.

For example, on a system that uses `~/Library/Scripts`:

```sh
chmod +x router_log_analyze.py
cp router_log_analyze.py ~/Library/Scripts/router_log_analyze.py
```

Copying is the recommended runtime installation because it keeps the utility working if the repository is later moved or removed. A symlink can still be convenient during active development, but it intentionally couples the installed command to the repository checkout.

After copying, verify the installed command rather than only the repository file:

```sh
router_log_analyze.py --version
router_log_analyze.py --help
```

The launcher runs via [uv](https://docs.astral.sh/uv/) using a PEP 723 inline-metadata header. On the first run, uv resolves its PDF-parsing dependencies (`PyMuPDF`, `pypdf`) into its shared cache; that invocation may briefly hit the network. Its SQLite state lives under `~/.router-log-analyzer/` by default.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv`) — manages the Python interpreter and dependencies
- Network access on first run so uv can resolve `PyMuPDF` and `pypdf`

## Input Format

The parser accepts PDF files with extractable text and plain-text files. A log event must contain a NETGEAR timestamp in this form:

```text
Thursday, March 25, 2037 13:11:47
```

Event labels are read from square brackets. MAC addresses and IPv4 addresses are extracted when present. Exact duplicate events and DHCP repeats for the same MAC/IP within one second are suppressed.

## Baseline and Router Config

The analyzer requires an active baseline before normal log analysis can run. You can either import one ahead of time or pass a baseline JSON on the first analysis command.

If a `router-security-config.md` file lives next to the log file or baseline file, the script auto-detects and imports it unless you pass `--config` explicitly.

A baseline is a JSON object with a `devices` object. Device keys are MAC addresses; each value can name the device and provide initial ranges or timing expectations. For example:

```json
{
  "devices": {
    "02:00:00:00:00:01": {
      "name": "SYNTHETIC LAPTOP",
      "dhcp_per_day_range": [1, 4],
      "events_per_day": [2, 8],
      "active_hours": [8, 9, 17, 18]
    }
  }
}
```

Baseline imports activate a new learning epoch. Older runs remain in the database but are not mixed into the new epoch's learned profile.

## Usage

Import a baseline:

```zsh
router_log_analyze.py --import-baseline baseline.json
```

Import a router access-control export:

```zsh
router_log_analyze.py --import-config router-security-config.md
```

Analyze a log after a baseline has already been imported:

```zsh
router_log_analyze.py router-log.pdf
```

Replace a previously stored analysis of the same file after analyzer logic or policy changes:

```zsh
router_log_analyze.py router-log.pdf --reprocess
```

`--reprocess` atomically removes the matching stored run and writes the replacement. If analysis fails before the replacement commits, SQLite rolls back the removal and preserves the prior run.

Analyze a log and bootstrap the baseline in the same command:

```zsh
router_log_analyze.py router-log.pdf baseline.json
```

Use a specific SQLite database instead of the default:

```zsh
router_log_analyze.py router-log.pdf --db ./disposable-network.db
```

Emit JSON to standard output:

```zsh
router_log_analyze.py router-log.pdf --json
```

Write one or more report files:

```zsh
router_log_analyze.py router-log.pdf --report markdown,html,json --report-dir ./reports
```

Generated files are named from the log file, for example `router-log.report.md`. `--report text` prints to standard output; when `text` is combined with another format, it also writes a `.txt` report.

Export the active learned baseline:

```zsh
router_log_analyze.py --export-baseline learned-baseline.json
```

## Policy

The built-in policy controls learning windows, severity scoring, partial-run detection, cluster behavior, reset correlation, and finding/device/event overrides. The safest way to create an override is to export the effective policy, edit the JSON, and import it:

```zsh
router_log_analyze.py --export-policy policy.json
router_log_analyze.py --import-policy policy.json
```

An imported policy is merged over the built-in defaults and becomes active for subsequent analyses. Policy documents use `schema_version: 1`.

## State Storage

Persistent state lives under `~/.router-log-analyzer/` by default:

- `network.db` - learned baseline, imported config, and analysis history

Set `ROUTER_LOG_ANALYZER_HOME` to move the default runtime directory, or pass `--db` to select a database for one command:

```zsh
ROUTER_LOG_ANALYZER_HOME=~/.router-log-analyzer-lab router_log_analyze.py router-log.pdf
```

Python dependencies are managed by uv (declared in the launcher's PEP 723 header) and cached in uv's shared cache, not under `~/.router-log-analyzer/`.

The file content hash identifies an analyzed run. Re-analyzing identical bytes produces a fresh report but does not add duplicate learning rows. Use `--reprocess` when the stored run should be atomically replaced after analyzer or policy changes.

## Learning Behavior

- Frequent device metrics use a seven-day rolling window; sparse event behavior uses a 28-day window under the default policy.
- Runs spanning less than 20 hours are treated as partial and excluded from learning by default.
- Days containing reset-attributed activity, blocked devices, or high/critical findings are quarantined from the affected learned profiles.
- Stable metric-only DHCP or event-volume changes can still enter future metric calculations so the baseline can adapt.
- The tool is self-contained and does not import local modules from this repository at runtime.

## Internet Reset Correlation

The analyzer treats a completed internet disconnect/reconnect sequence followed by synchronized activity from known allowed devices as one network-level recovery incident. DHCP leases and successful WLAN reconnections inside the recovery window remain visible in raw report totals, but they are removed from device-level anomaly analysis so one router reset does not become dozens of independent findings.

When the router does not export explicit internet transition events, the analyzer can infer a probable reset from a stronger synchronized DHCP/WLAN recovery burst. An unresolved disconnect is never treated as a benign reset.

Incident attribution is deliberately limited to `DHCP_IP` and `WLAN_ACCESS_ALLOWED` events from known allowed devices. Unknown devices, blocked devices, WLAN rejections, and administrative or security events remain independently actionable even when they occur during a reset.

The default incident policy can be customized through an imported partial policy document. For example:

```json
{
  "schema_version": 1,
  "network_incidents": {
    "enabled": true,
    "merge_gap_seconds": 300,
    "recovery_lookback_seconds": 300,
    "recovery_window_seconds": 300,
    "minimum_known_devices": 5,
    "minimum_known_device_fraction": 0.25,
    "inferred_window_seconds": 300,
    "inferred_minimum_known_devices": 8,
    "inferred_minimum_known_device_fraction": 0.5,
    "inferred_require_dhcp": true,
    "confirmed_severity": "low",
    "probable_severity": "low"
  }
}
```

Raw reset-day statistics are retained in SQLite for auditability. Rows containing incident-attributed behavior are excluded from ordinary baseline learning so recovery activity does not inflate future expectations. Each incident is also stored in the `network_incidents` table with its evidence, affected devices, and event breakdown.

## Tests

```zsh
cd /path/to/utilities-public/router-log-analyzer
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

`requirements-dev.txt` reproduces the launcher's PDF dependencies and adds pytest.

## Updating An Installed Copy

An installed copy is not updated automatically when this repository changes. Use this release sequence:

1. Run the complete project test suite shown above.
2. Run any repository-level launcher validation required by the checkout.
3. Only after all validation succeeds, copy `router_log_analyze.py` over the installed runtime copy in the user's chosen executable directory.
4. Run the installed command's `--version` and `--help`, then perform a safe analysis against a disposable database copy when the change affects analysis or persistence behavior.
5. Confirm the installed artifact matches the validated repository file.

Do not deploy an unvalidated repository version. Do not assume a repository commit, merge, or pull has updated copies already installed elsewhere on the system.
