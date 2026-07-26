"""Provider-specific schema and rendering knowledge.

Profiles are selected by ``ProviderConfig.kind`` and carry the vocabulary and
schema choices that differ between providers. The default price/count
predicates intentionally call :func:`default_categorize` directly. A custom
profile that overrides ``categorize`` and wants those predicates to follow the
override must provide matching predicate callables as well.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace


PathCandidates = tuple[tuple[str, ...], ...]


def default_categorize(field_name: str) -> str:
    lower = field_name.lower()
    if any(p in lower for p in ("pricing.", "price", "cost", "_rate")):
        return "Pricing"
    if any(
        p in lower
        for p in (
            "context_length",
            "context_window",
            "max_completion",
            "max_tokens",
            "max_output",
        )
    ):
        return "Context & Limits"
    if "supported_parameters" in lower or lower == "parameters":
        return "Parameters"
    if any(
        p in lower
        for p in (
            "vision",
            "audio",
            "image",
            "tool",
            "reasoning",
            "structured",
            "modality",
        )
    ):
        return "Capabilities"
    if lower.startswith("benchmarks.") or lower == "benchmarks":
        return "Benchmarks"
    return "Other"


def default_is_price_amount_field(field_name: str) -> bool:
    """Distinguish monetary leaves from thresholds nested under pricing."""
    if default_categorize(field_name) != "Pricing":
        return False
    leaf = field_name.rsplit(".", 1)[-1]
    leaf = leaf.split("[", 1)[0]
    return "token" not in leaf.lower()


def default_is_count_field(field_name: str) -> bool:
    lower = field_name.lower()
    leaf = lower.rsplit(".", 1)[-1].split("[", 1)[0]
    return "token" in leaf or default_categorize(field_name) == "Context & Limits"


@dataclass(frozen=True)
class ProviderProfile:
    """Provider-specific behavior bound to one provider configuration.

    Profiles contain mappings and callables and therefore are not hashable.
    Never use a profile as a dictionary key or set member.
    """

    kind: str
    price_multiplier: int = 1
    price_divisor: int = 1
    envelope_keys: tuple[str, ...] = ("data", "models", "result", "results")
    normalized_fields: Mapping[str, PathCandidates] = field(default_factory=dict)
    field_path_labels: Mapping[str, str] = field(default_factory=dict)
    field_leaf_labels: Mapping[str, str] = field(default_factory=dict)
    known_boolean_fields: frozenset[str] = frozenset()
    categorize: Callable[[str], str] = default_categorize
    is_price_amount_field: Callable[[str], bool] = default_is_price_amount_field
    is_count_field: Callable[[str], bool] = default_is_count_field
    pricing_override_condition_fields: tuple[str, ...] = (
        "min_prompt_tokens",
        "utc_start",
        "utc_end",
    )
    default_show_fields: tuple[str, ...] = ()
    default_squelch_fields: tuple[str, ...] = ()

    def with_pricing(self, multiplier: int, divisor: int) -> ProviderProfile:
        return replace(
            self,
            price_multiplier=multiplier,
            price_divisor=divisor,
        )


# Field label registry
#
# ``RenderedChange.label`` is the human-readable name every non-JSON renderer
# prints; the raw dotted path remains the audit and JSON contract.
#
# TWO PLAIN DICTS, ON PURPOSE. Each label lives in exactly one table.
#
# WHICH TABLE DOES A NAME GO IN?
#
# ``field_path_labels`` is keyed by the FULL dotted path and is the default.
# A path key labels exactly the field it names and nothing else.
#
# ``field_leaf_labels`` is keyed by the LAST segment and is a last resort used
# only when the field's parent is dynamic. Conditional-pricing paths and
# ``default_parameters.<leaf>`` create that situation.
#
# A leaf key is a claim over EVERY path ending in that segment, including
# nested homonyms nobody has written yet. Prefer a path key unless a dynamic
# parent makes one impossible. Lookup order is exact path, leaf, prettified
# leaf.
_OPENROUTER_FIELD_PATH_LABELS: dict[str, str] = {
    # Pricing. Only money leaves observed under conditional pricing are
    # leaf-keyed; these paths are intentionally exact.
    "pricing.audio": "Audio",
    "pricing.image": "Image",
    "pricing.request": "Per request",
    "pricing.overrides": "Conditional pricing",
    # Context & limits. These two context paths are intentionally distinct.
    "context_length": "Context length (model)",
    "top_provider.context_length": "Context length",
    "top_provider.max_completion_tokens": "Max output",
    # Capabilities.
    "reasoning": "Reasoning",
    "reasoning.default_enabled": "Reasoning default",
    "reasoning.default_effort": "Reasoning effort",
    "reasoning.supported_efforts": "Supported efforts",
    "reasoning.mandatory": "Reasoning required",
    "supported_parameters": "Supported parameters",
    "supported_voices": "Supported voices",
    "architecture.modality": "Modality",
    "architecture.input_modalities": "Input modalities",
    "architecture.instruct_type": "Instruct type",
    # Metadata.
    "top_provider.is_moderated": "Moderated",
    "knowledge_cutoff": "Knowledge cutoff",
    "expiration_date": "Expiration date",
    "description": "Description",
    "name": "Name",
    "created": "Created",
    "links": "Links",
    "hugging_face_id": "Hugging Face ID",
    # The container is path-keyed; its dynamic children are leaf-keyed.
    "default_parameters": "Default parameters",
}

_OPENROUTER_FIELD_LEAF_LABELS: dict[str, str] = {
    # Pricing money leaves move below conditional-tier paths.
    "prompt": "Input",
    "completion": "Output",
    "input_cache_read": "Cache read",
    "input_cache_write": "Cache write",
    "input_cache_write_1h": "Cache write (1h)",
    "input_audio_cache": "Audio cache",
    "audio_output": "Audio output",
    "image_output": "Image output",
    "web_search": "Web search",
    "internal_reasoning": "Internal reasoning",
    # Default-parameter leaves have a dynamic parent.
    "frequency_penalty": "Frequency penalty",
    "presence_penalty": "Presence penalty",
    "repetition_penalty": "Repetition penalty",
    "temperature": "Temperature",
    "top_k": "Top-K",
    "top_p": "Top-P",
}

_OPENROUTER_KNOWN_BOOLEAN_FIELDS = frozenset(
    {
        "top_provider.is_moderated",
        "reasoning.default_enabled",
        "reasoning.mandatory",
        "deprecated",
    }
)

_OPENROUTER_DEFAULT_SHOW_FIELDS = (
    "pricing.*",
    "context_length",
    "top_provider.context_length",
    "top_provider.max_completion_tokens",
    "supported_parameters",
    "default_parameters",
    "default_parameters.*",
    "architecture.*",
    "reasoning",
    "reasoning.*",
    "expiration_date",
    "status",
    "deprecated",
    "knowledge_cutoff",
    "top_provider.is_moderated",
)

_OPENROUTER_DEFAULT_SQUELCH_FIELDS = (
    "benchmarks",
    "benchmarks.*",
)

_DEFAULT_NORMALIZED_FIELDS: Mapping[str, PathCandidates] = {
    "provider_model_id": (("id",), ("model",), ("name",)),
    "display_name": (("name",), ("display_name",)),
    "description": (("description",), ("short_description",)),
    "model_family": (("family",), ("developer",)),
    "created_at_provider": (("created",), ("created_at",)),
    "context_window": (
        ("context_length",),
        ("limit", "context"),
        ("context_window",),
    ),
    "max_output_tokens": (
        ("top_provider", "max_completion_tokens"),
        ("limit", "output"),
        ("max_output_tokens",),
    ),
    "input_price": (
        ("pricing", "input"),
        ("pricing", "prompt"),
        ("cost", "input"),
        ("input_token_rate",),
    ),
    "output_price": (
        ("pricing", "output"),
        ("pricing", "completion"),
        ("cost", "output"),
        ("output_token_rate",),
    ),
    "cache_read_price": (
        ("pricing", "input_cache_read"),
        ("pricing", "cache_read"),
    ),
    "cache_write_price": (
        ("pricing", "input_cache_write"),
        ("pricing", "cache_write"),
    ),
}


GENERIC_PROFILE = ProviderProfile(
    kind="generic",
    normalized_fields=_DEFAULT_NORMALIZED_FIELDS,
)

OPENROUTER_PROFILE = ProviderProfile(
    kind="openrouter",
    envelope_keys=("data",),
    normalized_fields=_DEFAULT_NORMALIZED_FIELDS,
    field_path_labels=_OPENROUTER_FIELD_PATH_LABELS,
    field_leaf_labels=_OPENROUTER_FIELD_LEAF_LABELS,
    known_boolean_fields=_OPENROUTER_KNOWN_BOOLEAN_FIELDS,
    default_show_fields=_OPENROUTER_DEFAULT_SHOW_FIELDS,
    default_squelch_fields=_OPENROUTER_DEFAULT_SQUELCH_FIELDS,
)

PROFILE_REGISTRY: dict[str, ProviderProfile] = {
    "openrouter": OPENROUTER_PROFILE,
}


def resolve_profile(
    kind: str,
    *,
    price_multiplier: int = 1,
    price_divisor: int = 1,
) -> ProviderProfile:
    """Resolve ``kind`` with a generic fallback and bind pricing factors."""
    profile = PROFILE_REGISTRY.get(kind.lower(), GENERIC_PROFILE)
    return profile.with_pricing(price_multiplier, price_divisor)
