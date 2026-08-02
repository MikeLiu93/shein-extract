"""Test: I 列价格区间 + M 列库存串的格式化。
Run: python test_price_stock_format.py
"""
from shein_scraper import _format_price_range, _format_stock_summary


def test_price_range_single_value_returns_number():
    skus = [{"sale_price": 12.99, "stock": 5, "attrs": {"Color": "Black"}}]
    assert _format_price_range(skus) == 12.99


def test_price_range_all_equal_returns_number():
    skus = [{"sale_price": 9.5}, {"sale_price": 9.5}, {"sale_price": 9.5}]
    assert _format_price_range(skus) == 9.5


def test_price_range_differing_returns_endash_string():
    skus = [{"sale_price": 9.99}, {"sale_price": 14.99}, {"sale_price": 12.0}]
    assert _format_price_range(skus) == "9.99–14.99"


def test_price_range_ignores_none_and_garbage():
    skus = [{"sale_price": None}, {"sale_price": "abc"}, {"sale_price": 7.25}]
    assert _format_price_range(skus) == 7.25


def test_price_range_empty_returns_none():
    assert _format_price_range([]) is None
    assert _format_price_range(None) is None


def test_stock_summary_labels_by_attrs():
    skus = [
        {"attrs": {"Color": "Black", "Size": "M"}, "stock": 42},
        {"attrs": {"Color": "Black", "Size": "L"}, "stock": 0},
        {"attrs": {"Color": "Red", "Size": "M"}, "stock": 3},
    ]
    assert _format_stock_summary(skus) == "Black-M: 42 / Black-L: 缺货 / Red-M: 少货 3"


def test_stock_summary_low_threshold_boundary():
    # LOW_STOCK_THRESHOLD == 15: 15 是少货，16 是普通数字
    skus = [{"attrs": {"Size": "M"}, "stock": 15},
            {"attrs": {"Size": "L"}, "stock": 16}]
    assert _format_stock_summary(skus) == "M: 少货 15 / L: 16"


def test_stock_summary_falls_back_to_sku_code():
    skus = [{"attrs": {}, "sku_code": "sr123", "stock": 8}]
    assert _format_stock_summary(skus) == "sr123: 少货 8"


def test_stock_summary_empty_returns_empty_string():
    assert _format_stock_summary([]) == ""


if __name__ == "__main__":
    test_price_range_single_value_returns_number()
    test_price_range_all_equal_returns_number()
    test_price_range_differing_returns_endash_string()
    test_price_range_ignores_none_and_garbage()
    test_price_range_empty_returns_none()
    test_stock_summary_labels_by_attrs()
    test_stock_summary_low_threshold_boundary()
    test_stock_summary_falls_back_to_sku_code()
    test_stock_summary_empty_returns_empty_string()
    print("ALL PASS")
