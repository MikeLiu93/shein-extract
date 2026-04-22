# Shein Extract Pipeline - Architecture & Logic

## Overview

Automated pipeline that scrapes SHEIN product data, generates eBay listing assets (Excel + images + listing text), and manages the full lifecycle from intake to completion via Google Drive shared folders.

```
Google Drive (submitted/*.txt)
        |
        v
  take_orders_worker.py  --once / --retry / loop
        |
        v
  shein_scraper.py  (Chrome CDP, per-URL scraping)
        |
        +---> Excel (.xlsx with embedded images)
        +---> Media folders (seq/img_*.webp, video_*.mp4)
        +---> eBay listing text (eBay上架描述.txt)
        |
        v
Google Drive (completed/{employee}/{folder}/)
```

---

## File Map

| File | Role |
|------|------|
| `shein_scraper.py` | Core scraper — Chrome CDP, data extraction, Excel output, AI title generation |
| `take_orders_worker.py` | Pipeline orchestrator — reads inbox, dispatches scraper, moves files, resume logic |
| `state_tracker.py` | Heartbeat writer — atomic `state/state.json` + append `state/events.jsonl` |
| `dashboard.py` | Local web UI at `:5055` — reads state files, shows health/progress/log tail |
| `notify.py` | Email alerts via Gmail SMTP — captcha, login, generic errors with screenshots |
| `merge_store_reports.py` | Weekly Excel merge — dedup by seq, embed images, group by employee+store |
| `run_once_from_txt.py` | Convenience — process a single .txt file directly |
| `run.cmd` | Manual trigger — runs `--once` then `--retry`, pauses at end |
| `run_scheduled.cmd` | Task Scheduler entry — same as run.cmd but no pause, logs to `cmd_*.log` |
| `run_dashboard.cmd` | Starts dashboard.py |
| `setup_schedule.ps1` | Registers Windows scheduled task (14:00 + 20:00 daily, wake-from-sleep) |

---

## Directory Layout

```
Project root (C:\Users\ak\Desktop\Claude\shein extract\)
  shein_scraper.py
  take_orders_worker.py
  ...
  .env                      # ANTHROPIC_API_KEY (gitignored)
  debug_logs/               # Per-run logs: run_YYYYMMDD_HHMMSS.log, cmd_*.log
  state/                    # Runtime: state.json, events.jsonl (gitignored)

Google Drive (D:\共享云端硬盘\02 希音\Auto Pipeline\)
  Listing - web links (submitted)/    # INBOX: drop .txt files here (1 URL per line)
  Listing - web links (processed)/    # Successful .txt moved here (by employee)
  Listing - web links (failed)/       # Failed .txt moved here
  Listing - completed/                # OUTPUT: Excel + media folders
    {EMPLOYEE}/
      {txt_filename}/
        shein_products_{store}_{seq}.xlsx
        69/  70/  71/  ...            # seq folders = media per product
          img_001.webp
          img_002.webp
          video_001.mp4
          eBay上架描述.txt
        _retry.txt                    # Failed URLs for --retry mode
```

---

## Filename Convention

Input .txt files follow this pattern:
```
20260417 - TT - B5 - 69-80.txt
^^^^^^^^   ^^   ^^   ^^^^^
  date    emp  store  seq range
```

- **Employee codes**: NA, TT, YAN, ZQW, LUMEI
- **Store code**: used in output Excel filename (`shein_products_B5_69-80.xlsx`)
- **Seq range**: determines start sequence number for Excel rows and media folder names

---

## Core Scraping Flow (shein_scraper.py)

### Per-URL Processing

```
1. Open new Chrome tab, navigate to URL
2. _check_and_handle_block()  <-- captcha/login detection
3. Wait for page ready (poll goods_sn, max 20s)
4. Scroll gallery to trigger lazy-load
5. Extract product data via JS injection:
   - goods_sn (SKU), title, price, shipping
   - variations (color, size, etc.)
   - sku_prices (per-variant pricing)
   - media URLs (images, videos)
   - stock info
6. Generate eBay title (AI via Claude Haiku, fallback to rules)
7. Download media (parallel, 8 threads)
8. Write eBay listing text
9. Close tab, record result
```

### Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `CDP_PORT` | 9222 | Chrome DevTools Protocol port |
| `PAGE_LOAD_MAX_WAIT` | 20s | Max wait for page data to appear |
| `PAGE_LOAD_RETRIES` | 3 | Retries for error/empty pages |
| `DELAY_BETWEEN_PAGES` | 2s | Cooldown between URLs |
| `EXTRACTION_TIMEOUT_SEC` | 240s | Hard timeout per URL (4 min) |
| `CAPTCHA_AUTO_RETRIES` | 2 | Auto-refresh attempts on captcha |
| `RATE_LIMIT_CONSECUTIVE` | 3 | Consecutive fails = rate limit trigger |
| `IMAGE_DOWNLOAD_WORKERS` | 8 | Parallel image download threads |
| `KEEP_CHROME_OPEN` | True | Reuse Chrome across URLs |
| `EBAY_MARKUP` | 1.4 | eBay price = max(price+ship, $22) x 1.4 |
| `LOW_STOCK_THRESHOLD` | 15 | Mark "少货" if stock <= this |

---

## Interception Handling (captcha / login / timeout)

### Detection

JS (`_JS_DETECT_BLOCK`) checks for:
- Login/signin overlays (`.c-login`, `#login-panel`, etc.)
- Captcha iframes (`iframe[src*="captcha"]`, `iframe[src*="recaptcha"]`)
- Captcha elements (`[class*="captcha"]`, `[id*="captcha"]`)
- Challenge text ("verify you are human", etc.)

Returns: `{blocked: bool, type: "signin" | "captcha" | "captcha_text"}`

### Response Flow

```
                  URL loaded
                     |
             _check_and_handle_block()
                     |
            +----- blocked? -----+
            |                    |
           No                  Yes
            |                    |
         continue           what type?
                           /          \
                     signin          captcha
                       |                |
                 auto-dismiss      auto-refresh x2
                  (3 attempts)         |
                       |          still blocked?
                  still blocked?       |
                       |         Yes: email alert
                 Yes: email         + wait 300s
                   + BLOCKED        (poll every 15s)
                                       |
                                  resolved?
                                  /        \
                                Yes       No (timeout)
                                 |           |
                              continue    BLOCKED
```

### After BLOCKED

```
URL marked BLOCKED → _consecutive_fails += 1
                           |
                    consecutive_fails >= 3?
                      /              \
                    No               Yes
                     |                |
                 next URL        RATE LIMITED
                                     |
                             remaining URLs marked
                             RATE_LIMITED in records
                                     |
                             _save_excel (partial)
                             _retry.txt written
                                     |
                             raise RateLimitError
```

### Worker-Level RateLimitError Handling

| Mode | Behavior |
|------|----------|
| `run_batch_once()` | Catch → sleep 2 hours → continue to next .txt file |
| `main()` loop | Catch → sleep 2 hours → continue to next .txt file |
| `--once` | Catch → sleep 2 hours → continue remaining .txt → exit |
| `--retry` | Not caught (propagates up) |

### Timeout Detection (secondary)

If a single URL exceeds `EXTRACTION_TIMEOUT_SEC` (240s) during data extraction retries:
1. Takes a screenshot (`_timeout_screenshot.png`)
2. Re-checks for captcha
3. Sends `alert_generic()` email with screenshot
4. Marks URL as `TIMEOUT` or `PARSE_ERROR`
5. Counts toward `_consecutive_fails`

---

## eBay Title Generation

### AI Path (primary)

1. Load API key from `.env` (`ANTHROPIC_API_KEY`)
2. Call Claude Haiku with product title + style instruction
3. Style varies by employee code (anti-association for multi-store):
   - NA: features/specs first
   - TT: use case/audience first
   - YAN: size/material first
   - ZQW: category/benefit first
   - LUMEI: color/design first
4. `temperature=0.5` for natural variation
5. Post-processing: strip wrapping quotes, fix truncated "FREE SH..." tags
6. Sanity check: non-empty and <= 80 chars

### Fallback Path (on API failure)

1. Strip brand prefix (all-caps or PascalCase first 1-2 words)
2. Remove articles (the/a/an) and marketing noise phrases
3. Split by segment delimiters (comma, dash, semicolon)
4. Join segments front-to-back up to 80 chars
5. Add "NEW " prefix and " FREE SHIPPING" suffix if space allows

---

## Resume / Retry Mechanism

### Resume (automatic on re-run)

When `process_order_file()` finds an existing output folder:
1. Scan for seq sub-folders containing files (= completed)
2. Filter out completed URLs from the list
3. Pass remaining URLs with `seq_list` to scraper
4. Output to `*_resumed.xlsx` (separate from original)

### Retry (explicit --retry mode)

1. Scan all `_retry.txt` files under completed/
2. Parse failed URL + original seq number
3. Re-run only those URLs with `seq_list`
4. Output to `*_2nd_run.xlsx`

---

## Dashboard (dashboard.py)

- URL: `http://127.0.0.1:5055/`
- Auto-refresh: 3 seconds
- API endpoint: `/state.json`

### Health Badge Logic

| Level | Condition | Color |
|-------|-----------|-------|
| OK | PID alive + heartbeat < 60s | Green |
| WARN | PID alive + heartbeat 60-300s | Yellow |
| DEAD | PID dead OR heartbeat > 300s | Red |
| UNKNOWN | No state.json OR status=stopped | Gray |

### Display

- State table: PID, mode, started, heartbeat, phase, status, current file, current URL
- Progress bar: done / total URLs
- Recent events: last 8 from events.jsonl
- Log tail: last 25 lines of newest `debug_logs/run_*.log`
- Error banner: last error timestamp + message

---

## Scheduled Tasks

| Task Name | Schedule | Action |
|-----------|----------|--------|
| `SheinListing-TakeOrders` | Daily 14:00 + 20:00 | `run_scheduled.cmd` (--once + --retry) |
| `SheinListing-WeeklyMerge` | Weekly | `merge_store_reports.py` |

Both tasks: wake-from-sleep enabled, 2-hour timeout, restart on failure.

---

## Email Alerts (notify.py)

| Function | Subject | Trigger |
|----------|---------|---------|
| `alert_captcha()` | "Shein 爬虫被验证码拦截" | Captcha auto-retry exhausted |
| `alert_signin()` | "Shein 要求登录" | Login popup can't auto-dismiss |
| `alert_generic()` | "Shein 爬虫异常" | Page timeout, extraction failure |

All alerts include: URL, timestamp, optional screenshot attachment.
Config: Gmail SMTP (587), credentials from env vars `GMAIL_USER` + `GMAIL_APP_PASSWORD`.

---

## Configuration Files

| File | Purpose | In Git? |
|------|---------|---------|
| `.env` | `ANTHROPIC_API_KEY` for AI title generation | No (gitignored) |
| `notify.py` | Gmail credentials via env vars | Yes (no secrets in code) |
| `SheinTask.xml` | Task Scheduler export (reference only) | Yes |
| `setup_schedule.ps1` | Task registration script | Yes |
| `shein_scraper.py.bak.*` | Pre-change backup of scraper | Yes |
