r"""
paths.py — one place that resolves every path, for both dev and the packaged exe.

Two kinds of paths:
  • Read-only bundled assets (hud/, core/prompt.txt, icon) → resource(), which
    points at the PyInstaller bundle (sys._MEIPASS) when frozen, else the repo.
  • Writable app data (api_keys.json, settings, memory, logs) → %APPDATA%\JARVIS
    when frozen, so the exe can be deleted/rebuilt without losing keys or memory.
    In dev it stays in the repo so the existing layout is unchanged.
"""

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def resource(*rel) -> str:
    """Absolute path to a bundled, read-only asset."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *rel)


# ── writable app data ────────────────────────────────────────────────────────
if FROZEN:
    DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "JARVIS"
else:
    DATA_DIR = Path(__file__).resolve().parent      # repo root in dev

CONFIG_DIR          = DATA_DIR / "config"
MEMORY_DIR          = DATA_DIR / "memory"
LOGS_DIR            = DATA_DIR / "logs"

API_FILE            = CONFIG_DIR / "api_keys.json"
SETTINGS_FILE       = CONFIG_DIR / "settings.json"
BRIEFING_STATE_FILE = CONFIG_DIR / "briefing_state.json"
MEMORY_FILE         = MEMORY_DIR / "long_term.json"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, MEMORY_DIR, LOGS_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


ensure_dirs()

# ── read-only bundled assets ─────────────────────────────────────────────────
PROMPT_PATH = resource("core", "prompt.txt")
HUD_HTML    = resource("hud", "jarvis_hud.html")
ICON_PATH   = resource("config", "jarvis.ico")
