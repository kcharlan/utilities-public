# Operator Guide

## Bootstrap

Validated entrypoints:

```bash
./switchyard --help
./switchyard packs
./switchyard serve --help
./switchyard start --session demo --pack claude-code
```

The CLI runs via [uv](https://docs.astral.sh/uv/) (`brew install uv`) using the `switchyard` launcher's PEP 723 header; uv resolves dependencies into its shared cache (no private venv). Runtime state lives in the runtime home at `~/.cognitive_switchyard`.

## Core Commands

```bash
./switchyard paths                                        # Print canonical runtime paths
./switchyard packs                                        # List available runtime packs
./switchyard sync-packs                                   # Sync built-in packs to runtime
./switchyard reset-pack claude-code                       # Reset one built-in pack to factory
./switchyard reset-all-packs                              # Reset all built-in packs to factory
./switchyard init-pack my-pack                            # Scaffold a new custom pack
./switchyard validate-pack ~/.cognitive_switchyard/packs/my-pack
./switchyard start --session demo --pack claude-code      # Start or resume a headless session
./switchyard start --session demo --pack codex-hybrid
./switchyard start --session demo --pack codex
./switchyard start --session demo --pack claude-code --name "My Session"
./switchyard serve                                        # Start the web UI server
./switchyard serve --host 0.0.0.0 --port 8200            # Custom host/port (default: 127.0.0.1:8100)
```

`serve` opens the UI in the default browser unless `COGNITIVE_SWITCHYARD_NO_BROWSER=1` is set. If the requested port is busy, the server scans the next 19 ports and uses the first available port.

## Session Lifecycle

1. Create or pick a pack.
   `claude-code` is the reference Claude pack, `codex-hybrid` uses Claude for planning/fixing with Codex execution, and `codex` is the strict all-Codex pack.
2. Select a repository root and branch in the Setup view. When both are provided, a git worktree is created in a peer directory of the source repo so that workers never modify the original checkout.
   For monorepos, optionally set a repository-relative project directory so the built-in verifier scopes tests to that project.
3. Put intake files into the session intake directory from the CLI or Setup view.
4. Run preflight.
5. Start the session.
6. Monitor active work in the UI or logs.
7. Review retained artifacts after completion.

When the session is deleted (via the Reset button or the purge API), the worktree is removed and the git worktree reference is cleaned up in the source repo.

## History and Retention

Successful sessions are trimmed to the retained artifact set:

- `summary.json`
- `resolution.json`
- `logs/session.log`
- `RELEASE_NOTES.md` when generated

Failed or aborted sessions are not trimmed.

`RELEASE_NOTES.md` is derived from completed plan `## Operator Actions` sections before trimming. If no completed plan contains that section, no release-notes artifact is retained.

## Troubleshooting

- Run `./switchyard validate-pack <path>` before starting a custom pack.
- Use `./switchyard sync-packs` to refresh bundled packs into the runtime directory.
- Use `./switchyard reset-pack claude-code` to restore the bundled Claude pack.
- Use `./switchyard reset-pack codex-hybrid` to restore the bundled hybrid Codex pack.
- Use `./switchyard reset-pack codex` to restore the bundled Codex pack.
- The `claude-code` pack also requires `jq`; all coding packs require their agent CLI, `git`, and an authenticated CLI session.
- If the UI is unavailable, the CLI and retained session logs remain authoritative.
