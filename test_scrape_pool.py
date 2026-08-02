"""Test: 并发调度器 —— 并发度上限 3、结果按 seq 排序、限流时不丢已完成结果。
Run: python test_scrape_pool.py
"""
import threading
import time

import shein_scraper
from shein_scraper import _run_scrape_pool, _reset_rate_limit_state


def _install_fake_worker(behavior):
    """behavior(index) -> status 字符串。返回 (restore, live)。"""
    orig = shein_scraper._scrape_one_url
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def fake(url, index, total, seq_num,
             override_price, override_shipping, variant_filter_decl):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.05)
        with lock:
            live["now"] -= 1
        return {"url": url, "seq_num": seq_num, "status": behavior(index),
                "_ov": (override_price, override_shipping, variant_filter_decl)}

    shein_scraper._scrape_one_url = fake

    def restore():
        shein_scraper._scrape_one_url = orig

    return restore, live


def test_concurrency_never_exceeds_three():
    _reset_rate_limit_state()
    restore, live = _install_fake_worker(lambda i: "OK")
    try:
        urls = [f"http://x/{i}" for i in range(12)]
        records, limited = _run_scrape_pool(
            urls, list(range(1, 13)), None, None, None, 1)
    finally:
        restore()
    assert shein_scraper.MAX_PARALLEL_TABS == 3
    assert live["peak"] <= 3, live["peak"]
    assert live["peak"] > 1, "应该真的并发起来了"
    assert len(records) == 12
    assert limited is False


def test_results_sorted_by_seq():
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "OK")
    try:
        urls = [f"http://x/{i}" for i in range(8)]
        seqs = [11, 3, 7, 1, 22, 5, 9, 2]
        records, _ = _run_scrape_pool(urls, seqs, None, None, None, 1)
    finally:
        restore()
    assert [r["seq_num"] for r in records] == sorted(seqs)


def test_per_url_overrides_are_passed_through():
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "OK")
    try:
        records, _ = _run_scrape_pool(
            ["u0", "u1"], [1, 2], [None, 9.5], [0.0, None], ["", "Black / M"], 1)
    finally:
        restore()
    by_seq = {r["seq_num"]: r["_ov"] for r in records}
    assert by_seq[1] == (None, 0.0, "")
    assert by_seq[2] == (9.5, None, "Black / M")


def test_rate_limit_marks_remaining_and_keeps_completed():
    """前 3 条全失败 → 触发限流。已完成的必须在 records 里，
    剩下的标 RATE_LIMITED，一条都不能丢。"""
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "BLOCKED")
    try:
        urls = [f"http://x/{i}" for i in range(9)]
        records, limited = _run_scrape_pool(
            urls, list(range(1, 10)), None, None, None, 1)
    finally:
        restore()
    assert limited is True
    assert len(records) == 9, [r["seq_num"] for r in records]
    assert [r["seq_num"] for r in records] == list(range(1, 10))
    statuses = {r["seq_num"]: r["status"] for r in records}
    assert sum(1 for s in statuses.values() if s == "BLOCKED") >= 3
    assert sum(1 for s in statuses.values() if s == "RATE_LIMITED") >= 1


def test_worker_exception_becomes_error_record_not_a_crash():
    _reset_rate_limit_state()
    orig = shein_scraper._scrape_one_url

    def boom(url, index, total, seq_num, *a):
        if seq_num == 2:
            raise RuntimeError("kaboom")
        return {"url": url, "seq_num": seq_num, "status": "OK"}

    shein_scraper._scrape_one_url = boom
    try:
        records, limited = _run_scrape_pool(
            ["u1", "u2", "u3"], [1, 2, 3], None, None, None, 1)
    finally:
        shein_scraper._scrape_one_url = orig
    assert len(records) == 3
    bad = next(r for r in records if r["seq_num"] == 2)
    assert bad["status"].startswith("ERROR:"), bad


def test_progress_callback_fires_once_per_url():
    _reset_rate_limit_state()
    restore, _ = _install_fake_worker(lambda i: "OK")
    seen = []
    try:
        _run_scrape_pool(["a", "b", "c"], [1, 2, 3], None, None, None, 1,
                         progress_cb=lambda done, total, url: seen.append(done))
    finally:
        restore()
    assert sorted(seen) == [1, 2, 3], seen


def test_image_pool_reduced_for_parallelism():
    assert shein_scraper.IMAGE_DOWNLOAD_WORKERS == 4


if __name__ == "__main__":
    test_concurrency_never_exceeds_three()
    test_results_sorted_by_seq()
    test_per_url_overrides_are_passed_through()
    test_rate_limit_marks_remaining_and_keeps_completed()
    test_worker_exception_becomes_error_record_not_a_crash()
    test_progress_callback_fires_once_per_url()
    test_image_pool_reduced_for_parallelism()
    print("ALL PASS")
