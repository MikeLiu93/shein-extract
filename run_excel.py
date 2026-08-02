"""
Excel-based pipeline: 从中文表头模板读待处理 URL，抓取后把结果写回 F–M 列，
并在 OUTPUT_ROOT/{sheet名}/ 下产出媒体文件夹和批次汇总 xlsx。

Usage:
    python run_excel.py                          # 默认 SUBMITTED_DIR/INPUT_FILENAME
    python run_excel.py "path/to/file.xlsx"      # 指定文件

Columns (strict, 中文表头模板):
    A: 编号       — 序号，同时是输出子文件夹名。READ.
    B: 链接       — Shein 商品 URL。READ.
    C: 原价       — 手填售价 (USD)。READ. 空 → 用网页抓到的价。
    D: 运费       — 手填运费 (USD)。READ. 空 → 用扫描推导的运费。
    E: 变体       — 变体过滤声明。READ. 空 → 抓全部变体。
    F: 日期       — 运行日期。WRITE.
    G: 状态       — Done / Failed / Delisted。WRITE.
    H: 图片       — 嵌入首张商品图。WRITE.
    I: 希音价格   — 网页售价；多变体不同价时是 "9.99–14.99" 区间串。WRITE.
    J: 希音标题   — 原始 h1 标题。WRITE.
    K: eBay标题   — AI 生成（Haiku），失败回退规则。WRITE.
    L: eBay价格   — (C或抓到价 + D或推导运费) × 1.4。WRITE.
    M: 库存       — 单行变体库存摘要。WRITE.

只处理「链接有值 且 日期/状态都为空」的行。B1 不是「链接」的 sheet 直接跳过。
"""

import argparse
import logging
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from shein_scraper import scrape_shein, RateLimitError, _add_picture_to_cell
from config import SUBMITTED_DIR, OUTPUT_ROOT_2ND as OUTPUT_ROOT, BACKUP_DIR, INPUT_FILENAME

logger = logging.getLogger("run_excel")
DEFAULT_XLSX = INPUT_FILENAME
DEBUG_LOG_DIR = Path(__file__).resolve().parent / "debug_logs"

# ── 中文表头模板 schema（A–M）────────────────────────────────────────────────
# 见 docs/superpowers/specs/2026-08-02-us-template-parallel-design.md §1
COL_SEQ, COL_URL, COL_PRICE, COL_SHIPPING, COL_VARIANT_FILTER = 1, 2, 3, 4, 5
COL_DATE, COL_STATUS, COL_PICTURE = 6, 7, 8
COL_WEB_PRICE, COL_SHEIN_TITLE = 9, 10
COL_EBAY_TITLE, COL_EBAY_PRICE, COL_STOCK = 11, 12, 13

EXPECTED_HEADERS = ["编号", "链接", "原价", "运费", "变体",
                    "日期", "状态", "图片", "希音价格", "希音标题",
                    "eBay标题", "eBay价格", "库存"]


def _sheet_matches_template(ws) -> bool:
    """只有 B1 == 「链接」的 sheet 才按新 schema 处理。"""
    return str(ws.cell(1, COL_URL).value or "").strip() == "链接"


def _read_pending_rows(ws) -> list[dict]:
    """返回 [{row, seq, url, price, shipping, variant_filter}, ...]。

    只挑「链接有值 且 日期/状态都为空」的行。非模板 sheet 返回 []。
    原价/运费为空 → None（交给 scraper 回退）。编号或原价/运费非数字 → 跳过并记日志。
    """
    if not _sheet_matches_template(ws):
        return []
    pending = []
    for r in range(2, ws.max_row + 1):
        seq = ws.cell(r, COL_SEQ).value
        url = ws.cell(r, COL_URL).value
        if not url or ws.cell(r, COL_DATE).value or ws.cell(r, COL_STATUS).value:
            continue
        if seq is None:
            logger.info("  row %d: skip (无编号)", r)
            continue
        try:
            seq_int = int(seq)
        except (TypeError, ValueError):
            logger.info("  row %d: skip (编号 '%s' 非数字)", r, seq)
            continue
        raw_price = ws.cell(r, COL_PRICE).value
        raw_ship = ws.cell(r, COL_SHIPPING).value
        try:
            price = float(raw_price) if raw_price not in (None, "") else None
        except (TypeError, ValueError):
            logger.info("  row %d: skip (原价 '%s' 非数字)", r, raw_price)
            continue
        try:
            shipping = float(raw_ship) if raw_ship not in (None, "") else None
        except (TypeError, ValueError):
            logger.info("  row %d: skip (运费 '%s' 非数字)", r, raw_ship)
            continue
        pending.append({
            "row": r,
            "seq": seq_int,
            "url": str(url).strip(),
            "price": price,
            "shipping": shipping,
            "variant_filter": str(ws.cell(r, COL_VARIANT_FILTER).value or "").strip(),
        })
    return pending


def _write_result_row(
    ws, row: int, date: str, status: str,
    picture_path=None,
    web_price=None,
    shein_title=None,
    ebay_title=None,
    ebay_price=None,
    stock=None,
) -> None:
    """写结果列 F–M。日期(F) 和 状态(G) 总是写；其余为 None 就不写
    （Failed / Delisted 的行只留日期和状态）。picture_path 是真实文件时
    把图嵌进 H 并把行高撑到放得下。"""
    ws.cell(row, COL_DATE).value = date
    ws.cell(row, COL_STATUS).value = status
    if picture_path and Path(picture_path).is_file():
        row_h = _add_picture_to_cell(ws, row, COL_PICTURE, Path(picture_path))
        if row_h:
            existing = ws.row_dimensions[row].height or 0
            ws.row_dimensions[row].height = max(existing, row_h)
    if web_price is not None:
        ws.cell(row, COL_WEB_PRICE).value = web_price
    if shein_title is not None:
        ws.cell(row, COL_SHEIN_TITLE).value = shein_title
    if ebay_title is not None:
        ws.cell(row, COL_EBAY_TITLE).value = ebay_title
    if ebay_price is not None:
        ws.cell(row, COL_EBAY_PRICE).value = ebay_price
    if stock is not None:
        ws.cell(row, COL_STOCK).value = stock


def setup_logging():
    DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = DEBUG_LOG_DIR / f"excel_{ts}.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    root = logging.getLogger("run_excel")
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

    logger.info("Log: %s", log_path)
    return log_path


def backup_excel(xlsx_path: Path) -> None:
    """Backup Excel to personal Drive before reading, with date suffix."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    stem = xlsx_path.stem
    backup_name = f"{stem}_{today}.xlsx"
    dest = BACKUP_DIR / backup_name
    try:
        shutil.copy2(xlsx_path, dest)
        logger.info("Backup: %s → %s", xlsx_path.name, dest)
    except Exception as e:
        logger.warning("Backup failed (continuing anyway): %s", e)


def safe_save(wb, xlsx_path: Path) -> None:
    """Save workbook. If locked by another user, save as copy with '2' suffix."""
    try:
        wb.save(xlsx_path)
    except PermissionError:
        alt = xlsx_path.with_stem(xlsx_path.stem + "2")
        logger.warning("Cannot save to %s (locked), saving to %s", xlsx_path.name, alt.name)
        wb.save(alt)
        logger.info("Saved to alternate: %s", alt.name)


def process_excel(xlsx_path: Path) -> None:
    """Process all worksheets in an Excel file."""
    logger.info("Opening: %s", xlsx_path.name)
    wb = load_workbook(xlsx_path)

    for ws_name in wb.sheetnames:
        ws = wb[ws_name]
        store = ws_name.strip()
        logger.info("Sheet: %s", store)

        # Normalize headers: col C = Price, col D = Date
        if str(ws.cell(1, 3).value or "").strip() == "":
            ws.cell(1, 3).value = "Price"
        header_d = str(ws.cell(1, 4).value or "").strip()
        if header_d in ("Execute Date", ""):
            ws.cell(1, 4).value = "Date"

        # Collect pending rows (Date AND Status both empty)
        pending = []
        for row in range(2, ws.max_row + 1):
            seq = ws.cell(row, 1).value
            url = ws.cell(row, 2).value
            price_val = ws.cell(row, 3).value
            date_val = ws.cell(row, 4).value
            status_val = ws.cell(row, 5).value
            if url and seq is not None and not date_val and not status_val:
                try:
                    price_f = float(price_val) if price_val not in (None, "") else None
                except (TypeError, ValueError):
                    price_f = None
                pending.append((row, int(seq), str(url).strip(), price_f))

        if not pending:
            logger.info("  No pending rows in '%s'", store)
            continue

        logger.info("  %d pending URL(s): seq %s",
                     len(pending), [p[1] for p in pending])

        # Prepare output folder
        store_dir = OUTPUT_ROOT / store
        store_dir.mkdir(parents=True, exist_ok=True)

        # Run scraper
        urls = [p[2] for p in pending]
        seqs = [p[1] for p in pending]
        prices = [p[3] for p in pending]
        today = datetime.now().strftime("%Y-%m-%d")
        seq_min, seq_max = min(seqs), max(seqs)
        xlsx_name = f"{store}-{seq_min}-{seq_max}-{today.replace('-', '')}.xlsx"

        # screenshots/ subfolder is created lazily by the scraper itself
        old_cwd = Path.cwd()
        results = None
        try:
            # Google Drive sync may briefly lock new folders
            for _retry in range(5):
                try:
                    os.chdir(store_dir)
                    break
                except PermissionError:
                    time.sleep(2)
            else:
                os.chdir(store_dir)  # final attempt, let it raise
            logger.info("  Scraping %d URLs → %s/%s", len(urls), store, xlsx_name)
            results = scrape_shein(urls, output=xlsx_name, seq_list=seqs,
                                   price_list=prices)
        except RateLimitError:
            logger.warning("  [限流] Rate limited during '%s'", store)
        except Exception as e:
            logger.exception("  Error processing '%s': %s", store, e)
            try:
                tb = traceback.format_exc()
                (DEBUG_LOG_DIR / "last_traceback.txt").write_text(tb, encoding="utf-8")
            except OSError:
                pass
        finally:
            os.chdir(old_cwd)

        # Update Date + Status based on results
        for row_idx, seq, url, _price in pending:
            seq_folder = store_dir / str(seq)
            has_files = seq_folder.is_dir() and any(seq_folder.iterdir())

            # Determine status from result record
            rec = None
            if results:
                rec = next((r for r in results if r.get("seq_num") == seq), None)

            # A record with empty SKU or [goods_name] title is not a real success
            is_bad_data = (rec and rec.get("status") == "OK"
                           and (not rec.get("sku")
                                or "[goods_name]" in (rec.get("title") or "")))

            if has_files and not is_bad_data:
                ws.cell(row_idx, 4).value = today
                ws.cell(row_idx, 5).value = "Done"
                logger.info("    seq %d → Done", seq)
            elif rec and rec.get("status") == "DELISTED":
                ws.cell(row_idx, 4).value = today
                ws.cell(row_idx, 5).value = "Delisted"
                logger.info("    seq %d → Delisted", seq)
            else:
                detail = rec.get("status", "") if rec else ""
                if is_bad_data:
                    detail = "no data loaded"
                ws.cell(row_idx, 4).value = today
                ws.cell(row_idx, 5).value = "Failed"
                logger.info("    seq %d → Failed %s", seq,
                            f"({detail})" if detail else "")

        # Save after each store (so progress isn't lost)
        safe_save(wb, xlsx_path)
        logger.info("  Saved progress to %s", xlsx_path.name)

    wb.close()
    logger.info("Done: %s", xlsx_path.name)


def main():
    parser = argparse.ArgumentParser(
        description="Excel-based Shein scraper pipeline")
    parser.add_argument("file", nargs="?", default=None,
                        help="Path to .xlsx file (default: Shein Submited Links.xlsx)")
    args = parser.parse_args()

    setup_logging()

    if args.file:
        files = [Path(args.file)]
    else:
        default = SUBMITTED_DIR / DEFAULT_XLSX
        if default.exists():
            files = [default]
        else:
            logger.error("Default file not found: %s", default)
            return

    for f in files:
        logger.info("=" * 60)
        # Backup before reading
        backup_excel(f)
        try:
            process_excel(f)
        except Exception as e:
            logger.exception("Fatal error processing %s: %s", f.name, e)

    logger.info("All done.")


if __name__ == "__main__":
    main()
