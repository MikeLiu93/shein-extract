"""
Path + env config. Reads .env into os.environ on import.

Override on this machine via .env:
    SHEIN_DRIVE=D:                 # default G: (Google Drive default mount)
    SHEIN_AUTO_PIPELINE_BASE=...   # full override (rare)
    SHEIN_BACKUP_BASE=...          # full override (rare)
    ANTHROPIC_API_KEY=...
    GMAIL_APP_PASSWORD=...
"""
import os
from pathlib import Path


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        # Process env wins over .env (so CLI overrides keep working)
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file()

DRIVE = os.environ.get("SHEIN_DRIVE", "G:")

AUTO_PIPELINE_BASE = Path(os.environ.get(
    "SHEIN_AUTO_PIPELINE_BASE",
    rf"{DRIVE}\共享云端硬盘\02 希音\Auto Pipeline",
))
BACKUP_BASE = Path(os.environ.get(
    "SHEIN_BACKUP_BASE",
    rf"{DRIVE}\我的云端硬盘\Backup\Shein\总表",
))

SUBMITTED_DIR = AUTO_PIPELINE_BASE / "Listing - web links (submitted)"
OUTPUT_ROOT_2ND = AUTO_PIPELINE_BASE / "Listing - completed 2nd"
COMPLETED_ROOT = AUTO_PIPELINE_BASE / "Listing - completed"
BACKUP_DIR = BACKUP_BASE
