"""Pure primitives for saved provider endpoint lists.

This module holds no I/O. It defines the endpoint-capture constants, how an
endpoint's comparable state is separated from volatile telemetry and status, how
endpoints in a response-ordered list are keyed, how two keyed lists are
compared, how scalar price leaves are resolved, and how a capture's overall
status is derived. Transport, storage and rendering consume these functions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final, Literal, NamedTuple, TypeAlias

from .change_render import resolve_price_value
from .diffing import diff_values
from .models import EndpointChange, canonical_json
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
