"""Pure primitives for saved provider endpoint lists.

This module holds no I/O. It defines the endpoint-capture constants, how each
catalog model maps to an endpoint-list path (alias resolution and path
validation included), how a list response is validated, how an endpoint's
comparable state is separated from volatile telemetry and status, how
endpoints in a response-ordered list are keyed, how two keyed lists are
compared, how scalar price leaves are resolved, and how a capture's overall
status is derived. Transport, storage and rendering consume these functions.
"""

from __future__ import annotations

import hashlib
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final, Literal, NamedTuple, TypeAlias
from urllib.parse import urlsplit

from .change_render import resolve_price_value
from .diffing import diff_values
from .models import EndpointChange, EndpointMapping, NormalizedModel, canonical_json
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
_OVERRIDES_FIELD: Final = "pricing.overrides"

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
    return tuple(_resolve_mapping(model_id, links) for model_id in sorted(links))


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
    alias = metadata.get("alias_target")
    if alias is not None:
        slug = alias.get("slug") if isinstance(alias, Mapping) else None
        if isinstance(slug, str) and slug:
            return MAPPING_ALIAS, None, slug
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
) -> EndpointMapping:
    outcome, list_path, target = links[model_id]
    if outcome == MAPPING_LISTED:
        return EndpointMapping(model_id, outcome, list_path, None, None, None)
    if outcome != MAPPING_ALIAS:
        return EndpointMapping(model_id, outcome, None, None, None, outcome)
    visited = {model_id}
    current = target
    while True:
        if current not in links:
            error_code = ALIAS_TARGET_MISSING
            break
        if current in visited:
            error_code = ALIAS_CYCLE
            break
        visited.add(current)
        next_outcome, next_path, next_target = links[current]
        if next_outcome == MAPPING_LISTED:
            return EndpointMapping(model_id, MAPPING_ALIAS, next_path, target, current, None)
        if next_outcome != MAPPING_ALIAS:
            error_code = next_outcome
            break
        current = next_target
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
        changes.append((_OVERRIDES_FIELD, old_overrides, new_overrides))
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
    identity; only then are `normalized_exact_value`, `unit_label` and
    `comparison_group` set. Unresolved leaves stay visible for matching but must
    not enter price arithmetic.
    """

    path: str
    raw_value: Any
    resolved: bool
    normalized_exact_value: Fraction | None = None
    unit_label: str | None = None
    comparison_group: str | None = None


def resolved_price_leaves(
    metadata: Mapping[str, Any],
    profile: ProviderProfile,
) -> tuple[PriceLeaf, ...]:
    """Return the direct scalar children of `pricing`, sorted by path.

    Object and array children (including `pricing.overrides`) are excluded
    before resolution. Each remaining leaf is resolved through the strict
    `resolve_price_value` contract, so an unmatched field is unresolved.
    """
    pricing = metadata.get("pricing")
    if not isinstance(pricing, Mapping):
        return ()
    leaves: list[PriceLeaf] = []
    for name in sorted(pricing, key=str):
        value = pricing[name]
        if isinstance(value, (Mapping, list, tuple)):
            continue
        path = f"pricing.{name}"
        resolved = resolve_price_value(path, value, profile)
        if resolved is None:
            leaves.append(PriceLeaf(path=path, raw_value=value, resolved=False))
            continue
        leaves.append(
            PriceLeaf(
                path=path,
                raw_value=value,
                resolved=True,
                normalized_exact_value=resolved.normalized_exact_value,
                unit_label=resolved.price_rule.unit_label,
                comparison_group=resolved.price_rule.comparison_group,
            )
        )
    return tuple(leaves)


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
