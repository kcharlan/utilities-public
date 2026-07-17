# Router Log Analyzer

`router_log_analyze.py` is a standalone NETGEAR router log analyzer with persistent SQLite-backed learning. It ingests PDF or plain-text log exports, tracks known devices and behavioral baselines over time, and flags anomalies such as unknown devices, timing drift, event spikes, and cluster gaps.

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

The launcher runs via [uv](https://docs.astral.sh/uv/) using a PEP 723 inline-metadata header. On the first run, uv resolves its PDF-parsing dependencies (`PyMuPDF`, `pypdf`) into its shared cache — that invocation may briefly hit the network. Its SQLite state lives under `~/.router-log-analyzer/`.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv`) — manages the Python interpreter and dependencies
- Network access on first run so uv can resolve `PyMuPDF` and `pypdf`

## Baseline And Config

The analyzer requires an active baseline before normal log analysis can run. You can either import one ahead of time or pass a baseline JSON on the first analysis command.

If a `router-security-config.md` file lives next to the log file or baseline file, the script auto-detects and imports it unless you pass `--config` explicitly.

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

Write report files instead of console output:

```zsh
router_log_analyze.py router-log.pdf --report markdown,html,json --report-dir ./reports
```

## State Storage

All persistent state lives under `~/.router-log-analyzer/`:

- `network.db` - learned baseline, imported config, and analysis history

Python dependencies are managed by uv (declared in the launcher's PEP 723 header) and cached in uv's shared cache, not under `~/.router-log-analyzer/`.

## Notes

- The tool is self-contained and does not import local modules from this repo at runtime.
- Default output is a text report. `--report` can emit `markdown`, `html`, and `json` report files.
- Under uv, the very first invocation of any command (including `--help`/`--version`) may resolve and cache the environment; subsequent runs are fast.

## Internet Reset Correlation

The analyzer treats a completed internet disconnect/reconnect sequence followed by synchronized activity from known allowed devices as one network-level recovery incident. DHCP leases and successful WLAN reconnections inside the recovery window remain visible in raw report totals, but they are removed from device-level anomaly analysis so one router reset does not become dozens of independent findings.

When the router does not export explicit internet transition events, the analyzer can infer a probable reset from a stronger synchronized DHCP/WLAN recovery burst. An unresolved disconnect is never treated as a benign reset.

Incident attribution is deliberately limited to `DHCP_IP` and `WLAN_ACCESS_ALLOWED` events from known allowed devices. Unknown devices, blocked devices, WLAN rejections, and administrative or security events remain independently actionable even when they occur during a reset.

The default incident policy can be customized through an imported policy document:

```json
{
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
cd /path/to/utilities/router-log-analyzer
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

## Updating An Installed Copy

An installed copy is not updated automatically when this repository changes. Use this release sequence:

1. Run the complete project test suite shown above.
2. Run any repository-level launcher validation required by the checkout.
3. Only after all validation succeeds, copy `router_log_analyze.py` over the installed runtime copy in the user's chosen executable directory.
4. Run the installed command's `--version` and `--help`, then perform a safe analysis against a disposable database copy when the change affects analysis or persistence behavior.
5. Confirm the installed artifact matches the validated repository file.

Do not deploy an unvalidated repository version. Do not assume a repository commit, merge, or pull has updated copies already installed elsewhere on the system.
