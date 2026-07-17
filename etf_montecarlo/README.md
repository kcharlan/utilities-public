# ETF Monte Carlo

> [!WARNING]
> This public project contains no portfolio data. Never put real symbols, holdings, share counts, balances, output paths, or finance exports in this repository. Keep them only in your private local config.

`etf_montecarlo` downloads dividend-payment history for a privately configured portfolio, bootstraps one representative year of payments for each holding, and reports annual dividend-income percentiles per share and scaled by the configured share count. With more than one holding it also reports an aggregate portfolio-income distribution.

## Run

Install [uv](https://docs.astral.sh/uv/), then run the standalone launcher:

```bash
./etf_montecarlo
```

The first run creates an intentionally incomplete private skeleton at `~/.etf_montecarlo/config.json`, prints a prominent warning, and stops before contacting a finance service. Edit that local file, then run the command again. `ETF_MONTECARLO_HOME` changes the runtime directory; `--config PATH` selects an explicit private config.

The launcher never imports adjacent or legacy configuration. A copied launcher therefore keeps working independently of this source directory while continuing to use the user-home config. If the optional results file already exists, the launcher refuses to replace it unless `--overwrite` is supplied.

## Configuration

[`config.example.json`](config.example.json) documents the schema with only `SYNTH1` and `SYNTH2` and zero placeholder shares. It is deliberately unusable: replace both symbols and every zero or blank setting only in your private `~/.etf_montecarlo/config.json`. Do not copy an edited config back into the repository.

- `holdings`: one or more unique `symbol` and positive `shares` entries.
- `history.years`: positive number of trailing calendar years of dividend payments to use.
- `simulation.trials`: positive number of simulated annual-income draws.
- `simulation.seed`: whole number from 0 through 4,294,967,295 for reproducible output, or `null` for a fresh random stream.
- `output.results_csv`: optional private path for the percentile summary. A relative path is resolved from the private config directory; an empty string prints only the summary.

Configuration is validated in full before network access. Boolean schema versions, tracked placeholder symbols, and symbols beginning with spreadsheet formula characters are explicitly rejected. Result paths containing control characters are invalid. Config and result paths may not use case variants, hard-link aliases, or other aliases to the public source tree, and results may not alias the private config. Symbolic links are rejected in every path component. Runtime directories are restricted to mode `0700`; config and results files are written with mode `0600`. Result replacement is atomic, while the default no-overwrite installation atomically refuses a target created after preflight.

## Method and limitations

For each holding, the launcher keeps dividend payments dated within the configured trailing calendar window. It counts payments in each represented calendar year and uses the median annual count as the number of payments in a simulated year. Every trial samples that many payment amounts with replacement from the holding's filtered empirical history. The P5, P25, P50, P75, and P95 annual-income results are reported per share and after multiplication by the private share count.

Holdings are bootstrapped independently; the aggregate portfolio distribution sums their trial-level scaled income. The model therefore does not preserve cross-holding dividend timing or dependence. It also does not model taxes, fees, dividend growth, cuts outside the observed history, reinvestment, or price returns. This is a historical bootstrap, not a forecast or financial advice.

## Development

Use a project virtual environment; never install packages into the system or Homebrew Python:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -v
```

Tests inject dividend history and do not contact a finance service.
