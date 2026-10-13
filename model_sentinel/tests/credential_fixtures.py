"""Shared synthetic credential configuration in pytest's external temp roots."""
from pathlib import Path
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import threading


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


@contextmanager
def synthetic_provider_server(runtime_home: Path, *, raw_response: bytes | None = None):
    """Serve invented models on loopback and record the actual bearer headers."""
    authorizations: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            authorizations.append(self.headers.get("Authorization"))
            if raw_response is not None:
                self.wfile.write(raw_response)
                self.close_connection = True
                return
            payload = json.dumps({"data": [{"id": "synthetic-not-a-real-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    settings = runtime_home / "providers.env"
    settings.write_text(
        settings.read_text(encoding="utf-8").replace(
            "http://127.0.0.1:1", f"http://127.0.0.1:{server.server_port}"
        ), encoding="utf-8",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield authorizations
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def synthetic_protocol_response(failure: str, echo: str) -> bytes:
    """Produce actual malformed status or truncated body bytes for loopback tests."""
    body = echo.encode("ascii")
    if failure == "malformed_status":
        return body + b"\r\n\r\n"
    if failure == "truncated_body":
        return (
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(body) + 100).encode("ascii")
            + b"\r\nConnection: close\r\n\r\n" + body
        )
    raise ValueError(f"Unknown synthetic protocol failure: {failure}")


def assert_synthetic_saved_snapshot(runtime_home: Path) -> None:
    """Check persistence, not just successful execution or database creation."""
    with sqlite3.connect(runtime_home / "model_sentinel.db") as db:
        assert db.execute(
            "SELECT provider_id, status, saved_snapshot, model_count FROM scrapes"
        ).fetchall() == [("synthetic_enabled", "success", 1, 1)]
        assert db.execute(
            "SELECT provider_id, provider_model_id FROM snapshot_models"
        ).fetchall() == [("synthetic_enabled", "synthetic-not-a-real-model")]
