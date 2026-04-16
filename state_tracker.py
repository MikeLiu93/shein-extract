"""
Lightweight heartbeat + event tracker for shein extract worker.

Writes two files under ./state/:
  - state.json      latest snapshot (atomic write)
  - events.jsonl    append-only event log

Consumed by dashboard.py. Zero external deps.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
STATE_FILE = STATE_DIR / "state.json"
EVENTS_FILE = STATE_DIR / "events.jsonl"

_lock = Lock()
_state: dict = {
    "pid": os.getpid(),
    "started_at": None,
    "last_heartbeat": None,
    "phase": "init",
    "current_file": None,
    "progress": {"done": 0, "total": 0, "current_url": None},
    "status": "idle",
    "last_error": None,
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _flush() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state["last_heartbeat"] = _now_iso()
    _atomic_write(STATE_FILE, json.dumps(_state, ensure_ascii=False, indent=2))


def _append_event(kind: str, **info) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": _now_iso(), "kind": kind, **info}
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def start(mode: str = "loop") -> None:
    with _lock:
        _state["pid"] = os.getpid()
        _state["started_at"] = _now_iso()
        _state["phase"] = "started"
        _state["status"] = "running"
        _state["mode"] = mode
        _flush()
        _append_event("start", pid=os.getpid(), mode=mode)


def heartbeat(phase: str | None = None, **info) -> None:
    with _lock:
        if phase is not None:
            _state["phase"] = phase
        for k, v in info.items():
            _state[k] = v
        _flush()


def set_file(current_file: str | None, total_urls: int = 0) -> None:
    with _lock:
        _state["current_file"] = current_file
        _state["progress"] = {"done": 0, "total": total_urls, "current_url": None}
        _state["phase"] = "processing_file" if current_file else "idle"
        _flush()
        if current_file:
            _append_event("file_start", file=current_file, total=total_urls)


def url_progress(done: int, total: int, current_url: str | None = None) -> None:
    with _lock:
        _state["progress"] = {"done": done, "total": total, "current_url": current_url}
        _flush()


def file_done(current_file: str, ok: bool, msg: str = "") -> None:
    with _lock:
        _state["phase"] = "file_done"
        _state["status"] = "running"
        _flush()
        _append_event("file_done", file=current_file, ok=ok, msg=msg)


def error(msg: str, **info) -> None:
    with _lock:
        _state["last_error"] = {"ts": _now_iso(), "msg": msg, **info}
        _state["status"] = "error"
        _flush()
        _append_event("error", msg=msg, **info)


def idle(reason: str = "waiting") -> None:
    with _lock:
        _state["phase"] = reason
        _state["status"] = "idle"
        _state["current_file"] = None
        _state["progress"] = {"done": 0, "total": 0, "current_url": None}
        _flush()


def stop(reason: str = "exit") -> None:
    with _lock:
        _state["phase"] = "stopped"
        _state["status"] = "stopped"
        _flush()
        _append_event("stop", reason=reason)
