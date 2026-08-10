"""Test: app_main 的启动菜单和配置检查（单图标方案）。
Run: python test_app_main_menu.py
"""
import tempfile
from pathlib import Path

import app_main


def _input_seq(*responses):
    """依次吐出预设回答的假 input()。"""
    it = iter(responses)
    return lambda prompt="": next(it)


def test_menu_returns_1():
    assert app_main.read_menu_choice(_input_seq("1")) == "1"


def test_menu_returns_2():
    assert app_main.read_menu_choice(_input_seq("2")) == "2"


def test_menu_q_lower_returns_Q():
    assert app_main.read_menu_choice(_input_seq("q")) == "Q"


def test_menu_q_upper_returns_Q():
    assert app_main.read_menu_choice(_input_seq("Q")) == "Q"


def test_menu_empty_returns_Q():
    """菜单上直接回车 = 退出，不要误跑。"""
    assert app_main.read_menu_choice(_input_seq("")) == "Q"


def test_menu_strips_whitespace():
    assert app_main.read_menu_choice(_input_seq("  2  ")) == "2"


def test_menu_invalid_then_valid():
    """乱按不该崩，重新问一次。"""
    assert app_main.read_menu_choice(_input_seq("x", "9", "2")) == "2"


def test_has_valid_config_false_when_file_missing():
    assert app_main.has_valid_config(Path("__nonexistent_config__.env")) is False


def test_has_valid_config_false_when_keys_missing():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "config.env"
        p.write_text("SHEIN_SUBMITTED_DIR=D:\\x\n", encoding="utf-8")
        # 缺 OUTPUT_DIR / BACKUP_DIR
        assert app_main.has_valid_config(p) is False


def test_has_valid_config_true_when_all_keys_present():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "config.env"
        p.write_text(
            "SHEIN_SUBMITTED_DIR=D:\\x\n"
            "SHEIN_OUTPUT_DIR=D:\\x\n"
            "SHEIN_BACKUP_DIR=D:\\y\n",
            encoding="utf-8")
        assert app_main.has_valid_config(p) is True


if __name__ == "__main__":
    test_menu_returns_1()
    test_menu_returns_2()
    test_menu_q_lower_returns_Q()
    test_menu_q_upper_returns_Q()
    test_menu_empty_returns_Q()
    test_menu_strips_whitespace()
    test_menu_invalid_then_valid()
    test_has_valid_config_false_when_file_missing()
    test_has_valid_config_false_when_keys_missing()
    test_has_valid_config_true_when_all_keys_present()
    print("ALL PASS")
