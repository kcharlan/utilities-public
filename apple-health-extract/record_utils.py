"""Helpers for reconciling identical samples from different sources."""

DISTANCE_UNITS_TO_KM = {"m": 0.001, "km": 1.0, "mi": 1.609344}


def distance_km(value, unit):
    try:
        return value * DISTANCE_UNITS_TO_KM[unit]
    except KeyError:
        raise ValueError(f"Unsupported distance unit {unit!r}") from None


def deduplicate_sources(records, keys):
    if records.empty:
        return records
    # Preserve repeated samples from the chosen source; drop equivalent samples
    # from other sources. Missing source names form their own source.
    codes = records['sourceName'].astype('category').cat.codes
    first = codes.groupby([records[key] for key in keys], dropna=False).transform('first')
    return records.loc[codes == first]
