def test_name_keeps_all_parenthesized_detail(dl):
    assert dl.split_name("Synthetic (example) (detail)") == {
        "short": "Synthetic", "detail": "example) (detail"
    }
    assert dl.split_name("Synthetic") == {"short": "Synthetic", "detail": ""}
    assert dl.split_name("Synthetic (unfinished") == {"short": "Synthetic (unfinished", "detail": ""}
    assert dl.split_name("Synthetic()") == {"short": "Synthetic()", "detail": ""}
