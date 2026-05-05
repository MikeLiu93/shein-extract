"""
PyInstaller entry point for the employee-facing .exe.

Flow on every launch:
  1. If first run → run setup wizard. Wizard writes config.env. If user
     cancels, exit cleanly.
  2. Check for updates (max once / 24h). If newer release exists, prompt.
     If user accepts: download new .exe, swap, relaunch (current process exits).
  3. Run the main pipeline (run_excel.py main()).
  4. Pause at the end so the employee can read the console.

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

        # --config: re-run the setup wizard and exit (don't proceed to scrape)
        if "--config" in sys.argv:
            from setup_wizard import run_wizard
            print("[配置] 打开设置向导...")
            ok = run_wizard()
            if ok:
                print("[配置] 已保存。")
                return 0
            print("[配置] 已取消（未保存）。")
            return 1

        # 1. First-run wizard
        from setup_wizard import is_first_run_complete, run_wizard
        if not is_first_run_complete():
            print("[首次设置] 启动设置向导...")
            ok = run_wizard()
            if not ok:
                print("[首次设置] 用户取消，退出。")
                return 1
            print("[首次设置] 完成。")

        # Reload config now that the wizard wrote config.env. config.py
        # reads from %APPDATA%\shein-extract\config.env on import — but
        # if config was already imported before the wizard ran (e.g. by
        # some other module), we need to re-resolve the env vars.
        # Cleanest approach: re-import config in a fresh namespace.
        for mod_name in list(sys.modules.keys()):
            if mod_name == "config" or mod_name.startswith("config."):
                del sys.modules[mod_name]

        # 2. Update check
        try:
            from update_check import check_for_update
            check_for_update()
        except Exception as e:
            # Never let an update check failure block the actual run
            print(f"[更新检查] 跳过（{e.__class__.__name__}）")

        # 3. Run the pipeline
        print()
        print("=" * 60)
        print("开始抓取...")
        print("=" * 60)
        print()
        from run_excel import main as run_excel_main
        run_excel_main()
        return 0

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
