from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard.cli import main
from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_builtin_pack(root: Path, *, name: str, body: str = "factory\n") -> Path:
    pack_root = root / name
    scripts_dir = pack_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (pack_root / "prompts").mkdir(parents=True, exist_ok=True)
    (pack_root / "README.md").write_text(body, encoding="utf-8")
    execute_path = scripts_dir / "execute"
    execute_path.write_text(
        dedent(
            """
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            task_path = Path(sys.argv[1])
            task_id = task_path.name.removesuffix(".plan.md")
            print(f"##PROGRESS## {task_id} | Phase: Execute | 1/1")
            status_path = task_path.with_name(task_id + ".status")
            status_path.write_text(
                "STATUS: done\\nCOMMITS: none\\nTESTS_RAN: targeted\\nTEST_RESULT: pass\\n",
                encoding="utf-8",
            )
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path.chmod(execute_path.stat().st_mode | 0o111)
    (pack_root / "pack.yaml").write_text(
        dedent(
            f"""
            name: {name}
            description: Built-in pack fixture.
            version: 1.2.3

            phases:
              resolution:
                enabled: true
                executor: passthrough
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1

            timeouts:
              task_idle: 5
              task_max: 0
              session_max: 60

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return pack_root


def _write_intake_plan(path: Path, task_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            PRIORITY: normal
            ESTIMATED_SCOPE: src/{task_id}.py
            DEPENDS_ON: none
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}

            Execute the built-in pack fixture.
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_bootstrap_creates_runtime_home_default_config_and_builtin_packs_when_dependencies_are_available(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "packs",
        ]
    )

    runtime_paths = build_runtime_paths(home=tmp_path)
    synced_pack = runtime_paths.packs / "claude-code"

    assert exit_code == 0
    assert runtime_paths.home.is_dir()
    assert runtime_paths.packs.is_dir()
    assert runtime_paths.sessions.is_dir()
    assert runtime_paths.config.read_text(encoding="utf-8") == (
        "retention_days: 30\n"
        "default_planners: 3\n"
        "default_workers: 3\n"
        "default_pack: claude-code\n"
        "terminal_app: iTerm\n"
    )
    assert synced_pack.is_dir()
    assert synced_pack.joinpath("pack.yaml").is_file()
    assert os.access(synced_pack / "scripts" / "execute", os.X_OK)
    assert load_pack_manifest(synced_pack).name == "claude-code"


def test_sync_builtin_packs_is_non_destructive_for_existing_runtime_customizations(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code", body="factory copy\n")
    runtime_paths = build_runtime_paths(home=tmp_path)
    customized_readme = runtime_paths.packs / "claude-code" / "README.md"
    customized_readme.parent.mkdir(parents=True, exist_ok=True)
    customized_readme.write_text("customized copy\n", encoding="utf-8")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "sync-packs",
        ]
    )

    assert exit_code == 0
    assert customized_readme.read_text(encoding="utf-8") == "customized copy\n"


def test_reset_pack_restores_factory_copy_for_one_builtin_pack(tmp_path: Path) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code", body="factory copy\n")

    main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "packs",
        ]
    )
    runtime_paths = build_runtime_paths(home=tmp_path)
    readme_path = runtime_paths.packs / "claude-code" / "README.md"
    readme_path.write_text("customized copy\n", encoding="utf-8")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "reset-pack",
            "claude-code",
        ]
    )

    assert exit_code == 0
    assert readme_path.read_text(encoding="utf-8") == "factory copy\n"


def test_reset_all_packs_restores_all_builtin_packs_but_keeps_custom_only_runtime_packs(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code", body="claude factory\n")
    _write_builtin_pack(builtin_root, name="starter", body="starter factory\n")

    main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "packs",
        ]
    )
    runtime_paths = build_runtime_paths(home=tmp_path)
    (runtime_paths.packs / "claude-code" / "README.md").write_text(
        "custom claude\n",
        encoding="utf-8",
    )
    (runtime_paths.packs / "starter" / "README.md").write_text(
        "custom starter\n",
        encoding="utf-8",
    )
    custom_only = runtime_paths.packs / "my-custom-pack"
    custom_only.mkdir(parents=True, exist_ok=True)
    (custom_only / "README.md").write_text("keep me\n", encoding="utf-8")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "reset-all-packs",
        ]
    )

    assert exit_code == 0
    assert (runtime_paths.packs / "claude-code" / "README.md").read_text(
        encoding="utf-8"
    ) == "claude factory\n"
    assert (runtime_paths.packs / "starter" / "README.md").read_text(
        encoding="utf-8"
    ) == "starter factory\n"
    assert (custom_only / "README.md").read_text(encoding="utf-8") == "keep me\n"


def test_start_command_creates_or_resumes_session_and_invokes_existing_orchestrator_pipeline(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")
    runtime_paths = build_runtime_paths(home=tmp_path)
    expired = initialize_state_store(runtime_paths)
    expired.create_session(
        session_id="expired-session",
        name="Expired session",
        pack="claude-code",
        created_at="2026-01-01T00:00:00Z",
    )
    expired.update_session_status(
        "expired-session",
        status="completed",
        completed_at="2026-02-01T00:00:00Z",
    )

    _write_intake_plan(
        runtime_paths.session_paths("session-10-cli").intake / "001.plan.md",
        "001",
    )

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "start",
            "--pack",
            "claude-code",
            "--session",
            "session-10-cli",
        ]
    )

    store = initialize_state_store(runtime_paths)
    session = store.get_session("session-10-cli")
    done_task = store.get_task("session-10-cli", "001")

    assert exit_code == 0
    with pytest.raises(KeyError, match="Unknown session: expired-session"):
        store.get_session("expired-session")
    assert session.status == "idle"
    assert done_task.status == "done"
    # Session is idle (not completed), so summary is not written yet and
    # artifacts are not trimmed — the done plan should still exist on disk.
    session_paths = runtime_paths.session_paths("session-10-cli")
    assert session_paths.done.joinpath("001.plan.md").exists()
    assert not runtime_paths.session("expired-session").exists()


def test_start_command_uses_default_claude_runtime_for_agent_enabled_builtin_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")
    pack_root = builtin_root / "claude-code"
    (pack_root / "prompts" / "planner.md").write_text("Planner prompt.\n", encoding="utf-8")
    (pack_root / "prompts" / "resolver.md").write_text("Resolver prompt.\n", encoding="utf-8")
    (pack_root / "prompts" / "fixer.md").write_text("Fixer prompt.\n", encoding="utf-8")
    (pack_root / "pack.yaml").write_text(
        dedent(
            """
            name: claude-code
            description: Built-in pack fixture.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/planner.md
                max_instances: 1
              resolution:
                enabled: true
                executor: agent
                model: claude-opus
                prompt: prompts/resolver.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute
                max_workers: 1
              verification:
                enabled: false

            auto_fix:
              enabled: true
              max_attempts: 2
              model: claude-opus
              prompt: prompts/fixer.md

            isolation:
              type: none
            """
        ).lstrip(),
        encoding="utf-8",
    )

    runtime_paths = build_runtime_paths(home=tmp_path)
    initialize_state_store(runtime_paths)
    session_paths = runtime_paths.session_paths("session-13-cli-default-runtime")
    session_paths.intake.mkdir(parents=True, exist_ok=True)
    (session_paths.intake / "001_feature.md").write_text("# Feature request\n", encoding="utf-8")

    from cognitive_switchyard import orchestrator
    from cognitive_switchyard.models import FixerAttemptResult

    captured: dict[str, object] = {}

    class FakeRuntime:
        def planner_agent(self, **kwargs):
            captured["planner"] = kwargs
            return dedent(
                """
                ---
                PLAN_ID: 001
                PRIORITY: normal
                ESTIMATED_SCOPE: src/feature.py
                DEPENDS_ON: none
                FULL_TEST_AFTER: no
                ---

                # Plan: Task 001

                Implement the feature.
                """
            ).lstrip()

        def resolver_agent(self, **kwargs):
            captured["resolver"] = kwargs
            return (
                '{\n'
                '  "resolved_at": "2026-03-10T10:00:00Z",\n'
                '  "tasks": [{"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}],\n'
                '  "groups": [],\n'
                '  "conflicts": [],\n'
                '  "notes": "default runtime"\n'
                '}\n'
            )

        def fixer_executor(self, context, **kwargs):
            captured["fixer_context_type"] = context.context_type
            captured["fixer"] = kwargs
            return FixerAttemptResult(success=True, summary="fixed")

    monkeypatch.setattr(orchestrator, "build_agent_runtime", lambda runtime_kind, output_line_callback=None: FakeRuntime())
    # Agent planning requires COGNITIVE_SWITCHYARD_REPO_ROOT in the environment
    monkeypatch.setenv("COGNITIVE_SWITCHYARD_REPO_ROOT", str(tmp_path))

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "start",
            "--pack",
            "claude-code",
            "--session",
            "session-13-cli-default-runtime",
        ]
    )

    store = initialize_state_store(runtime_paths)
    assert exit_code == 0
    assert store.get_session("session-13-cli-default-runtime").status == "idle"
    assert captured["planner"]["model"] == "claude-opus"
    assert captured["planner"]["reasoning_effort"] is None
    assert captured["resolver"]["model"] == "claude-opus"
    assert captured["resolver"]["reasoning_effort"] is None


def test_serve_command_is_available_in_help_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "serve" in captured.out


def test_paths_reports_runtime_root_override_without_creating_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime_root = tmp_path / "sandbox"

    exit_code = main(["--runtime-root", str(runtime_root), "paths"])

    assert exit_code == 0
    assert f"runtime home: {runtime_root / '.cognitive_switchyard'}" in capsys.readouterr().out
    assert not runtime_root.exists()


def test_paths_reports_default_canonical_home_without_creating_state(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    exit_code = main(["paths"])

    assert exit_code == 0
    assert "runtime home: ~/.cognitive_switchyard" in capsys.readouterr().out
    assert not (tmp_path / ".cognitive_switchyard").exists()


def test_serve_command_purges_expired_sessions_before_starting_backend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    store.create_session(
        session_id="expired-session",
        name="Expired session",
        pack="claude-code",
        created_at="2026-01-01T00:00:00Z",
    )
    store.update_session_status(
        "expired-session",
        status="aborted",
        completed_at="2026-02-01T00:00:00Z",
    )

    def fake_serve_backend(*, runtime_paths, builtin_packs_root, host: str, port: int) -> int:
        return port

    monkeypatch.setattr("cognitive_switchyard.server.serve_backend", fake_serve_backend)

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8100",
        ]
    )

    refreshed = initialize_state_store(runtime_paths)
    assert exit_code == 0
    with pytest.raises(KeyError, match="Unknown session: expired-session"):
        refreshed.get_session("expired-session")
    assert not runtime_paths.session("expired-session").exists()


def test_init_pack_creates_runtime_scaffold_with_expected_contract_files_and_executable_placeholders(
    tmp_path: Path,
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "init-pack",
            "lint-pack",
        ]
    )

    runtime_paths = build_runtime_paths(home=tmp_path)
    pack_root = runtime_paths.packs / "lint-pack"

    assert exit_code == 0
    assert pack_root.is_dir()
    assert (pack_root / "README.md").is_file()
    assert (pack_root / "pack.yaml").is_file()
    assert (pack_root / "prompts").is_dir()
    assert (pack_root / "scripts").is_dir()
    assert (pack_root / "templates").is_dir()
    assert (pack_root / "templates" / "intake.md").is_file()
    assert (pack_root / "templates" / "plan.md").is_file()
    assert (pack_root / "templates" / "status.md").is_file()
    assert os.access(pack_root / "scripts" / "execute", os.X_OK)
    assert os.access(pack_root / "scripts" / "preflight", os.X_OK)
    manifest = load_pack_manifest(pack_root)
    assert manifest.name == "lint-pack"
    assert manifest.phases.execution.command == pack_root / "scripts" / "execute"


def test_validate_pack_reports_manifest_reference_permission_shebang_and_regex_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builtin_root = tmp_path / "builtin-source"
    _write_builtin_pack(builtin_root, name="claude-code")
    pack_root = tmp_path / "broken-pack"
    (pack_root / "scripts").mkdir(parents=True)
    (pack_root / "prompts").mkdir(parents=True)
    (pack_root / "pack.yaml").write_text(
        dedent(
            """
            name: broken-pack
            description: Broken validator fixture.
            version: 1.2.3

            phases:
              planning:
                enabled: true
                executor: agent
                model: claude-sonnet
                prompt: prompts/missing-planner.md
              execution:
                enabled: true
                executor: shell
                command: scripts/execute

            isolation:
              type: none

            status:
              progress_format: "[unterminated"
            """
        ).lstrip(),
        encoding="utf-8",
    )
    execute_path = pack_root / "scripts" / "execute"
    execute_path.write_text("print('missing shebang')\n", encoding="utf-8")
    execute_path.chmod(0o755)
    preflight_path = pack_root / "scripts" / "preflight"
    preflight_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    preflight_path.chmod(0o644)

    exit_code = main(
        [
            "--runtime-root",
            str(tmp_path),
            "--builtin-packs-root",
            str(builtin_root),
            "validate-pack",
            str(pack_root),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "phases.planning.prompt: referenced file does not exist" in captured.out
    assert "status.progress_format: must be a valid regex" in captured.out
    assert "scripts/preflight: script is not executable" in captured.out
    assert "scripts/execute: text executable is missing a shebang" in captured.out
