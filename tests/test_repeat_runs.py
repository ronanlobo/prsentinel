from scripts import repeat_summary as rs
def test_summarize_caught_and_rates():
    runs = [
        {"invalid": False, "caught_yes_no": True, "tests_generated": 4, "tests_catching": 2, "test_content_hash": "h1"},
        {"invalid": False, "caught_yes_no": False, "tests_generated": 4, "tests_catching": 1, "test_content_hash": "h2"},
    ]
    s = rs.summarize(runs)
    assert s["caught"] == 1
    assert s["catch_rate"] == 0.5


def test_summarize_wilson_bounds():
    runs = [{"invalid": False, "caught_yes_no": True} for _ in range(6)] + [{"invalid": False, "caught_yes_no": False} for _ in range(4)]
    s = rs.summarize(runs)
    assert "wilson_lo" in s and "wilson_hi" in s
    assert abs(s["wilson_lo"] - 0.3127) < 0.01
    assert abs(s["wilson_hi"] - 0.8318) < 0.01


def test_summarize_mean_fraction_and_distinct():
    runs = [
        {"invalid": False, "caught_yes_no": True, "tests_generated": 10, "tests_catching": 6, "test_content_hash": "h1"},
        {"invalid": False, "caught_yes_no": True, "tests_generated": 4, "tests_catching": 2, "test_content_hash": "h1"},
        {"invalid": False, "caught_yes_no": False, "tests_generated": 2, "tests_catching": 0, "test_content_hash": "h2"},
    ]
    s = rs.summarize(runs)
    assert abs(s["mean_fraction_catching"] - ((0.6 + 0.5 + 0.0) / 3)) < 1e-9
    assert s["distinct_test_files"] == 2


def test_summarize_zero_valid_runs():
    runs = [{"invalid": True}, {"invalid": True}]
    s = rs.summarize(runs)
    assert s["valid"] == 0
    assert s["excluded"] == 2
    assert s["caught"] == 0
    assert s["catch_rate"] == 0.0
    assert s["wilson_lo"] == 0.0
    assert s["wilson_hi"] == 1.0
    assert s["mean_fraction_catching"] == 0.0
    assert s["distinct_test_files"] == 0