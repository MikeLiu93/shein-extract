"""Test: 模板 C（原价）/ D（运费）/ E（变体）三列对抓取结果的覆盖合成。
Run: python test_row_overrides.py
"""
from shein_scraper import _apply_row_overrides


def _data():
    return {
        "price": 10.00,
        "free_threshold": None,
        "unconditional_free": False,
        "variations": {"Color": ["Black", "Red"], "Size": ["M", "L"]},
        "sku_prices": [
            {"sku_code": "a", "sale_price": 10.00, "stock": 20,
             "attrs": {"Color": "Black", "Size": "M"}},
            {"sku_code": "b", "sale_price": 12.00, "stock": 0,
             "attrs": {"Color": "Black", "Size": "L"}},
            {"sku_code": "c", "sale_price": 14.00, "stock": 3,
             "attrs": {"Color": "Red", "Size": "M"}},
        ],
    }


def test_no_overrides_uses_scraped_price_and_derived_shipping():
    d = _data()
    out = _apply_row_overrides(d, None, None, "")
    assert out["price"] == 10.00
    assert out["shipping"] == 2.99          # DEFAULT_SHIPPING_FEE
    assert out["ebay_price"] == round((10.00 + 2.99) * 1.4, 2) == 18.19
    assert out["web_price_display"] == "10.00–14.00"
    assert out["variant_filter_no_match"] is False


def test_c_column_overrides_price_and_every_sku_sale_price():
    d = _data()
    out = _apply_row_overrides(d, 20.00, None, "")
    assert out["price"] == 20.00
    assert d["price"] == 20.00
    assert [sp["sale_price"] for sp in d["sku_prices"]] == [20.0, 20.0, 20.0]
    # I 列显示的是覆盖 *之前* 的网页价，用来核对 C 列填得对不对
    assert out["web_price_display"] == "10.00–14.00"
    assert out["ebay_price"] == round((20.00 + 2.99) * 1.4, 2)


def test_d_column_overrides_shipping_including_zero():
    d = _data()
    out = _apply_row_overrides(d, None, 0.0, "")
    assert out["shipping"] == 0.0
    assert out["ebay_price"] == round(10.00 * 1.4, 2) == 14.00
    d2 = _data()
    out2 = _apply_row_overrides(d2, None, 7.50, "")
    assert out2["shipping"] == 7.50
    assert out2["ebay_price"] == round((10.00 + 7.50) * 1.4, 2)


def test_free_shipping_threshold_still_honored_when_d_blank():
    d = _data()
    d["unconditional_free"] = True
    out = _apply_row_overrides(d, None, None, "")
    assert out["shipping"] == 0.0


def test_e_column_filters_before_price_range_and_stock():
    d = _data()
    out = _apply_row_overrides(d, None, None, "Black / M")
    assert [sp["sku_code"] for sp in d["sku_prices"]] == ["a"]
    assert d["variations"] == {"Color": ["Black"], "Size": ["M"]}
    assert out["web_price_display"] == 10.00     # 只剩一个变体 → 数字，不是区间
    assert out["stock_summary"] == "Black-M: 20"
    assert out["unknown_variants"] == []


def test_e_column_no_match_flags_failure():
    d = _data()
    out = _apply_row_overrides(d, None, None, "Purple")
    assert out["variant_filter_no_match"] is True
    assert out["unknown_variants"] == ["Purple"]


def test_e_column_partial_match_reports_unknown_but_succeeds():
    d = _data()
    out = _apply_row_overrides(d, None, None, "Black, Purple / M")
    assert out["variant_filter_no_match"] is False
    assert out["unknown_variants"] == ["Purple"]
    assert out["stock_summary"] == "Black-M: 20"


def test_c_override_applies_to_filtered_skus_only():
    d = _data()
    out = _apply_row_overrides(d, 99.0, None, "Black / M")
    assert [sp["sale_price"] for sp in d["sku_prices"]] == [99.0]
    assert out["price"] == 99.0


def test_stock_summary_marks_out_of_stock_and_low():
    d = _data()
    out = _apply_row_overrides(d, None, None, "")
    assert out["stock_summary"] == \
        "Black-M: 20 / Black-L: 缺货 / Red-M: 少货 3"


if __name__ == "__main__":
    test_no_overrides_uses_scraped_price_and_derived_shipping()
    test_c_column_overrides_price_and_every_sku_sale_price()
    test_d_column_overrides_shipping_including_zero()
    test_free_shipping_threshold_still_honored_when_d_blank()
    test_e_column_filters_before_price_range_and_stock()
    test_e_column_no_match_flags_failure()
    test_e_column_partial_match_reports_unknown_but_succeeds()
    test_c_override_applies_to_filtered_skus_only()
    test_stock_summary_marks_out_of_stock_and_low()
    print("ALL PASS")
