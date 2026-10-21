from __future__ import annotations

import json
import ssl
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from http.client import HTTPException
from typing import Any, Final, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    Request,
    build_opener,
    urlopen,
)

from . import __version__
from .config import ProviderConfig
from .endpoints import (
    ENDPOINT_ERROR_BUDGET_EXCEEDED,
    ENDPOINT_ERROR_HTTP_STATUS,
    ENDPOINT_ERROR_INVALID_JSON,
    ENDPOINT_ERROR_NETWORK,
    ENDPOINT_ERROR_REDIRECT,
    ENDPOINT_ERROR_TIMEOUT,
    ENDPOINT_FETCH_BUDGET_SECONDS,
    ENDPOINT_FETCH_TIMEOUT_SECONDS,
    ENDPOINT_FETCH_WORKERS,
    ENDPOINT_RETRY_DELAY_SECONDS,
    PATH_EMPTY,
    PATH_ERROR,
    PATH_OK,
    EndpointListError,
    EndpointOrigin,
    build_endpoint_mappings,
    endpoint_origin,
    parse_endpoint_list,
    planned_endpoint_paths,
    sanitize_endpoint_error_message,
)
from .models import EndpointFetchResult, EndpointPathResult, NormalizedModel
from .provider_profiles import ProviderProfile
from .time_utils import now_utc

USER_AGENT: Final = f"model_sentinel/{__version__}"

# Opens one request with a timeout and returns a context-managed response.
ResponseOpener: TypeAlias = Callable[[Request, float], Any]


class ProviderFetchError(RuntimeError):
    """Raised when a provider fetch fails.

    `http_status` is the response status for an HTTP failure, else None.
    """

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class _TransportError(Exception):
    """A categorized request failure that carries no upstream text.

    `category` is one of the endpoint error codes `http_status`, `timeout`,
    `network`, or `invalid_json`; `http_status` is set for the first.
    """

    def __init__(self, category: str, http_status: int | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.http_status = http_status


def _request_json(request: Request, *, timeout: float, open_response: ResponseOpener) -> Any:
    """Send one request and decode its JSON body.

    Failures become `_TransportError` with the original exception chain
    suppressed, because upstream reasons and error bodies can echo credentials.
    HTTP error bodies are closed without being read.
    """
    try:
        with open_response(request, timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        exc.close()
        raise _TransportError(ENDPOINT_ERROR_HTTP_STATUS, exc.code) from None
    except (URLError, OSError, HTTPException) as exc:
        category = ENDPOINT_ERROR_TIMEOUT if _is_timeout(exc) else ENDPOINT_ERROR_NETWORK
        raise _TransportError(category) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _TransportError(ENDPOINT_ERROR_INVALID_JSON) from None


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)


def _open_catalog(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout, context=ssl.create_default_context())


def fetch_raw_models(
    provider: ProviderConfig,
    api_key: str,
    profile: ProviderProfile,
    *,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    request = Request(
        provider.models_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        payload = _request_json(request, timeout=timeout, open_response=_open_catalog)
    except _TransportError as exc:
        raise _catalog_error(provider, exc) from None
    return extract_model_list(provider, payload, profile)


def _catalog_error(provider: ProviderConfig, exc: _TransportError) -> ProviderFetchError:
    if exc.category == ENDPOINT_ERROR_HTTP_STATUS:
        return ProviderFetchError(
            f"{provider.label} request failed with HTTP {exc.http_status}",
            http_status=exc.http_status,
        )
    if exc.category == ENDPOINT_ERROR_INVALID_JSON:
        return ProviderFetchError(f"{provider.label} returned invalid JSON")
    return ProviderFetchError(f"{provider.label} request failed: network error")


def extract_model_list(
    provider: ProviderConfig,
    payload: Any,
    profile: ProviderProfile,
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _ensure_model_dicts(provider, payload)
    if not isinstance(payload, dict):
        raise ProviderFetchError(f"{provider.label} returned an unsupported payload shape")
    for key in profile.envelope_keys:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return _ensure_model_dicts(provider, candidate)
    raise ProviderFetchError(f"{provider.label} response did not include a model list")


def _ensure_model_dicts(provider: ProviderConfig, models: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ProviderFetchError(
                f"{provider.label} returned a non-object model entry at index {index}"
            )
        normalized.append(model)
    return normalized


class _RejectRedirects(HTTPRedirectHandler):
    """Never follow a redirect; the default error handler then raises HTTPError."""

    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def endpoint_opener() -> OpenerDirector:
    """Return the endpoint-list opener: default TLS context, no redirects, no cookies."""
    return build_opener(_RejectRedirects(), HTTPSHandler(context=ssl.create_default_context()))


def _open_with(opener: OpenerDirector) -> ResponseOpener:
    def open_response(request: Request, timeout: float) -> Any:
        return opener.open(request, timeout=timeout)

    return open_response


def _endpoint_request(url: str) -> Request:
    """Build an anonymous request: no authorization or cookie header is ever added."""
    return Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )


def fetch_endpoint_lists(
    provider: ProviderConfig,
    current_map: Mapping[str, NormalizedModel],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    open_response: ResponseOpener | None = None,
    now: Callable[[], datetime] = now_utc,
) -> EndpointFetchResult:
    """Fetch the endpoint list of every distinct path the catalog maps to.

    Requests are anonymous and never follow redirects. At most
    `ENDPOINT_FETCH_WORKERS` are in flight; workers take the next path only
    when they finish one, so unstarted paths are never queued for sending. Each
    initial attempt and retry must start before a monotonic admission deadline
    `ENDPOINT_FETCH_BUDGET_SECONDS` after fetching begins; paths not started by
    then are `budget_exceeded` errors. HTTP 429 and 5xx get one retry after
    `ENDPOINT_RETRY_DELAY_SECONDS` when the delay ends before the deadline.
    Each attempt's timeout is the smaller of the remaining admission time and
    `ENDPOINT_FETCH_TIMEOUT_SECONDS`. Started workers are drained before
    returning, so a slow response can outlast the deadline; this is not a hard
    wall-clock bound.

    Raises ValueError, before any request, when the provider's models URL is
    not a valid endpoint origin. An unexpected worker exception is re-raised
    after the other workers finish their current path.
    """
    origin = endpoint_origin(provider.models_url)
    started_at = now()
    mappings = build_endpoint_mappings(current_map, origin.path_prefix)
    paths = planned_endpoint_paths(mappings)
    if open_response is None:
        open_response = _open_with(endpoint_opener())
    deadline = clock() + ENDPOINT_FETCH_BUDGET_SECONDS

    def fetch_one(path: str) -> tuple[EndpointPathResult, Any, bool]:
        return _fetch_endpoint_path(
            path,
            origin=origin,
            open_response=open_response,
            clock=clock,
            sleep=sleep,
            deadline=deadline,
        )

    outcomes = _run_bounded(paths, fetch_one)
    results = tuple(outcomes[path][0] for path in paths)
    return EndpointFetchResult(
        provider_id=provider.provider_id,
        started_at=started_at.isoformat(),
        completed_at=now().isoformat(),
        mappings=mappings,
        paths=results,
        paths_requested=len(paths),
        paths_attempted=sum(1 for path in paths if outcomes[path][2]),
        paths_failed=sum(1 for result in results if result.outcome == PATH_ERROR),
        mapping_failures=sum(1 for mapping in mappings if mapping.is_failure),
        bodies={path: outcomes[path][1] for path in paths if outcomes[path][0].outcome != PATH_ERROR},
    )


def _run_bounded(
    paths: tuple[str, ...],
    fetch_one: Callable[[str], tuple[EndpointPathResult, Any, bool]],
) -> dict[str, tuple[EndpointPathResult, Any, bool]]:
    """Run `fetch_one` over `paths` on at most `ENDPOINT_FETCH_WORKERS` threads."""
    pending = deque(paths)
    lock = threading.Lock()
    outcomes: dict[str, tuple[EndpointPathResult, Any, bool]] = {}
    failures: list[Exception] = []

    def worker() -> None:
        while True:
            with lock:
                if failures or not pending:
                    return
                path = pending.popleft()
            try:
                outcome = fetch_one(path)
            except Exception as exc:  # re-raised on the calling thread below
                with lock:
                    failures.append(exc)
                return
            with lock:
                outcomes[path] = outcome

    threads = [
        threading.Thread(target=worker, name=f"model-sentinel-endpoints-{index}", daemon=True)
        for index in range(min(ENDPOINT_FETCH_WORKERS, len(paths)))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if failures:
        raise failures[0]
    return outcomes


def _fetch_endpoint_path(
    path: str,
    *,
    origin: EndpointOrigin,
    open_response: ResponseOpener,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    deadline: float,
) -> tuple[EndpointPathResult, Any, bool]:
    """Return (path result, decoded body or None, whether a request was sent)."""
    remaining = deadline - clock()
    if remaining <= 0:
        return (
            _path_error(
                path,
                ENDPOINT_ERROR_BUDGET_EXCEEDED,
                f"not requested within the {ENDPOINT_FETCH_BUDGET_SECONDS:g}-second admission budget",
            ),
            None,
            False,
        )
    url = origin.url(path)
    retried = False
    while True:
        try:
            payload = _request_json(
                _endpoint_request(url),
                timeout=min(remaining, ENDPOINT_FETCH_TIMEOUT_SECONDS),
                open_response=open_response,
            )
            break
        except _TransportError as exc:
            if not retried and _retryable(exc) and deadline - clock() > ENDPOINT_RETRY_DELAY_SECONDS:
                sleep(ENDPOINT_RETRY_DELAY_SECONDS)
                remaining = deadline - clock()
                if remaining > 0:
                    retried = True
                    continue
            return _transport_path_error(path, exc, retried=retried), None, True
    try:
        list_model_id, entries = parse_endpoint_list(payload)
    except EndpointListError as exc:
        return _path_error(path, exc.code, str(exc)), None, True
    outcome = PATH_OK if entries else PATH_EMPTY
    return EndpointPathResult(path, list_model_id, outcome, entries, None, None, None), payload, True


def _retryable(exc: _TransportError) -> bool:
    status = exc.http_status
    return exc.category == ENDPOINT_ERROR_HTTP_STATUS and status is not None and (
        status == 429 or 500 <= status <= 599
    )


def _transport_path_error(path: str, exc: _TransportError, *, retried: bool) -> EndpointPathResult:
    status = exc.http_status
    if exc.category == ENDPOINT_ERROR_HTTP_STATUS and status is not None and 300 <= status <= 399:
        return _path_error(path, ENDPOINT_ERROR_REDIRECT, f"redirect not followed (HTTP {status})", status)
    if exc.category == ENDPOINT_ERROR_HTTP_STATUS:
        suffix = " after one retry" if retried else ""
        return _path_error(path, ENDPOINT_ERROR_HTTP_STATUS, f"HTTP {status}{suffix}", status)
    messages = {
        ENDPOINT_ERROR_TIMEOUT: "request timed out",
        ENDPOINT_ERROR_NETWORK: "network error",
        ENDPOINT_ERROR_INVALID_JSON: "response was not valid JSON",
    }
    return _path_error(path, exc.category, messages[exc.category])


def _path_error(path: str, code: str, message: str, http_status: int | None = None) -> EndpointPathResult:
    return EndpointPathResult(
        list_path=path,
        list_model_id=None,
        outcome=PATH_ERROR,
        endpoints=(),
        error_code=code,
        error_message=sanitize_endpoint_error_message(message),
        http_status=http_status,
    )
