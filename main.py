import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

# ── stdout/stderr: UTF-8 + crash-proof ───────────────────────────────────────
# Upstream prints emoji (🎤 🔊 …); on a cp1252 console or redirected pipe that
# raises UnicodeEncodeError and kills the audio tasks, and under --noconsole
# packaging sys.stdout is None (print() would crash). Make both safe.
class _NullStream:
    def write(self, *a, **k): pass
    def flush(self): pass

for _name in ("stdout", "stderr"):
    _s = getattr(sys, _name, None)
    if _s is None:
        setattr(sys, _name, _NullStream())
    else:
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
# ─────────────────────────────────────────────────────────────────────────────

import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
)

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action, get_weather_text
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import _capture_camera, _capture_screen
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


import paths
BASE_DIR        = get_base_dir()
API_CONFIG_PATH = paths.API_FILE          # %APPDATA%\JARVIS when packaged
PROMPT_PATH     = Path(paths.PROMPT_PATH)  # bundled (read-only)
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

# ── API usage / cost meter ───────────────────────────────────────────────────
# Cumulative spend is persisted here so the HUD's TOTAL survives restarts.
USAGE_STATS_PATH = paths.CONFIG_DIR / "usage_stats.json"
# USD per 1,000,000 tokens for gemini-2.5-flash native-audio via the Live API.
# These are ESTIMATES for the on-screen cost meter — edit if Google's pricing
# changes. Native-audio in/out is billed at the audio rate; text at the text rate.
_PRICE_PER_M = {
    "text_in":   0.50,  "audio_in":  3.00,  "image_in":  3.00,  "video_in":  3.00,
    "text_out":  2.00,  "audio_out": 12.00, "image_out": 12.00, "video_out": 12.00,
}


def _modality_cost_key(modality, direction: str) -> str:
    name = (getattr(modality, "name", None) or str(modality).rsplit(".", 1)[-1]).lower()
    if   "audio" in name: base = "audio"
    elif "image" in name: base = "image"
    elif "video" in name: base = "video"
    else:                 base = "text"
    return f"{base}_{direction}"


def _cost_from_details(details, direction: str):
    """Sum USD cost + token count from a list of ModalityTokenCount entries."""
    cost, toks = 0.0, 0
    for md in details or []:
        c = int(getattr(md, "token_count", 0) or 0)
        toks += c
        key  = _modality_cost_key(getattr(md, "modality", ""), direction)
        rate = _PRICE_PER_M.get(key, _PRICE_PER_M[f"text_{direction}"])
        cost += c * rate / 1_000_000.0
    return cost, toks


# ── App settings (settings.json) ─────────────────────────────────────────────
SETTINGS_PATH = paths.SETTINGS_FILE


def _read_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_settings(**updates) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        st = _read_settings()
        st.update(updates)
        SETTINGS_PATH.write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Settings] save failed: {e}")


# ── Morning news window (spoken briefing once per day, mornings only) ────────
BRIEFING_STATE_PATH = paths.BRIEFING_STATE_FILE
BRIEFING_TZ_OFFSET_H = 7          # GMT+7
BRIEFING_START_HOUR  = 5          # 05:00
BRIEFING_END_HOUR    = 11         # 11:00 (exclusive)


def _briefing_now():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=BRIEFING_TZ_OFFSET_H)))


def _should_brief_news_today() -> bool:
    """True only inside the morning window and not already briefed today."""
    now = _briefing_now()
    if not (BRIEFING_START_HOUR <= now.hour < BRIEFING_END_HOUR):
        return False
    today = now.strftime("%Y-%m-%d")
    try:
        state = json.loads(BRIEFING_STATE_PATH.read_text(encoding="utf-8"))
        if state.get("last_news_date") == today:
            return False
    except Exception:
        pass
    return True


def _read_briefing_state() -> dict:
    try:
        return json.loads(BRIEFING_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_briefing_state(**updates) -> None:
    """Merge-write so news date and launch counter never clobber each other."""
    try:
        BRIEFING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        st = _read_briefing_state()
        st.update(updates)
        BRIEFING_STATE_PATH.write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Briefing] could not save state: {e}")


def _mark_briefed_today() -> None:
    _write_briefing_state(last_news_date=_briefing_now().strftime("%Y-%m-%d"))


def _next_launch_index() -> int:
    """Monotonic per-launch counter — rotates the greeting style so successive
    startups never open the same way."""
    n = int(_read_briefing_state().get("launch_count", 0)) + 1
    _write_briefing_state(launch_count=n)
    return n


# Rotating greeting directives — the model gets a different one each launch, on
# top of an explicit "never repeat yourself" instruction, so JARVIS feels alive
# rather than reading a fixed script.
GREETING_STYLES = [
    "Open with dry, understated British wit — a light quip about the hour.",
    "Greet warmly and note the mood of this time of day.",
    "Lead with one genuinely interesting fact or observation about today's date, then greet.",
    "Be crisp and mission-focused, like reporting for duty — one sharp line.",
    "Greet, then ask one genuinely useful question about what they want to accomplish today.",
    "Reference the day of the week and its character (Monday reset, Friday wind-down, weekend calm).",
    "Be subtly playful with a touch of Stark-style banter — without overdoing it.",
    "Greet, then proactively offer a specific way you could help right now.",
]


def _daypart(hour: int) -> str:
    if   5 <= hour < 12: return "morning"
    if  12 <= hour < 17: return "afternoon"
    if  17 <= hour < 22: return "evening"
    return "late night"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "play_music",
        "description": (
            "Plays music in YouTube Music using the user's logged-in Chrome profile. "
            "Call whenever the user asks to play music, put on a song / artist / album / "
            "genre / mood, play their favourite or liked songs, or play recommended music. "
            "With NO query it plays the user's Liked Music (their favourites). "
            "The user can say this in ANY language (e.g. 'nhạc yêu thích của tôi')."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":   {"type": "STRING", "description": "Song, artist, album, genre or mood to play. Leave empty to play the user's liked/favourite music. Value in English or the original title."},
                "shuffle": {"type": "BOOLEAN", "description": "Shuffle when playing liked music / a playlist (default true). Ignored for a specific song search."},
            },
            "required": []
        }
    },
    {
        "name": "music_control",
        "description": (
            "Controls playback of music already playing in YouTube Music: pause, resume, "
            "next/skip, previous, volume up/down, set volume, mute/unmute. Call when the user "
            "says pause, stop the music, next song, skip, previous, louder, quieter, turn it "
            "up/down, mute — in ANY language. Works whether the HUD is full size or in mini "
            "reactor mode. (Use play_music to START music; use this to control it.)"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "pause | resume | toggle | next | previous | volume_up | volume_down | set_volume | mute | unmute"},
                "value":  {"type": "STRING", "description": "For set_volume only: 0-100 percent."},
            },
            "required": ["action"]
        }
    },
    {
        "name": "set_budget",
        "description": (
            "Sets the user's SOFT spending budget — a warning threshold only; it never blocks "
            "or slows anything. Call when the user asks to set or change their daily or monthly "
            "budget/limit/cap, e.g. 'set my daily budget to 5 dollars', 'giới hạn chi tiêu mỗi "
            "ngày 3 đô', 'warn me at 20 dollars a month'. Pass 0 to turn a cap off."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "daily":   {"type": "NUMBER", "description": "Daily budget in USD. 0 disables the daily guard."},
                "monthly": {"type": "NUMBER", "description": "Monthly budget in USD. 0 disables the monthly guard."},
            },
            "required": []
        }
    },
    {
        "name": "set_relationship_profile",
        "description": (
            "Changes HOW you speak Vietnamese to the user — the relationship pronouns, tone, "
            "and sentence particles. Call when the user asks to change how you address each "
            "other or the vibe, e.g. 'từ giờ xưng em gọi anh', 'gọi tôi là sếp', 'nói chuyện "
            "thân mật hơn', 'be more formal', 'call me boss'. Infer the correct Vietnamese "
            "pronouns and tone from the request. Only pass the fields that change."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "ai_pronoun":   {"type": "STRING", "description": "How you refer to YOURSELF in Vietnamese, e.g. Con, Em, Mình, Tôi."},
                "user_pronoun": {"type": "STRING", "description": "How you address the USER in Vietnamese, e.g. Bố, Sếp, Anh, Cậu."},
                "tone":         {"type": "STRING", "description": "Tone descriptor, e.g. 'filial and warm', 'professional and respectful', 'casual and friendly'."},
                "particles":    {"type": "STRING", "description": "Mandatory sentence-ending particle(s), e.g. 'ạ', 'nhé'."},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off camera, "
            "kamerayı kapat, kapat, creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
]

# --- Plugin system ---


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_reconfigure    = self.request_reconnect
        self._reconnect_requested = False
        # Proactive check-ins are OFF by default (opt-in via tray toggle) so
        # JARVIS never pings unprompted unless the user asks for it.
        self._proactive_enabled   = bool(_read_settings().get("proactive_enabled", False))
        self.ui.on_proactive_toggle = self._set_proactive
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance

        # ── API usage / cost meter ──────────────────────────────────────────
        self._usage_lock     = threading.Lock()
        self._session_cost   = 0.0
        self._session_tokens = 0
        self._total_cost     = 0.0
        self._total_tokens   = 0
        self._daily          = {}   # {"YYYY-MM-DD": cost} for today's spend + monthly forecast
        try:
            _st = json.loads(USAGE_STATS_PATH.read_text(encoding="utf-8"))
            self._total_cost   = float(_st.get("total_cost", 0.0))
            self._total_tokens = int(_st.get("total_tokens", 0))
            self._daily        = {k: float(v) for k, v in (_st.get("daily", {}) or {}).items()}
        except Exception:
            pass

        # Soft budget guard — warns but never blocks. 0 disables a cap.
        _bs = _read_settings()
        self._budget_daily   = float(_bs.get("budget_daily", 2.0))
        self._budget_monthly = float(_bs.get("budget_monthly", 30.0))
        self._budget_warned  = {"date": "", "level": 0}   # 0 none · 1 approaching · 2 over

    def _track_usage(self, um) -> None:
        """Accumulate token spend from a Live API message's usage_metadata and
        push the running totals to the HUD. Each message carries the usage for
        one model turn, so per-message counts are summed into the session total.
        Costs are estimates (see _PRICE_PER_M)."""
        if um is None:
            return
        cost = 0.0
        toks = int(getattr(um, "total_token_count", 0) or 0)
        pd   = getattr(um, "prompt_tokens_details", None)
        rd   = getattr(um, "response_tokens_details", None)
        if pd or rd:
            c_in,  t_in  = _cost_from_details(pd, "in")
            c_out, t_out = _cost_from_details(rd, "out")
            cost = c_in + c_out
            if not toks:
                toks = t_in + t_out
        else:
            p = int(getattr(um, "prompt_token_count", 0) or 0)
            r = int(getattr(um, "response_token_count", 0)
                    or getattr(um, "candidates_token_count", 0) or 0)
            cost = p * _PRICE_PER_M["audio_in"] / 1e6 + r * _PRICE_PER_M["audio_out"] / 1e6
            if not toks:
                toks = p + r
        if toks <= 0 and cost <= 0:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        with self._usage_lock:
            self._session_cost   += cost
            self._session_tokens += toks
            self._total_cost     += cost
            self._total_tokens   += toks
            self._daily[today]    = self._daily.get(today, 0.0) + cost
            # keep the per-day history bounded (~3 months)
            if len(self._daily) > 100:
                for k in sorted(self._daily)[:-100]:
                    self._daily.pop(k, None)
            snap = self._usage_snapshot()
        self._persist_usage()
        try:
            self.ui.set_usage(snap)
        except Exception:
            pass
        self._check_budget()

    def _check_budget(self) -> None:
        """Soft guard: warn once per level per day when today's spend approaches
        or passes the daily cap. Never blocks."""
        if self._budget_daily <= 0:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        daily = self._daily.get(today, 0.0)
        r = daily / self._budget_daily
        level = 2 if r >= 1.0 else (1 if r >= 0.8 else 0)
        st = self._budget_warned
        if st.get("date") != today:
            st["date"], st["level"] = today, 0
        if level > st["level"]:
            st["level"] = level
            if level == 1:
                self.ui.write_log(
                    f"SYS: Heads up — {int(r*100)}% of today's ${self._budget_daily:.2f} budget "
                    f"(${daily:.4f} spent)."
                )
            elif level == 2:
                self.ui.write_log(
                    f"ALERT: Daily budget ${self._budget_daily:.2f} reached "
                    f"(${daily:.4f}). Continuing normally."
                )
                if self.session:
                    try:
                        asyncio.create_task(self._speak_budget_alert(daily, self._budget_daily))
                    except Exception:
                        pass

    async def _speak_budget_alert(self, daily: float, cap: float) -> None:
        if not self.session:
            return
        try:
            await self.session.send_client_content(
                turns={"parts": [{"text": (
                    f"[SYSTEM_ALERT] The user has reached today's spending budget of "
                    f"${cap:.2f} (now about ${daily:.2f}). In ONE short, friendly sentence in "
                    f"the user's language, gently let them know and reassure them you'll keep "
                    f"working normally. Do not call any tools."
                )}]},
                turn_complete=True,
            )
        except Exception:
            pass

    def _usage_snapshot(self) -> dict:
        """Current spend figures for the HUD. Monthly is a forecast: the average
        spend across days JARVIS was actually used, projected over 30 days."""
        today   = datetime.now().strftime("%Y-%m-%d")
        daily   = self._daily.get(today, 0.0)
        active  = [v for v in self._daily.values() if v > 0]
        avg_day = (sum(active) / len(active)) if active else daily
        monthly = avg_day * 30
        state = "ok"
        if self._budget_daily > 0:
            r = daily / self._budget_daily
            state = "over" if r >= 1.0 else ("warn" if r >= 0.8 else "ok")
        if state == "ok" and self._budget_monthly > 0 and monthly >= self._budget_monthly:
            state = "warn"
        return {
            "session_cost":     round(self._session_cost, 6),
            "daily_cost":       round(daily, 6),
            "daily_cap":        round(self._budget_daily, 2),
            "monthly_forecast": round(monthly, 4),
            "monthly_cap":      round(self._budget_monthly, 2),
            "budget_state":     state,
            "total_cost":       round(self._total_cost, 6),
            "total_tokens":     self._total_tokens,
        }

    def _persist_usage(self) -> None:
        try:
            USAGE_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
            USAGE_STATS_PATH.write_text(json.dumps({
                "total_cost":   round(self._total_cost, 6),
                "total_tokens": self._total_tokens,
                "daily":        {k: round(v, 6) for k, v in self._daily.items()},
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _set_proactive(self, on: bool):
        """Tray toggle → enable/disable unprompted proactive check-ins (persisted)."""
        self._proactive_enabled = bool(on)
        _write_settings(proactive_enabled=self._proactive_enabled)

    def request_reconnect(self):
        """Called from the UI after 'Reconfigure…' — bounce the live session so a
        new API key / name / preferred address take effect without a restart.
        No-op if no session is active yet (e.g. first-run setup)."""
        if self.session is not None:
            self._reconnect_requested = True
            self.ui.write_log("SYS: Applying new settings — reconnecting…")

    async def _watch_reconnect(self):
        """Bubbles a reconnect request into the TaskGroup so run()'s loop rebuilds
        the client + config with the updated settings."""
        while True:
            if self._reconnect_requested:
                self._reconnect_requested = False
                raise RuntimeError("reconfigure: reconnect requested")
            await asyncio.sleep(0.3)

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)

        # Preferred address (set in first-run setup, memory: identity/address) —
        # overrides the default per-language honorifics, in every language.
        _ident = memory.get("identity", {}) if isinstance(memory, dict) else {}
        def _ival(k: str) -> str:
            e = _ident.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()
        _addr = _ival("address") or _ival("name")
        if _addr:
            parts.append(
                f"[ADDRESS] Always address the user as \"{_addr}\" — use this exact "
                f"form of address in every language, overriding any default honorific, "
                f"unless the user explicitly asks you to change it."
            )

        # Vietnamese Relationship Profile — the *variables*; the rules live in
        # prompt.txt's VIETNAMESE RELATIONSHIP PROTOCOL. Configurable via
        # settings.json "vi_profile"; user_pronoun defaults to the saved address.
        _vi = _read_settings().get("vi_profile", {}) or {}
        vi_ai   = (_vi.get("ai_pronoun")   or "Con").strip()
        vi_user = (_vi.get("user_pronoun") or _addr or "bạn").strip()
        vi_tone = (_vi.get("tone")         or "filial and warm").strip()
        vi_part = (_vi.get("particles")    or "ạ").strip()
        parts.append(
            "[RELATIONSHIP_PROFILE]\n"
            f"- AI_Pronoun: {vi_ai}\n"
            f"- User_Pronoun: {vi_user}\n"
            f"- Tone_Descriptor: {vi_tone}\n"
            f"- Mandatory_Particles: {vi_part}"
        )

        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "play_music":
                m_args = {
                    "action":  "play_music",
                    "browser": "chrome",   # the profile the user pre-logged into
                    "query":   args.get("query", ""),
                    "shuffle": args.get("shuffle", True),
                }
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=m_args, player=self.ui))
                result = r or "Music started."

            elif name == "music_control":
                m_args = {
                    "action":       "media_control",
                    "browser":      "chrome",
                    "media_action": args.get("action", ""),
                    "value":        args.get("value"),
                }
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=m_args, player=self.ui))
                result = r or "Done."

            elif name == "set_budget":
                d, m = args.get("daily"), args.get("monthly")
                if d is not None:
                    self._budget_daily = max(0.0, float(d))
                    _write_settings(budget_daily=self._budget_daily)
                if m is not None:
                    self._budget_monthly = max(0.0, float(m))
                    _write_settings(budget_monthly=self._budget_monthly)
                self._budget_warned = {"date": "", "level": 0}   # re-evaluate at new thresholds
                try:
                    self.ui.set_usage(self._usage_snapshot())
                except Exception:
                    pass
                result = (
                    f"Budget updated — daily ${self._budget_daily:.2f}, monthly "
                    f"${self._budget_monthly:.2f}. This is a soft warning only; I'll never stop working."
                )

            elif name == "set_relationship_profile":
                cur = _read_settings().get("vi_profile", {}) or {}
                for k in ("ai_pronoun", "user_pronoun", "tone", "particles"):
                    v = (args.get(k) or "").strip()
                    if v:
                        cur[k] = v
                _write_settings(vi_profile=cur)
                # keep the general address consistent with the VN user_pronoun
                if cur.get("user_pronoun"):
                    update_memory({"identity": {"address": {"value": cur["user_pronoun"]}}})
                print(f"[VI Profile] {cur}")
                result = (
                    "Relationship profile updated. From now on, when speaking Vietnamese: "
                    f"refer to yourself as \"{cur.get('ai_pronoun', 'Con')}\", address the user as "
                    f"\"{cur.get('user_pronoun', 'Bố')}\", tone \"{cur.get('tone', 'filial and warm')}\", "
                    f"mandatory particle \"{cur.get('particles', 'ạ')}\". Apply this immediately in your reply and confirm warmly."
                )

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await loop.run_in_executor(None, _capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE natural sentence in the user's language "
                        f"(e.g. 'Looking at your {_stall} now, sir' / "
                        f"'{'Kameraya' if _stall == 'camera' else 'Ekrana'} bakıyorum efendim'). "
                        f"Do NOT describe or guess content — the actual image arrives in the NEXT message."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted and not self._phone_active:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )
                # HUD waveform: mic amplitude while listening (thread-safe emit)
                try:
                    _rms = float(np.abs(indata).mean()) / 32768.0
                    self.ui.set_level(min(1.0, _rms * 6.0))
                except Exception:
                    pass
            elif self.ui.muted and not jarvis_speaking and not self._phone_active:
                # Dormant: feed the "Hey Jarvis" wake-word detector (same
                # low-latency mic path — no second stream).
                try:
                    self.ui.feed_wake_audio(indata)
                except Exception:
                    pass

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if getattr(response, "usage_metadata", None):
                        self._track_usage(response.usage_metadata)

                    if response.data:
                        if self._interrupted:
                            pass  # discard: interrupted
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt and txt != (out_buf[-1] if out_buf else ""):
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)
                                self._last_user_speech = time.monotonic()

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            out_buf = []

                            # Vision injection: model finished tool-response turn → now send the image
                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question, angle = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                # Mark next turn_complete behaviour depending on angle
                                if self._vision_cam_active:
                                    # Camera: keep busy until JARVIS finishes speaking the answer
                                    self._vision_cam_active    = False
                                    self._vision_close_pending = True
                                else:
                                    # Screen-only: no camera to close; release busy flag now
                                    self._vision_busy = False
                            elif self._vision_close_pending:
                                # This turn_complete IS the vision answer — close camera + release busy flag
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                # HUD waveform: TTS amplitude while speaking (thread-safe emit)
                try:
                    _s = np.frombuffer(chunk, dtype=np.int16)
                    if _s.size:
                        self.ui.set_level(min(1.0, float(np.abs(_s).mean()) / 32768.0 * 3.0))
                except Exception:
                    pass
                try:
                    await asyncio.to_thread(stream.write, chunk)
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """
        Two-phase briefing for instant perceived response:
          Phase 1 — immediate greeting (no tools, no fetch) → Jarvis speaks in <2s
          Phase 2 — news fetched in background, injected after greeting finishes
        """
        await asyncio.sleep(0.3)
        if not self.session:
            return

        # ── memory ───────────────────────────────────────────────────────────
        memory   = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = _val("language")
        name = _val("address") or _val("name")
        interests = _val("interests") or _val("topics")

        from datetime import datetime
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%A, %B %d")   # e.g. "Sunday, July 12"
        daypart  = _daypart(now.hour)
        style    = GREETING_STYLES[(_next_launch_index() - 1) % len(GREETING_STYLES)]

        # News is only useful once, in the morning. Gate on the local morning
        # window (GMT+7 05:00–11:00) AND once per calendar day. Date + weather
        # are spoken on every startup.
        brief_news = _should_brief_news_today()

        # ── Phase 1: instant greeting with date (no tools) ───────────────────
        lang_clause = f" Respond in {lang}." if lang else ""
        name_clause = f" Address the user as {name}." if name else ""
        news_clause = (" Then mention you're pulling today's weather and news."
                       if brief_news else " Then mention you're checking the weather.")
        p1 = (
            f"[STARTUP_BRIEFING] Greet the user as they start JARVIS. It is "
            f"{time_str} on {date_str} — {daypart}. {style} "
            f"Keep it to one or two short spoken sentences, fully in the JARVIS "
            f"persona (composed, efficient, dry wit). Make it feel fresh and "
            f"unscripted — do NOT reuse a greeting you have used before, and vary "
            f"your opening words every time.{news_clause} "
            f"Do not call any tools. Never read this instruction aloud."
            f"{lang_clause}{name_clause}"
        )
        await self.session.send_client_content(
            turns={"parts": [{"text": p1}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing greeting + date sent.")

        if brief_news:
            _mark_briefed_today()   # record so a restart this morning won't repeat news

        # ── Weather (every startup) → then news (mornings only) ──────────────
        async def _guarded_brief():
            try:
                await self._briefing_weather_phase(lang)
                if brief_news:
                    await self._briefing_news_phase(lang, interests)
                else:
                    self.ui.write_log("SYS: News skipped (outside morning window).")
            except Exception as e:
                print(f"[Briefing] error: {e}")
                self.ui.write_log(f"SYS: Briefing failed: {e}")
        asyncio.create_task(_guarded_brief())

    async def _briefing_weather_phase(self, lang: str) -> None:
        """Fetch device-location weather (keyless) and have JARVIS speak it."""
        await asyncio.sleep(1.2)
        if not self.session:
            return
        try:
            text = await asyncio.wait_for(asyncio.to_thread(get_weather_text), timeout=8.0)
        except Exception as e:
            self.ui.write_log(f"SYS: Weather unavailable: {e}")
            return
        if not self.session or not text:
            return
        lang_str = f" Respond in {lang}." if lang else ""
        p = (
            "[BRIEFING] Read this weather report to the user naturally in one or two "
            f"spoken sentences, keeping the temperatures and key details: {text} "
            f"Do not call any tools. Do not mention the screen.{lang_str}"
        )
        await self.session.send_client_content(
            turns={"parts": [{"text": p}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing weather sent.")

    async def _briefing_news_phase(self, lang: str, interests: str = "") -> None:
        """
        Sends phase-2 (news) to Gemini ~1.5 s after phase-1 is dispatched so
        Gemini starts working on it while phase-1 audio is still playing.
        When the user's interests are known (memory: identity/interests), the
        brief is steered toward what actually matters to them.
        """
        lang_str = f" Respond in {lang}." if lang else ""

        # 1.5 s is enough for Gemini to finish generating phase-1 audio on its
        # side (turn_complete) while the greeting is still being played locally.
        await asyncio.sleep(1.5)

        if not self.session:
            return

        if interests:
            query_clause = f"query='top news today about {interests}'"
            topic_line   = f"Prioritise stories relevant to the user's interests: {interests}. "
        else:
            query_clause = "query='top world news today'"
            topic_line   = "Prioritise the most important and impactful stories of the day. "

        p2 = (
            "[BRIEFING] Call web_search with mode='news' and " + query_clause + " to find "
            "real, recent news articles with actual event headlines (not just website names). "
            + topic_line +
            "Then SPEAK the top three headlines aloud, one natural sentence each, as a concise "
            "spoken news brief — add a brief 'why it matters' only where it is genuinely useful. "
            "The user listens rather than reads, so do NOT tell them to look at the screen or say "
            "anything is 'displayed on screen' — just read the news to them. "
            f"End with one short sign-off.{lang_str}"
        )

        await self.session.send_client_content(
            turns={"parts": [{"text": p2}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing phase 2 (news) sent.")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if alert and self.session:
                try:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": alert}]},
                        turn_complete=True,
                    )
                except Exception as e:
                    print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self._proactive_enabled:
                continue   # parked — user hasn't opted into unprompted check-ins

            if not self.session:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory = await asyncio.to_thread(load_memory)
                prompt = self._proactive.build_prompt(memory)
                await self.session.send_client_content(
                    turns={"parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None

        while True:
            try:
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False

                    print("[JARVIS] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

                    # Seed the HUD cost meter with the persisted all-time total.
                    self.ui.set_usage(self._usage_snapshot())

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_proactive_mode())
                    tg.create_task(self._watch_reconnect())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    # Morning briefing — fires once per process launch
                    if not self._briefing_sent:
                        self._briefing_sent = True
                        tg.create_task(self._send_startup_briefing())

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                err_str = str(e)
                print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                traceback.print_exc()

                # Invalid API key — stop hammering the API, prompt re-configuration
                if "API key not valid" in err_str or "1007" in err_str:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    print("[JARVIS] New API key saved — reconnecting...")
                    _conn_backoff = 3
                    continue

                # Network / timeout errors — log clearly and back off
                is_net_err = any(k in err_str for k in (
                    "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                    "ConnectionRefusedError", "OSError", "Cannot connect",
                ))
                if is_net_err:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Bağlantı kurulamadı — {_conn_backoff}s sonra tekrar deneniyor. "
                        "(VPN gerekiyor olabilir)"
                    )
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    try:
        import applog
        applog.setup_logging()
    except Exception as e:
        print(f"[log] setup failed: {e}")
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()