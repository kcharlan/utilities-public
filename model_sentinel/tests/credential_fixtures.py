"""Shared synthetic credential configuration in pytest's external temp roots."""
from pathlib import Path


def write_credential_config(root: Path, *, source: str = "file") -> Path:
    runtime_home = root / "synthetic_runtime"
    runtime_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    template = Path(__file__).resolve().parents[1] / "settings.env.template"
    settings = template.read_text(encoding="utf-8")
    # Replace a template default when present; older templates need the setting added.
    settings = "\n".join(
        line for line in settings.splitlines()
        if not line.startswith("MODEL_SENTINEL_CREDENTIAL_SOURCE=")
    )
    (runtime_home / "settings.env").write_text(
        settings + f"\nMODEL_SENTINEL_CREDENTIAL_SOURCE={source}\n", encoding="utf-8"
    )
    definitions: list[str] = []
    for provider_id, enabled in (("synthetic_enabled", 1), ("synthetic_disabled", 0)):
        prefix = f"MODEL_SENTINEL_PROVIDER_{provider_id.upper()}_"
        definitions.extend(
            f"{prefix}{key}={value}" for key, value in {
                "ENABLED": enabled,
                "LABEL": provider_id,
                "KIND": "openrouter",
                "BASE_URL": "http://127.0.0.1:1",
                "MODELS_PATH": "/models",
                "API_KEY_ENV": f"{provider_id.upper()}_KEY",
                "PRICE_MULTIPLIER": 1,
                "PRICE_DIVISOR": 1,
            }.items()
        )
    (runtime_home / "providers.env").write_text("\n".join(definitions) + "\n", encoding="utf-8")
    return runtime_home
