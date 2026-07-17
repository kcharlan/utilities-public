from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from . import PACKAGE_NAME, RUNTIME_HOME
from .runtime_env import default_runtime_settings, initialize_runtime_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PACKAGE_NAME,
        description="Cognitive Switchyard command-line operator surface.",
        epilog=f"Canonical runtime home: {RUNTIME_HOME}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--runtime-root", help=argparse.SUPPRESS)
    parser.add_argument("--builtin-packs-root", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")

    paths_parser = subparsers.add_parser(
        "paths",
        help="Print canonical runtime paths.",
    )
    paths_parser.set_defaults(handler=handle_paths)

    packs_parser = subparsers.add_parser(
        "packs",
        help="List runtime packs from ~/.cognitive_switchyard/packs.",
    )
    packs_parser.set_defaults(handler=handle_packs)

    sync_parser = subparsers.add_parser(
        "sync-packs",
        help="Sync bundled built-in packs into the runtime pack directory.",
    )
    sync_parser.set_defaults(handler=handle_sync_packs)

    reset_pack_parser = subparsers.add_parser(
        "reset-pack",
        help="Restore one built-in pack to its bundled contents.",
    )
    reset_pack_parser.add_argument("name")
    reset_pack_parser.set_defaults(handler=handle_reset_pack)

    reset_all_parser = subparsers.add_parser(
        "reset-all-packs",
        help="Restore all built-in packs to their bundled contents.",
    )
    reset_all_parser.set_defaults(handler=handle_reset_all_packs)

    init_pack_parser = subparsers.add_parser(
        "init-pack",
        help="Scaffold a new runtime pack in ~/.cognitive_switchyard/packs.",
    )
    init_pack_parser.add_argument("name")
    init_pack_parser.set_defaults(handler=handle_init_pack)

    validate_pack_parser = subparsers.add_parser(
        "validate-pack",
        help="Validate a pack directory before starting a session.",
    )
    validate_pack_parser.add_argument("path")
    validate_pack_parser.set_defaults(handler=handle_validate_pack)

    start_parser = subparsers.add_parser(
        "start",
        help="Create or resume a headless session.",
    )
    start_parser.add_argument("--session", required=True, help="Session identifier.")
    start_parser.add_argument("--pack", help="Runtime pack name. Defaults to config.yaml.")
    start_parser.add_argument("--name", help="Human-readable session name.")
    start_parser.set_defaults(handler=handle_start)

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the FastAPI backend for local monitoring and control.",
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8100)
    serve_parser.set_defaults(handler=handle_serve)
    return parser


def handle_paths(args: argparse.Namespace) -> int:
    settings = _resolve_runtime_settings(args)
    print(f"package: {PACKAGE_NAME}")
    print(f"runtime home: {_display_path(settings.runtime_paths.home)}")
    print(f"builtin packs root: {_display_path(settings.builtin_packs_root)}")
    return 0


def handle_packs(args: argparse.Namespace) -> int:
    from .pack_loader import list_runtime_pack_names

    settings, _config = _initialize_runtime(args)
    for name in list_runtime_pack_names(settings.runtime_paths.packs):
        print(name)
    return 0


def handle_sync_packs(args: argparse.Namespace) -> int:
    from .pack_loader import sync_builtin_packs

    settings, _config = _initialize_runtime(args)
    synced = sync_builtin_packs(
        builtin_packs_root=settings.builtin_packs_root,
        runtime_packs_dir=settings.runtime_paths.packs,
    )
    if synced:
        print(f"Synced {len(synced)} built-in pack(s): {', '.join(synced)}")
    else:
        print("All built-in packs already present, nothing to sync.")
    return 0


def handle_reset_pack(args: argparse.Namespace) -> int:
    from .pack_loader import sync_builtin_packs

    settings, _config = _initialize_runtime(args)
    try:
        synced = sync_builtin_packs(
            builtin_packs_root=settings.builtin_packs_root,
            runtime_packs_dir=settings.runtime_paths.packs,
            reset_pack=args.name,
        )
    except KeyError as exc:
        print(str(exc))
        return 1
    print(f"Reset built-in pack: {synced[0]}")
    return 0


def handle_reset_all_packs(args: argparse.Namespace) -> int:
    from .pack_loader import sync_builtin_packs

    settings, _config = _initialize_runtime(args)
    synced = sync_builtin_packs(
        builtin_packs_root=settings.builtin_packs_root,
        runtime_packs_dir=settings.runtime_paths.packs,
        reset_all=True,
    )
    if synced:
        print(f"Reset {len(synced)} built-in pack(s): {', '.join(synced)}")
    else:
        print("No built-in packs found to reset.")
    return 0


def handle_init_pack(args: argparse.Namespace) -> int:
    from .pack_loader import create_pack_scaffold

    settings, _config = _initialize_runtime(args)
    try:
        pack_root = create_pack_scaffold(
            runtime_packs_dir=settings.runtime_paths.packs,
            pack_name=args.name,
        )
    except (FileExistsError, ValueError) as exc:
        print(str(exc))
        return 1
    print(pack_root)
    return 0


def handle_validate_pack(args: argparse.Namespace) -> int:
    from .pack_loader import validate_pack_directory

    findings = validate_pack_directory(Path(args.path))
    if findings:
        for finding in findings:
            print(f"{finding.path}: {finding.message}")
        return 1
    print(f"Pack is valid: {Path(args.path)}")
    return 0


def handle_start(args: argparse.Namespace) -> int:
    from .config import load_global_config
    from .orchestrator import start_session
    from .pack_loader import load_pack_manifest
    from .server import cleanup_session_worktree_if_needed
    from .state import initialize_state_store

    settings, _config = _initialize_runtime(args)
    store = initialize_state_store(settings.runtime_paths)
    config = load_global_config(settings.runtime_paths.config)
    store.purge_expired_sessions(
        retention_days=config.retention_days,
        now=_timestamp(),
        pre_delete=cleanup_session_worktree_if_needed,
    )
    session_id = args.session

    try:
        session = store.get_session(session_id)
        if args.pack and session.pack != args.pack:
            raise ValueError(
                f"Session {session_id!r} already uses pack {session.pack!r}, not {args.pack!r}."
            )
        pack_name = session.pack
    except KeyError:
        pack_name = args.pack or config.default_pack
        store.create_session(
            session_id=session_id,
            name=args.name or session_id,
            pack=pack_name,
            created_at=_timestamp(),
            pre_delete=cleanup_session_worktree_if_needed,
        )

    pack_manifest = load_pack_manifest(settings.runtime_paths.packs / pack_name)
    result = start_session(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        env=os.environ.copy(),
        poll_interval=0.01,
    )
    return 0 if result.startup_failure is None else 1


def handle_serve(args: argparse.Namespace) -> int:
    from .server import cleanup_session_worktree_if_needed, serve_backend
    from .state import initialize_state_store

    settings, config = _initialize_runtime(args)
    initialize_state_store(settings.runtime_paths).purge_expired_sessions(
        retention_days=config.retention_days,
        now=_timestamp(),
        pre_delete=cleanup_session_worktree_if_needed,
    )
    serve_backend(
        runtime_paths=settings.runtime_paths,
        builtin_packs_root=Path(settings.builtin_packs_root),
        host=args.host,
        port=args.port,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


def _initialize_runtime(args: argparse.Namespace):
    settings = _resolve_runtime_settings(args)
    config = initialize_runtime_environment(settings)
    return settings, config


def _resolve_runtime_settings(args: argparse.Namespace):
    runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else None
    builtin_packs_root = (
        Path(args.builtin_packs_root).expanduser() if args.builtin_packs_root else None
    )
    return default_runtime_settings(
        runtime_root=runtime_root,
        builtin_packs_root=builtin_packs_root,
    )


def _display_path(path: Path) -> str:
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
