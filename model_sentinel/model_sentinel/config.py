from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .envfile import EnvFileError, parse_env_file


class ConfigError(ValueError):
    """Raised when runtime configuration is invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    label: str
    kind: str
    base_url: str
    models_path: str
    credential_env_var: str
    price_multiplier: int
    price_divisor: int
    enabled: bool

    @property
    def models_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.models_path.lstrip('/')}"


@dataclass(frozen=True)
class Settings:
    log_max_bytes: int
    log_keep_files: int
    report_dir: Path
    report_retention_days: int
    report_detail: str
    report_show_fields: tuple[str, ...]
    report_squelch_fields: tuple[str, ...]
    report_unclassified_limit: int
    notify_default: bool
    notify_on: str
    notify_open_target: str
    notify_sound: str | None
    terminal_notifier_path: Path | None
    runtime_home: Path


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    providers_env: Path
    settings_env: Path
    runtime_home: Path
    database_path: Path
    logs_dir: Path
    log_file: Path
    debug_dir: Path
    report_dir: Path

    def ensure_directories(self) -> None:
        self.runtime_home.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class LoadedConfig:
    project_root: Path
    runtime_paths: RuntimePaths
    settings: Settings
    providers: tuple[ProviderConfig, ...]


_PROVIDER_SUFFIXES = (
    "ENABLED",
    "LABEL",
    "KIND",
    "BASE_URL",
    "MODELS_PATH",
    "API_KEY_ENV",
    "PRICE_MULTIPLIER",
    "PRICE_DIVISOR",
)


def load_config(project_root: Path) -> LoadedConfig:
    runtime_home = default_runtime_home()
    providers_env = runtime_home / "providers.env"
    settings_env = runtime_home / "settings.env"
    if not providers_env.is_file():
        raise ConfigError(
            f"Missing provider config: {providers_env}. Run ./setup.sh to create the config files in the runtime home."
        )
    if not settings_env.is_file():
        raise ConfigError(
            f"Missing settings config: {settings_env}. Run ./setup.sh to create the config files in the runtime home."
        )
    providers = load_provider_configs(providers_env)
    settings = load_settings(settings_env, runtime_home=runtime_home)
    runtime_paths = build_runtime_paths(
        project_root=project_root,
        providers_env=providers_env,
        settings_env=settings_env,
        settings=settings,
    )
    return LoadedConfig(
        project_root=project_root,
        runtime_paths=runtime_paths,
        settings=settings,
        providers=providers,
    )


def build_runtime_paths(
    *,
    project_root: Path,
    providers_env: Path,
    settings_env: Path,
    settings: Settings,
) -> RuntimePaths:
    runtime_home = settings.runtime_home
    return RuntimePaths(
        project_root=project_root,
        providers_env=providers_env,
        settings_env=settings_env,
        runtime_home=runtime_home,
        database_path=runtime_home / "model_sentinel.db",
        logs_dir=runtime_home / "logs",
        log_file=runtime_home / "logs" / "model_sentinel.log",
        debug_dir=runtime_home / "debug",
        report_dir=settings.report_dir,
    )


def load_provider_configs(path: Path) -> tuple[ProviderConfig, ...]:
    try:
        raw = parse_env_file(path)
    except EnvFileError as exc:
        raise ConfigError(str(exc)) from exc
    grouped: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        match = _match_provider_key(key)
        if not match:
            continue
        provider_id, suffix = match
        grouped.setdefault(provider_id, {})[suffix] = value
    if not grouped:
        raise ConfigError(f"No provider definitions found in {path}")
    providers: list[ProviderConfig] = []
    for provider_id, values in sorted(grouped.items()):
        missing = [suffix for suffix in _PROVIDER_SUFFIXES if suffix not in values]
        if missing:
            joined = ", ".join(missing)
            raise ConfigError(f"Provider {provider_id!r} missing required keys: {joined}")
        enabled = _parse_bool(values["ENABLED"])
        providers.append(
            ProviderConfig(
                provider_id=provider_id.lower(),
                label=values["LABEL"],
                kind=values["KIND"],
                base_url=values["BASE_URL"].rstrip("/"),
                models_path=values["MODELS_PATH"],
                credential_env_var=values["API_KEY_ENV"],
                price_multiplier=_parse_positive_int(
                    values["PRICE_MULTIPLIER"],
                    f"MODEL_SENTINEL_PROVIDER_{provider_id.upper()}_PRICE_MULTIPLIER",
                ),
                price_divisor=_parse_positive_int(
                    values["PRICE_DIVISOR"],
                    f"MODEL_SENTINEL_PROVIDER_{provider_id.upper()}_PRICE_DIVISOR",
                ),
                enabled=enabled,
            )
        )
    _reject_duplicate_labels(providers, path)
    return tuple(providers)


def _reject_duplicate_labels(providers: list[ProviderConfig], path: Path) -> None:
    """Refuse a providers.env in which two providers claim the same label.

    A label is display text; `provider_id` is identity. Reports key on identity
    and disambiguate a shared label as `Label (provider_id)`, so a collision is
    no longer a correctness problem -- but it is still a config authoring
    mistake that makes every report, notification and summary row ambiguous
    about which provider it is talking about, and the user owns the file that
    fixes it.

    Raised, not warned, because `ConfigError` is the only validation mechanism
    this module has: every other invalid value here (a bad boolean, a
    non-positive price divisor, an unknown detail mode) already halts the load.
    `healthcheck` catches `ConfigError` and renders it as a failed `config_load`
    check, so the one command a user runs to diagnose config keeps working and
    names the problem exactly.

    Comparison is exact. Labels differing in case or spacing are still
    distinguishable to a reader; only identical spellings are not.
    """
    by_label: dict[str, list[str]] = {}
    for provider in providers:
        by_label.setdefault(provider.label, []).append(provider.provider_id)
    collisions = sorted(
        (label, ids) for label, ids in by_label.items() if len(ids) > 1
    )
    if not collisions:
        return
    detail = "; ".join(f"{label!r} used by {', '.join(sorted(ids))}" for label, ids in collisions)
    raise ConfigError(
        f"Duplicate provider label{'s' if len(collisions) != 1 else ''} in {path}: {detail}. "
        "Provider labels must be unique; give each provider a distinct "
        "MODEL_SENTINEL_PROVIDER_<ID>_LABEL."
    )


def load_settings(path: Path, *, runtime_home: Path) -> Settings:
    try:
        raw = parse_env_file(path)
    except EnvFileError as exc:
        raise ConfigError(str(exc)) from exc
    def _required(name: str) -> str:
        if name not in raw:
            raise ConfigError(f"Missing required setting {name} in {path}")
        return raw[name]

    log_max_bytes = _parse_positive_int(_required("MODEL_SENTINEL_LOG_MAX_BYTES"), "MODEL_SENTINEL_LOG_MAX_BYTES")
    log_keep_files = _parse_positive_int(_required("MODEL_SENTINEL_LOG_KEEP_FILES"), "MODEL_SENTINEL_LOG_KEEP_FILES")
    if log_keep_files < 1:
        raise ConfigError("MODEL_SENTINEL_LOG_KEEP_FILES must be at least 1")
    report_dir = _resolve_path(
        _required("MODEL_SENTINEL_REPORT_DIR"),
        base_dir=runtime_home,
    )
    retention_raw = raw.get("MODEL_SENTINEL_REPORT_RETENTION_DAYS", "30").strip()
    try:
        report_retention_days = int(retention_raw)
    except ValueError as exc:
        raise ConfigError("MODEL_SENTINEL_REPORT_RETENTION_DAYS must be an integer") from exc
    if report_retention_days < 0:
        raise ConfigError("MODEL_SENTINEL_REPORT_RETENTION_DAYS must be >= 0 (0 disables cleanup)")
    report_detail = raw.get("MODEL_SENTINEL_REPORT_DETAIL", "default").strip().lower()
    if report_detail not in {"default", "all", "squelched"}:
        raise ConfigError("MODEL_SENTINEL_REPORT_DETAIL must be one of default, all, squelched")
    report_show_fields = _parse_csv_patterns(
        raw.get(
            "MODEL_SENTINEL_REPORT_SHOW_FIELDS",
            (
                "pricing.*,context_length,top_provider.context_length,"
                "top_provider.max_completion_tokens,supported_parameters,"
                "default_parameters,default_parameters.*,architecture.*,reasoning,"
                "reasoning.*,expiration_date,status,deprecated,knowledge_cutoff,"
                "top_provider.is_moderated"
            ),
        )
    )
    report_squelch_fields = _parse_csv_patterns(
        raw.get("MODEL_SENTINEL_REPORT_SQUELCH_FIELDS", "benchmarks,benchmarks.*")
    )
    unclassified_raw = raw.get("MODEL_SENTINEL_REPORT_UNCLASSIFIED_LIMIT", "20").strip()
    try:
        report_unclassified_limit = int(unclassified_raw)
    except ValueError as exc:
        raise ConfigError("MODEL_SENTINEL_REPORT_UNCLASSIFIED_LIMIT must be an integer") from exc
    if report_unclassified_limit < 0:
        raise ConfigError("MODEL_SENTINEL_REPORT_UNCLASSIFIED_LIMIT must be >= 0")
    notify_default = _parse_bool(_required("MODEL_SENTINEL_NOTIFY_DEFAULT"))
    notify_on = _required("MODEL_SENTINEL_NOTIFY_ON").strip().lower()
    if notify_on not in {"changes", "errors", "both", "never"}:
        raise ConfigError("MODEL_SENTINEL_NOTIFY_ON must be one of changes, errors, both, never")
    notify_open_target = _required("MODEL_SENTINEL_NOTIFY_OPEN_TARGET").strip().lower()
    if notify_open_target not in {"file", "folder"}:
        raise ConfigError("MODEL_SENTINEL_NOTIFY_OPEN_TARGET must be one of file or folder")
    notify_sound = _parse_optional_sound_name(raw.get("MODEL_SENTINEL_NOTIFY_SOUND", "default"))
    terminal_notifier_path = _parse_optional_path(raw.get("MODEL_SENTINEL_TERMINAL_NOTIFIER_PATH", ""))
    return Settings(
        log_max_bytes=log_max_bytes,
        log_keep_files=log_keep_files,
        report_dir=report_dir,
        report_retention_days=report_retention_days,
        report_detail=report_detail,
        report_show_fields=report_show_fields,
        report_squelch_fields=report_squelch_fields,
        report_unclassified_limit=report_unclassified_limit,
        notify_default=notify_default,
        notify_on=notify_on,
        notify_open_target=notify_open_target,
        notify_sound=notify_sound,
        terminal_notifier_path=terminal_notifier_path,
        runtime_home=runtime_home,
    )


def validate_selected_providers(
    providers: tuple[ProviderConfig, ...],
    *,
    provider_id: str | None,
) -> tuple[ProviderConfig, ...]:
    if provider_id is None:
        selected = tuple(provider for provider in providers if provider.enabled)
        if not selected:
            raise ConfigError("No enabled providers found in providers.env")
        return selected
    selected = tuple(provider for provider in providers if provider.provider_id == provider_id)
    if not selected:
        raise ConfigError(f"Unknown provider {provider_id!r}")
    return selected


def missing_credentials(
    providers: tuple[ProviderConfig, ...],
    environ: dict[str, str] | os._Environ[str],
) -> list[str]:
    missing: list[str] = []
    for provider in providers:
        value = environ.get(provider.credential_env_var, "").strip()
        if not value:
            missing.append(provider.credential_env_var)
    return missing


def _match_provider_key(key: str) -> tuple[str, str] | None:
    for suffix in _PROVIDER_SUFFIXES:
        token = f"MODEL_SENTINEL_PROVIDER_"
        ending = f"_{suffix}"
        if key.startswith(token) and key.endswith(ending):
            provider_id = key[len(token):-len(ending)]
            if not provider_id:
                return None
            if not re.fullmatch(r"[A-Z0-9_]+", provider_id):
                raise ConfigError(f"Invalid provider key {key!r}")
            return provider_id.lower(), suffix
    return None


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value: {value!r}")


def _parse_positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be > 0")
    return parsed


def _parse_csv_patterns(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def default_runtime_home() -> Path:
    override = os.environ.get("MODEL_SENTINEL_HOME", "").strip()
    if override:
        return Path(os.path.expanduser(override)).resolve()
    return (Path.home() / ".model_sentinel").resolve()


def _resolve_path(value: str, *, base_dir: Path) -> Path:
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _parse_optional_sound_name(value: str) -> str | None:
    normalized = value.strip()
    if not normalized or normalized.lower() in {"none", "off", "0"}:
        return None
    return normalized


def _parse_optional_path(value: str) -> Path | None:
    normalized = value.strip()
    if not normalized:
        return None
    return Path(os.path.expanduser(normalized)).resolve()
