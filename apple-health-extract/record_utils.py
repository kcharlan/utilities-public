"""Helpers for reconciling identical samples from different sources."""


def deduplicate_sources(records, keys):
    if records.empty:
        return records
    # Preserve repeated samples from the chosen source; drop equivalent samples
    # from other sources. Missing source names form their own source.
    codes = records['sourceName'].astype('category').cat.codes
    first = codes.groupby([records[key] for key in keys], dropna=False).transform('first')
    return records.loc[codes == first]
