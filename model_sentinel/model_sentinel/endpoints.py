"""Pure primitives for saved provider endpoint lists.

This module holds no I/O. It defines the endpoint-capture constants, how each
catalog model maps to an endpoint-list path (alias resolution and path
validation included), how a list response is validated, how an endpoint's
comparable state is separated from volatile telemetry and status, how
endpoints in a response-ordered list are keyed, how two keyed lists are
compared, how scalar price leaves are resolved, how a capture's overall
status is derived, and how a capture is compared with its selected baseline
capture into the in-memory summary that storage persists. Transport, storage
and rendering consume these functions.
"""

from __future__ import annotations

import hashlib
import json
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Final, Literal, NamedTuple, TypeAlias
from urllib.parse import urlsplit

from .change_render import ResolvedPriceValue, resolve_price_value
from .credentials import redact_credential_values
from .diffing import diff_values
from .models import (
    EndpointCaptureCandidate,
    EndpointCaptureSummary,
    EndpointChange,
    EndpointChangeRecord,
    EndpointComparisonGap,
    EndpointFetchResult,
    EndpointListRecord,
    EndpointMapping,
    EndpointObservationRecord,
    NormalizedModel,
    canonical_json,
)
from .provider_profiles import ProviderProfile

ENDPOINT_FETCH_TIMEOUT_SECONDS: Final[float] = 30.0
ENDPOINT_FETCH_WORKERS: Final[int] = 4
ENDPOINT_FETCH_BUDGET_SECONDS: Final[float] = 180.0
ENDPOINT_RETRY_DELAY_SECONDS: Final[float] = 1.0
CONCISE_ENDPOINT_LIST_CAP: Final[int] = 25
DOSSIER_ENDPOINT_CHANGE_LIMIT: Final[int] = 200

CAPTURE_COMPLETE: Final = "complete"
CAPTURE_PARTIAL: Final = "partial"
CAPTURE_ERROR: Final = "error"
CAPTURE_STATUSES: Final = (CAPTURE_COMPLETE, CAPTURE_PARTIAL, CAPTURE_ERROR)
CaptureStatus: TypeAlias = Literal["complete", "partial", "error"]

ENDPOINT_ADDED: Final = "endpoint_added"
ENDPOINT_REMOVED: Final = "endpoint_removed"
FIELD_CHANGED: Final = "field_changed"
STATUS_CHANGED: Final = "status_changed"

# Entries with no usable tag, name or provider_name share this base. It is the
# empty string so it cannot equal the base of any entry that has an identifier.
UNNAMED_ENDPOINT_BASE: Final = ""
PRICING_OVERRIDES_FIELD: Final = "pricing.overrides"

# endpoint key -> (stable state, status value), as `diff_endpoint_lists` expects.
EndpointObservation: TypeAlias = tuple[Mapping[str, Any], Any]

MAPPING_LISTED: Final = "listed"
MAPPING_ALIAS: Final = "alias"
MAPPING_NO_LINK: Final = "no_link"
MAPPING_INVALID_LINK: Final = "invalid_link"
MAPPING_OUTCOMES: Final = (MAPPING_LISTED, MAPPING_ALIAS, MAPPING_NO_LINK, MAPPING_INVALID_LINK)
ALIAS_TARGET_MISSING: Final = "alias_target_missing"
ALIAS_CYCLE: Final = "alias_cycle"

PATH_OK: Final = "ok"
PATH_EMPTY: Final = "empty"
PATH_ERROR: Final = "error"
PATH_OUTCOMES: Final = (PATH_OK, PATH_EMPTY, PATH_ERROR)

# Per-path error codes. Messages paired with them are built from fixed text and
# numbers only; no upstream reason, header, or body text is ever included.
ENDPOINT_ERROR_HTTP_STATUS: Final = "http_status"
ENDPOINT_ERROR_REDIRECT: Final = "redirect"
ENDPOINT_ERROR_TIMEOUT: Final = "timeout"
ENDPOINT_ERROR_NETWORK: Final = "network"
ENDPOINT_ERROR_INVALID_JSON: Final = "invalid_json"
ENDPOINT_ERROR_INVALID_ENVELOPE: Final = "invalid_envelope"
ENDPOINT_ERROR_INVALID_ENDPOINT: Final = "invalid_endpoint"
ENDPOINT_ERROR_BUDGET_EXCEEDED: Final = "budget_exceeded"
ENDPOINT_ERROR_CODES: Final = (
    ENDPOINT_ERROR_HTTP_STATUS,
    ENDPOINT_ERROR_REDIRECT,
    ENDPOINT_ERROR_TIMEOUT,
    ENDPOINT_ERROR_NETWORK,
    ENDPOINT_ERROR_INVALID_JSON,
    ENDPOINT_ERROR_INVALID_ENVELOPE,
    ENDPOINT_ERROR_INVALID_ENDPOINT,
    ENDPOINT_ERROR_BUDGET_EXCEEDED,
)
ENDPOINT_ERROR_MESSAGE_LIMIT: Final[int] = 200

_ENDPOINTS_SUFFIX: Final = "/endpoints"
_MODELS_SEGMENT: Final = "/models"
# RFC 3986 pchar characters other than percent escapes, which are decoded and
# checked separately.
_PATH_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "-._~!$&'()*+,;=:@")
_FORBIDDEN_DECODED_BYTES: Final = frozenset(b"/\\?#%") | frozenset(range(0x20)) | {0x7F}
_HEX_DIGITS: Final = frozenset(string.hexdigits)
_ORIGIN_ERROR: Final = (
    "endpoint capture requires an HTTPS models URL with a host, an optional port, "
    "no user information, query or fragment, and a path ending in /models"
)


@dataclass(frozen=True)
class EndpointOrigin:
    """The validated request origin and the path prefix every list path must have."""

    origin: str
    path_prefix: str

    def url(self, list_path: str) -> str:
        return f"{self.origin}{list_path}"


def endpoint_origin(models_url: str) -> EndpointOrigin:
    """Validate the configured models URL and derive the endpoint-list origin.

    The URL must be HTTPS with a hostname and an optional port, and must have no
    user information, query, fragment, whitespace or control characters. Its
    path, after trailing slashes are removed, must end in a `/models` segment;
    endpoint-list paths must start with that path plus `/`. The error message
    never repeats the URL, which could carry user information.
    """
    if not isinstance(models_url, str) or any(
        not character.isprintable() or character.isspace() for character in models_url
    ):
        raise ValueError(_ORIGIN_ERROR)
    try:
        parts = urlsplit(models_url)
        parts.port
    except ValueError:
        raise ValueError(_ORIGIN_ERROR) from None
    base_path = parts.path.rstrip("/")
    if (
        parts.scheme != "https"
        or not parts.hostname
        or "@" in parts.netloc
        or "?" in models_url
        or "#" in models_url
        or not base_path.endswith(_MODELS_SEGMENT)
    ):
        raise ValueError(_ORIGIN_ERROR)
    return EndpointOrigin(origin=f"https://{parts.netloc}", path_prefix=f"{base_path}/")


def endpoint_list_path(link: Any, path_prefix: str) -> str | None:
    """Return `link` when it is a valid endpoint-list path under `path_prefix`.

    A valid path is absolute, starts with the prefix (which ends in `/`), has a
    nonempty slug, and ends in `/endpoints`. Every segment must be nonempty,
    use only RFC 3986 path characters or well-formed percent escapes, and must
    not decode to a dot segment or to a separator, backslash, query, fragment,
    percent sign or control character. Anything else returns None.
    """
    if (
        not isinstance(link, str)
        or not link.startswith(path_prefix)
        or not link.endswith(_ENDPOINTS_SUFFIX)
        or len(link) <= len(path_prefix) + len(_ENDPOINTS_SUFFIX)
    ):
        return None
    if not all(_valid_path_segment(segment) for segment in link[1:].split("/")):
        return None
    return link


def _valid_path_segment(segment: str) -> bool:
    decoded = bytearray()
    index = 0
    while index < len(segment):
        character = segment[index]
        if character == "%":
            escape = segment[index + 1 : index + 3]
            if len(escape) != 2 or not set(escape) <= _HEX_DIGITS:
                return False
            decoded.append(int(escape, 16))
            index += 3
            continue
        if character not in _PATH_CHARACTERS:
            return False
        decoded.append(ord(character))
        index += 1
    if not decoded or bytes(decoded) in (b".", b".."):
        return False
    return not any(byte in _FORBIDDEN_DECODED_BYTES for byte in decoded)


def build_endpoint_mappings(
    models: Mapping[str, NormalizedModel],
    path_prefix: str,
) -> tuple[EndpointMapping, ...]:
    """Return one mapping per catalog model, sorted by catalog model ID.

    Each model's `metadata()` is classified on its own: a non-null
    `alias_target` makes it an alias (a nonempty string `slug` is required,
    otherwise `invalid_link`) and takes precedence over any link; otherwise a
    null or absent `links` or `links.details` is `no_link`, and a non-object
    `links` or a `details` value that is not a valid path is `invalid_link`.
    Aliases are then followed by exact catalog model ID with a visited set
    until a listed model is reached; a missing ID, a revisited ID, or a model
    with no usable link leaves the alias unresolved. Targets are never inferred
    from names, prefixes or version-like text.
    """
    links = {
        model.provider_model_id: _classify_link(model.metadata(), path_prefix)
        for model in models.values()
    }
    alias_targets = {model_id: target for model_id, (_, _, target) in links.items()}
    return tuple(
        _resolve_mapping(model_id, links, alias_targets) for model_id in sorted(links)
    )


def alias_declaration(metadata: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Return (whether the model declares an alias, its direct target ID).

    A non-null `alias_target` declares an alias. Its target is the nonempty
    string `slug`; any other shape is a malformed declaration with no target.
    """
    alias = metadata.get("alias_target")
    if alias is None:
        return False, None
    slug = alias.get("slug") if isinstance(alias, Mapping) else None
    return True, slug if isinstance(slug, str) and slug else None


def resolve_alias_chain(
    alias_model_id: str,
    alias_targets: Mapping[str, str | None],
) -> tuple[str | None, str | None]:
    """Follow an alias chain by exact catalog model ID with a visited set.

    `alias_targets` maps every catalog model ID to its direct alias target, or
    None for a model with no followable target (not an alias, or a malformed
    declaration). Returns (terminal model ID, None), where the terminal is the
    first model on the chain without a followable target, or (None, error) with
    `alias_target_missing` for an ID outside the catalog or `alias_cycle` for a
    revisited ID, including an alias that targets itself. Link validity plays
    no part; callers judge the terminal model. Raises ValueError when
    `alias_model_id` has no followable target.
    """
    current = alias_targets.get(alias_model_id)
    if current is None:
        raise ValueError("alias chain must start at a model with an alias target")
    visited = {alias_model_id}
    while True:
        if current not in alias_targets:
            return None, ALIAS_TARGET_MISSING
        if current in visited:
            return None, ALIAS_CYCLE
        visited.add(current)
        following = alias_targets[current]
        if following is None:
            return current, None
        current = following


def planned_endpoint_paths(mappings: Sequence[EndpointMapping]) -> tuple[str, ...]:
    """Return the distinct paths of `listed` mappings, sorted.

    Aliases resolve only to paths some listed model already has, so they add no
    request of their own.
    """
    return tuple(
        sorted({mapping.list_path for mapping in mappings if mapping.outcome == MAPPING_LISTED})
    )


def _classify_link(metadata: Mapping[str, Any], path_prefix: str) -> tuple[str, str | None, str | None]:
    """Return (outcome, own list path, direct alias target) for one model."""
    declares_alias, target = alias_declaration(metadata)
    if declares_alias:
        if target is not None:
            return MAPPING_ALIAS, None, target
        return MAPPING_INVALID_LINK, None, None
    links = metadata.get("links")
    if links is None:
        return MAPPING_NO_LINK, None, None
    if not isinstance(links, Mapping):
        return MAPPING_INVALID_LINK, None, None
    details = links.get("details")
    if details is None:
        return MAPPING_NO_LINK, None, None
    list_path = endpoint_list_path(details, path_prefix)
    if list_path is None:
        return MAPPING_INVALID_LINK, None, None
    return MAPPING_LISTED, list_path, None


def _resolve_mapping(
    model_id: str,
    links: Mapping[str, tuple[str, str | None, str | None]],
    alias_targets: Mapping[str, str | None],
) -> EndpointMapping:
    outcome, list_path, target = links[model_id]
    if outcome == MAPPING_LISTED:
        return EndpointMapping(model_id, outcome, list_path, None, None, None)
    if outcome != MAPPING_ALIAS:
        return EndpointMapping(model_id, outcome, None, None, None, outcome)
    terminal, error_code = resolve_alias_chain(model_id, alias_targets)
    if terminal is not None:
        terminal_outcome, terminal_path, _ = links[terminal]
        if terminal_outcome == MAPPING_LISTED:
            return EndpointMapping(model_id, MAPPING_ALIAS, terminal_path, target, terminal, None)
        # A terminal model without a usable link passes its own reason through.
        error_code = terminal_outcome
    return EndpointMapping(model_id, MAPPING_ALIAS, None, target, None, error_code)


class EndpointListError(ValueError):
    """A decoded endpoint-list response with an invalid shape; `code` is its error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_endpoint_list(payload: Any) -> tuple[str | None, tuple[dict[str, Any], ...]]:
    """Return (response `data.id` or None, endpoint objects) from a decoded body.

    The body must be an object whose `data` object holds an `endpoints` array
    of objects. A missing, null or empty `data.id` is allowed; any other
    non-string ID is an invalid envelope.
    """
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping) or not isinstance(data.get("endpoints"), list):
        raise EndpointListError(ENDPOINT_ERROR_INVALID_ENVELOPE, "response did not include an endpoint list")
    list_model_id = data.get("id")
    if list_model_id is not None and not isinstance(list_model_id, str):
        raise EndpointListError(ENDPOINT_ERROR_INVALID_ENVELOPE, "response model id was not a string")
    entries = data["endpoints"]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise EndpointListError(
                ENDPOINT_ERROR_INVALID_ENDPOINT, f"non-object endpoint entry at index {index}"
            )
    return list_model_id or None, tuple(entries)


def sanitize_endpoint_error_message(message: str) -> str:
    """Collapse whitespace and control characters and bound the length."""
    text = " ".join(
        "".join(character if character.isprintable() else " " for character in str(message)).split()
    )
    if len(text) > ENDPOINT_ERROR_MESSAGE_LIMIT:
        text = text[: ENDPOINT_ERROR_MESSAGE_LIMIT - 3] + "..."
    return text


def endpoint_failure_message(error: BaseException, credential_values: Mapping[str, str]) -> str:
    """Exception type and message with credential values masked; never a traceback."""
    return sanitize_endpoint_error_message(
        redact_credential_values(f"{type(error).__name__}: {error}", credential_values)
    )


class KeyedEndpoint(NamedTuple):
    key: str
    endpoint: Mapping[str, Any]


def endpoint_state(endpoint: Mapping[str, Any], profile: ProviderProfile) -> dict[str, Any]:
    """Return the endpoint without profile telemetry and status fields.

    Only top-level fields are removed. The input is not modified.
    """
    excluded = set(profile.endpoint_telemetry_fields)
    if profile.endpoint_status_field is not None:
        excluded.add(profile.endpoint_status_field)
    return {name: value for name, value in endpoint.items() if name not in excluded}


def endpoint_status(endpoint: Mapping[str, Any], profile: ProviderProfile) -> Any:
    """Return the endpoint's status value, or None when the profile has no status field."""
    if profile.endpoint_status_field is None:
        return None
    return endpoint.get(profile.endpoint_status_field)


def endpoint_state_hash(state: Mapping[str, Any]) -> str:
    """Return the SHA-256 hex digest of the state's canonical JSON."""
    return hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()


def endpoint_key(endpoint: Mapping[str, Any], occurrence: int) -> str:
    """Return `<base>#<occurrence>` for one endpoint.

    The base is the first nonempty string among `tag`, `name` and
    `provider_name`, else the reserved unnamed base. `occurrence` is the
    zero-based position among entries sharing that base in response order.
    Reordering entries that share a base can therefore appear as changes; this
    key is not a stable physical endpoint identity.
    """
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise ValueError("endpoint occurrence must be a non-negative integer")
    return f"{_endpoint_base(endpoint)}#{occurrence}"


def key_endpoint_list(endpoints: Sequence[Mapping[str, Any]]) -> tuple[KeyedEndpoint, ...]:
    """Key a response-ordered endpoint list, counting occurrences per base."""
    seen: dict[str, int] = {}
    keyed: list[KeyedEndpoint] = []
    for endpoint in endpoints:
        base = _endpoint_base(endpoint)
        occurrence = seen.get(base, 0)
        seen[base] = occurrence + 1
        keyed.append(KeyedEndpoint(endpoint_key(endpoint, occurrence), endpoint))
    return tuple(keyed)


def _endpoint_base(endpoint: Mapping[str, Any]) -> str:
    for field_name in ("tag", "name", "provider_name"):
        value = endpoint.get(field_name)
        if isinstance(value, str) and value:
            return value
    return UNNAMED_ENDPOINT_BASE


def diff_endpoint_lists(
    old: Mapping[str, EndpointObservation],
    new: Mapping[str, EndpointObservation],
) -> tuple[EndpointChange, ...]:
    """Compare two keyed endpoint lists.

    Output follows the old list's order (removals, or field then status changes
    of common keys), then additions in the new list's order. Field changes
    within one endpoint are sorted by dotted path.
    """
    changes: list[EndpointChange] = []
    for key, (old_state, old_status) in old.items():
        if key not in new:
            changes.append(EndpointChange(key, ENDPOINT_REMOVED, None, dict(old_state), None))
            continue
        new_state, new_status = new[key]
        for path, old_value, new_value in _diff_states(old_state, new_state):
            changes.append(EndpointChange(key, FIELD_CHANGED, path, old_value, new_value))
        if old_status != new_status:
            changes.append(EndpointChange(key, STATUS_CHANGED, None, old_status, new_status))
    for key, (new_state, _) in new.items():
        if key not in old:
            changes.append(EndpointChange(key, ENDPOINT_ADDED, None, None, dict(new_state)))
    return tuple(changes)


def _diff_states(
    old_state: Mapping[str, Any],
    new_state: Mapping[str, Any],
) -> list[tuple[str, Any, Any]]:
    """Diff two stable states with `pricing.overrides` kept as one parent change.

    A missing or null `pricing` on one side is compared as an empty object when
    the other side has one, so scalar price children are reported individually
    instead of as one whole-object change, and overrides never expand into
    selector or rate descendants.
    """
    old_rest, old_overrides = _split_overrides(old_state)
    new_rest, new_overrides = _split_overrides(new_state)
    if isinstance(old_rest.get("pricing"), dict) and not new_rest.get("pricing"):
        new_rest["pricing"] = {}
    elif isinstance(new_rest.get("pricing"), dict) and not old_rest.get("pricing"):
        old_rest["pricing"] = {}
    changes = diff_values(old_rest, new_rest)
    if old_overrides != new_overrides:
        changes.append((PRICING_OVERRIDES_FIELD, old_overrides, new_overrides))
    return sorted(changes, key=lambda change: change[0])


def _split_overrides(state: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
    rest = dict(state)
    pricing = rest.get("pricing")
    if not isinstance(pricing, dict) or "overrides" not in pricing:
        return rest, None
    rest["pricing"] = {name: value for name, value in pricing.items() if name != "overrides"}
    return rest, pricing["overrides"]


@dataclass(frozen=True)
class PriceLeaf:
    """One direct scalar child of an endpoint's `pricing` object.

    `resolved` is True only when the profile gives the leaf a strict price
    identity; only then are `normalized_exact_value`, `unit_label`,
    `comparison_group` and `price` set. Unresolved leaves stay visible for
    matching but must not enter price arithmetic. `price` is the full resolved
    value, which `format_price_values` formats; it takes no part in equality.
    """

    path: str
    raw_value: Any
    resolved: bool
    normalized_exact_value: Fraction | None = None
    unit_label: str | None = None
    comparison_group: str | None = None
    price: ResolvedPriceValue | None = field(default=None, compare=False, repr=False)


def resolve_price_leaf(path: str, raw_value: Any, profile: ProviderProfile) -> PriceLeaf:
    """Resolve one scalar price value at `path` through the strict contract."""
    resolved = resolve_price_value(path, raw_value, profile)
    if resolved is None:
        return PriceLeaf(path=path, raw_value=raw_value, resolved=False)
    return PriceLeaf(
        path=path,
        raw_value=raw_value,
        resolved=True,
        normalized_exact_value=resolved.normalized_exact_value,
        unit_label=resolved.price_rule.unit_label,
        comparison_group=resolved.price_rule.comparison_group,
        price=resolved,
    )


def resolved_price_leaves(
    metadata: Mapping[str, Any],
    profile: ProviderProfile,
) -> tuple[PriceLeaf, ...]:
    """Return the direct scalar children of `pricing`, sorted by path.

    Object and array children are excluded before resolution, and so is
    `pricing.overrides` whatever its value: a null or scalar policy is still
    a policy, never a price leaf. Each remaining leaf is resolved through the
    strict `resolve_price_value` contract, so an unmatched field is unresolved.
    """
    pricing = metadata.get("pricing")
    if not isinstance(pricing, Mapping):
        return ()
    return tuple(
        resolve_price_leaf(f"pricing.{name}", pricing[name], profile)
        for name in sorted(pricing, key=str)
        if f"pricing.{name}" != PRICING_OVERRIDES_FIELD
        and not isinstance(pricing[name], (Mapping, list, tuple))
    )


def aggregate_capture_status(
    *,
    paths_requested: int,
    paths_failed: int,
    mapping_failures: int,
    capture_exception: bool = False,
) -> CaptureStatus:
    """Derive a capture's status from its counts.

    `paths_failed` includes paths never attempted after the admission cutoff, so
    the successful paths are `paths_requested - paths_failed`. A capture with no
    failure is complete, including when nothing could be planned; a failure with
    at least one successful path is partial; a failure with none, or a
    capture-level exception, is an error.
    """
    if paths_requested < 0 or paths_failed < 0 or mapping_failures < 0:
        raise ValueError("capture counts must be non-negative")
    if paths_failed > paths_requested:
        raise ValueError("paths_failed cannot exceed paths_requested")
    if capture_exception:
        return CAPTURE_ERROR
    if paths_failed == 0 and mapping_failures == 0:
        return CAPTURE_COMPLETE
    if paths_requested - paths_failed > 0:
        return CAPTURE_PARTIAL
    return CAPTURE_ERROR


# How the selected catalog baseline's capture relates to this capture.
COMPARISON_AVAILABLE: Final = "available"
COMPARISON_NO_SELECTED_BASELINE: Final = "no_selected_baseline"
COMPARISON_MISSING_BASELINE_CAPTURE: Final = "missing_baseline_capture"
COMPARISON_UNUSABLE_BASELINE: Final = "unusable_baseline"
COMPARISON_STATES: Final = (
    COMPARISON_AVAILABLE,
    COMPARISON_NO_SELECTED_BASELINE,
    COMPARISON_MISSING_BASELINE_CAPTURE,
    COMPARISON_UNUSABLE_BASELINE,
)

# Why a list could not be compared. Gaps are recorded only when the comparison
# state is `available`.
GAP_BASELINE_OBSERVATION_FAILED: Final = "baseline_observation_failed"
GAP_CURRENT_OBSERVATION_FAILED: Final = "current_observation_failed"
GAP_NEW_PATH_UNPAIRED: Final = "new_path_unpaired"
GAP_REMOVED_PATH_UNPAIRED: Final = "removed_path_unpaired"
GAP_AMBIGUOUS_MAPPING: Final = "ambiguous_mapping"
GAP_REASONS: Final = (
    GAP_BASELINE_OBSERVATION_FAILED,
    GAP_CURRENT_OBSERVATION_FAILED,
    GAP_NEW_PATH_UNPAIRED,
    GAP_REMOVED_PATH_UNPAIRED,
    GAP_AMBIGUOUS_MAPPING,
)

_SQLITE_INTEGER_MIN: Final = -(2**63)
_SQLITE_INTEGER_MAX: Final = 2**63 - 1


def endpoint_status_code(status: Any) -> int | None:
    """Return a status value that is a storable integer, else None.

    Booleans and non-integer values are not status codes. Both sides of every
    comparison use this value, so a non-integer status never yields a change
    against its persisted form; the raw value survives in the capture archive.
    """
    if isinstance(status, bool) or not isinstance(status, int):
        return None
    if not _SQLITE_INTEGER_MIN <= status <= _SQLITE_INTEGER_MAX:
        return None
    return status


def endpoint_list_records(
    fetch: EndpointFetchResult,
    profile: ProviderProfile,
) -> tuple[EndpointListRecord, ...]:
    """Return one list record per fetched path, in the fetch's path order."""
    model_ids: dict[str, list[str]] = {}
    for mapping in fetch.mappings:
        if mapping.outcome == MAPPING_LISTED and mapping.list_path is not None:
            model_ids.setdefault(mapping.list_path, []).append(mapping.provider_model_id)
    records: list[EndpointListRecord] = []
    for path in fetch.paths:
        observations = tuple(
            _observation_record(keyed.key, keyed.endpoint, profile)
            for keyed in key_endpoint_list(path.endpoints)
        )
        records.append(
            EndpointListRecord(
                list_path=path.list_path,
                list_model_id=path.list_model_id,
                outcome=path.outcome,
                endpoint_count=len(observations),
                error_code=path.error_code,
                error_message=(
                    None
                    if path.error_message is None
                    else sanitize_endpoint_error_message(path.error_message)
                ),
                model_ids=tuple(sorted(model_ids.get(path.list_path, ()))),
                observations=observations,
            )
        )
    return tuple(records)


def _observation_record(
    key: str,
    endpoint: Mapping[str, Any],
    profile: ProviderProfile,
) -> EndpointObservationRecord:
    state = endpoint_state(endpoint, profile)
    # Decode the canonical form so the in-memory state equals its persisted copy
    # and shares no mutable values with the fetched response.
    return EndpointObservationRecord(
        endpoint_key=key,
        state_hash=endpoint_state_hash(state),
        state=json.loads(canonical_json(state)),
        status_code=endpoint_status_code(endpoint_status(endpoint, profile)),
    )


def endpoint_capture_usable(capture: EndpointCaptureSummary) -> bool:
    """Whether a capture can serve as a comparison baseline.

    A capture is unusable when its status is `error` and none of its lists has
    a successful (`ok` or `empty`) observation, which includes every minimal
    error capture. A partial capture is usable; its failed lists become gaps.
    """
    return capture.status != CAPTURE_ERROR or any(listing.succeeded for listing in capture.lists)


def endpoint_comparison_state(
    *,
    provider_id: str,
    baseline_scrape_id: int | None,
    baseline_capture: EndpointCaptureSummary | None,
) -> tuple[str, int | None]:
    """Return (comparison_state, baseline_capture_id) for the selected baseline.

    `baseline_scrape_id` is the selected catalog baseline scrape and
    `baseline_capture` that scrape's persisted capture, if any; no other
    capture is ever substituted. Raises ValueError when the capture does not
    belong to that scrape and provider or was never persisted.
    """
    if baseline_scrape_id is None:
        if baseline_capture is not None:
            raise ValueError("a baseline capture was given without a selected baseline scrape")
        return COMPARISON_NO_SELECTED_BASELINE, None
    if baseline_capture is None:
        return COMPARISON_MISSING_BASELINE_CAPTURE, None
    if baseline_capture.scrape_id != baseline_scrape_id:
        raise ValueError("baseline capture does not belong to the selected baseline scrape")
    if baseline_capture.provider_id != provider_id:
        raise ValueError("baseline capture belongs to a different provider")
    if baseline_capture.capture_id is None:
        raise ValueError("baseline capture has not been persisted")
    if not endpoint_capture_usable(baseline_capture):
        return COMPARISON_UNUSABLE_BASELINE, baseline_capture.capture_id
    return COMPARISON_AVAILABLE, baseline_capture.capture_id


def compare_endpoint_captures(
    baseline_lists: Sequence[EndpointListRecord],
    current_lists: Sequence[EndpointListRecord],
    *,
    from_capture_id: int,
) -> tuple[tuple[EndpointChangeRecord, ...], tuple[EndpointComparisonGap, ...]]:
    """Compare a usable baseline capture's lists with the current lists.

    A path present on both sides is compared in place. A path that disappeared
    is compared with a newly present path only through a unique moved-mapping
    edge (see `_pair_moved_paths`); the changes are stored under the new path
    with `from_list_path` preserving the old one. Diffs need a successful
    observation on each side; a failed side records a gap instead. Unpaired
    and ambiguously mapped paths record gaps and no presence diff.

    Changes follow current path order, then `diff_endpoint_lists` order. Gaps
    are sorted by (list_path, reason).
    """
    old = {listing.list_path: listing for listing in baseline_lists}
    new = {listing.list_path: listing for listing in current_lists}
    pairs, ambiguous = _pair_moved_paths(old, new)
    changes: list[EndpointChangeRecord] = []
    gaps: list[EndpointComparisonGap] = []
    for path in sorted(new):
        current = new[path]
        source_path = path if path in old else pairs.get(path)
        if source_path is None:
            reason = GAP_AMBIGUOUS_MAPPING if path in ambiguous else GAP_NEW_PATH_UNPAIRED
            gaps.append(EndpointComparisonGap(path, reason, None))
            continue
        baseline = old[source_path]
        if not baseline.succeeded:
            gaps.append(EndpointComparisonGap(path, GAP_BASELINE_OBSERVATION_FAILED, source_path))
        if not current.succeeded:
            gaps.append(EndpointComparisonGap(path, GAP_CURRENT_OBSERVATION_FAILED, source_path))
        if not (baseline.succeeded and current.succeeded):
            continue
        for change in diff_endpoint_lists(_observation_map(baseline), _observation_map(current)):
            changes.append(
                EndpointChangeRecord(
                    from_capture_id=from_capture_id,
                    to_capture_id=None,
                    from_list_path=source_path,
                    list_path=path,
                    endpoint_key=change.endpoint_key,
                    change_kind=change.change_kind,
                    field_name=change.field_name,
                    old_value=change.old_value,
                    new_value=change.new_value,
                    display_id=current.display_id,
                    model_ids=current.model_ids,
                )
            )
    paired_sources = set(pairs.values())
    for path in sorted(old):
        if path in new or path in paired_sources:
            continue
        reason = GAP_AMBIGUOUS_MAPPING if path in ambiguous else GAP_REMOVED_PATH_UNPAIRED
        gaps.append(EndpointComparisonGap(path, reason, path))
    gaps.sort(key=lambda gap: (gap.list_path, gap.reason))
    return tuple(changes), tuple(gaps)


def _pair_moved_paths(
    old: Mapping[str, EndpointListRecord],
    new: Mapping[str, EndpointListRecord],
) -> tuple[dict[str, str], set[str]]:
    """Return ({new path: old path} for unique moves, ambiguous paths).

    Candidate edges come from common catalog models whose `listed` path
    changed, deduplicated to distinct (old, new) path pairs. An edge pairs its
    paths only when the old path disappeared, the new path is newly present,
    and the edge is the only one leaving the old path and the only one
    reaching the new path, counting every candidate edge. Any other
    disappeared or newly present path on a candidate edge (splits, merges,
    partial moves, moves into or out of a shared path) is ambiguous. Shared
    paths are never ambiguous: same-path comparison takes precedence.
    """
    old_paths = {model_id: path for path, listing in old.items() for model_id in listing.model_ids}
    new_paths = {model_id: path for path, listing in new.items() for model_id in listing.model_ids}
    edges = {
        (old_paths[model_id], new_paths[model_id])
        for model_id in old_paths.keys() & new_paths.keys()
        if old_paths[model_id] != new_paths[model_id]
    }
    targets: dict[str, set[str]] = {}
    sources: dict[str, set[str]] = {}
    for old_path, new_path in edges:
        targets.setdefault(old_path, set()).add(new_path)
        sources.setdefault(new_path, set()).add(old_path)
    pairs = {
        new_path: old_path
        for old_path, new_path in edges
        if old_path not in new
        and new_path not in old
        and targets[old_path] == {new_path}
        and sources[new_path] == {old_path}
    }
    paired = set(pairs) | set(pairs.values())
    involved = {path for edge in edges for path in edge}
    ambiguous = {
        path
        for path in involved - paired
        if (path in old) != (path in new)
    }
    return pairs, ambiguous


def _observation_map(listing: EndpointListRecord) -> dict[str, EndpointObservation]:
    return {
        observation.endpoint_key: (observation.state, observation.status_code)
        for observation in listing.observations
    }


def build_endpoint_capture(
    fetch: EndpointFetchResult,
    *,
    profile: ProviderProfile,
    scrape_id: int,
    baseline_scrape_id: int | None,
    baseline_capture: EndpointCaptureSummary | None,
) -> EndpointCaptureCandidate:
    """Build the in-memory capture, its comparison and records, before saving.

    `scrape_id` is the saved catalog scrape this capture belongs to.
    `baseline_scrape_id` is that scan's selected catalog baseline scrape (None
    when there was none) and `baseline_capture` the persisted capture of that
    scrape, if any (`Store.get_endpoint_capture_for_scrape`). Changes and gaps
    are computed only when the comparison state is `available`.
    `first_capture` stays None and `capture_id` None until persistence.
    """
    comparison_state, baseline_capture_id = endpoint_comparison_state(
        provider_id=fetch.provider_id,
        baseline_scrape_id=baseline_scrape_id,
        baseline_capture=baseline_capture,
    )
    lists = endpoint_list_records(fetch, profile)
    changes: tuple[EndpointChangeRecord, ...] = ()
    gaps: tuple[EndpointComparisonGap, ...] = ()
    if (
        comparison_state == COMPARISON_AVAILABLE
        and baseline_capture is not None
        and baseline_capture_id is not None
    ):
        changes, gaps = compare_endpoint_captures(
            baseline_capture.lists, lists, from_capture_id=baseline_capture_id
        )
    summary = EndpointCaptureSummary(
        capture_id=None,
        scrape_id=scrape_id,
        provider_id=fetch.provider_id,
        started_at=fetch.started_at,
        completed_at=fetch.completed_at,
        status=aggregate_capture_status(
            paths_requested=fetch.paths_requested,
            paths_failed=fetch.paths_failed,
            mapping_failures=fetch.mapping_failures,
        ),
        paths_requested=fetch.paths_requested,
        paths_attempted=fetch.paths_attempted,
        paths_failed=fetch.paths_failed,
        mapping_failures=fetch.mapping_failures,
        first_capture=None,
        comparison_state=comparison_state,
        baseline_capture_id=baseline_capture_id,
        error_summary=None,
        changes=changes,
        comparison_gaps=gaps,
        lists=lists,
    )
    return EndpointCaptureCandidate(summary=summary, mappings=fetch.mappings, archive=fetch.bodies)


def build_endpoint_error_summary(
    *,
    provider_id: str,
    scrape_id: int,
    completed_at: str,
    error_summary: str,
    started_at: str | None = None,
    baseline_scrape_id: int | None = None,
    baseline_capture: EndpointCaptureSummary | None = None,
) -> EndpointCaptureSummary:
    """Build the in-memory summary of a capture that failed as a whole.

    The summary has status `error`, zero counts, no lists, changes or gaps,
    and the sanitized, bounded `error_summary`. `started_at` defaults to
    `completed_at`. The comparison state describes the selected baseline as
    far as it is known: pass the selected baseline scrape and, when it could
    be read, its capture; an unknown capture reads as
    `missing_baseline_capture`. Persist it with
    `Store.save_endpoint_error_capture`.
    """
    comparison_state, baseline_capture_id = endpoint_comparison_state(
        provider_id=provider_id,
        baseline_scrape_id=baseline_scrape_id,
        baseline_capture=baseline_capture,
    )
    return EndpointCaptureSummary(
        capture_id=None,
        scrape_id=scrape_id,
        provider_id=provider_id,
        started_at=started_at if started_at is not None else completed_at,
        completed_at=completed_at,
        status=aggregate_capture_status(
            paths_requested=0, paths_failed=0, mapping_failures=0, capture_exception=True
        ),
        paths_requested=0,
        paths_attempted=0,
        paths_failed=0,
        mapping_failures=0,
        first_capture=None,
        comparison_state=comparison_state,
        baseline_capture_id=baseline_capture_id,
        error_summary=sanitize_endpoint_error_message(error_summary),
    )
