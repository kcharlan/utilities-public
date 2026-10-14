# Colophon

A macOS C17 application that compiles local Codex sessions, token usage and
dated API-equivalent cost estimates into a private, self-contained offline
HTML page. The canonical source project at `colophon/` embeds its page
assets, fonts and public rate seeds in the executable.

Build prerequisites are Apple's clang/Command Line Tools, make, Perl,
ripgrep (for the development sort guard), and Homebrew SQLite. Install
prerequisites deliberately; the build does not install dependencies:

```sh
xcode-select --install
brew install sqlite
make
./colophon --help
./colophon --version
```

The SQLite prefix defaults to `/opt/homebrew/opt/sqlite`. Override it when
needed, for example `make SQLITE_PREFIX=/usr/local/opt/sqlite`. The release
links SQLite, libcurl, pthreads and CoreFoundation. Building and running it
requires no Python, uv, npm or font generator. Python is used only for
development tests and optional Unicode maintenance.

For the maintained macOS installation, use
`node ../tools/deploy_colophon.mjs --dry-run` and then
`node ../tools/deploy_colophon.mjs` after validation. This builds and
deploys the native executable as `~/Library/Scripts/colophon`, with private
backups and a read-only source/binary receipt audit. See the
[deployment guide](../docs/local_deployment_sync.md#native-colophon-deployment)
for prerequisites, fleet validation and rollback.

Run against a chosen existing source and private output directory; replace
these placeholder paths before running:

```sh
COLOPHON_HOME=/path/to/private/native-runtime ./colophon --no-open --codex-home /path/to/codex-home
COLOPHON_HOME=/path/to/private/native-runtime ./colophon --offline --rebuild --no-open --codex-home /path/to/codex-home
COLOPHON_HOME=/path/to/private/native-runtime ./colophon --offline --no-open --codex-home /path/to/codex-home --output /path/to/private/report.html
```

Without overrides, the source is `~/.codex` and the runtime home is
`~/.colophon`. Runtime files remain compatible with prior Python releases;
native uses its own `cache-native/`. Use a separately selected `COLOPHON_HOME`
for independent state. If an older release shares this home, run commands
sequentially and avoid editing the ledger during a run:
the existing ledger read/replace race is not a cross-process transaction.
No private state is migrated automatically.

[Runtime behavior](docs/runtime.md) covers flags, permissions, source SQLite
coordination, privacy and current limitations. [Architecture](docs/architecture.md)
describes the modules. [Accounting decisions](docs/token_rules.md) and
[lessons learned](docs/LESSONS_LEARNED.md) retain applicable historical knowledge.
[Development](docs/development.md) and the
[tests README](tests/README.md) describe standalone validation:

```sh
make test
make sanitize
make tsan
make check-assets
make check-sort
```

Individual categories are `make test-unit`, `make test-cli` and
`make test-browser`. Help lists these shipped standalone checks. The original
native parity/performance tools and their private workflow are not included
here. The listed standalone checks are the available validation;
they do not reproduce captured-corpus parity or historical performance
acceptance. Keep temporary fixtures and evidence outside the public checkout.

Performance is workload-dependent; three original performance targets were
missed. This project makes no new speed or memory acceptance claim.
[Third-party attribution and notices](THIRD_PARTY.md) cover the retained
components; they do not assign a new license to Kevin's application.
