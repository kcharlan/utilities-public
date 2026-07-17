from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ProviderConfig


class ProviderFetchError(RuntimeError):
    """Raised when a provider fetch fails."""


def fetch_raw_models(provider: ProviderConfig, api_key: str, *, timeout: float = 30.0) -> list[dict[str, Any]]:
    request = Request(
        provider.models_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "model_sentinel/0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ProviderFetchError(
            f"{provider.label} request failed with HTTP {exc.code}: {details.strip() or exc.reason}"
        ) from exc
    except URLError as exc:
        raise ProviderFetchError(f"{provider.label} request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ProviderFetchError(f"{provider.label} returned invalid JSON") from exc
    return extract_model_list(provider, payload)


def extract_model_list(provider: ProviderConfig, payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _ensure_model_dicts(provider, payload)
    if not isinstance(payload, dict):
        raise ProviderFetchError(f"{provider.label} returned an unsupported payload shape")
    for key in ("data", "models", "result", "results"):
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

