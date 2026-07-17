from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_SESSION_SUBDIRS = (
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


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    database: Path
    config: Path
    packs: Path
    sessions: Path

    def session(self, session_id: str) -> Path:
        return self.sessions / session_id

    def session_paths(self, session_id: str) -> "SessionPaths":
        root = self.session(session_id)
        return SessionPaths(
            root=root,
            intake=root / "intake",
            claimed=root / "claimed",
            staging=root / "staging",
            review=root / "review",
            ready=root / "ready",
            workers=root / "workers",
            done=root / "done",
            blocked=root / "blocked",
            logs=root / "logs",
            worker_logs=root / "logs" / "workers",
            task_logs=root / "logs" / "tasks",
            summary=root / "summary.json",
            release_notes=root / "RELEASE_NOTES.md",
            resolution=root / "resolution.json",
            session_log=root / "logs" / "session.log",
            verify_log=root / "logs" / "verify.log",
        )


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    intake: Path
    claimed: Path
    staging: Path
    review: Path
    ready: Path
    workers: Path
    done: Path
    blocked: Path
    logs: Path
    worker_logs: Path
    task_logs: Path
    summary: Path
    release_notes: Path
    resolution: Path
    session_log: Path
    verify_log: Path

    def worker_dir(self, slot: int) -> Path:
        return self.workers / str(slot)

    def worker_log(self, slot: int) -> Path:
        return self.worker_logs / f"{slot}.log"

    def task_log(self, task_id: str) -> Path:
        return self.task_logs / f"{task_id}.log"

    def worker_recovery_path(self, slot: int) -> Path:
        return self.worker_dir(slot) / "recovery.json"

    def plan_path(
        self, task_id: str, *, status: str, worker_slot: int | None = None
    ) -> Path:
        directory = self._status_directory(status, worker_slot=worker_slot)
        return directory / f"{task_id}.plan.md"

    def materialize(self) -> None:
        for subdir in session_subdirs():
            (self.root / subdir).mkdir(parents=True, exist_ok=True)
        next_seq = self.intake / "NEXT_SEQUENCE"
        if not next_seq.exists():
            next_seq.write_text("1\n", encoding="utf-8")

    def _status_directory(self, status: str, *, worker_slot: int | None) -> Path:
        directories = {
            "intake": self.intake,
            "planning": self.claimed,
            "staged": self.staging,
            "review": self.review,
            "ready": self.ready,
            "done": self.done,
            "blocked": self.blocked,
        }
        if status == "active":
            if worker_slot is None:
                raise ValueError("worker_slot is required when status is active")
            return self.worker_dir(worker_slot)
        try:
            return directories[status]
        except KeyError as exc:
            raise ValueError(f"Unsupported task status: {status}") from exc


def build_runtime_paths(home: Path | None = None) -> RuntimePaths:
    user_home = home if home is not None else Path.home()
    runtime_home = user_home / ".cognitive_switchyard"
    return RuntimePaths(
        home=runtime_home,
        database=runtime_home / "cognitive_switchyard.db",
        config=runtime_home / "config.yaml",
        packs=runtime_home / "packs",
        sessions=runtime_home / "sessions",
    )


@dataclass(frozen=True)
class GlobalConfig:
    retention_days: int = 30
    default_planners: int = 3
    default_workers: int = 3
    default_pack: str = "claude-code"
    terminal_app: str = "iTerm"


def session_subdirs() -> tuple[str, ...]:
    return _SESSION_SUBDIRS


def canonical_pack_path(pack_name: str, relative_path: str | None = None) -> str:
    base = f"~/.cognitive_switchyard/packs/{pack_name}"
    if not relative_path:
        return base
    return f"{base}/{relative_path}"


def default_global_config(*, default_pack: str = "claude-code") -> GlobalConfig:
    return GlobalConfig(default_pack=default_pack)


def render_global_config(config: GlobalConfig) -> str:
    return (
        f"retention_days: {config.retention_days}\n"
        f"default_planners: {config.default_planners}\n"
        f"default_workers: {config.default_workers}\n"
        f"default_pack: {config.default_pack}\n"
        f"terminal_app: {config.terminal_app}\n"
    )


def write_global_config(path: Path, config: GlobalConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_global_config(config), encoding="utf-8")


def ensure_global_config(path: Path, *, default_pack: str = "claude-code") -> GlobalConfig:
    if path.is_file():
        return load_global_config(path)
    config = default_global_config(default_pack=default_pack)
    write_global_config(path, config)
    return config


def load_global_config(path: Path) -> GlobalConfig:
    import yaml

    raw = path.read_text(encoding="utf-8")
    values = yaml.safe_load(raw) or {}
    if not isinstance(values, dict):
        values = {}
    return GlobalConfig(
        retention_days=int(values.get("retention_days", 30)),
        default_planners=int(values.get("default_planners", 3)),
        default_workers=int(values.get("default_workers", 3)),
        default_pack=str(values.get("default_pack") or "claude-code"),
        terminal_app=str(values.get("terminal_app", "iTerm")),
    )
