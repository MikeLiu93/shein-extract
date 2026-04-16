"""
Local dashboard for shein extract worker.

Reads state/state.json, state/events.jsonl, and tails the latest debug_logs/run_*.log.
Serves a single auto-refreshing page at http://127.0.0.1:5055/

Run:
    python dashboard.py
    (or: run_dashboard.cmd)

Zero third-party deps (stdlib only).
"""

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state" / "state.json"
EVENTS_FILE = BASE_DIR / "state" / "events.jsonl"
DEBUG_LOG_DIR = BASE_DIR / "debug_logs"

PORT = 5055
REFRESH_SEC = 3
STUCK_WARN_SEC = 60
STUCK_DEAD_SEC = 300


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_error": f"state.json parse error: {e}"}


def _recent_events(n: int = 8) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(out))


def _latest_log_tail(n: int = 25) -> tuple[str, list[str]]:
    if not DEBUG_LOG_DIR.exists():
        return ("", [])
    logs = sorted(DEBUG_LOG_DIR.glob("run_*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return ("", [])
    latest = logs[-1]
    try:
        with latest.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return (latest.name, [ln.rstrip() for ln in lines[-n:]])
    except Exception as e:
        return (latest.name, [f"(read error: {e})"])


def _health(state: dict) -> tuple[str, str]:
    """Return (level, label). level in: ok, warn, dead, unknown."""
    if not state:
        return ("unknown", "no state.json yet — worker hasn't run since tracking added")
    if state.get("status") == "stopped":
        return ("unknown", "worker stopped cleanly")
    pid = int(state.get("pid") or 0)
    hb = _parse_iso(state.get("last_heartbeat"))
    alive = _pid_alive(pid)
    if not alive:
        return ("dead", f"PID {pid} not running")
    if hb is None:
        return ("warn", "no heartbeat yet")
    age = (datetime.now() - hb).total_seconds()
    if age > STUCK_DEAD_SEC:
        return ("dead", f"heartbeat stale {int(age)}s (>{STUCK_DEAD_SEC}s)")
    if age > STUCK_WARN_SEC:
        return ("warn", f"heartbeat stale {int(age)}s")
    return ("ok", f"alive, heartbeat {int(age)}s ago")


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_page() -> str:
    state = _load_state()
    level, health_label = _health(state)
    events = _recent_events(8)
    log_name, log_lines = _latest_log_tail(25)

    color = {"ok": "#22c55e", "warn": "#f59e0b", "dead": "#ef4444", "unknown": "#64748b"}[level]

    progress = state.get("progress") or {}
    done = progress.get("done", 0)
    total = progress.get("total", 0)
    current_url = progress.get("current_url") or "-"
    pct = int((done / total) * 100) if total else 0

    rows = []
    rows.append(f'<tr><td>PID</td><td>{state.get("pid", "-")}</td></tr>')
    rows.append(f'<tr><td>Mode</td><td>{_html_escape(str(state.get("mode", "-")))}</td></tr>')
    rows.append(f'<tr><td>Started</td><td>{_html_escape(str(state.get("started_at", "-")))}</td></tr>')
    rows.append(f'<tr><td>Last heartbeat</td><td>{_html_escape(str(state.get("last_heartbeat", "-")))}</td></tr>')
    rows.append(f'<tr><td>Phase</td><td>{_html_escape(str(state.get("phase", "-")))}</td></tr>')
    rows.append(f'<tr><td>Status</td><td>{_html_escape(str(state.get("status", "-")))}</td></tr>')
    rows.append(f'<tr><td>Current file</td><td>{_html_escape(str(state.get("current_file") or "-"))}</td></tr>')
    rows.append(f'<tr><td>Current URL</td><td style="word-break:break-all">{_html_escape(current_url)}</td></tr>')

    last_err = state.get("last_error")
    err_block = ""
    if last_err:
        err_block = f'<div class="err">Last error @ {_html_escape(str(last_err.get("ts","")))}: {_html_escape(str(last_err.get("msg","")))}</div>'

    event_rows = []
    for ev in events:
        kind = ev.get("kind", "?")
        ts = ev.get("ts", "")
        extra = {k: v for k, v in ev.items() if k not in ("kind", "ts")}
        event_rows.append(
            f'<tr><td>{_html_escape(ts)}</td><td><b>{_html_escape(kind)}</b></td>'
            f'<td>{_html_escape(json.dumps(extra, ensure_ascii=False))}</td></tr>'
        )

    log_html = "<br>".join(_html_escape(ln) for ln in log_lines) or "(no log)"

    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>SHEIN Extract · Dashboard</title>
<meta http-equiv="refresh" content="{REFRESH_SEC}">
<style>
  body {{ font-family: Consolas, Menlo, monospace; background:#0f172a; color:#e2e8f0; margin:24px; }}
  h1 {{ margin:0 0 8px; font-size:20px; }}
  .sub {{ color:#94a3b8; font-size:12px; margin-bottom:16px; }}
  .pill {{ display:inline-block; padding:4px 10px; border-radius:999px; font-weight:bold; color:#0f172a; }}
  table {{ border-collapse:collapse; width:100%; margin:8px 0 18px; }}
  td {{ border-bottom:1px solid #1e293b; padding:6px 8px; vertical-align:top; }}
  td:first-child {{ color:#94a3b8; width:160px; }}
  .bar {{ background:#1e293b; border-radius:6px; height:18px; overflow:hidden; margin:6px 0; }}
  .bar > div {{ background:#22c55e; height:100%; }}
  .log {{ background:#020617; padding:12px; border-radius:6px; font-size:12px; max-height:340px; overflow:auto; white-space:pre-wrap; }}
  .err {{ background:#7f1d1d; padding:8px 12px; border-radius:6px; margin:8px 0; }}
  h2 {{ font-size:14px; color:#94a3b8; text-transform:uppercase; letter-spacing:1px; margin:18px 0 6px; }}
</style>
</head><body>
<h1>SHEIN Extract · Dashboard <span class="pill" style="background:{color}">{level.upper()}</span></h1>
<div class="sub">{_html_escape(health_label)} · auto-refresh {REFRESH_SEC}s · {datetime.now().isoformat(timespec='seconds')}</div>

{err_block}

<h2>State</h2>
<table>{''.join(rows)}</table>

<h2>URL Progress</h2>
<div>{done} / {total} ({pct}%)</div>
<div class="bar"><div style="width:{pct}%"></div></div>

<h2>Recent events</h2>
<table>{''.join(event_rows) or '<tr><td colspan=3>(none)</td></tr>'}</table>

<h2>Latest log · {_html_escape(log_name or '(none)')}</h2>
<div class="log">{log_html}</div>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silence
        pass

    def do_GET(self):
        if self.path == "/state.json":
            body = json.dumps(_load_state(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = render_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    print(f"SHEIN extract dashboard → http://127.0.0.1:{PORT}/")
    print(f"  state: {STATE_FILE}")
    print(f"  refresh: {REFRESH_SEC}s · stuck warn {STUCK_WARN_SEC}s · dead {STUCK_DEAD_SEC}s")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
