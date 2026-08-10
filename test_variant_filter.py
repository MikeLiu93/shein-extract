"""Test: 模板 E 列（变体）的声明式过滤。
Run: python test_variant_filter.py
"""
from shein_scraper import _filter_variants_by_declaration


def _skus():
    """8 个变体：Black/Red/Blue/Green × M/L。"""
    out = []
    for color in ("Black", "Red", "Blue", "Green"):
        for size in ("M", "L"):
            out.append({
                "sku_code": f"sk-{color}-{size}",
                "sale_price": 10.0,
                "stock": 5,
                "attrs": {"Color": color, "Size": size},
            })
    return out


_VARS = {"Color": ["Black", "Red", "Blue", "Green"], "Size": ["M", "L"]}


def test_empty_declaration_returns_inputs_unchanged():
    skus = _skus()
    kept, vars_, unknown = _filter_variants_by_declaration("", skus, _VARS)
    assert kept is skus and vars_ is _VARS and unknown == []
    kept, vars_, unknown = _filter_variants_by_declaration("   ", skus, _VARS)
    assert len(kept) == 8 and unknown == []


def test_two_groups_intersect():
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Black, Red / M", _skus(), _VARS)
    codes = sorted(s["sku_code"] for s in kept)
    assert codes == ["sk-Black-M", "sk-Red-M"], codes
    assert vars_ == {"Color": ["Black", "Red"], "Size": ["M"]}, vars_
    assert unknown == []


def test_single_group_is_flat_allowlist():
    # 没有 "/" → 扁平白名单，Black 和 Red 的所有尺码都保留
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Black, Red", _skus(), _VARS)
    codes = sorted(s["sku_code"] for s in kept)
    assert codes == ["sk-Black-L", "sk-Black-M", "sk-Red-L", "sk-Red-M"], codes


def test_matching_is_case_and_whitespace_insensitive():
    kept, _, unknown = _filter_variants_by_declaration(
        "  bLaCk  /   m ", _skus(), _VARS)
    assert [s["sku_code"] for s in kept] == ["sk-Black-M"]
    assert unknown == []


def test_no_match_returns_empty_and_reports_all_declared():
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Purple / XXL", _skus(), _VARS)
    assert kept == [] and vars_ == {}
    assert unknown == ["Purple", "XXL"], unknown


def test_partial_match_keeps_matches_and_reports_unknown():
    # Black 存在、Purple 不存在；组内是 or，所以 Black-M 保留
    kept, vars_, unknown = _filter_variants_by_declaration(
        "Black, Purple / M", _skus(), _VARS)
    assert [s["sku_code"] for s in kept] == ["sk-Black-M"]
    assert unknown == ["Purple"], unknown


def test_flat_variations_key_preserved_when_not_in_kept_attrs():
    # variations 里有一个 sku_prices attrs 里没有的键，其值命中声明 → 保留
    skus = [{"sku_code": "a", "sale_price": 1.0, "stock": 1,
             "attrs": {"Color": "Black"}}]
    vars_in = {"Color": ["Black", "Red"], "Style": ["Plain", "Fancy"]}
    kept, vars_out, _ = _filter_variants_by_declaration(
        "Black, Fancy", skus, vars_in)
    assert kept and vars_out["Color"] == ["Black"]
    assert vars_out["Style"] == ["Fancy"], vars_out


if __name__ == "__main__":
    test_empty_declaration_returns_inputs_unchanged()
    test_two_groups_intersect()
    test_single_group_is_flat_allowlist()
    test_matching_is_case_and_whitespace_insensitive()
    test_no_match_returns_empty_and_reports_all_declared()
    test_partial_match_keeps_matches_and_reports_unknown()
    test_flat_variations_key_preserved_when_not_in_kept_attrs()
    print("ALL PASS")
