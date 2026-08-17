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

from shein_scraper import (scrape_shein, RateLimitError, CaptchaAbort,
                           _add_picture_to_cell, save_workbook_atomic)
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

# 这些状态代表「这一行压根没抓过」（本轮被人机验证提前掐掉了）。
# 对应的行一个字都不写，日期/状态留空，下次重跑照样能挑到它。
UNATTEMPTED_STATUSES = {"CAPTCHA_ABORTED"}


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
    """跑之前先备份一份带日期后缀的输入表。

    备份目录建不出来（盘符不存在、没配过）时退回输入文件所在目录，再不行就
    放弃备份。这个函数**绝不抛异常** —— 以前 BACKUP_DIR.mkdir() 在 try 外面，
    备份盘没配好就把整轮抓取挡在门外了。
    """
    today = datetime.now().strftime("%Y%m%d")
    backup_name = f"{xlsx_path.stem}_{today}.xlsx"
    tried = []
    for dest_dir in (BACKUP_DIR, xlsx_path.parent):
        if dest_dir in tried:
            continue
        tried.append(dest_dir)
        try:
            dest = dest_dir / backup_name
            if dest.resolve() == xlsx_path.resolve():
                continue        # 备份名和原文件撞了，换下一个目录
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(xlsx_path, dest)
            logger.info("Backup: %s → %s", xlsx_path.name, dest)
            return
        except Exception as e:
            logger.warning("Backup to %s failed: %s", dest_dir, e)
    logger.warning("Backup skipped (continuing anyway)")


def safe_save(wb, xlsx_path: Path) -> None:
    """原子保存。存不进去时退回 '2' 后缀的副本，别让一整轮的活白干。

    走 save_workbook_atomic：先在本地盘写临时文件、自检完整性，再拷到目标盘
    原子替换。保存中途失败时目标文件一个字节都不会变 —— 以前是直接
    wb.save(目标)，写到一半炸掉就会留下没有 [Content_Types].xml 的半截文件。

    目标盘（云盘）抽风时不能直接放弃：抓好的结果只在内存里，扔了就得重跑。
    先试目标文件，不行就写同目录的 '<名字>2.xlsx'，两个都不行才抛。
    """
    try:
        save_workbook_atomic(wb, xlsx_path)
        return
    except Exception as e:
        alt = xlsx_path.with_stem(xlsx_path.stem + "2")
        logger.warning("Cannot save to %s (%s: %s), trying %s",
                       xlsx_path.name, type(e).__name__, e, alt.name)
    save_workbook_atomic(wb, alt)
    logger.warning("Saved to alternate: %s —— 请手动核对后替换原表", alt.name)


def process_excel(xlsx_path: Path) -> None:
    """按中文表头模板处理 `xlsx_path` 里的每个 sheet。非模板 sheet 跳过。
    列定义见模块 docstring 和 design spec §1。"""
    logger.info("Opening: %s", xlsx_path.name)
    wb = load_workbook(xlsx_path)
    captcha_aborted = False

    for ws_name in wb.sheetnames:
        ws = wb[ws_name]
        store = ws_name.strip()
        if not _sheet_matches_template(ws):
            logger.warning("  Sheet '%s': 不是中文模板（B1 不是「链接」），跳过", store)
            continue

        pending = _read_pending_rows(ws)
        if not pending:
            logger.info("  Sheet '%s': 没有待处理的行", store)
            continue

        logger.info("  Sheet '%s': %d 行待处理: seq %s",
                    store, len(pending), [p["seq"] for p in pending])

        store_dir = OUTPUT_ROOT / store
        store_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        seqs = [p["seq"] for p in pending]
        seq_min, seq_max = min(seqs), max(seqs)
        batch_xlsx = f"{store}-{seq_min}-{seq_max}-{today.replace('-', '')}.xlsx"

        old_cwd = Path.cwd()
        results = None
        try:
            # Google Drive 同步偶尔会短暂锁住新建目录
            for _retry in range(5):
                try:
                    os.chdir(store_dir)
                    break
                except PermissionError:
                    time.sleep(2)
            else:
                os.chdir(store_dir)   # 最后一次，让它抛
            logger.info("  Scraping %d URLs → %s/%s", len(pending), store, batch_xlsx)
            results = scrape_shein(
                [p["url"] for p in pending],
                output=batch_xlsx,
                seq_list=seqs,
                price_list=[p["price"] for p in pending],
                shipping_list=[p["shipping"] for p in pending],
                variant_filter_list=[p["variant_filter"] for p in pending],
            )
        except RateLimitError as e:
            logger.warning("  [限流] Rate limited during '%s'", store)
            results = e.records
        except CaptchaAbort as e:
            logger.warning("  [人机验证] %s", e)
            results = e.records
            captcha_aborted = True
        except Exception as e:
            logger.exception("  Error processing '%s': %s", store, e)
            try:
                tb = traceback.format_exc()
                (DEBUG_LOG_DIR / "last_traceback.txt").write_text(tb, encoding="utf-8")
            except OSError:
                pass
        finally:
            os.chdir(old_cwd)

        # 把结果扇回模板行
        for p in pending:
            row, seq = p["row"], p["seq"]
            seq_folder = store_dir / str(seq)
            has_files = seq_folder.is_dir() and any(seq_folder.iterdir())

            rec = None
            if results:
                rec = next((r for r in results if r.get("seq_num") == seq), None)

            # 人机验证收工时没轮到的行：日期/状态留空，下次重跑还能挑到它们。
            # 标成 Failed 反而会让这些根本没抓过的行被永久跳过。
            if rec and rec.get("status") in UNATTEMPTED_STATUSES:
                logger.info("    seq %d → 跳过（本轮未抓，保持待处理）", seq)
                continue

            # SKU 为空或标题里还带 [goods_name] 的，不算真成功
            is_bad_data = (rec and rec.get("status") == "OK"
                           and (not rec.get("sku")
                                or "[goods_name]" in (rec.get("title") or "")))

            if rec and has_files and not is_bad_data and rec.get("status") == "OK":
                _write_result_row(
                    ws, row=row, date=today, status="Done",
                    picture_path=rec.get("first_image_path") or None,
                    web_price=rec.get("web_price_display"),
                    shein_title=rec.get("original_title") or rec.get("title"),
                    ebay_title=rec.get("ebay_title"),
                    ebay_price=rec.get("ebay_price"),
                    stock=rec.get("stock_summary"),
                )
                logger.info("    seq %d → Done", seq)
            elif rec and rec.get("status") == "DELISTED":
                _write_result_row(ws, row=row, date=today, status="Delisted")
                logger.info("    seq %d → Delisted", seq)
            else:
                detail = rec.get("status", "") if rec else ""
                if is_bad_data:
                    detail = "no data loaded"
                _write_result_row(ws, row=row, date=today, status="Failed")
                logger.info("    seq %d → Failed %s", seq,
                            f"({detail})" if detail else "")

        safe_save(wb, xlsx_path)
        logger.info("  Saved progress to %s", xlsx_path.name)

        if captcha_aborted:
            logger.warning("  [人机验证] 本轮结束，剩下的 sheet 留到下次重跑")
            break

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
