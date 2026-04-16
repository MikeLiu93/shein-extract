"""
Take orders from Google Drive `Listing - web links (submitted)` (*.txt, one Shein URL per line),
run scrape_shein, write to `Listing - completed`.

计划任务：任务名 SheinListing-TakeOrders，每天本机 15:00 / 21:00 运行 run_submitted_once.cmd。
首次运行该 .cmd 时会自动执行 setup_shein_schedule.ps1 注册任务（生成 .shein_schedule_autoreg.done 后不再重复）。
也可手动：python take_orders_worker.py --once
日志：logs/scheduled_run.log；注册日志：logs/schedule_autoinstall.log
Debug：项目下 debug_logs/run_YYYYMMDD_HHMMSS.log（每轮一份：logging + 爬虫 print/stderr 追加写入）
稳定备份：saved-versions/2026-03-29-stable/
"""

import argparse
import logging
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
import re

from shein_scraper import scrape_shein, RateLimitError
import state_tracker


BASE_DIR = Path(__file__).resolve().parent
DEBUG_LOG_DIR = BASE_DIR / "debug_logs"

logger = logging.getLogger("take_orders_worker")
_RUN_LOG_PATH: Path | None = None

# Drop .txt listing files here (one SHEIN URL per line). Worker moves them to processed/failed after run.
INBOX_DIR = Path(r"D:\共享云端硬盘\02 希音\Auto Pipeline\Listing - web links (submitted)")
PROCESSED_DIR = Path(r"D:\共享云端硬盘\02 希音\Auto Pipeline\Listing - web links (processed)")
FAILED_DIR = Path(r"D:\共享云端硬盘\02 希音\Auto Pipeline\Listing - web links (failed)")
OUTPUT_ROOT = Path(r"D:\共享云端硬盘\02 希音\Auto Pipeline\Listing - completed")

POLL_SECONDS = 3600


class _TeeIO:
    """Mirror writes to multiple text streams (for scraper print → debug log + console)."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass
        try:
            return len(data)
        except Exception:
            return 0

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def setup_debug_logging() -> Path:
    """Create debug_logs/ and attach file + console handlers. Returns path to this run's log file."""
    global _RUN_LOG_PATH
    DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = DEBUG_LOG_DIR / f"run_{ts}.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    root = logging.getLogger("take_orders_worker")
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    _RUN_LOG_PATH = log_path
    logger.debug("Debug log file: %s", log_path)
    return log_path


def read_urls(txt_path: Path) -> list[str]:
    raw = txt_path.read_text(encoding="utf-8", errors="ignore")
    urls = []
    for line in raw.splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.lower().startswith("http"):
            urls.append(line)
    return urls


def _parse_seq_from_filename(name: str) -> tuple[int, int]:
    """
    从文件名中提取 seq range，如 '20260331 - TT - B5 - 16-23' → (16, 23)
    或 '20260331-NA-L8-(28-32)' → (28, 32)
    返回 (start_seq, expected_end)。解析失败则返回 (1, 0)。
    """
    m = re.search(r'\(?(\d+)\s*[-–]\s*(\d+)\)?\s*$', name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1, 0


def _parse_store_and_seq_label(name: str) -> str:
    """
    从文件名提取 store name + seq range 用于 Excel 文件名后缀。
    '20260331 - TT - B2 - 23-37' → 'B2_23-37'
    '20260331-NA-L8-(28-32)' → 'L8_28-32'
    """
    start, end = _parse_seq_from_filename(name)
    seq_str = f"{start}-{end}" if start > 0 and end > 0 else ""

    # 去掉末尾的 seq 部分（包括括号）和日期前缀
    clean = re.sub(r'\(?\d+\s*[-–]\s*\d+\)?\s*$', '', name).strip().rstrip(' -–')
    clean = re.sub(r'^\d{8}\s*[-–]?\s*', '', clean).strip().rstrip(' -–')

    # 现在 clean 应该是 "TT - B2" 或 "NA-L8"
    # store 是最后一段
    parts = re.split(r'\s*[-–]\s*', clean)
    store = parts[-1].strip() if parts else ""

    if store and seq_str:
        return f"{store}_{seq_str}"
    if seq_str:
        return seq_str
    return ""


_KNOWN_EMPLOYEES = {"NA", "TT", "YAN", "ZQW", "LUMEI"}


def _parse_employee_code(name: str) -> str:
    """
    从文件名提取员工代号（第二段）。
    '20260403 - YAN - B4 - 64-80' → 'YAN'
    '20260403- LUMEI-Z3-24-43' → 'LUMEI'
    返回匹配的员工代号，或空字符串。
    """
    clean = re.sub(r'^\d{8}\s*[-–]?\s*', '', name).strip()
    parts = re.split(r'\s*[-–]\s*', clean)
    if parts:
        candidate = parts[0].strip().upper()
        if candidate in _KNOWN_EMPLOYEES:
            return candidate
    return ""


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name or "order"


def unique_output_folder(root: Path, base_name: str) -> Path:
    # Required by user: output folder uses txt filename
    safe = _safe_name(base_name)
    folder = root / safe
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    i = 2
    while True:
        candidate = root / f"{safe}-{i}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        i += 1


def process_order_file(txt_path: Path) -> tuple[bool, str]:
    try:
        urls = read_urls(txt_path)
    except OSError as e:
        logger.error("Cannot read %s: %s", txt_path, e)
        return False, f"Cannot read txt: {e}"

    if not urls:
        return False, "No valid URL lines found in txt."

    state_tracker.set_file(txt_path.name, total_urls=len(urls))

    employee = _parse_employee_code(txt_path.stem)
    out_root = OUTPUT_ROOT / employee if employee else OUTPUT_ROOT
    out_root.mkdir(parents=True, exist_ok=True)
    run_dir = unique_output_folder(out_root, txt_path.stem)
    try:
        shutil.copy2(txt_path, run_dir / txt_path.name)
    except OSError as e:
        logger.warning("copy2 failed (%s), writing URL sidecar only", e)
        sidecar = run_dir / f"{_safe_name(txt_path.stem)}_source_urls.txt"
        sidecar.write_text("\n".join(urls) + "\n", encoding="utf-8")

    old_cwd = Path.cwd()
    old_out, old_err = sys.stdout, sys.stderr
    scrape_log_append = None
    try:
        import os

        os.chdir(run_dir)
        if _RUN_LOG_PATH is not None:
            scrape_log_append = open(_RUN_LOG_PATH, "a", encoding="utf-8")
            scrape_log_append.write("\n--- scrape_shein stdout/stderr ---\n")
            scrape_log_append.flush()
            sys.stdout = _TeeIO(old_out, scrape_log_append)
            sys.stderr = _TeeIO(old_err, scrape_log_append)
        start_seq, _ = _parse_seq_from_filename(txt_path.stem)
        suffix = _parse_store_and_seq_label(txt_path.stem)
        xlsx_name = f"shein_products_{suffix}.xlsx" if suffix else "shein_products.xlsx"
        logger.info("Seq range: start=%d, %d URLs, output=%s", start_seq, len(urls), xlsx_name)
        scrape_shein(urls, output=xlsx_name, start_seq=start_seq)
    finally:
        import os

        if scrape_log_append is not None:
            sys.stdout, sys.stderr = old_out, old_err
            try:
                scrape_log_append.close()
            except OSError:
                pass
        os.chdir(old_cwd)

    return True, str(run_dir)


def move_file(src: Path, dest_dir: Path) -> Path:
    if not src.exists():
        logger.warning("Source file already gone (Drive sync?): %s", src)
        return dest_dir / src.name
    dest = dest_dir / src.name
    if not dest.exists():
        return src.replace(dest)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return src.replace(dest_dir / f"{src.stem}_{stamp}{src.suffix}")


def run_batch_once() -> int:
    """Process every *.txt currently in INBOX; move to processed/failed. Returns exit code 0 if all OK."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(INBOX_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime)
    logger.info("Found %d .txt file(s) in %s", len(txt_files), INBOX_DIR)
    if not txt_files:
        logger.info("No .txt files in: %s", INBOX_DIR)
        return 0

    any_fail = False
    for txt in txt_files:
        logger.info("Processing: %s", txt.name)
        try:
            ok, msg = process_order_file(txt)
            if ok:
                emp = _parse_employee_code(txt.stem)
                proc_dest = PROCESSED_DIR / emp if emp else PROCESSED_DIR
                proc_dest.mkdir(parents=True, exist_ok=True)
                move_file(txt, proc_dest)
                logger.info("Done. Output folder: %s", msg)
            else:
                any_fail = True
                move_file(txt, FAILED_DIR)
                logger.warning("Failed: %s", msg)
        except RateLimitError:
            logger.warning("[限流] Shein 限流检测触发，当前文件已保存已完成部分。")
            logger.info("[限流] 等待 2 小时后自动继续剩余文件...")
            time.sleep(7200)
            logger.info("[限流] 2 小时已到，继续处理...")
        except Exception as e:
            any_fail = True
            logger.exception("Error processing %s: %s", txt.name, e)
            tb = traceback.format_exc()
            try:
                (DEBUG_LOG_DIR / "last_traceback.txt").write_text(tb, encoding="utf-8")
            except OSError:
                pass
            move_file(txt, FAILED_DIR)
    return 1 if any_fail else 0


def run_retry() -> int:
    """
    扫描 completed 文件夹中的 _retry.txt，只重跑失败的 URL，原地更新已有 Excel。
    """
    retry_files = list(OUTPUT_ROOT.rglob("_retry.txt"))
    if not retry_files:
        logger.info("[Retry] No _retry.txt found — nothing to retry.")
        return 0

    logger.info("[Retry] Found %d folder(s) with _retry.txt", len(retry_files))
    any_fail = False
    old_cwd = Path.cwd()
    old_out, old_err = sys.stdout, sys.stderr
    scrape_log_append = None

    for retry_path in retry_files:
        run_dir = retry_path.parent
        logger.info("[Retry] Processing: %s", run_dir.name)

        # 读取失败 URL
        lines = retry_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        retry_urls = []
        retry_seqs = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 3:
                seq = int(parts[0]) if parts[0].isdigit() else 1
                url = parts[2].strip()
                if url.startswith("http"):
                    retry_urls.append(url)
                    retry_seqs.append(seq)

        if not retry_urls:
            logger.info("[Retry] No valid URLs in %s, removing.", retry_path)
            retry_path.unlink(missing_ok=True)
            continue

        # 找到原始 xlsx，生成 "2nd run" 文件名
        xlsx_files = list(run_dir.glob("*.xlsx"))
        if not xlsx_files:
            logger.warning("[Retry] No .xlsx found in %s, skipping.", run_dir)
            continue
        orig_name = xlsx_files[0].stem
        retry_xlsx = f"{orig_name} 2nd run.xlsx"

        logger.info("[Retry] %d failed URL(s) (seq: %s), output: %s",
                     len(retry_urls), retry_seqs, retry_xlsx)

        try:
            import os
            os.chdir(run_dir)
            if _RUN_LOG_PATH is not None:
                scrape_log_append = open(_RUN_LOG_PATH, "a", encoding="utf-8")
                scrape_log_append.write(f"\n--- retry scrape_shein: {run_dir.name} ---\n")
                scrape_log_append.flush()
                sys.stdout = _TeeIO(old_out, scrape_log_append)
                sys.stderr = _TeeIO(old_err, scrape_log_append)

            scrape_shein(retry_urls, output=retry_xlsx, seq_list=retry_seqs)
        except Exception as e:
            any_fail = True
            logger.exception("[Retry] Error retrying %s: %s", run_dir.name, e)
        finally:
            import os
            if scrape_log_append is not None:
                sys.stdout, sys.stderr = old_out, old_err
                try:
                    scrape_log_append.close()
                except OSError:
                    pass
                scrape_log_append = None
            os.chdir(old_cwd)

    return 1 if any_fail else 0


def main():
    parser = argparse.ArgumentParser(description="Listing txt -> SHEIN scrape -> Listing - completed")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process all .txt in submitted folder once, then exit (no hourly loop).",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Only retry failed URLs from _retry.txt in completed folders.",
    )
    args = parser.parse_args()

    log_path = setup_debug_logging()
    logger.info("Debug log: %s", log_path)

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if args.retry:
        logger.info("Retry mode — re-running failed URLs")
        state_tracker.start(mode="retry")
        try:
            raise SystemExit(run_retry())
        finally:
            state_tracker.stop("retry_done")

    if args.once:
        logger.info("Take Orders — single batch")
        logger.info("Submitted: %s", INBOX_DIR)
        state_tracker.start(mode="once")
        try:
            raise SystemExit(run_batch_once())
        finally:
            state_tracker.stop("once_done")

    logger.info("Take Orders worker started (hourly poll). Inbox: %s", INBOX_DIR)
    state_tracker.start(mode="loop")

    while True:
        txt_files = sorted(INBOX_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime)
        if not txt_files:
            state_tracker.idle(f"sleeping_{POLL_SECONDS}s")
            time.sleep(POLL_SECONDS)
            continue

        for txt in txt_files:
            logger.info("Processing: %s", txt.name)
            try:
                ok, msg = process_order_file(txt)
                if ok:
                    move_file(txt, PROCESSED_DIR)
                    logger.info("Done. Output folder: %s", msg)
                    state_tracker.file_done(txt.name, ok=True, msg=msg)
                else:
                    move_file(txt, FAILED_DIR)
                    logger.warning("Failed: %s", msg)
                    state_tracker.file_done(txt.name, ok=False, msg=msg)
            except Exception as e:
                logger.exception("Error: %s", e)
                tb = traceback.format_exc()
                try:
                    (DEBUG_LOG_DIR / "last_traceback.txt").write_text(tb, encoding="utf-8")
                except OSError:
                    pass
                move_file(txt, FAILED_DIR)
                state_tracker.error(str(e), file=txt.name)


if __name__ == "__main__":
    main()
