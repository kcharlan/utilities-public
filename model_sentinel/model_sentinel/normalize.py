from __future__ import annotations

import json
from typing import Any

from .config import ProviderConfig
from .models import NormalizedModel, canonical_json
from .provider_profiles import ProviderProfile


def normalize_models(
    provider: ProviderConfig,
    raw_models: list[dict[str, Any]],
    profile: ProviderProfile,
) -> list[NormalizedModel]:
    normalized: list[NormalizedModel] = []
    for raw_model in raw_models:
        provider_model_id = _coerce_str(
            _profile_field(raw_model, profile, "provider_model_id")
        )
        if not provider_model_id:
            raise ValueError(f"Provider {provider.provider_id} returned a model without a stable id")
        display_name = _coerce_str(
            _profile_field(raw_model, profile, "display_name")
            or provider_model_id
        )
        input_price = _normalize_price(
            profile,
            _coerce_float(
                _profile_field(raw_model, profile, "input_price")
            ),
        )
        output_price = _normalize_price(
            profile,
            _coerce_float(
                _profile_field(raw_model, profile, "output_price")
            ),
        )
        cache_read_price = _normalize_price(
            profile,
            _coerce_float(
                _profile_field(raw_model, profile, "cache_read_price")
            ),
        )
        cache_write_price = _normalize_price(
            profile,
            _coerce_float(
                _profile_field(raw_model, profile, "cache_write_price")
            ),
        )
        normalized.append(
            NormalizedModel(
                provider_id=provider.provider_id,
                provider_label=provider.label,
                provider_model_id=provider_model_id,
                display_name=display_name,
                description=_coerce_str(
                    _profile_field(raw_model, profile, "description")
                ),
                model_family=_coerce_str(
                    _profile_field(raw_model, profile, "model_family")
                ),
                created_at_provider=_coerce_str(
                    _profile_field(raw_model, profile, "created_at_provider")
                ),
                context_window=_coerce_int(
                    _profile_field(raw_model, profile, "context_window")
                ),
                max_output_tokens=_coerce_int(
                    _profile_field(raw_model, profile, "max_output_tokens")
                ),
                input_price=input_price,
                output_price=output_price,
                cache_read_price=cache_read_price,
                cache_write_price=cache_write_price,
                reasoning_supported=_coerce_bool(
                    raw_model.get("reasoning")
                    if raw_model.get("reasoning") is not None
                    else _supports_parameter(raw_model, "reasoning")
                ),
                tool_calling_supported=_coerce_bool(
                    raw_model.get("tool_call")
                    if raw_model.get("tool_call") is not None
                    else _supports_parameter(raw_model, "tools")
                ),
                vision_supported=_detect_modality(raw_model, {"vision"}),
                audio_supported=_detect_modality(raw_model, {"audio"}),
                image_supported=_detect_modality(raw_model, {"image"}),
                structured_output_supported=_coerce_bool(
                    _supports_parameter(raw_model, "response_format")
                    or _supports_parameter(raw_model, "json_schema")
                ),
                deprecated=_coerce_bool(raw_model.get("deprecated")),
                status=_coerce_str(raw_model.get("status")),
                metadata_json=canonical_json(raw_model),
            )
        )
    normalized.sort(key=lambda item: item.provider_model_id)
    return normalized


def metadata_for_comparison(model: NormalizedModel) -> dict[str, Any]:
    return json.loads(model.metadata_json)


def _nested_get(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _profile_field(
    raw_model: dict[str, Any],
    profile: ProviderProfile,
    field_name: str,
) -> Any:
    """Return the first truthy configured candidate, matching old ``or`` chains.

    Explicit but falsy values (``0``, ``""``, ``False``, and ``None``) are
    skipped exactly as they were before profiles moved the candidate paths out
    of this module.
    """
    for path in profile.normalized_fields.get(field_name, ()):
        value = _nested_get(raw_model, *path)
        if value:
            return value
    return None


def _supports_parameter(raw_model: dict[str, Any], token: str) -> bool | None:
    params = raw_model.get("supported_parameters")
    if not isinstance(params, list):
        return None
    lowered = {str(item).strip().lower() for item in params}
    return token.lower() in lowered


def _detect_modality(raw_model: dict[str, Any], tokens: set[str]) -> bool | None:
    candidates: list[str] = []
    for field in ("modality", "modalities"):
        value = raw_model.get(field)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(str(item) for item in value)
    architecture = raw_model.get("architecture")
    if isinstance(architecture, dict):
        for field in ("modality", "input_modalities", "output_modalities"):
            value = architecture.get(field)
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(str(item) for item in value)
    if not candidates:
        return None
    normalized = " ".join(candidates).lower()
    return any(token in normalized for token in tokens)


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_price(
    profile: ProviderProfile,
    value: float | None,
) -> float | None:
    if value is None:
        return None
    return (value * profile.price_multiplier) / profile.price_divisor


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None
