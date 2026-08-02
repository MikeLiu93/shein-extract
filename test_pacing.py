"""Test: URL 之间的间隔固定在 2–3 秒，没有长歇。
Run: python test_pacing.py
"""
import time

import shein_scraper


def test_pause_always_between_2_and_3_seconds():
    slept = []
    orig = time.sleep
    time.sleep = lambda s: slept.append(s)
    try:
        for _ in range(200):
            shein_scraper._inter_url_pause()
    finally:
        time.sleep = orig
    assert len(slept) == 200, len(slept)
    assert all(2.0 <= s <= 3.0 for s in slept), (min(slept), max(slept))
    # 随机性确实存在（200 次不可能全同一个值）
    assert len(set(slept)) > 1


def test_pause_takes_no_arguments():
    orig = time.sleep
    time.sleep = lambda s: None
    try:
        shein_scraper._inter_url_pause()   # 不传参必须能调
    finally:
        time.sleep = orig


def test_long_pause_and_old_delay_constants_are_gone():
    for name in ("LONG_PAUSE_EVERY", "LONG_PAUSE_MIN", "LONG_PAUSE_MAX",
                 "INTER_URL_DELAY_MIN", "INTER_URL_DELAY_MAX"):
        assert not hasattr(shein_scraper, name), f"{name} 应该已被删除"


def test_new_pause_bounds_are_2_and_3():
    assert shein_scraper.INTER_URL_PAUSE_MIN == 2.0
    assert shein_scraper.INTER_URL_PAUSE_MAX == 3.0


if __name__ == "__main__":
    test_pause_always_between_2_and_3_seconds()
    test_pause_takes_no_arguments()
    test_long_pause_and_old_delay_constants_are_gone()
    test_new_pause_bounds_are_2_and_3()
    print("ALL PASS")
