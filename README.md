# Utilities Toolkit

Personal collection of independently maintained automation scripts, data tools, native macOS apps, browser applications, and local services. Each project has its own prerequisites, setup, and validation commands.

> [!WARNING]
> This repository is public. Never commit sensitive data; use synthetic examples and keep private configuration and runtime data outside the checkout.

## Featured projects

A selection of useful and distinctive projects across the collection. These highlights are editorial choices, not maintenance-status or activity rankings.

| Project | What it does |
| --- | --- |
| [Colophon](colophon/README.md) | Compiles local Codex, Claude Code, OpenCode, and Antigravity sessions into a private offline HTML explorer, with token usage and API-equivalent cost estimates. Built as a native macOS executable. |
| [Model Sentinel](model_sentinel/README.md) | Tracks model availability, pricing, and metadata changes across providers. Saved endpoint captures support Hosts comparisons and uptime history in an offline history browser. |
| [Cognitive Switchyard](cognitive_switchyard/README.md) | Coordinates parallel CLI work through planning, dispatch, verification, and bounded auto-fix. Runner packs, worktree isolation, recovery, and a local dashboard support different workloads. |
| [Git Fleet](git-multirepo-dashboard/README.md) | Brings repository activity, working-tree state, branch health, and dependency checks into one local dashboard, including discovery of nested project manifests. |
| [harscope](harscope/README.md) | Inspects HAR captures through waterfall, request, sequence, and dashboard views, with secret detection, explicit redaction decisions, and sanitized exports. |
| [Brew Version](brew_version/README.md) | A native macOS menu bar app and Swift CLI that watch Homebrew formula and cask versions, including third-party taps, and notify about updates. |

## Browse the collection

The [complete project catalog](docs/projects.md) groups applications, utilities, and reference material by purpose, with delivery types and links to their documentation.

- [AI tools and observability](docs/projects.md#ai-tools-and-observability)
- [Development and data tools](docs/projects.md#development-and-data-tools)
- [macOS and system utilities](docs/projects.md#macos-and-system-utilities)
- [Finance and calculators](docs/projects.md#finance-and-calculators)
- [Documents and media](docs/projects.md#documents-and-media)
- [Games and visualizations](docs/projects.md#games-and-visualizations)
- [Infrastructure and reference material](docs/projects.md#infrastructure-and-reference-material)

## Using a project

Start with the linked project README. There is no repository-wide installation step: delivery ranges from shell commands and static pages to Python applications, native binaries, and Docker stacks.

Many Python tools use [uv](https://docs.astral.sh/uv/) to resolve their declared dependencies on first run. Other prerequisites, credentials, configuration, or build steps are project-specific. A local browser interface may still load assets from public CDNs; check the project documentation before relying on offline use.

Keep operational configuration, inputs, and generated output in the project's documented private runtime locations. The source checkout is not a data directory.

## Development and deployment

Each project README describes its setup and validation commands. Contributor conventions and the rules for choosing a CLI, built page, static page, or local server live in [agents.md](agents.md).

Shared repository tooling lives in [tools/](tools/): deployment installers, the read-only fleet deployment audit, the uv launcher header guard, browser and launcher test helpers, and the shared temporary-file leak checker. Their tests are in [tools/tests/](tools/tests/).

Repository updates do not update installed copies. See the [deployment guide](docs/local_deployment_sync.md) for installation, verification, and rollback, the [maintenance to-do list](docs/todo.md) for open follow-ups, and the [lessons learned](docs/lessons_learned.md) for cross-project pitfalls.
