from __future__ import annotations

import json
from pathlib import Path

from cognitive_switchyard.config import (
    GlobalConfig,
    build_runtime_paths,
    load_global_config,
    render_global_config,
    session_subdirs,
)
from cognitive_switchyard.models import (
    ExecutionPhaseConfig,
    PackManifest,
    PhaseConfigSet,
    SessionRecord,
    build_effective_session_runtime_config,
)


def test_runtime_paths_use_canonical_cognitive_switchyard_names(tmp_path: Path) -> None:
    paths = build_runtime_paths(home=tmp_path)

    assert paths.home == tmp_path / ".cognitive_switchyard"
    assert paths.database == tmp_path / ".cognitive_switchyard" / "cognitive_switchyard.db"
    assert paths.config == tmp_path / ".cognitive_switchyard" / "config.yaml"
    assert paths.packs == tmp_path / ".cognitive_switchyard" / "packs"
    assert paths.sessions == tmp_path / ".cognitive_switchyard" / "sessions"
    assert paths.session("session-123") == tmp_path / ".cognitive_switchyard" / "sessions" / "session-123"


def test_session_subdirs_match_design_doc_exactly() -> None:
    assert session_subdirs() == (
        "intake",
        "claimed",
        "staging",
        "review",
        "ready",
        "workers",
        "done",
        "blocked",
        "logs",
        "logs/workers",
        "logs/tasks",
    )


def test_global_config_terminal_app_default() -> None:
    config = GlobalConfig()
    assert config.terminal_app == "iTerm"


def test_render_global_config_includes_terminal_app() -> None:
    config = GlobalConfig()
    rendered = render_global_config(config)
    assert "terminal_app: iTerm" in rendered


def test_load_global_config_backward_compatibility_missing_terminal_app(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("retention_days: 30\ndefault_pack: claude-code\n", encoding="utf-8")
    loaded = load_global_config(config_file)
    assert loaded.terminal_app == "iTerm"


def test_load_global_config_explicit_terminal_app(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("retention_days: 30\nterminal_app: Kitty\n", encoding="utf-8")
    loaded = load_global_config(config_file)
    assert loaded.terminal_app == "Kitty"


def test_load_global_config_empty_default_pack_falls_back_to_claude_code(tmp_path: Path) -> None:
    """Regression: YAML `default_pack:` (empty value) must not produce 'None' string."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("retention_days: 14\ndefault_pack: \n", encoding="utf-8")
    loaded = load_global_config(config_file)
    assert loaded.default_pack == "claude-code"


def test_session_paths_expose_reserved_artifact_locations(tmp_path: Path) -> None:
    runtime_paths = build_runtime_paths(home=tmp_path)
    session_paths = runtime_paths.session_paths("session-123")

    assert session_paths.root == tmp_path / ".cognitive_switchyard" / "sessions" / "session-123"
    assert session_paths.resolution == session_paths.root / "resolution.json"
    assert session_paths.session_log == session_paths.logs / "session.log"
    assert session_paths.verify_log == session_paths.logs / "verify.log"
    assert session_paths.worker_dir(1) == session_paths.workers / "1"
    assert session_paths.worker_log(1) == session_paths.worker_logs / "1.log"
    assert session_paths.task_log("039") == session_paths.task_logs / "039.log"
    assert session_paths.plan_path("039", status="ready") == session_paths.ready / "039.plan.md"
    assert (
        session_paths.plan_path("039", status="active", worker_slot=1)
        == session_paths.workers / "1" / "039.plan.md"
    )


# ---------------------------------------------------------------------------
# Regression: 012 — worker_count caps and defaults for EffectiveSessionRuntimeConfig
# ---------------------------------------------------------------------------

def _make_pack(tmp_path: Path, max_workers: int = 4) -> PackManifest:
    return PackManifest(
        root=tmp_path,
        name="test-pack",
        description="Test pack",
        version="1.0.0",
        phases=PhaseConfigSet(execution=ExecutionPhaseConfig(max_workers=max_workers)),
    )


def _make_session(config_json: str | None = None) -> SessionRecord:
    return SessionRecord(
        id="session-test",
        name="test",
        pack="test-pack",
        status="created",
        created_at="2026-01-01T00:00:00",
        config_json=config_json,
    )


def test_effective_worker_count_defaults_to_pack_max_workers(tmp_path: Path) -> None:
    """Regression: no session override → worker_count equals pack max_workers, not global default."""
    pack = _make_pack(tmp_path, max_workers=4)
    session = _make_session(config_json=None)
    config = build_effective_session_runtime_config(
        session=session, pack_manifest=pack, default_poll_interval=0.05
    )
    assert config.worker_count == 4


def test_effective_worker_count_respects_explicit_override(tmp_path: Path) -> None:
    """Regression: explicit worker_count override below pack max is honoured."""
    pack = _make_pack(tmp_path, max_workers=4)
    session = _make_session(config_json=json.dumps({"worker_count": 2}))
    config = build_effective_session_runtime_config(
        session=session, pack_manifest=pack, default_poll_interval=0.05
    )
    assert config.worker_count == 2


def test_effective_worker_count_caps_override_at_pack_max(tmp_path: Path) -> None:
    """Regression: worker_count override above pack max is capped to pack max."""
    pack = _make_pack(tmp_path, max_workers=4)
    session = _make_session(config_json=json.dumps({"worker_count": 6}))
    config = build_effective_session_runtime_config(
        session=session, pack_manifest=pack, default_poll_interval=0.05
    )
    assert config.worker_count == 4
