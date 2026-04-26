"""
Excel-based pipeline: read pending URLs from .xlsx worksheets (one per store),
scrape them, write results to Listing - completed 2nd/{store}/, and update
Date + Status columns in the source Excel.

Usage:
    python run_excel.py                          # scan submitted/ for .xlsx
    python run_excel.py "path/to/file.xlsx"      # specific file

Columns (strict):
    A: Seq       — sequence number (= output folder name). READ ONLY.
    B: Website   — Shein product URL. READ ONLY.
    C: Date      — filled after run: YYYY-MM-DD. WRITE.
    D: Status    — filled after run: Done / Failed / Delisted. WRITE.

Only rows with BOTH Date and Status empty are processed.
"""

import argparse
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from shein_scraper import scrape_shein, RateLimitError

logger = logging.getLogger("run_excel")

SUBMITTED_DIR = Path(r"D:\共享云端硬盘\02 希音\Auto Pipeline\Listing - web links (submitted)")
OUTPUT_ROOT = Path(r"D:\共享云端硬盘\02 希音\Auto Pipeline\Listing - completed 2nd")
DEBUG_LOG_DIR = Path(__file__).resolve().parent / "debug_logs"


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


def find_xlsx_files() -> list[Path]:
    """Find all .xlsx in submitted folder (exclude temp files ~$...)."""
    if not SUBMITTED_DIR.exists():
        return []
    return [f for f in SUBMITTED_DIR.glob("*.xlsx") if not f.name.startswith("~$")]


def process_excel(xlsx_path: Path) -> None:
    """Process all worksheets in an Excel file."""
    logger.info("Opening: %s", xlsx_path.name)
    wb = load_workbook(xlsx_path)

    for ws_name in wb.sheetnames:
        ws = wb[ws_name]
        store = ws_name.strip()
        logger.info("Sheet: %s", store)

        # Collect pending rows (Date AND Status both empty)
        pending = []
        for row in range(2, ws.max_row + 1):
            seq = ws.cell(row, 1).value
            url = ws.cell(row, 2).value
            date_val = ws.cell(row, 3).value
            status_val = ws.cell(row, 4).value
            if url and seq is not None and not date_val and not status_val:
                pending.append((row, int(seq), str(url).strip()))

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
        xlsx_name = f"shein_products_{store}.xlsx"

        old_cwd = Path.cwd()
        results = None
        try:
            os.chdir(store_dir)
            logger.info("  Scraping %d URLs → %s/%s", len(urls), store, xlsx_name)
            results = scrape_shein(urls, output=xlsx_name, seq_list=seqs)
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
        today = datetime.now().strftime("%Y-%m-%d")

        for row_idx, seq, url in pending:
            seq_folder = store_dir / str(seq)
            has_files = seq_folder.is_dir() and any(seq_folder.iterdir())

            if has_files:
                ws.cell(row_idx, 3).value = today
                ws.cell(row_idx, 4).value = "Done"
                logger.info("    seq %d → Done", seq)
            elif results:
                rec = next((r for r in results
                            if r.get("seq_num") == seq), None)
                if rec and rec.get("status") == "DELISTED":
                    ws.cell(row_idx, 3).value = today
                    ws.cell(row_idx, 4).value = "Delisted"
                    logger.info("    seq %d → Delisted", seq)
                elif rec and rec.get("status") not in ("OK", None):
                    ws.cell(row_idx, 3).value = today
                    ws.cell(row_idx, 4).value = "Failed"
                    logger.info("    seq %d → Failed (%s)", seq, rec.get("status"))
                # If rec is OK but no folder → scraper didn't get to download
                # Leave empty so it's retried next run
            # If results is None (crash) and no folder → leave empty for retry

        # Save after each store (so progress isn't lost)
        wb.save(xlsx_path)
        logger.info("  Saved progress to %s", xlsx_path.name)

    wb.close()
    logger.info("Done: %s", xlsx_path.name)


def main():
    parser = argparse.ArgumentParser(
        description="Excel-based Shein scraper pipeline")
    parser.add_argument("file", nargs="?", default=None,
                        help="Path to .xlsx file (default: scan submitted folder)")
    args = parser.parse_args()

    setup_logging()

    if args.file:
        files = [Path(args.file)]
    else:
        files = find_xlsx_files()

    if not files:
        logger.info("No .xlsx files found.")
        return

    for f in files:
        logger.info("=" * 60)
        try:
            process_excel(f)
        except Exception as e:
            logger.exception("Fatal error processing %s: %s", f.name, e)

    logger.info("All done.")


if __name__ == "__main__":
    main()
