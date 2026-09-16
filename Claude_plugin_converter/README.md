# Claude Plugin Converter

Utilities for adapting Claude-style plugin skills and commands to other CLI
formats.

## Available converter

- [Gemini CLI](./to_gemini_cli/): links skill directories into a Gemini
  workspace and converts Markdown commands to Gemini CLI TOML commands.

Gemini CLI is currently the only target. The converter is a standalone,
standard-library Python script; there is no shared package or repository-wide
setup step.

Read the target-specific README and migration guide before running it. The
current Gemini converter validates Agent Skills metadata, leaves the source
plugin unchanged, links compliant skills by their existing names, and preserves
Gemini CLI's directory-based command namespacing.
