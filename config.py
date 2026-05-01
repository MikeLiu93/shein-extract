"""
Path + env config for the Shein extract pipeline. Reads .env on import.

设计原则（v3.5+）
================
所有"用户决定"的路径都通过 .env 配置，每条路径独立可设：

    SHEIN_SUBMITTED_DIR  — 输入 Excel 所在目录（共享盘上）
    SHEIN_INPUT_FILENAME — 输入 Excel 文件名
    SHEIN_OUTPUT_DIR     — 输出根目录（共享盘上）
    SHEIN_BACKUP_DIR     — 备份目录（独立的共享备份盘上，不再假设和共享盘同盘符）
    ANTHROPIC_API_KEY    — Claude Haiku key（AI 标题）

兼容旧变量（v3.0~v3.4 留下的，仍读取作为 fallback）：

    SHEIN_DRIVE                — 默认 G:
    SHEIN_AUTO_PIPELINE_BASE   — 默认 {DRIVE}\共享云端硬盘\02 希音\Auto Pipeline
    SHEIN_BACKUP_BASE          — 旧名，等价于 SHEIN_BACKUP_DIR

进程环境优先级 > .env 文件 > 默认值。
"""
import os
from pathlib import Path


def _load_env_file() -> None:
    """Load .env into os.environ. Supports both project-local .env and
    %APPDATA%\\shein-extract\\config.env (set up by the first-run wizard)."""
    candidates = []
    # 1) Per-user wizard-managed config (Windows %APPDATA%)
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "shein-extract" / "config.env")
    # 2) Project-local .env (developer / source checkout)
    candidates.append(Path(__file__).resolve().parent / ".env")

    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            # Strip surrounding quotes if any
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            # Process env wins over .env (so CLI overrides keep working)
            if key and key not in os.environ:
                os.environ[key] = val


_load_env_file()

# ── Drive / base (legacy fallback) ────────────────────────────────────────────
DRIVE = os.environ.get("SHEIN_DRIVE", "G:")
AUTO_PIPELINE_BASE = Path(os.environ.get(
    "SHEIN_AUTO_PIPELINE_BASE",
    rf"{DRIVE}\共享云端硬盘\02 希音\Auto Pipeline",
))

# ── Submitted (input) directory ───────────────────────────────────────────────
SUBMITTED_DIR = Path(os.environ.get(
    "SHEIN_SUBMITTED_DIR",
    str(AUTO_PIPELINE_BASE / "Listing - web links (submitted)"),
))

# ── Input filename (default = legacy name) ────────────────────────────────────
INPUT_FILENAME = os.environ.get("SHEIN_INPUT_FILENAME", "Shein Submited Links.xlsx")

# ── Output directory (where {store}/{seq}/ folders go) ────────────────────────
OUTPUT_ROOT_2ND = Path(os.environ.get(
    "SHEIN_OUTPUT_DIR",
    str(AUTO_PIPELINE_BASE / "Listing - completed 2nd"),
))

# ── Legacy completed root (for merge_store_reports.py only) ───────────────────
COMPLETED_ROOT = Path(os.environ.get(
    "SHEIN_COMPLETED_ROOT",
    str(AUTO_PIPELINE_BASE / "Listing - completed"),
))

# ── Backup directory (independent shared drive — no longer derived from DRIVE) ─
# Priority: SHEIN_BACKUP_DIR > legacy SHEIN_BACKUP_BASE > legacy default on personal Drive.
_backup = (
    os.environ.get("SHEIN_BACKUP_DIR")
    or os.environ.get("SHEIN_BACKUP_BASE")
    or rf"{DRIVE}\我的云端硬盘\Backup\Shein\总表"
)
BACKUP_DIR = Path(_backup)
