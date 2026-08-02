# Shein Extract Pipeline - Architecture & Logic

## Overview

Two pipelines for scraping SHEIN product data and generating eBay listing assets:

1. **Excel Pipeline (primary)** — input from `.xlsx`, output to `completed 2nd/`
2. **TXT Pipeline (legacy)** — input from `.txt`, output to `completed/`

Plus a lightweight **Stock Checker** for monitoring inventory.

```
┌─────────────────────────────────────────────────────┐
│  Input Excel (.xlsx in submitted/)                  │
│  Worksheets = stores, Columns: Seq|URL|Date|Status  │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
   run_excel.py               check_stock.py
   (full scrape)              (stock only)
          │                         │
          ▼                         │
   shein_scraper.py                 │
   Chrome CDP + AI titles           │
          │                         │
          ▼                         ▼
   completed 2nd/{store}/     Update Excel cols:
   ├─ {seq}/ (media)          Stock + Last Checked
   └─ {store}-{min}-{max}-{date}.xlsx
          │
          ▼
   Update Excel cols:
   Date + Status (Done/Failed/Delisted)
```

---

## File Map

| File | Role |
|------|------|
| **run_excel.py** | Excel pipeline — read pending URLs, scrape, write Date+Status back |
| **check_stock.py** | Stock checker — lightweight, Done URLs only, no image download |
| **shein_scraper.py** | Core scraper — Chrome CDP, data extraction, Excel output, AI titles |
| **state_tracker.py** | Heartbeat writer — `state/state.json` + `state/events.jsonl` |
| **dashboard.py** | Local web UI at `:5055` — health/progress/log tail |
| **notify.py** | Email alerts via Gmail SMTP — captcha, login, errors |
| **merge_store_reports.py** | Weekly Excel merge — dedup by seq, embed images |
| **run_excel.cmd** | Double-click to run Excel pipeline |
| **run_dashboard.cmd** | Start dashboard |

---

## Input Excel Format

File: `SHEIN_SUBMITTED_DIR / SHEIN_INPUT_FILENAME`
(e.g. `D:\共享云端硬盘\02 希音\01 店铺资料\99 ZR\美国希音链接汇总 - ZR.xlsx`)

Each **worksheet = one store** (e.g. `ZR1`, `ZR2`) — also the output subfolder name.

Chinese-header template, columns A–M. **A–E the operator fills, F–M the scripts fill.**

| Col | Header | Read/Write | Description |
|-----|--------|------------|-------------|
| A | 编号 | **Read** | Sequence number = output folder name |
| B | 链接 | **Read** | Shein product URL |
| C | 原价 | **Read** | Manual sale price (USD). Blank → scraped price |
| D | 运费 | **Read** | Manual shipping (USD). Blank → derived (free-threshold → $0, else $2.99) |
| E | 变体 | **Read** | Variant declaration, e.g. `Black, Red / M, L`. Blank → scrape all |
| F | 日期 | **Write** | Execution date (YYYY-MM-DD) |
| G | 状态 | **Write** | Done / Failed / Delisted |
| H | 图片 | **Write** | First product image, embedded |
| I | 希音价格 | **Write** | Scraped price; a `9.99–14.99` range string when variants differ |
| J | 希音标题 | **Write** | Raw scraped h1 title |
| K | eBay标题 | **Write** | AI-generated (Haiku), rule fallback |
| L | eBay价格 | **Write** | `(C or scraped + D or derived) × 1.4` |
| M | 库存 | **Write** | One-line variant stock summary |

**Rules:**
- `run_excel.py` processes rows where **链接 is filled AND 日期/状态 are both empty**
- Sheets whose `B1` is not `链接` are skipped with a warning — the old English
  schema (`Seq/Website/Price/Date/Status`) was **removed in v3.8.0**
- Columns A–E are **never modified** by any script
- Column C, if filled, replaces the web-scraped sale price for that row — and is
  propagated to every `sku_prices` variant so the batch xlsx and the per-SKU txt
  agree with the main row. Column D likewise overrides the derived shipping.
- Column E, if filled and **nothing** matches, the row is marked `Failed`
  (`variant_filter_no_match`) rather than written half-scraped
- `check_stock.py` is a **no-op on this template** (its Stock / Last Checked columns
  no longer exist). Re-check support returns once the S/T/U columns land.

---

## Directory Layout

```
Project root (C:\Users\ak\Desktop\Claude\shein extract\)
  run_excel.py / check_stock.py / shein_scraper.py / ...
  .env                          # ANTHROPIC_API_KEY (gitignored)
  debug_logs/                   # run_*, excel_*, stock_* logs
  state/                        # Runtime heartbeat (gitignored)
  exam pics/
    failed_captchas/            # 19 real GeeTest captcha screenshots
    not_captcha/                # Normal page screenshots

Google Drive (D:\共享云端硬盘\02 希音\Auto Pipeline\)
  Listing - web links (submitted)/
    Shein Submited Links Test.xlsx    # Input Excel
  Listing - completed 2nd/           # NEW: Excel pipeline output
    {store}/
      {seq}/                         # Media folder per product
        img_001.webp / video_001.mp4 / eBay上架描述.txt
      {store}-{min}-{max}-{date}.xlsx
      screenshots/                   # Captcha/error screenshots
  Listing - completed/               # LEGACY: TXT pipeline output
    {employee}/{folder}/...
```

---

## Core Scraping Flow (shein_scraper.py)

### Anti-Detection Navigation (v3.4.1+)

```
_ensure_shein_session()
  ├─ Once per process: visit Shein homepage to warm cookies
  └─ No-op if a Shein page already exists in any tab

_navigate_and_wait(url)
  ├─ PUT /json/new?<url>  ← single-step: open new tab AT URL
  ├─ Equivalent to user typing URL in fresh tab's address bar
  ├─ No Referer (avoids src_identifier vs Referer reconciliation)
  └─ Poll for goods_sn up to 20s

After scrape:
  └─ _close_tab(tab_id)  ← finally clause closes the tab
```

### Per-URL Processing

```
1. Navigate via JS (reuse tab)
2. _check_and_handle_block()     ← captcha/login detection
3. Detect [goods_name]           ← instant skip if no data loaded
4. Detect Oops/404               ← DELISTED, doesn't count as failure
5. Wait for page ready (poll goods_sn, max 20s)
6. Scroll gallery (trigger lazy-load)
7. Extract: SKU, title, price, shipping, variations, stock, media URLs
8. Generate eBay title (AI Haiku + per-store style, fallback to rules)
9. Download media (parallel, 8 threads)
10. Write eBay listing text
```

### Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `CDP_PORT` | 9222 | Chrome DevTools Protocol port |
| `PAGE_LOAD_MAX_WAIT` | 20s | Max wait for goods_sn |
| `INTER_URL_PAUSE_MIN` / `MAX` | 2.0s / 3.0s | Random pause each worker takes after finishing a URL. No long pauses. |
| `EXTRACTION_TIMEOUT_SEC` | 60s | Hard timeout per URL |
| `CAPTCHA_AI_MAX_ATTEMPTS` | 3 | AI captcha solve attempts |
| `RATE_LIMIT_CONSECUTIVE` | 3 | Consecutive fails = rate limit |
| `MAX_PARALLEL_TABS` | 3 | Concurrent CDP tabs scraping |
| `IMAGE_DOWNLOAD_WORKERS` | 4 | Parallel download threads (3 products × 4 = 12 sockets) |
| `EBAY_MARKUP` | 1.4 | eBay price multiplier — no minimum-subtotal floor |

---

## Interception Handling

### Flow (v3.5+: no auto-solve, no email — local console only)

```
URL loaded
    │
    ├─ [goods_name] title? → NO_DATA → skip instantly
    ├─ Oops/404? → backoff 30-60s + retry once → DELISTED if still Oops
    │
    ├─ Captcha detected?
    │     ├─ Take screenshot to screenshots/_captcha_<ts>.png
    │     ├─ Print warning to console
    │     └─ Wait up to 300s for human to solve in Chrome window
    │
    └─ Login popup?
          ├─ Auto-dismiss x3
          └─ Print warning + screenshot if dismiss fails

After BLOCKED (captcha unsolved or signin stuck):
    _consecutive_fails += 1
    ≥ 3 → RATE LIMITED → raise RateLimitError → run_excel.py moves on
```

### Captcha Types (GeeTest Icon-Click)

Three sub-types observed:
1. **Animals/Objects** — match semantic identity (head↔full body, rotated)
2. **Document types** — read text on icons (FON/PDF/CSV/DOC/TXT)
3. **People** — match by features (police hat, book, etc.)

AI auto-solver was removed — Haiku vision wasn't reliable enough on these.
Current approach: detect captcha → screenshot → print to console → wait
for the employee to solve it manually in the visible Chrome window.

---

## eBay Title Generation

### AI Path (primary)
- Claude Haiku API
- `temperature=0.5` for natural variation between similar products
- Post-processing: fix truncated `FREE SHIPPING` tag, enforce ≤80 chars
- (Per-employee style variation was removed in v3.5 — single shared prompt)

### Fallback Path
- Strip brand prefix (ALL-CAPS / PascalCase)
- Remove articles + noise phrases
- Segment-based truncation preserving punctuation
- Add NEW / FREE SHIPPING if space allows

---

## Stock Checker (check_stock.py)

- Lightweight: only loads page + extracts stock count via JS
- No image download, no media, no Excel output file
- Writes directly to input Excel: Stock + Last Checked columns
- Skips Failed rows, only checks Done
- Anti-rate-limit: 4s delay, 1 min pause every 200 URLs
- Results: `In Stock (N)` / `Low Stock (N)` / `Sold Out` / `Delisted` / `Unknown`

**Estimated performance:** ~8s per URL → 1000 URLs ≈ 2-4 hours

---

## Anti-Detection Measures

| Measure | Purpose |
|---------|---------|
| New tab per URL via `PUT /json/new?<url>` | Equivalent to user pasting URL into fresh tab — no Referer, no `Page.navigate` fingerprint |
| Session warmup | Visit homepage once per process to seed cookies |
| Persistent profile | `~/shein-cdp-profile` retains cookies / login across runs |
| `--disable-blink-features=AutomationControlled` | Chrome launch flag |
| Random 4-12s + long pause every 18 URLs | Human-ish pacing (1000 URLs ≈ 6h) |
| `[goods_name]` instant skip | Don't waste time on failed pages |
| Oops backoff retry | 30-60s sleep + reload before judging DELISTED (avoids false positives from soft bans) |
| `RATE_LIMIT_CONSECUTIVE = 3` | Bail out after 3 consecutive failures so we don't push through a ban |

---

## Scheduled Tasks

| Task | Status | Notes |
|------|--------|-------|
| `SheinListing-TakeOrders` | **Removed** | Was daily 14:00+20:00, caused captcha issues |
| `SheinListing-WeeklyMerge` | Active | Weekly merge reports |

All runs are now **manual** via `run_excel.cmd` or command line.

---

## Alerts (notify.py — v3.5+: local console only)

Email was removed when the project was packaged for employees. The same
function names (`alert_captcha`, `alert_signin`, `alert_generic`) now just
print a banner to stdout and reference the screenshot file. Function
signatures unchanged so the scraper code didn't need to change.

---

## What Changed (2026-04-25 ~ 2026-04-26)

Major architectural shift from TXT-based to Excel-based pipeline:

1. **New Excel pipeline** (`run_excel.py`) — worksheet per store, explicit Seq numbers, Date/Status writeback
2. **Stock checker** (`check_stock.py`) — lightweight inventory monitoring
3. **Removed scheduled task** — manual runs only (screen-off → captcha → rate limit)
4. **Navigation rewrite** — single tab reuse + JS navigation (was: new tab per URL + CDP navigate)
5. **Anti-detection** — referrer, session warmup, webdriver hiding
6. **[goods_name] instant skip** — no more 60s wait on dead pages
7. **Delisted detection** — Oops/404 doesn't trigger rate-limit
8. **_retry.txt disabled** — failures tracked in input Excel instead
9. **Output naming** — `{store}-{min}-{max}-{date}.xlsx`
10. **Seq always recorded** — even for Failed rows in output Excel
