# Colophon Native

A macOS C17 application that compiles local Codex sessions, token usage and
dated API-equivalent cost estimates into a private, self-contained offline
HTML page. This independently maintained native project embeds its page
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
requires no Python, uv, npm or font generator.

Run against a chosen existing source and private output directory; replace
these placeholder paths before running:

```sh
COLOPHON_HOME=/path/to/private/native-runtime ./colophon --no-open --codex-home /path/to/codex-home
COLOPHON_HOME=/path/to/private/native-runtime ./colophon --offline --rebuild --no-open --codex-home /path/to/codex-home
COLOPHON_HOME=/path/to/private/native-runtime ./colophon --offline --no-open --codex-home /path/to/codex-home --output /path/to/private/report.html
```

Without overrides, the source is `~/.codex` and the runtime home is
`~/.colophon`. Python and native Colophon share editable runtime files by
default; native uses its own `cache-native/`. Use a separately selected
`COLOPHON_HOME` for independent state. When sharing a home, run the two
implementations sequentially and avoid editing the ledger during a run:
the existing ledger read/replace race is not a cross-process transaction.
No private state is migrated automatically.

[Runtime behavior](docs/runtime.md) covers flags, permissions, source SQLite
coordination, privacy and current limitations. [Architecture](docs/architecture.md)
describes the modules. [Development](docs/development.md) and the
[tests README](tests/README.md) describe standalone validation:

```sh
make test
make sanitize
make tsan
make check-assets
make check-sort
```

Individual categories are `make test-unit`, `make test-cli` and
`make test-browser`. The inherited `--help` statement about development
acceptance and explicit `private/` destinations refers to the original
native parity/performance tools. Those tools and that workflow are not
included here. The listed standalone checks are the available validation;
they do not reproduce captured-corpus parity or historical performance
acceptance. Keep temporary fixtures and evidence outside the public checkout.

Performance is workload-dependent; three original performance targets were
missed. This project makes no new speed or memory acceptance claim.
[Third-party attribution and notices](THIRD_PARTY.md) cover the retained
components; they do not assign a new license to Kevin's application.
