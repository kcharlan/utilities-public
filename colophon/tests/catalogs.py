"""Invented models.dev catalogs; never derived from private or prebuilt data."""

import copy


def catalog(models=None, *, wrapped=False):
    provider = {"id": "openai", "name": "Synthetic OpenAI catalog", "models":
                copy.deepcopy(models if models is not None else SYNTHETIC_MODELS)}
    providers = {"openai": provider, "synthetic-other": {"id": "synthetic-other", "models": {
        "gpt-synthetic-other": {"id": "gpt-synthetic-other", "cost": {"input": 99, "output": 99}}}}}
    return {"providers": providers} if wrapped else providers


def model(identifier="gpt-synthetic-1", **cost):
    return {"id": identifier, "cost": cost}


SYNTHETIC_MODELS = {
    "gpt-synthetic-1": model(input=2, output=7, cache_read=0.5, cache_write=3),
    "gpt-synthetic-missing-caches": model("gpt-synthetic-missing-caches", input=2, output=7),
    "gpt-synthetic-long": model("gpt-synthetic-long", input=2, output=7, cache_read=0.5,
                                cache_write=3, context_over_200k={"input": 4, "output": 11}),
    "gpt-synthetic-tiers": model("gpt-synthetic-tiers", input=2, output=7,
                                 tiers=[{"threshold": 272000, "input": 4, "output": 11}]),
    # Task 13's independently hand-derived reference check, no fixture read.
    "gpt-5.4": model("gpt-5.4", input=1.5, output=9),
}
