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
from typing import TYPE_CHECKING, Any, Hashable, Literal

if TYPE_CHECKING:
    from .config import ProviderConfig


PathCandidates = tuple[tuple[str, ...], ...]
PriceNormalizedTarget = Literal["per_million_tokens"]
PriceRuleMatchSource = Literal["path", "leaf", "unmatched"]
ConditionFamily = Literal["time", "threshold"]
ConditionSemanticRole = Literal[
    "utc_weekdays",
    "utc_start_inclusive",
    "utc_end_exclusive",
    "integer_strictly_greater",
]

PER_MILLION_TOKENS_TARGET: PriceNormalizedTarget = "per_million_tokens"
USD_PER_MILLION_TOKENS_GROUP = "usd_per_million_tokens"


@dataclass(frozen=True)
class ConditionalPricingConditionDescriptor:
    """Provider-owned parsing and identity semantics for one rule selector.

    The stored callables operate on successive values: ``parse_value`` accepts
    raw JSON, ``canonical_identity`` accepts the parsed value, and
    ``format_value`` accepts the canonical value. Raw-boundary consumers must
    use :meth:`canonicalize_raw` or :meth:`format_raw` rather than invoking a
    stage callable directly.
    """

    field_name: str
    family: ConditionFamily
    semantic_role: ConditionSemanticRole
    parse_value: Callable[[Any], Any]
    canonical_identity: Callable[[Any], Hashable]
    format_value: Callable[[Any], str]
    participates_in_interval_grouping: bool

    def __post_init__(self) -> None:
        if not isinstance(self.field_name, str) or not self.field_name.strip():
            raise ValueError("conditional pricing descriptor field_name must be non-empty")
        if self.family not in ("time", "threshold"):
            raise ValueError(f"unsupported conditional pricing family: {self.family!r}")
        if self.semantic_role not in {
            "utc_weekdays",
            "utc_start_inclusive",
            "utc_end_exclusive",
            "integer_strictly_greater",
        }:
            raise ValueError(
                f"unsupported conditional pricing semantic role: {self.semantic_role!r}"
            )
        role_contract = {
            "utc_weekdays": ("time", True),
            "utc_start_inclusive": ("time", True),
            "utc_end_exclusive": ("time", True),
            "integer_strictly_greater": ("threshold", False),
        }[self.semantic_role]
        if self.family != role_contract[0]:
            raise ValueError("conditional pricing semantic role is incompatible with its family")
        for name, value in (
            ("parse_value", self.parse_value),
            ("canonical_identity", self.canonical_identity),
            ("format_value", self.format_value),
        ):
            if not callable(value):
                raise ValueError(f"conditional pricing descriptor {name} must be callable")
        if not isinstance(self.participates_in_interval_grouping, bool):
            raise ValueError(
                "conditional pricing descriptor participates_in_interval_grouping must be bool"
            )
        if self.participates_in_interval_grouping != role_contract[1]:
            raise ValueError(
                "conditional pricing semantic role is incompatible with interval grouping"
            )

    def canonicalize_raw(self, raw_value: Any) -> Hashable:
        """Parse raw JSON and return its canonical selector identity."""
        parsed_value = self.parse_value(raw_value)
        return self.canonical_identity(parsed_value)

    def format_raw(self, raw_value: Any) -> str:
        """Parse and canonicalize raw JSON before formatting it for presentation."""
        parsed_value = self.parse_value(raw_value)
        canonical_value = self.canonical_identity(parsed_value)
        return self.format_value(canonical_value)


@dataclass(frozen=True)
class ConditionalPricingConditionSetSemantics:
    """Provider-owned rules for absent and paired time selectors."""

    missing_weekdays: Literal["all_seven"]
    missing_endpoints: Literal["all_day"]
    endpoint_pairing: Literal["both_or_neither"]
    equal_endpoints: Literal["unsupported"]

    def __post_init__(self) -> None:
        if self.missing_weekdays != "all_seven":
            raise ValueError("unsupported missing_weekdays semantics")
        if self.missing_endpoints != "all_day":
            raise ValueError("unsupported missing_endpoints semantics")
        if self.endpoint_pairing != "both_or_neither":
            raise ValueError("unsupported endpoint_pairing semantics")
        if self.equal_endpoints != "unsupported":
            raise ValueError("unsupported equal_endpoints semantics")


@dataclass(frozen=True)
class ConditionalPricingPolicySemantics:
    """Provider-owned precedence and inheritance semantics for rule policies."""

    condition_combination: Literal["all_conditions"]
    rule_precedence: Literal["later_per_key"]
    omitted_price_behavior: Literal["retain_prior_or_base"]
    top_level_price_role: Literal["default_base"]

    def __post_init__(self) -> None:
        if self.condition_combination != "all_conditions":
            raise ValueError("unsupported condition_combination semantics")
        if self.rule_precedence != "later_per_key":
            raise ValueError("unsupported rule_precedence semantics")
        if self.omitted_price_behavior != "retain_prior_or_base":
            raise ValueError("unsupported omitted_price_behavior semantics")
        if self.top_level_price_role != "default_base":
            raise ValueError("unsupported top_level_price_role semantics")


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
    pricing_override_condition_descriptors: Mapping[
        str, ConditionalPricingConditionDescriptor
    ] = field(default_factory=dict)
    pricing_override_condition_set_semantics: ConditionalPricingConditionSetSemantics | None = None
    pricing_override_policy_semantics: ConditionalPricingPolicySemantics | None = None
    pricing_override_base_paths: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "price_path_rules",
            "price_leaf_rules",
            "pricing_override_condition_descriptors",
            "pricing_override_base_paths",
        ):
            registry = getattr(self, name)
            object.__setattr__(self, name, MappingProxyType(dict(registry)))

        descriptor_roles: set[ConditionSemanticRole] = set()
        for raw_name, descriptor in self.pricing_override_condition_descriptors.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ValueError("conditional pricing descriptor keys must be non-empty strings")
            if not isinstance(descriptor, ConditionalPricingConditionDescriptor):
                raise ValueError("conditional pricing descriptor registry values must be descriptors")
            if raw_name != descriptor.field_name:
                raise ValueError("conditional pricing descriptor registry key must match field_name")
            if descriptor.semantic_role in descriptor_roles:
                raise ValueError("conditional pricing descriptor semantic roles must be unique")
            descriptor_roles.add(descriptor.semantic_role)

        for dimension, base_path in self.pricing_override_base_paths.items():
            if (
                not isinstance(dimension, str)
                or not dimension.strip()
                or dimension != dimension.strip()
            ):
                raise ValueError("conditional pricing base-path dimensions must be non-empty strings")
            if (
                not isinstance(base_path, str)
                or not base_path.strip()
                or base_path != base_path.strip()
            ):
                raise ValueError("conditional pricing base paths must be non-empty strings")

        if self.pricing_override_condition_set_semantics is not None and not isinstance(
            self.pricing_override_condition_set_semantics,
            ConditionalPricingConditionSetSemantics,
        ):
            raise ValueError(
                "conditional pricing condition-set semantics must be a semantics declaration or None"
            )
        if self.pricing_override_policy_semantics is not None and not isinstance(
            self.pricing_override_policy_semantics,
            ConditionalPricingPolicySemantics,
        ):
            raise ValueError(
                "conditional pricing policy semantics must be a semantics declaration or None"
            )

    @property
    def pricing_override_selector_names(self) -> tuple[str, ...]:
        """Return selector identities, with rich declarations taking precedence.

        Legacy names remain identity-only compatibility inputs. Consumers that
        need parsing, ordering, grouping, or comparison semantics must ask for
        a rich descriptor instead of inferring behavior from this tuple.
        """
        return tuple(
            dict.fromkeys(
                (
                    *self.pricing_override_condition_fields,
                    *self.pricing_override_condition_descriptors,
                )
            )
        )

    def is_pricing_override_selector_path(self, field_path: str) -> bool:
        """Return whether ``field_path`` is one exact override selector leaf.

        Selector identity is provider-owned, while the namespace shape is the
        canonical report path: ``pricing.overrides[<rule>].<leaf>``.  The
        bracket qualifier may contain dots, so split only outside brackets.
        A malformed/unbalanced path is never granted selector identity.
        """
        if not isinstance(field_path, str) or not field_path:
            return False
        segments: list[str] = []
        current: list[str] = []
        depth = 0
        for character in field_path:
            if character == "[":
                depth += 1
            elif character == "]":
                depth -= 1
                if depth < 0:
                    return False
            if character == "." and depth == 0:
                segments.append("".join(current))
                current = []
            else:
                current.append(character)
        if depth != 0:
            return False
        segments.append("".join(current))
        if len(segments) != 3 or segments[0] != "pricing":
            return False
        override_segment = segments[1]
        if override_segment != "overrides" and not (
            override_segment.startswith("overrides[")
            and override_segment.endswith("]")
        ):
            return False
        return segments[2] in self.pricing_override_selector_names

    def pricing_override_condition_descriptor(
        self,
        field_name: str,
    ) -> ConditionalPricingConditionDescriptor | None:
        """Return the rich declaration for ``field_name``, if the profile owns one."""
        return self.pricing_override_condition_descriptors.get(field_name)

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
        object.__setattr__(
            bound,
            "pricing_override_condition_descriptors",
            self.pricing_override_condition_descriptors,
        )
        object.__setattr__(bound, "pricing_override_base_paths", self.pricing_override_base_paths)
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

_OPENROUTER_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_OPENROUTER_WEEKDAY_ABBREVIATIONS = {
    "monday": "Mon",
    "tuesday": "Tue",
    "wednesday": "Wed",
    "thursday": "Thu",
    "friday": "Fri",
    "saturday": "Sat",
    "sunday": "Sun",
}


def _parse_openrouter_integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("OpenRouter conditional integer values must be JSON integers")
    return value


def _format_openrouter_min_prompt_tokens(value: Any) -> str:
    return f"Prompt > {_parse_openrouter_integer(value):,} tokens"


def _parse_openrouter_utc_days(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("OpenRouter utc_days must be a non-empty JSON list")
    if any(not isinstance(day, str) for day in value):
        raise ValueError("OpenRouter utc_days must contain weekday names")
    if len(set(value)) != len(value):
        raise ValueError("OpenRouter utc_days must not contain duplicate weekdays")
    if any(day not in _OPENROUTER_WEEKDAYS for day in value):
        raise ValueError("OpenRouter utc_days contains an unknown weekday")
    return tuple(day for day in _OPENROUTER_WEEKDAYS if day in value)


def _format_openrouter_utc_days(value: Any) -> str:
    days = _parse_openrouter_utc_days(list(value))
    runs: list[tuple[str, ...]] = []
    current: list[str] = []
    previous_index: int | None = None
    for day in days:
        index = _OPENROUTER_WEEKDAYS.index(day)
        if previous_index is not None and index != previous_index + 1:
            runs.append(tuple(current))
            current = []
        current.append(day)
        previous_index = index
    if current:
        runs.append(tuple(current))
    return ", ".join(
        _OPENROUTER_WEEKDAY_ABBREVIATIONS[run[0]]
        if len(run) == 1
        else (
            f"{_OPENROUTER_WEEKDAY_ABBREVIATIONS[run[0]]}-"
            f"{_OPENROUTER_WEEKDAY_ABBREVIATIONS[run[-1]]}"
        )
        for run in runs
    )


def _parse_openrouter_utc_hhmm(value: Any) -> int:
    hhmm = _parse_openrouter_integer(value)
    hours, minutes = divmod(hhmm, 100)
    if hhmm < 0 or hours > 23 or minutes > 59:
        raise ValueError("OpenRouter UTC times must be valid HHMM integers")
    return hours * 60 + minutes


def _format_openrouter_utc_minute(value: Any) -> str:
    minute = _canonical_openrouter_utc_minute(value)
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def _format_openrouter_utc_end_minute(value: Any) -> str:
    minute = _canonical_openrouter_utc_minute(value)
    if minute == 0:
        return "24:00"
    return _format_openrouter_utc_minute(minute)


def _canonical_openrouter_utc_minute(value: Any) -> int:
    minute = _parse_openrouter_integer(value)
    if not 0 <= minute < 24 * 60:
        raise ValueError("OpenRouter UTC minute must be within one day")
    return minute


_OPENROUTER_CONDITIONAL_PRICING_DESCRIPTORS: Mapping[
    str, ConditionalPricingConditionDescriptor
] = MappingProxyType(
    {
        "min_prompt_tokens": ConditionalPricingConditionDescriptor(
            field_name="min_prompt_tokens",
            family="threshold",
            semantic_role="integer_strictly_greater",
            parse_value=_parse_openrouter_integer,
            canonical_identity=_parse_openrouter_integer,
            format_value=_format_openrouter_min_prompt_tokens,
            participates_in_interval_grouping=False,
        ),
        "utc_days": ConditionalPricingConditionDescriptor(
            field_name="utc_days",
            family="time",
            semantic_role="utc_weekdays",
            parse_value=_parse_openrouter_utc_days,
            canonical_identity=lambda value: _parse_openrouter_utc_days(list(value)),
            format_value=_format_openrouter_utc_days,
            participates_in_interval_grouping=True,
        ),
        "utc_start": ConditionalPricingConditionDescriptor(
            field_name="utc_start",
            family="time",
            semantic_role="utc_start_inclusive",
            parse_value=_parse_openrouter_utc_hhmm,
            canonical_identity=_canonical_openrouter_utc_minute,
            format_value=_format_openrouter_utc_minute,
            participates_in_interval_grouping=True,
        ),
        "utc_end": ConditionalPricingConditionDescriptor(
            field_name="utc_end",
            family="time",
            semantic_role="utc_end_exclusive",
            parse_value=_parse_openrouter_utc_hhmm,
            canonical_identity=_canonical_openrouter_utc_minute,
            format_value=_format_openrouter_utc_end_minute,
            participates_in_interval_grouping=True,
        ),
    }
)

_OPENROUTER_CONDITIONAL_PRICING_CONDITION_SET_SEMANTICS = (
    ConditionalPricingConditionSetSemantics(
        missing_weekdays="all_seven",
        missing_endpoints="all_day",
        endpoint_pairing="both_or_neither",
        equal_endpoints="unsupported",
    )
)

_OPENROUTER_CONDITIONAL_PRICING_POLICY_SEMANTICS = ConditionalPricingPolicySemantics(
    condition_combination="all_conditions",
    rule_precedence="later_per_key",
    omitted_price_behavior="retain_prior_or_base",
    top_level_price_role="default_base",
)

_OPENROUTER_PRICING_OVERRIDE_BASE_PATHS: Mapping[str, str] = MappingProxyType(
    {dimension: f"pricing.{dimension}" for dimension in _OPENROUTER_PRICE_LEAF_RULES}
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
    pricing_override_condition_descriptors=_OPENROUTER_CONDITIONAL_PRICING_DESCRIPTORS,
    pricing_override_condition_set_semantics=(
        _OPENROUTER_CONDITIONAL_PRICING_CONDITION_SET_SEMANTICS
    ),
    pricing_override_policy_semantics=_OPENROUTER_CONDITIONAL_PRICING_POLICY_SEMANTICS,
    pricing_override_base_paths=_OPENROUTER_PRICING_OVERRIDE_BASE_PATHS,
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
