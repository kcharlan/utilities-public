from __future__ import annotations

import errno
import importlib.resources
import json
import logging
import re
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from ..provider_profiles import profiles_for, resolve_profile
from ..reporting import detail_policy_from_settings
from . import api, queries
from .api import ApiContext, BadRequest, NotFound
from .aspects import build_aspect_catalog
from .readonly import DatabaseBusyError


_LOG = logging.getLogger("model_sentinel.browse")
_SAFE_STATIC_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_ENCODED_SEPARATOR = re.compile(r"%(?:2f|5c)", re.IGNORECASE)
_BUSY_MESSAGE = "The database is busy — a scan may be writing. Try again in a moment."
_API_ROUTES = frozenset(
    ("meta", "activity", "heatmap", "series", "events", "catalog", "models")
)


def _candidate_ports(start_port: int, max_attempts: int) -> range:
    if not isinstance(start_port, int) or isinstance(start_port, bool):
        raise ValueError("start_port must be an integer")
    if (
        not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or max_attempts < 1
    ):
        raise ValueError("max_attempts must be a positive integer")
    if start_port < 0 or start_port > 65535:
        raise ValueError("start_port must be between 0 and 65535")
    if start_port == 0:
        return range(0, 1)

    end_port = min(65535, start_port + max_attempts - 1)
    return range(start_port, end_port + 1)


def _no_free_port(start_port: int, candidates: range) -> RuntimeError:
    return RuntimeError(
        f"No free port found in range {start_port}–{candidates.stop - 1}"
    )


def find_free_port(start_port: int, max_attempts: int = 20) -> int:
    """Return the first bindable loopback port at or above ``start_port``."""
    candidates = _candidate_ports(start_port, max_attempts)
    if start_port == 0:
        return 0
    for candidate_port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", candidate_port))
            except OSError:
                continue
            return candidate_port
    raise _no_free_port(start_port, candidates)


class _BrowseHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], ctx: ApiContext) -> None:
        self.ctx = ctx
        super().__init__(server_address, _BrowseHandler)


class _BrowseHandler(BaseHTTPRequestHandler):
    server: _BrowseHTTPServer

    def __getattr__(self, name: str) -> Any:
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(
            f"{type(self).__name__!s} object has no attribute {name!r}"
        )

    def do_GET(self) -> None:
        if not self._valid_host():
            self._send_json(403, {"error": "forbidden"})
            return
        try:
            split = urlsplit(self.path)
            params = self._query_params(split.query)
            if self._serve_api(split.path, params):
                return
            if self._serve_static(split.path):
                return
            raise NotFound("not found")
        except BadRequest as exc:
            self._send_json(400, {"error": exc.message})
        except NotFound as exc:
            self._send_json(404, {"error": exc.message})
        except DatabaseBusyError:
            self._send_json(503, {"error": _BUSY_MESSAGE})
        except Exception as exc:
            _LOG.exception("Browse request failed")
            self._send_json(500, {"error": f"internal error: {type(exc).__name__}"})

    def do_POST(self) -> None:
        self._method_not_allowed()

    def do_HEAD(self) -> None:
        self._method_not_allowed(head=True)

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_TRACE(self) -> None:
        self._method_not_allowed()

    def do_CONNECT(self) -> None:
        self._method_not_allowed()

    def _method_not_allowed(self, *, head: bool = False) -> None:
        if not self._valid_host():
            self._send_json(403, {"error": "forbidden"}, head=head)
            return
        self._send_json(405, {"error": "method not allowed"}, head=head)

    def _valid_host(self) -> bool:
        values = self.headers.get_all("Host", failobj=[])
        if len(values) != 1:
            return False
        port = self.server.server_address[1]
        return values[0] in (f"127.0.0.1:{port}", f"localhost:{port}")

    @staticmethod
    def _query_params(query: str) -> dict[str, str]:
        parsed = parse_qs(query, keep_blank_values=True)
        for name, values in parsed.items():
            if len(values) != 1:
                raise BadRequest(f"duplicate query parameter: {name}")
        return {name: values[0] for name, values in parsed.items()}

    def _serve_api(self, path: str, params: dict[str, str]) -> bool:
        if path.startswith("/api/change/"):
            raw_change_id = path.removeprefix("/api/change/")
            if not raw_change_id.isdecimal() or "/" in raw_change_id:
                raise NotFound("not found")
            result = api.change(self.server.ctx, {**params, "change_id": raw_change_id})
            self._send_json(200, result)
            return True
        if not path.startswith("/api/"):
            return False
        name = path.removeprefix("/api/")
        if name not in _API_ROUTES:
            raise NotFound("not found")
        result = getattr(api, name)(self.server.ctx, params)
        self._send_json(200, result)
        return True

    def _serve_static(self, raw_path: str) -> bool:
        if _ENCODED_SEPARATOR.search(raw_path):
            raise NotFound("not found")
        path = unquote(raw_path)
        if path in ("/", "/index.html"):
            name = "index.html"
            location = (
                importlib.resources.files("model_sentinel.browse")
                .joinpath("assets")
                .joinpath(name)
            )
        elif path in ("/app.js", "/app.css"):
            name = path[1:]
            location = (
                importlib.resources.files("model_sentinel.browse")
                .joinpath("assets")
                .joinpath(name)
            )
        elif path.startswith("/vendor/"):
            name = path.removeprefix("/vendor/")
            if not name or ".." in name or not _SAFE_STATIC_NAME.fullmatch(name):
                raise NotFound("not found")
            location = (
                importlib.resources.files("model_sentinel.browse")
                .joinpath("assets")
                .joinpath("vendor")
                .joinpath(name)
            )
        else:
            return False
        try:
            body = location.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            raise NotFound("not found") from None
        self._send_bytes(200, body, _content_type(name))
        return True

    def _send_json(self, status: int, payload: Any, *, head: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8", head=head)

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        head: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        _LOG.debug("HTTP %s - %s", self.client_address[0], format % args)


def _content_type(name: str) -> str:
    suffix = name.rsplit(".", 1)[-1].casefold() if "." in name else ""
    return {
        "html": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "js": "application/javascript; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
    }.get(suffix, "text/plain; charset=utf-8")


def make_server(
    ctx: ApiContext,
    *,
    host: str = "127.0.0.1",
    port: int,
) -> ThreadingHTTPServer:
    return _BrowseHTTPServer((host, port), ctx)


def _bind_server(
    ctx: ApiContext,
    *,
    port: int,
    max_attempts: int = 20,
) -> tuple[ThreadingHTTPServer, int]:
    candidates = _candidate_ports(port, max_attempts)
    for candidate_port in candidates:
        try:
            return make_server(ctx, port=candidate_port), candidate_port
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
    raise _no_free_port(port, candidates)


def _open_browser(browser_url: str) -> None:
    try:
        webbrowser.open(browser_url)
    except Exception:
        _LOG.warning(
            "Could not open browser; visit %s manually.",
            browser_url,
            exc_info=True,
        )


def run_browse(
    *,
    db: Any,
    loaded: Any,
    port: int,
    open_browser: bool,
    initial_provider: str | None,
) -> int:
    server: ThreadingHTTPServer | None = None
    try:
        db_providers = tuple(queries.db_providers(db.connection()))
        profiles = profiles_for(loaded.providers)
        for row in db_providers:
            profiles.setdefault(
                str(row["provider_id"]), resolve_profile(str(row["kind"]))
            )
        policy = detail_policy_from_settings(loaded.settings)
        aspects = build_aspect_catalog(db, profiles=profiles, policy=policy)
        ctx = ApiContext(
            db=db,
            providers=loaded.providers,
            db_providers=db_providers,
            profiles=profiles,
            settings=loaded.settings,
            aspects=aspects,
        )

        server, resolved_port = _bind_server(ctx, port=port)
        if resolved_port != port:
            _LOG.warning("Port %s is in use; using port %s instead.", port, resolved_port)
        actual_port = server.server_address[1]
        base_url = f"http://127.0.0.1:{actual_port}/"
        print(f"Model Sentinel browser: {base_url}", flush=True)
        if open_browser:
            browser_url = base_url
            if initial_provider is not None:
                browser_url += f"#providers={quote(initial_provider, safe='')}"
            threading.Thread(
                target=_open_browser,
                args=(browser_url,),
                name="model-sentinel-browser-opener",
                daemon=True,
            ).start()

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        try:
            if server is not None:
                stopped = getattr(server, "_BaseServer__is_shut_down", None)
                if stopped is not None and not stopped.is_set():
                    stopped.set()
                try:
                    server.shutdown()
                finally:
                    server.server_close()
        finally:
            db.close_all()
