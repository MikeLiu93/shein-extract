"""Test: 线程安全的限流计数器。
Run: python test_rate_limit.py
"""
import threading

import shein_scraper
from shein_scraper import (_record_result_for_rate_limit,
                           _reset_rate_limit_state, RATE_LIMIT_CONSECUTIVE)


def test_ok_results_never_trip():
    _reset_rate_limit_state()
    for _ in range(50):
        assert _record_result_for_rate_limit("OK") is False


def test_three_consecutive_failures_trip():
    _reset_rate_limit_state()
    assert RATE_LIMIT_CONSECUTIVE == 3
    assert _record_result_for_rate_limit("BLOCKED") is False
    assert _record_result_for_rate_limit("TIMEOUT") is False
    assert _record_result_for_rate_limit("ERROR: boom") is True


def test_ok_resets_the_streak():
    _reset_rate_limit_state()
    _record_result_for_rate_limit("BLOCKED")
    _record_result_for_rate_limit("BLOCKED")
    _record_result_for_rate_limit("OK")          # 清零
    assert _record_result_for_rate_limit("BLOCKED") is False
    assert _record_result_for_rate_limit("BLOCKED") is False
    assert _record_result_for_rate_limit("BLOCKED") is True


def test_stays_tripped_once_tripped():
    _reset_rate_limit_state()
    for _ in range(3):
        _record_result_for_rate_limit("BLOCKED")
    assert _record_result_for_rate_limit("OK") is True    # 已触发就一直是 True


def test_reset_clears_tripped():
    _reset_rate_limit_state()
    for _ in range(3):
        _record_result_for_rate_limit("BLOCKED")
    _reset_rate_limit_state()
    assert _record_result_for_rate_limit("OK") is False


def test_concurrent_updates_do_not_lose_counts():
    """20 个线程各报 1 次失败：必须触发，且不出现竞态导致的漏计。"""
    _reset_rate_limit_state()
    results = []

    def worker():
        results.append(_record_result_for_rate_limit("BLOCKED"))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert any(results), "20 次连续失败必须触发限流"
    assert shein_scraper._rate_limit_state["tripped"] is True


def test_scrape_one_url_exists_with_expected_signature():
    import inspect
    params = list(inspect.signature(shein_scraper._scrape_one_url).parameters)
    assert params == ["url", "index", "total", "seq_num",
                      "override_price", "override_shipping",
                      "variant_filter_decl"], params


def test_scrape_shein_accepts_new_lists():
    import inspect
    params = inspect.signature(shein_scraper.scrape_shein).parameters
    assert "shipping_list" in params
    assert "variant_filter_list" in params


if __name__ == "__main__":
    test_ok_results_never_trip()
    test_three_consecutive_failures_trip()
    test_ok_resets_the_streak()
    test_stays_tripped_once_tripped()
    test_reset_clears_tripped()
    test_concurrent_updates_do_not_lose_counts()
    test_scrape_one_url_exists_with_expected_signature()
    test_scrape_shein_accepts_new_lists()
    print("ALL PASS")
