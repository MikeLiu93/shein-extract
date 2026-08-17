"""Test: 人机验证的处理方式 —— 不截图、不通知，等人工 10 分钟，等不到就整轮收工。

需求（2026-08-17）：遇到人机验证不要截图也不要发通知，就在 Chrome 窗口等人工过；
等满 10 分钟还没人处理就结束此轮，没轮到的 URL 保持待处理。

Run: python test_captcha_wait.py
"""
from types import SimpleNamespace

import shein_scraper
from shein_scraper import (CAPTCHA_WAIT_SEC, CAPTCHA_POLL_SEC, CaptchaAbort,
                           _captcha_abort, _check_and_handle_block)


class _Recorder:
    """把 _check_and_handle_block 依赖的外部动作全打桩，记录它做了什么。"""

    def __init__(self, block_states):
        # block_states: 每次 _JS_DETECT_BLOCK 依次返回的东西
        self.block_states = list(block_states)
        self.slept = []
        self.screenshots = []
        self.alerts = []

    def install(self, monkey):
        monkey(shein_scraper, "_ws_url_for_id", lambda port, tab: "ws://x")
        monkey(shein_scraper, "_run_js",
               lambda ws, js: self.block_states.pop(0) if self.block_states
               else {"blocked": False})
        monkey(shein_scraper, "time", SimpleNamespace(
            sleep=self.slept.append,
            strftime=lambda *a: "ts",
            monotonic=lambda: 0.0,
        ))
        monkey(shein_scraper, "_take_screenshot",
               lambda *a, **k: self.screenshots.append(a) or True)
        monkey(shein_scraper, "alert_signin",
               lambda *a, **k: self.alerts.append(("signin", a)))
        monkey(shein_scraper, "alert_generic",
               lambda *a, **k: self.alerts.append(("generic", a)))


def _with_patches(rec, fn):
    saved = {}

    def monkey(mod, name, value):
        saved.setdefault(name, getattr(mod, name))
        setattr(mod, name, value)

    rec.install(monkey)
    try:
        return fn()
    finally:
        for name, value in saved.items():
            setattr(shein_scraper, name, value)


def _captcha(n):
    return [{"blocked": True, "type": "captcha", "rect": None}] * n


def test_wait_is_ten_minutes():
    assert CAPTCHA_WAIT_SEC == 600, CAPTCHA_WAIT_SEC


def test_solved_captcha_resumes_without_screenshot_or_alert():
    _captcha_abort.clear()
    rec = _Recorder(_captcha(1) + [{"blocked": False}])
    out = _with_patches(rec, lambda: _check_and_handle_block(
        9222, "tab", "http://x", "."))
    assert out is True, "人工过了验证码就该继续"
    assert rec.screenshots == [], "不该截图"
    assert rec.alerts == [], "不该发通知"
    assert not _captcha_abort.is_set()


def test_unsolved_captcha_waits_ten_minutes_then_aborts_the_round():
    _captcha_abort.clear()
    try:
        polls = CAPTCHA_WAIT_SEC // CAPTCHA_POLL_SEC
        rec = _Recorder(_captcha(polls + 5))
        out = _with_patches(rec, lambda: _check_and_handle_block(
            9222, "tab", "http://x", "."))
        assert out is False
        assert rec.screenshots == [], "不该截图"
        assert rec.alerts == [], "不该发通知"
        assert sum(rec.slept) == CAPTCHA_WAIT_SEC, rec.slept
        assert _captcha_abort.is_set(), "等满 10 分钟必须置上收工标志"
    finally:
        _captcha_abort.clear()


def test_other_workers_stop_waiting_once_the_round_is_aborted():
    """一个 worker 等超时之后，其余 worker 不该再各自陪等 10 分钟。"""
    _captcha_abort.set()
    try:
        rec = _Recorder(_captcha(50))
        out = _with_patches(rec, lambda: _check_and_handle_block(
            9222, "tab", "http://x", "."))
        assert out is False
        assert rec.slept == [], "已经收工了还在睡"
    finally:
        _captcha_abort.clear()


def test_aborted_worker_skips_the_url_without_opening_a_tab():
    _captcha_abort.set()
    try:
        opened = []
        saved = shein_scraper._navigate_and_wait
        shein_scraper._navigate_and_wait = lambda *a: opened.append(1) or ("ws", "t")
        try:
            rec = shein_scraper._scrape_one_url(
                "http://x", 1, 3, 7, None, None, "")
        finally:
            shein_scraper._navigate_and_wait = saved
        assert rec["status"] == "CAPTCHA_ABORTED", rec
        assert opened == [], "收工之后不该再开 tab"
    finally:
        _captcha_abort.clear()


def test_captcha_abort_carries_the_records_it_already_scraped():
    e = CaptchaAbort("超时", records=[{"seq_num": 1, "status": "OK"}])
    assert e.records == [{"seq_num": 1, "status": "OK"}]
    assert shein_scraper.RateLimitError("x", records=[1]).records == [1]
    assert shein_scraper.RateLimitError("x").records == []


def test_signin_block_still_screenshots_and_alerts():
    """只有人机验证改成静默，登录弹窗关不掉时还是要留证据。"""
    _captcha_abort.clear()
    signin = {"blocked": True, "type": "signin", "rect": None}
    rec = _Recorder([signin] * 12)
    out = _with_patches(rec, lambda: _check_and_handle_block(
        9222, "tab", "http://x", "."))
    assert out is False
    assert rec.screenshots, "登录弹窗该截图"
    assert [k for k, _ in rec.alerts] == ["signin"], rec.alerts


if __name__ == "__main__":
    test_wait_is_ten_minutes()
    test_solved_captcha_resumes_without_screenshot_or_alert()
    test_unsolved_captcha_waits_ten_minutes_then_aborts_the_round()
    test_other_workers_stop_waiting_once_the_round_is_aborted()
    test_aborted_worker_skips_the_url_without_opening_a_tab()
    test_captcha_abort_carries_the_records_it_already_scraped()
    test_signin_block_still_screenshots_and_alerts()
    print("ALL PASS")
