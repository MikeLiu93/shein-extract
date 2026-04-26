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
| **take_orders_worker.py** | Legacy TXT pipeline — .txt intake (still works but not primary) |
| **state_tracker.py** | Heartbeat writer — `state/state.json` + `state/events.jsonl` |
| **dashboard.py** | Local web UI at `:5055` — health/progress/log tail |
| **notify.py** | Email alerts via Gmail SMTP — captcha, login, errors |
| **merge_store_reports.py** | Weekly Excel merge — dedup by seq, embed images |
| **run_excel.cmd** | Double-click to run Excel pipeline |
| **run.cmd** | Double-click to run legacy TXT pipeline |
| **run_dashboard.cmd** | Start dashboard |

---

## Input Excel Format

File: any `.xlsx` in `submitted/` folder (e.g. `Shein Submited Links Test.xlsx`)

Each **worksheet = one store** (e.g. `B4`, `L8`, `Test1`)

| Col | Header | Read/Write | Description |
|-----|--------|------------|-------------|
| A | Seq | **Read only** | Sequence number = output folder name |
| B | Website | **Read only** | Shein product URL |
| C | Date | **Write** | Execution date (YYYY-MM-DD) |
| D | Status | **Write** | Done / Failed / Delisted |
| E | Stock | **Write** | In Stock (N) / Low Stock (N) / Sold Out / Delisted |
| F | Last Checked | **Write** | Stock check date (YYYY-MM-DD) |

**Rules:**
- `run_excel.py` processes rows where **Date AND Status are both empty**
- `check_stock.py` processes rows where **Status == "Done"**
- Columns A and B are **never modified** by any script

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

### Anti-Detection Navigation

```
_ensure_shein_tab()
  ├─ Reuse SINGLE tab across ALL URLs (no new-tab-per-URL)
  ├─ If Chrome fresh: visit Shein homepage first (warm up session)
  └─ Inject JS: hide navigator.webdriver

_navigate_and_wait()
  ├─ Navigate via JS: window.location.href = url
  ├─ NOT CDP Page.navigate (detectable)
  └─ Poll for goods_sn up to 20s
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
| `DELAY_BETWEEN_PAGES` | 2s | Cooldown between URLs |
| `EXTRACTION_TIMEOUT_SEC` | 60s | Hard timeout per URL |
| `CAPTCHA_AI_MAX_ATTEMPTS` | 3 | AI captcha solve attempts |
| `RATE_LIMIT_CONSECUTIVE` | 3 | Consecutive fails = rate limit |
| `IMAGE_DOWNLOAD_WORKERS` | 8 | Parallel download threads |
| `EBAY_MARKUP` | 1.4 | eBay price multiplier |

---

## Interception Handling

### Flow

```
URL loaded
    │
    ├─ [goods_name] title? → NO_DATA → skip instantly
    ├─ Oops/404? → DELISTED → skip (no fail count)
    │
    ├─ Captcha detected?
    │     ├─ AI solve (crop+enlarge → Vision API → CDP click) x3
    │     ├─ Refresh page + AI retry x2
    │     └─ Email alert + wait 300s for manual solve
    │
    └─ Login popup?
          ├─ Auto-dismiss x3
          └─ Email alert

After BLOCKED:
    _consecutive_fails += 1
    ≥ 3 → RATE LIMITED → sleep 2h → next file
```

### Captcha Types (GeeTest Icon-Click)

Three sub-types observed:
1. **Animals/Objects** — match semantic identity (head↔full body, rotated)
2. **Document types** — read text on icons (FON/PDF/CSV/DOC/TXT)
3. **People** — match by features (police hat, book, etc.)

AI solver: crop captcha panel → enlarge 2x → Claude Haiku Vision API → CDP click.
Limited by Haiku vision capability; prevention (anti-detection) is more effective.

---

## eBay Title Generation

### AI Path (primary)
- Claude Haiku API with per-store style variation (anti-association)
- Styles: NA=specs, TT=use-case, YAN=dimensions, ZQW=category, LUMEI=design
- `temperature=0.5` for natural variation
- Post-processing: fix truncated tags, ≤80 chars

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
| Single tab reuse | No new-tab-per-URL (bot fingerprint) |
| JS navigation | `window.location.href` not CDP `Page.navigate` |
| Session warmup | Visit homepage on fresh Chrome to get cookies |
| Anti-detect JS | Hide `navigator.webdriver`, fake `chrome.runtime` |
| Persistent profile | `~/shein-cdp-profile` retains cookies |
| `--disable-blink-features=AutomationControlled` | Chrome flag |
| `[goods_name]` instant skip | Don't waste time on failed pages |
| Delisted detection | Oops/404 doesn't trigger rate-limit counter |

---

## Scheduled Tasks

| Task | Status | Notes |
|------|--------|-------|
| `SheinListing-TakeOrders` | **Removed** | Was daily 14:00+20:00, caused captcha issues |
| `SheinListing-WeeklyMerge` | Active | Weekly merge reports |

All runs are now **manual** via `run_excel.cmd` or command line.

---

## Email Alerts (notify.py)

| Function | Trigger |
|----------|---------|
| `alert_captcha()` | Captcha AI+refresh all failed |
| `alert_signin()` | Login popup can't auto-dismiss |
| `alert_generic()` | Page timeout, extraction failure |

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
