"""
PyInstaller entry point for the employee-facing .exe.

只有一个桌面图标。启动后：
  1. 密码门（auth.gate）。不通过 → 退出 2
  2. 首次运行 → 自动跑配置向导
  3. 更新检查（最多 24h 一次）
  4. 命令行参数分发：
       --config        → 只跑配置向导，然后退出
       --run [args...] → 直接跑抓取，剩余参数透传给 run_excel.main()
       没有参数        → 显示菜单让员工选：[1] 配置目标路径 / [2] 直接跑 / [Q] 退出
  5. 结束前 pause，员工能看清控制台输出

Console must stay visible — Mike's Q6 decision: "黑窗口 + pause".
"""

import os
import sys
import traceback
from pathlib import Path

# Force UTF-8 console (chcp 65001 should already be set by the .cmd, but
# Python may still default to cp936 on Chinese Windows without this).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def _pause_before_exit():
    """Keep the console window open so the user can read what happened."""
    try:
        print("\n" + "=" * 60)
        input("按 Enter 关闭窗口...")
    except (EOFError, KeyboardInterrupt):
        pass


# ── 纯函数（好单测，不碰 IO 之外的东西）─────────────────────────────────────

def has_valid_config(config_file=None) -> bool:
    """配置是否齐全。`config_file` 只给测试用。"""
    from setup_wizard import is_first_run_complete
    return is_first_run_complete(config_file)


def read_menu_choice(input_fn=input) -> str:
    """问一次菜单，返回 "1" / "2" / "Q"。输入无效就重问。
    直接回车 = "Q"（避免手滑误跑一整批）。"""
    prompt = (
        "\n请选择:\n"
        "  [1] 配置目标路径\n"
        "  [2] 直接跑\n"
        "  [Q] 退出\n"
        "> "
    )
    while True:
        raw = (input_fn(prompt) or "").strip()
        if raw == "":
            return "Q"
        c = raw.upper()
        if c in ("1", "2", "Q"):
            return c
        print(f"  无效输入「{raw}」；请输入 1 / 2 / Q。")


# ── 动作 ─────────────────────────────────────────────────────────────────────

def _reload_config():
    """向导刚写完 config.env，把已经 import 过的 config 清掉重新解析。"""
    for mod_name in list(sys.modules.keys()):
        if mod_name == "config" or mod_name.startswith("config."):
            del sys.modules[mod_name]


def _action_config() -> int:
    from setup_wizard import run_wizard
    print("[配置] 打开设置向导...")
    ok = run_wizard()
    if ok:
        print("[配置] 已保存。")
        _reload_config()
        return 0
    print("[配置] 已取消（未保存）。")
    return 1


def _action_run() -> int:
    if not has_valid_config():
        print("[运行] 还没配置路径；请先选 [1] 配置目标路径。")
        return 1
    _reload_config()
    print()
    print("=" * 60)
    print("开始抓取...")
    print("=" * 60)
    print()
    from run_excel import main as run_excel_main
    run_excel_main()
    return 0


def main():
    try:
        from version import VERSION
        print(f"SHEIN 上架工具  v{VERSION}")
        print("=" * 60)

        # 0. Password gate — applies to BOTH normal launch and --config mode
        #    so unauthorized users can't even reconfigure settings.
        from auth import gate
        if not gate():
            return 2

        # 1. --config：只跑向导，跑完就退出
        argv = sys.argv[1:]
        if "--config" in argv:
            return _action_config()

        # 2. 首次运行：还没配置过就先把向导跑起来
        if not has_valid_config():
            print("[首次设置] 启动设置向导...")
            from setup_wizard import run_wizard
            if not run_wizard():
                print("[首次设置] 用户取消，退出。")
                return 1
            print("[首次设置] 完成。")
            _reload_config()

        # 3. 更新检查
        try:
            from update_check import check_for_update
            check_for_update()
        except Exception as e:
            # Never let an update check failure block the actual run
            print(f"[更新检查] 跳过（{e.__class__.__name__}）")

        # 4. --run：直接跑，剩下的参数透传给 run_excel 的 argparse
        if "--run" in argv:
            sys.argv = [sys.argv[0]] + [a for a in argv if a != "--run"]
            return _action_run()

        # 5. 没参数 → 菜单
        choice = read_menu_choice()
        if choice == "Q":
            print("已退出。")
            return 0
        if choice == "1":
            return _action_config()
        sys.argv = [sys.argv[0]]
        return _action_run()

    except KeyboardInterrupt:
        print("\n[中断] 用户按 Ctrl+C")
        return 130
    except SystemExit as e:
        # Wizard / update check called sys.exit() — propagate
        return int(e.code) if isinstance(e.code, int) else 1
    except Exception:
        print("\n[严重错误] 发生未处理的异常：")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    rc = main()
    _pause_before_exit()
    sys.exit(rc)
