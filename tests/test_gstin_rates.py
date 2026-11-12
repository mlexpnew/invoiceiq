from datetime import date

from invoiceiq import gstin as G
from invoiceiq.rates import check_rate


def test_published_example_gstin_is_valid():
    assert G.is_valid("27AAPFU0939F1ZV")


def test_wrong_check_digit_explains_the_fix():
    (problem,) = G.problems("27AAPFU0939F1ZX")
    assert "should be V" in problem


def test_format_and_state_errors():
    assert G.problems("") == ["missing"]
    assert G.problems("27AAPFU0939F1Z")[0].startswith("format")
    assert any("state" in p for p in G.problems(G.make("25", "AAPFU0939F")))


def test_make_builds_valid_gstins():
    assert G.is_valid(G.make("29", "AACCN4821K")) and G.state_code("29AACCN4821K1Z9") == "29"


def test_gst2_rate_rules():
    before, after = date(2025, 6, 1), date(2025, 10, 1)
    assert check_rate(12, before) is None and check_rate(40, before) == "invalid"
    assert check_rate(18, after) is None and check_rate(40, after) is None
    assert check_rate(12, after) == "retired" and check_rate(28, after) == "retired"
    assert check_rate(7, after) == "invalid" and check_rate(3, after) is None
