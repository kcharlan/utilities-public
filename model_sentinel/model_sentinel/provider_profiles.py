"""Provider-specific schema and rendering knowledge.

Profiles are selected by ``ProviderConfig.kind`` and carry the vocabulary and
schema choices that differ between providers. The default price/count
predicates intentionally call :func:`default_categorize` directly. A custom
profile that overrides ``categorize`` and wants those predicates to follow the
override must provide matching predicate callables as well.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .config import ProviderConfig


PathCandidates = tuple[tuple[str, ...], ...]
PriceNormalizedTarget = Literal["per_million_tokens"]
PriceRuleMatchSource = Literal["path", "leaf", "unmatched"]

PER_MILLION_TOKENS_TARGET: PriceNormalizedTarget = "per_million_tokens"
USD_PER_MILLION_TOKENS_GROUP = "usd_per_million_tokens"


@dataclass(frozen=True)
class PriceDisplayRule:
    """Provider-declared conversion and display semantics for one price field."""

    unit_label: str
    multiplier: int | None = None
    divisor: int | None = None
    comparison_group: str | None = None
    normalized_target: PriceNormalizedTarget | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.unit_label, str) or not self.unit_label.strip():
            raise ValueError("price rule unit_label must be a non-empty string")
        if (self.multiplier is None) != (self.divisor is None):
            raise ValueError("price rule multiplier and divisor must both be explicit or inherited")
        for name, value in (("multiplier", self.multiplier), ("divisor", self.divisor)):
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 1
            ):
                raise ValueError(f"price rule {name} must be a positive integer")
        if self.comparison_group is not None and (
            not isinstance(self.comparison_group, str) or not self.comparison_group.strip()
        ):
            raise ValueError("price rule comparison_group must be a non-empty string or None")
        if self.normalized_target not in (None, PER_MILLION_TOKENS_TARGET):
            raise ValueError(
                f"unsupported price rule normalized_target: {self.normalized_target!r}"
            )


@dataclass(frozen=True)
class ResolvedPriceRule:
    """A price display rule with provider-bound effective factors."""

    unit_label: str
    multiplier: int
    divisor: int
    comparison_group: str | None
    normalized_target: PriceNormalizedTarget | None
    match_source: PriceRuleMatchSource


_EMPTY_PRICE_RULES: Mapping[str, PriceDisplayRule] = MappingProxyType({})
_GENERIC_UNMATCHED_PRICE_RULE = PriceDisplayRule(
    unit_label="/1M",
    normalized_target=PER_MILLION_TOKENS_TARGET,
)


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
    price_path_rules: Mapping[str, PriceDisplayRule] = field(
        default_factory=lambda: _EMPTY_PRICE_RULES
    )
    price_leaf_rules: Mapping[str, PriceDisplayRule] = field(
        default_factory=lambda: _EMPTY_PRICE_RULES
    )
    unmatched_price_rule: PriceDisplayRule = _GENERIC_UNMATCHED_PRICE_RULE
    primary_price_comparison_group: str | None = None
    envelope_keys: tuple[str, ...] = ("data", "models", "result", "results")
    normalized_fields: Mapping[str, PathCandidates] = field(default_factory=dict)
    field_path_labels: Mapping[str, str] = field(default_factory=dict)
    field_leaf_labels: Mapping[str, str] = field(default_factory=dict)
    pricing_field_order: tuple[str, ...] = ()
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

    def __post_init__(self) -> None:
        for name in ("price_path_rules", "price_leaf_rules"):
            registry = getattr(self, name)
            object.__setattr__(self, name, MappingProxyType(dict(registry)))

    def with_pricing(self, multiplier: int, divisor: int) -> ProviderProfile:
        bound = replace(
            self,
            price_multiplier=multiplier,
            price_divisor=divisor,
        )
        # `self` already owns defensive copies. Restore those trusted proxies
        # after `replace()` runs validation so rebinding factors preserves the
        # immutable registry objects without retaining caller-owned mappings.
        object.__setattr__(bound, "price_path_rules", self.price_path_rules)
        object.__setattr__(bound, "price_leaf_rules", self.price_leaf_rules)
        return bound


# ---------------------------------------------------------------------------
# Field label registry
#
# `RenderedChange.label` is the human-readable name every non-JSON renderer
# prints; `field_path` keeps the raw dotted path because the HTML tooltips and
# the JSON payload are audit surfaces. JSON never routes through here at all --
# `_delta_to_json` serialises `FieldChange` directly -- so labelling cannot
# change the machine-readable output.
#
# TWO PLAIN DICTS, ON PURPOSE. Adding, removing, or renaming a field label is a
# one-line edit to one of the literals below; there is no derivation, no
# decorator, and no ordering dependency between them. Each label lives in
# exactly one table so a rename is never a two-place edit.
#
# WHICH TABLE DOES A NAME GO IN?
#
#   field_path_labels -- keyed by the FULL dotted path. THE DEFAULT. A path key
#   labels exactly the field it names and nothing else.
#
#   field_leaf_labels -- keyed by the LAST segment. A LAST RESORT, used ONLY
#   when the field's parent is dynamic and therefore cannot be spelled in a
#   fixed path. Two producers create that situation, both in reporting.py:
#   `_pricing_override_path` emits
#   `pricing.overrides[min_prompt_tokens=200000].completion`, and
#   `_diff_structured_values` emits `default_parameters.<leaf>`. The pricing
#   money leaves and the six `default_parameters` leaves are leaf-keyed for
#   that reason and no other.
#
#   A leaf key is a claim over EVERY path in the product that ends in that
#   segment, including nested homonyms nobody has written yet. `name` was
#   leaf-keyed once; that made `architecture.tier_profiles[0].name` -- a tier's
#   name, filed under category "Other" -- carry the registry's label for the
#   MODEL's name. The raw path had conveyed the difference; the leaf key
#   asserted a false equivalence. Prefer a path key unless a dynamic parent
#   makes one impossible.
#
# Lookup order is exact path -> leaf -> prettified leaf. `resolve_field_label`
# is the only consumer.
#
# Seeded from every distinct non-benchmark field path observed in the history
# database. `test_registry_covers_every_seeded_field_name` pins the complete
# key/label set.
_OPENROUTER_PRICING_FIELD_ORDER = (
    "prompt",
    "input_cache_read",
    "input_cache_write",
    "input_cache_write_1h",
    "input_audio_cache",
    "completion",
)

_OPENROUTER_FIELD_PATH_LABELS: dict[str, str] = {
    # Pricing. Only the money leaves conditional pricing has been OBSERVED to
    # relocate are leaf-keyed (see below); these four are spelled in full.
    #
    # `pricing.audio`, `pricing.image` and `pricing.request` are path-keyed
    # because no recorded override tier has ever carried them -- an observation
    # about provider payloads, NOT a property of this code.
    # `_expand_pricing_override_changes` walks every key of a matched tier
    # through `_diff_structured_values`, so
    # `pricing.overrides[<condition>].request` is constructible the moment a
    # provider emits one.
    #
    # If that ever happens the three behave differently, and only one of them
    # visibly: `_prettify_leaf` spells `audio` and `image` exactly as the
    # registry does ("Audio", "Image"), so their tiered form reads correctly by
    # coincidence, while `request` falls back to "Request" and a single card
    # would show "Per request" at the base rate beside "Request
    # (min_prompt_tokens=...)" for the same money leaf. The fix at that point
    # is a leaf key for `request` -- deliberately NOT added ahead of the
    # evidence, because a leaf key claims every path in the product ending in
    # that segment (`provider_metadata.request` and any future homonym would
    # inherit "Per request", which for a non-pricing field is a false claim,
    # where "Request" is merely a plainer spelling of a true one).
    #
    # `pricing.overrides` is matched as a literal exact string -- it is never
    # itself a leaf under a dynamic parent, only the container that creates one.
    "pricing.audio": "Audio",
    "pricing.image": "Image",
    "pricing.request": "Per request",
    "pricing.overrides": "Conditional pricing",
    # Context & limits.
    #
    # `context_length` and `top_provider.context_length` are DISTINCT fields
    # that both occur in the history database, and the design requires they not
    # share a label verbatim or the report becomes ambiguous about which one
    # moved. Both are exact-path keys, so neither shadows the other and neither
    # depends on lookup order; the "(model)" disambiguator is a reader-facing
    # requirement, not a lookup mechanism, and survives on its own merits.
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
    # Default parameters. The container is path-keyed; its six leaves cannot
    # be, see below.
    "default_parameters": "Default parameters",
}

# Keyed by leaf segment. Consulted only when no full-path entry matched.
#
# EVERY entry here exists because its parent is dynamic and cannot be spelled
# as a fixed path. Nothing else belongs in this table -- a leaf key claims
# every path in the product ending in that segment.
_OPENROUTER_FIELD_LEAF_LABELS: dict[str, str] = {
    # Pricing money leaves. `_pricing_override_path` relocates these same
    # leaves under `pricing.overrides[<condition>]`, so one leaf key labels
    # both `pricing.completion` and every conditional-tier form of it.
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
    # Default parameters. The design specifies these as leaves because the
    # payload nests them one level below `default_parameters`.
    "frequency_penalty": "Frequency penalty",
    "presence_penalty": "Presence penalty",
    "repetition_penalty": "Repetition penalty",
    "temperature": "Temperature",
    "top_k": "Top-K",
    "top_p": "Top-P",
}

# Fields whose recorded values are 0/1 (not real Python bool) but are
# semantically flags, not magnitudes. Seeded from the boolean-valued fields
# observed in the history database (`top_provider.is_moderated`,
# `reasoning.default_enabled`, `reasoning.mandatory`) plus `deprecated`, which
# is not observed in any recorded change but appears in the default report
# show fields and is included as a forward guard.
#
# This set is a restriction, not a convenience: `default_parameters.top_p`,
# `default_parameters.temperature`, and `default_parameters.repetition_penalty`
# also hold 0/1 values in the history database, but they are genuinely numeric
# (a temperature of `1` is a magnitude, not a flag) and must never be treated
# as boolean.
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

_OPENROUTER_TOKEN_PRICE_RULE = PriceDisplayRule(
    unit_label="/1M tokens",
    multiplier=1_000_000,
    divisor=1,
    comparison_group=USD_PER_MILLION_TOKENS_GROUP,
    normalized_target=PER_MILLION_TOKENS_TARGET,
)

_OPENROUTER_PRICE_LEAF_RULES: Mapping[str, PriceDisplayRule] = MappingProxyType(
    {
        "prompt": _OPENROUTER_TOKEN_PRICE_RULE,
        "completion": _OPENROUTER_TOKEN_PRICE_RULE,
        "internal_reasoning": _OPENROUTER_TOKEN_PRICE_RULE,
        "input_cache_read": _OPENROUTER_TOKEN_PRICE_RULE,
        "input_cache_write": _OPENROUTER_TOKEN_PRICE_RULE,
        "web_search": PriceDisplayRule(
            unit_label="/1K searches",
            multiplier=1_000,
            divisor=1,
            comparison_group="usd_per_thousand_searches",
        ),
        "request": PriceDisplayRule(
            unit_label="/request",
            multiplier=1,
            divisor=1,
            comparison_group="usd_per_request",
        ),
        "image": PriceDisplayRule(
            unit_label="/image",
            multiplier=1,
            divisor=1,
            comparison_group="usd_per_image",
        ),
    }
)

_OPENROUTER_UNMATCHED_PRICE_RULE = PriceDisplayRule(
    unit_label="/unit unknown",
    multiplier=1,
    divisor=1,
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
    price_leaf_rules=_OPENROUTER_PRICE_LEAF_RULES,
    unmatched_price_rule=_OPENROUTER_UNMATCHED_PRICE_RULE,
    primary_price_comparison_group=USD_PER_MILLION_TOKENS_GROUP,
    envelope_keys=("data",),
    normalized_fields=_DEFAULT_NORMALIZED_FIELDS,
    field_path_labels=_OPENROUTER_FIELD_PATH_LABELS,
    field_leaf_labels=_OPENROUTER_FIELD_LEAF_LABELS,
    pricing_field_order=_OPENROUTER_PRICING_FIELD_ORDER,
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


def profiles_for(providers: Iterable[ProviderConfig]) -> dict[str, ProviderProfile]:
    return {
        provider.provider_id: resolve_profile(
            provider.kind,
            price_multiplier=provider.price_multiplier,
            price_divisor=provider.price_divisor,
        )
        for provider in providers
    }
