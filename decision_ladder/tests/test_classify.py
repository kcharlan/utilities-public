def test_classify_preserves_missing_values(dl):
    row = dl.classify({"systems": [{"key": "synthetic", "name": "Synthetic", "board": "api", "ranked": False,
                                    "capability": {"eligible": False, "within_caps": False}}]})[0]
    assert row["capability"] is None
    assert row["price"] is None
    assert row["latency"] is None
    assert row["latency_assumed"] is True
    assert row["price_published"] is False


def test_classify_preserves_zero_and_latency_fallback(dl):
    row = dl.classify({"systems": [{"key": "synthetic", "name": "Synthetic (example)", "board": "api", "ranked": True,
                                    "capability": {"score": 0, "eligible": True, "within_caps": True},
                                    "price": {"kind": "listed", "usd_per_1000_decisions": 0},
                                    "latency": {"p50_s_adjusted": None, "p50_s_measured": 0, "latency_basis": "api-end-to-end"}}]})[0]
    assert (row["short"], row["detail"], row["capability"], row["price"], row["latency"]) == ("Synthetic", "example", 0, 0, 0)
    assert row["price_published"] and not row["latency_assumed"]
