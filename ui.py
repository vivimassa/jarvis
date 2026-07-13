"""
ui.py — web HUD host.

Replaces the hand-painted PyQt HUD with a QWebEngineView that renders
hud/jarvis_hud.html (the design source of truth), driven from Python.

main.py talks to the UI ONLY through the JarvisUI facade below; every
method/property/callback name from the original ui.py is preserved, so
main.py and all actions/ modules are untouched. The one addition is
`set_level(float)` (upstream had no audio-level meter).

Threading: telemetry (Monitor) and audio levels arrive on background
threads. They are marshalled to the Qt main thread via signals before any
runJavaScript call — never touch the page off-thread.
"""

import os
import sys
import time
import json
import base64
import threading
from pathlib import Path

# Enable Chromium transparent compositing BEFORE QtWebEngine initialises — needed
# for the mini reactor's see-through background on Windows.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-transparent-visuals")

from PyQt6.QtCore import (
    Qt, QObject, pyqtSignal, pyqtSlot, QUrl, QTimer, QSettings, QAbstractNativeEventFilter,
)
import ctypes
try:
    from ctypes import wintypes
except Exception:
    wintypes = None
from PyQt6.QtGui import QCursor, QColor
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel

# Reuse the API-key setup panel from the original UI. Paths come from paths.py.
# SetupOverlay's internal references (C palette, _OS) resolve inside the
# ui_legacy module namespace, so importing the class is enough.
from ui_legacy import SetupOverlay
import paths
from paths import CONFIG_DIR, API_FILE, HUD_HTML

import jarvis_monitor

# main.py's set_state vocabulary → the HUD's five states.
_STATE_MAP = {
    "LISTENING": "listening",
    "THINKING":  "thinking",
    "SPEAKING":  "speaking",
    "SLEEPING":  "idle",
    "MUTED":     "idle",
}

# Alert thresholds (decided in Python, per the brief).
_CPU_TEMP_ALERT = 90.0
_MEM_ALERT = 92.0

# Wake-word ("Jarvis") session: dormant until the word, then an active
# listening window that stays open during conversation and closes after silence.
_LISTEN_TIMEOUT_MS = 12000      # go dormant after this much quiet
_LISTEN_ACTIVITY_LEVEL = 0.08   # mic level that counts as "still talking"


def _classify_log(text: str):
    """Map an upstream write_log() string to the HUD's (who, text)."""
    for prefix, who in (
        ("You:", "you"), ("Jarvis:", "jarvis"), ("JARVIS:", "jarvis"),
        ("ERR:", "alert"), ("SYS:", "sys"), ("[Web]:", "sys"), ("ALERT:", "alert"),
    ):
        if text.startswith(prefix):
            return who, text[len(prefix):].strip()
    return "sys", text


class _Bridge(QObject):
    """JS → Python. Registered on the QWebChannel as `jarvis`."""

    def __init__(self, win: "_WebWindow"):
        super().__init__()
        self._win = win

    @pyqtSlot(str)
    def command(self, text: str):
        cb = self._win.on_text_command
        text = (text or "").strip()
        if cb and text:
            threading.Thread(target=cb, args=(text,), daemon=True).start()

    @pyqtSlot()
    def interrupt(self):
        # Same call path the old UI used (GUI thread → JarvisLive.interrupt()).
        cb = self._win.on_interrupt
        if cb:
            cb()

    @pyqtSlot()
    def exitMini(self):
        # Double-click on the mini reactor → restore the full HUD.
        self._win.exit_mini()

    @pyqtSlot()
    def resizeBegin(self):
        self._win.resize_begin()

    @pyqtSlot()
    def resizeMove(self):
        self._win.resize_move()

    @pyqtSlot()
    def resizeEnd(self):
        self._win.resize_end()

    @pyqtSlot(int)
    def resizeStep(self, direction: int):
        self._win.resize_step(direction)

    # frameless-window drag — the header reports intent; we move the window
    # using Qt's own global cursor position (DPI-safe).
    @pyqtSlot()
    def dragBegin(self):
        self._win._drag = (QCursor.pos(), self._win.pos())

    @pyqtSlot()
    def dragMove(self):
        if self._win._drag:
            start_cur, start_win = self._win._drag
            self._win.move(start_win + (QCursor.pos() - start_cur))


class _HudPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        # Keep JS console noise out of stdout; uncomment to debug the HUD.
        # print(f"[HUD] {message} ({source}:{line})")
        pass


class _HotkeyFilter(QAbstractNativeEventFilter):
    """Catches WM_HOTKEY from the Windows message loop (for the global summon key)."""
    _WM_HOTKEY = 0x0312

    def __init__(self, hotkey_id: int, callback):
        super().__init__()
        self._id = hotkey_id
        self._cb = callback

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG" and wintypes is not None:
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == self._WM_HOTKEY and msg.wParam == self._id:
                    self._cb()
        except Exception:
            pass
        return False, 0


class _WebWindow(QMainWindow):
    # All cross-thread updates funnel through these signals (→ GUI thread slots).
    _state_sig   = pyqtSignal(str)
    _level_sig   = pyqtSignal(float)
    _log_sig     = pyqtSignal(str, str)   # who, text
    _tele_sig    = pyqtSignal(dict)
    _content_sig = pyqtSignal(str, str)
    _reconfig_sig = pyqtSignal()
    _camera_sig  = pyqtSignal(bytes)
    _camshow_sig = pyqtSignal(bool)
    _wake_sig    = pyqtSignal()     # "Jarvis" heard (from the wake-word thread)
    _wake_ready_sig = pyqtSignal(object, str)  # (detector|None, error) from the loader thread
    _usage_sig   = pyqtSignal(dict)  # API token/cost meter → HUD

    def __init__(self, face_path=None):
        super().__init__()
        self.on_text_command = None
        self.on_remote_clicked = None
        self.on_interrupt = None
        self.on_reconfigure = None   # called after settings change → live reconnect
        self.on_proactive_toggle = None  # enable/disable unprompted check-ins

        self._muted = True             # dormant until "Jarvis" (wake word)
        self._ready = self._check_config()
        self._loaded = False
        self._pending = []
        self._session_state = "idle"   # last non-alert state, for alert revert
        self._drag = None
        self._overlay = None
        self._cam_stop = threading.Event()
        self._wake = None              # WakeWordListener (started after load)
        self._hard_muted = False       # tray "Mute microphone" (fully deaf)
        self._quitting = False         # True only on tray Quit (else close→tray)
        self._mini = False             # mini reactor mode (transparent floating widget)
        self._normal_geo = None        # saved full-HUD geometry, for restore
        self._mini_size = 240          # current mini-reactor size (persisted)

        self.setWindowTitle("J.A.R.V.I.S")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        self._settings = QSettings("JARVIS", "HUD")
        geo = self._settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1180, 720)

        # web view + page
        self.view = QWebEngineView(self)
        self._page = _HudPage(self.view)
        self.view.setPage(self._page)
        s = self._page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.setCentralWidget(self.view)

        # Translucency must be set at construction — QtWebEngine won't convert a
        # live surface to transparent later (that showed a black box). The page
        # paints transparent; the HTML's solid body background keeps the normal
        # HUD opaque, and mini mode drops that background to reveal the desktop.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._page.setBackgroundColor(QColor(0, 0, 0, 0))

        # JS bridge
        self._channel = QWebChannel(self._page)
        self._bridge = _Bridge(self)
        self._channel.registerObject("jarvis", self._bridge)
        self._page.setWebChannel(self._channel)

        self.view.loadFinished.connect(self._on_load)
        self.view.load(QUrl.fromLocalFile(HUD_HTML))

        # signal → JS slots (run on GUI thread)
        self._state_sig.connect(self._js_state)
        self._level_sig.connect(self._js_level)
        self._log_sig.connect(self._js_log)
        self._tele_sig.connect(self._js_tele)
        self._content_sig.connect(lambda t, x: self._js_log("sys", f"{t} — {x}"))
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._js_camera)
        self._camshow_sig.connect(lambda on: None if on else self._run_js("hideCamera()"))

        # alert auto-revert
        self._alert_timer = QTimer(self)
        self._alert_timer.setSingleShot(True)
        self._alert_timer.timeout.connect(
            lambda: self._run_js(f"setState({json.dumps(self._session_state)})"))

        # telemetry sampler (daemon thread → _tele_sig)
        self._monitor = jarvis_monitor.Monitor(on_sample=self._tele_sig.emit).start()

        # wake-word ("Jarvis") session: dormant → active → dormant
        self._wake_sig.connect(self._activate_listening)
        self._wake_ready_sig.connect(self._on_wake_ready)
        self._wake_loading = False
        self._usage_sig.connect(self._js_usage)
        self._listen_timer = QTimer(self)
        self._listen_timer.setSingleShot(True)
        self._listen_timer.timeout.connect(self._deactivate_listening)

        self._setup_tray()
        self._register_global_hotkey()

        if not self._ready:
            QTimer.singleShot(0, self._show_setup)
        else:
            QTimer.singleShot(0, self._start_wake_word)

    # ---- page / JS plumbing -------------------------------------------------
    def _run_js(self, js: str):
        if self._loaded:
            self._page.runJavaScript(js)
        else:
            self._pending.append(js)

    def _on_load(self, ok: bool):
        self._loaded = True
        for js in self._pending:
            self._page.runJavaScript(js)
        self._pending.clear()
        self._run_js(f"setState({json.dumps(self._session_state)})")

    def _js_state(self, state: str):
        m = _STATE_MAP.get(state, state)
        if m not in ("idle", "listening", "thinking", "speaking", "alert"):
            return
        # Dormant (waiting for "Jarvis"): show standby for listening/thinking,
        # but let JARVIS's own speech (briefing/replies) still read as speaking.
        if self._muted and m in ("listening", "thinking"):
            m = "idle"
        if m != "alert":
            self._session_state = m
        # any real activity keeps an active session alive
        if not self._muted and m in ("thinking", "speaking", "listening"):
            self._listen_timer.start(_LISTEN_TIMEOUT_MS)
        self._run_js(f"setState({json.dumps(m)})")

    def _js_level(self, v: float):
        v = max(0.0, min(1.0, v))
        # while actively listening, ongoing speech refreshes the session window
        if not self._muted and v >= _LISTEN_ACTIVITY_LEVEL:
            self._listen_timer.start(_LISTEN_TIMEOUT_MS)
        self._run_js(f"setLevel({v:.3f})")

    def _js_log(self, who: str, text: str):
        self._run_js(f"log({json.dumps(who)},{json.dumps(text)})")

    def _js_tele(self, d: dict):
        self._run_js(f"telemetry({json.dumps(d)})")
        breach = ((d.get("cputemp") is not None and d["cputemp"] > _CPU_TEMP_ALERT) or
                  (d.get("mem") is not None and d["mem"] > _MEM_ALERT))
        if breach:
            self._run_js("setState('alert')")
            self._alert_timer.start(4000)

    def _js_usage(self, d: dict):
        self._run_js(f"usage({json.dumps(d)})")

    def _js_camera(self, jpeg: bytes):
        b64 = base64.b64encode(jpeg).decode("ascii")
        self._run_js(f"showCamera('data:image/jpeg;base64,{b64}')")

    # ---- mute ---------------------------------------------------------------
    def toggle_mute(self):
        self._muted = not self._muted
        if self._muted:
            self._log_sig.emit("sys", "Microphone muted.")
            self._state_sig.emit("MUTED")
        else:
            self._log_sig.emit("sys", "Microphone active.")
            self._state_sig.emit("LISTENING")

    # ---- wake word ("Hey Jarvis", openWakeWord — no key) -------------------
    def _start_wake_word(self):
        # The openWakeWord model download (~6 MB first run) + ONNX load is slow
        # and MUST NOT run on the Qt GUI thread — it would freeze the HUD while
        # it paints. Build the detector on a worker thread and marshal the
        # finished object back via _wake_ready_sig.
        if self._wake is not None or self._wake_loading:
            return
        self._wake_loading = True
        self._js_log("sys", "Bringing my senses online…")

        def _build():
            det, err = None, ""
            try:
                from wake_word import WakeWordDetector
                det = WakeWordDetector(on_wake=self._wake_sig.emit)
            except Exception as e:
                err = str(e)
            self._wake_ready_sig.emit(det, err)

        threading.Thread(target=_build, daemon=True, name="wake-word-init").start()

    def _on_wake_ready(self, det, err: str):
        # Runs on the GUI thread once the worker finishes loading the model.
        self._wake_loading = False
        if det is not None:
            self._wake = det
            det.set_enabled(True)          # dormant → listening for the phrase
            # respect a tray hard-mute that may have been toggled while loading
            if self._hard_muted:
                det.set_enabled(False)
            self._js_log("sys", "Standing by. Say 'Hey Jarvis' to wake me.")
        else:
            # If the detector can't start, fall back to always-listening so the
            # app stays usable rather than being stuck dormant.
            self._wake = None
            self._muted = False
            self._js_log("alert", f"Wake word unavailable ({err}); always listening.")
            self._state_sig.emit("LISTENING")

    def feed_wake_audio(self, indata):
        """Called from main.py's mic callback while dormant (16 kHz mono int16)."""
        if self._wake is None:
            return
        try:
            self._wake.feed(indata.tobytes() if hasattr(indata, "tobytes") else bytes(indata))
        except Exception:
            pass

    def _activate_listening(self):
        # runs on the GUI thread (via _wake_sig)
        if self._hard_muted:
            return                      # tray-muted: ignore wake entirely
        if not self._muted:
            self._listen_timer.start(_LISTEN_TIMEOUT_MS)
            return
        self._muted = False
        if self._wake:
            self._wake.set_enabled(False)   # stop wake detection while active
        self._js_log("sys", "Listening…")
        self._session_state = "listening"
        self._run_js("setState('listening')")
        self._listen_timer.start(_LISTEN_TIMEOUT_MS)

    def _deactivate_listening(self):
        if self._muted:
            return
        self._muted = True
        if self._wake:
            self._wake.set_enabled(True)    # resume waiting for "Hey Jarvis"
        self._session_state = "idle"
        self._js_log("sys", "Standing by. Say 'Hey Jarvis' to wake me.")
        self._run_js("setState('idle')")

    # ---- global summon hotkey (Ctrl+Alt+J) ---------------------------------
    def _register_global_hotkey(self):
        """System-wide Ctrl+Alt+J to summon/dismiss JARVIS without the wake word.
        Ctrl+Alt+J is chosen over Ctrl+J because a global hotkey grabs the combo
        from every app — Ctrl+J is already used by browsers/editors."""
        if sys.platform != "win32" or wintypes is None:
            return
        try:
            MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
            VK_J = 0x4A
            self._hk_id = 1
            self._hk_hwnd = None
            self._hk_filter = _HotkeyFilter(self._hk_id, self._hotkey_summon)
            QApplication.instance().installNativeEventFilter(self._hk_filter)
            hwnd = int(self.winId())
            mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
            if ctypes.windll.user32.RegisterHotKey(hwnd, self._hk_id, mods, VK_J):
                self._hk_hwnd = hwnd
            else:
                self._js_log("sys", "Ctrl+Alt+J hotkey unavailable (already in use).")
        except Exception as e:
            print(f"[Hotkey] register failed: {e}")

    def _hotkey_summon(self):
        """Toggle summon (activate listening) / dismiss — runs on the GUI thread."""
        if self._hard_muted:
            self._js_log("sys", "Mic is tray-muted — unmute to use Ctrl+Alt+J.")
            return
        if self._muted:
            self._activate_listening()
            if not self.isVisible():
                self.showNormal(); self.raise_()
        else:
            self._deactivate_listening()

    def _unregister_global_hotkey(self):
        try:
            if getattr(self, "_hk_hwnd", None) is not None:
                ctypes.windll.user32.UnregisterHotKey(self._hk_hwnd, self._hk_id)
                self._hk_hwnd = None
        except Exception:
            pass

    # ---- mini reactor mode --------------------------------------------------
    _MINI_MIN, _MINI_MAX = 140, 620

    def _settings_read(self) -> dict:
        try:
            return json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _settings_write(self, **kw):
        try:
            p = paths.SETTINGS_FILE
            p.parent.mkdir(parents=True, exist_ok=True)
            st = self._settings_read()
            st.update(kw)
            p.write_text(json.dumps(st, indent=2), encoding="utf-8")
        except Exception:
            pass

    def toggle_mini(self):
        self.exit_mini() if self._mini else self.enter_mini()

    def enter_mini(self):
        """Shrink to the transparent, always-on-top, drag-anywhere reactor.
        Transparency is already live (set at construction); mini mode just drops
        the CSS background and floats the window."""
        if self._mini:
            return
        self._mini = True
        self._normal_geo = self.saveGeometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._run_js("setMini(true)")
        size = self._settings_read().get("mini_size", 240)
        size = max(self._MINI_MIN, min(self._MINI_MAX, int(size)))
        self._mini_size = size
        geo = self.geometry()
        self.setGeometry(geo.x(), geo.y(), size, size)
        self.show()          # required after changing window flags
        self.raise_()

    # -- resize the mini reactor (drag its outer ring, or scroll) --
    def resize_begin(self):
        self._rz_cursor = QCursor.pos()
        g = self.geometry()
        self._rz_size = g.width()
        self._rz_center = g.center()

    def resize_move(self):
        if not self._mini:
            return
        cur = QCursor.pos()
        d = (cur.x() - self._rz_cursor.x()) + (cur.y() - self._rz_cursor.y())
        size = max(self._MINI_MIN, min(self._MINI_MAX, self._rz_size + d))
        c = self._rz_center
        self.setGeometry(c.x() - size // 2, c.y() - size // 2, size, size)
        self._mini_size = size

    def resize_end(self):
        self._settings_write(mini_size=int(getattr(self, "_mini_size", 240)))

    def resize_step(self, direction: int):
        if not self._mini:
            return
        g = self.geometry()
        c = g.center()
        step = 24 if direction > 0 else -24
        size = max(self._MINI_MIN, min(self._MINI_MAX, g.width() + step))
        self.setGeometry(c.x() - size // 2, c.y() - size // 2, size, size)
        self._mini_size = size
        self._settings_write(mini_size=int(size))

    def exit_mini(self):
        """Restore the full HUD (CSS background comes back → opaque again)."""
        if not self._mini:
            return
        self._mini = False
        self._run_js("setMini(false)")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        if self._normal_geo is not None:
            self.restoreGeometry(self._normal_geo)
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- camera preview (vision) -------------------------------------------
    def start_camera_stream(self):
        self._cam_stop.clear()
        threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream").start()

    def _cam_loop(self):
        try:
            import cv2
            cam_idx = 0
            try:
                cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    if ok:
                        self._camera_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] stream error: {e}")
        finally:
            self._camshow_sig.emit(False)

    def stop_camera_stream(self):
        self._cam_stop.set()
        self._camshow_sig.emit(False)

    # ---- first-run / reconfigure key setup ---------------------------------
    def _check_config(self) -> bool:
        if not API_FILE.exists():
            return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self, prefill: bool = False):
        ov = SetupOverlay()
        ov.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        ow, oh = 470, 420
        c = self.geometry().center()
        ov.setGeometry(c.x() - ow // 2, c.y() - oh // 2, ow, oh)
        if prefill:
            self._prefill_setup(ov)
        ov.done.connect(self._on_setup_done)
        ov.show()
        ov.raise_()
        ov.activateWindow()
        self._overlay = ov

    def _prefill_setup(self, ov):
        """Seed the wizard with current key/OS + saved name/address."""
        key = os_name = name = address = ""
        try:
            cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
            key = cfg.get("gemini_api_key", "")
            os_name = cfg.get("os_system", "")
        except Exception:
            pass
        try:
            from memory.memory_manager import load_memory
            ident = load_memory().get("identity", {})

            def _v(k):
                e = ident.get(k, {})
                return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

            name, address = _v("name"), _v("address")
        except Exception:
            pass
        ov.prefill(name=name, address=address, key=key, os_name=os_name)

    def _on_setup_done(self, key: str, os_name: str, name: str = "", address: str = ""):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        # merge, so we don't clobber camera_index etc. written elsewhere
        data = {}
        try:
            data = json.loads(API_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.update({"gemini_api_key": key, "os_system": os_name})
        API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")

        # Persist name + preferred address into memory so the greeting and every
        # reply address the user the way they asked (see main._build_config).
        try:
            from memory.memory_manager import update_memory
            ident = {}
            if name:
                ident["name"] = {"value": name}
            if address:
                ident["address"] = {"value": address}
            if ident:
                update_memory({"identity": ident})
        except Exception as e:
            print(f"[Setup] could not save identity: {e}")

        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        self._js_log("sys", f"Initialised. OS={os_name.upper()}. JARVIS online.")
        self._start_wake_word()

        # Apply the new settings to a running session (tray 'Reconfigure…').
        # No-ops on first-run when no session exists yet.
        if self.on_reconfigure:
            try:
                self.on_reconfigure()
            except Exception:
                pass

    # ---- system tray --------------------------------------------------------
    def _setup_tray(self):
        from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
        from PyQt6.QtGui import QIcon
        icon = QIcon(paths.ICON_PATH)
        self.setWindowIcon(icon)
        app = QApplication.instance()
        self._tray = QSystemTrayIcon(icon, app)
        self._tray.setToolTip("J.A.R.V.I.S — online")
        menu = QMenu()
        menu.addAction("Show / Hide HUD", self._toggle_visible)
        menu.addAction("Mini reactor", self.toggle_mini)
        self._mute_action = menu.addAction("Mute microphone", self._toggle_mute_tray)
        self._mute_action.setCheckable(True)
        self._proactive_action = menu.addAction("Proactive check-ins", self._toggle_proactive_tray)
        self._proactive_action.setCheckable(True)
        self._proactive_action.setChecked(self._read_proactive_setting())
        menu.addAction("Reconfigure…", lambda: self._show_setup(prefill=True))
        menu.addAction("Open logs", self._open_logs)
        menu.addSeparator()
        menu.addAction("Quit JARVIS", self._quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.show()

    def _tray_activated(self, reason):
        from PyQt6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    def _toggle_visible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def surface(self):
        """Bring the HUD to the front (used when a second instance is launched)."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_mute_tray(self, checked: bool):
        self._hard_muted = checked
        if checked:
            self._muted = True
            if self._wake:
                self._wake.set_enabled(False)   # fully deaf — actually stop feeding
            self._tray.setToolTip("J.A.R.V.I.S — muted")
            self._session_state = "idle"
            self._run_js("setState('idle')")
            self._js_log("sys", "Microphone muted.")
        else:
            self._muted = True                  # back to dormant
            if self._wake:
                self._wake.set_enabled(True)
            self._tray.setToolTip("J.A.R.V.I.S — online")
            self._run_js("setState('idle')")
            self._js_log("sys", "Microphone on. Say 'Hey Jarvis'.")

    def _read_proactive_setting(self) -> bool:
        try:
            return bool(json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8"))
                        .get("proactive_enabled", False))
        except Exception:
            return False

    def _toggle_proactive_tray(self, checked: bool):
        # persist so the choice survives restarts, and notify the live session
        try:
            p = paths.SETTINGS_FILE
            p.parent.mkdir(parents=True, exist_ok=True)
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                st = {}
            st["proactive_enabled"] = bool(checked)
            p.write_text(json.dumps(st, indent=2), encoding="utf-8")
        except Exception:
            pass
        if self.on_proactive_toggle:
            try:
                self.on_proactive_toggle(bool(checked))
            except Exception:
                pass
        self._js_log("sys", f"Proactive check-ins {'enabled' if checked else 'off — on-demand only'}.")

    def _open_logs(self):
        try:
            os.startfile(str(paths.LOGS_DIR))   # noqa (Windows)
        except Exception:
            pass

    def _quit(self):
        self._quitting = True
        self._cleanup()
        try:
            self._tray.hide()
        except Exception:
            pass
        QApplication.instance().quit()
        # hard backstop so no QtWebEngineProcess / mic lingers
        QTimer.singleShot(1500, lambda: os._exit(0))

    # ---- lifecycle ----------------------------------------------------------
    def _cleanup(self):
        try:
            self._settings.setValue("geometry", self.saveGeometry())
        except Exception:
            pass
        self._unregister_global_hotkey()
        for stop in (getattr(self, "_monitor", None), getattr(self, "_wake", None)):
            try:
                if stop:
                    stop.stop()
            except Exception:
                pass
        try:
            self._cam_stop.set()
        except Exception:
            pass

    def closeEvent(self, event):
        # Closing the window hides to tray; only tray Quit exits.
        if not self._quitting:
            event.ignore()
            self.hide()
            try:
                self._tray.showMessage(
                    "J.A.R.V.I.S", "Still running. Right-click the tray icon to quit.",
                    msecs=2500)
            except Exception:
                pass
            return
        self._cleanup()
        super().closeEvent(event)


class _RootShim:
    """Minimal Tk-compatible shim (the old UI mimicked a Tk root object)."""
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


class JarvisUI:
    """Facade — identical surface to the original ui.JarvisUI, plus set_level()."""

    def __init__(self, face_path=None, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._app.setQuitOnLastWindowClosed(False)   # closing the HUD hides to tray
        self._enforce_single_instance()              # exits if already running
        self._win = _WebWindow(face_path)
        if getattr(self, "_srv", None) is not None:
            self._srv.newConnection.connect(self._on_second_instance)
        self._win.show()
        self.root = _RootShim(self._app)

    _SINGLETON = "JARVIS_singleton_v1"

    def _enforce_single_instance(self):
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket
        probe = QLocalSocket()
        probe.connectToServer(self._SINGLETON)
        if probe.waitForConnected(250):
            # Another JARVIS is running — ask it to surface, then exit.
            try:
                probe.write(b"show")
                probe.flush()
                probe.waitForBytesWritten(300)
            finally:
                probe.abort()
            os._exit(0)
        probe.abort()
        QLocalServer.removeServer(self._SINGLETON)   # clear any stale socket
        self._srv = QLocalServer()
        if not self._srv.listen(self._SINGLETON):
            self._srv = None

    def _on_second_instance(self):
        try:
            sock = self._srv.nextPendingConnection()
            if sock:
                sock.readAll()
                sock.disconnectFromServer()
        except Exception:
            pass
        self._win.surface()

    # -- properties --
    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win.toggle_mute()

    @property
    def current_file(self):
        return None   # drag-drop attach not in the web HUD (Phase 1)

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_reconfigure(self):
        return self._win.on_reconfigure

    @on_reconfigure.setter
    def on_reconfigure(self, cb):
        self._win.on_reconfigure = cb

    @property
    def on_proactive_toggle(self):
        return self._win.on_proactive_toggle

    @on_proactive_toggle.setter
    def on_proactive_toggle(self, cb):
        self._win.on_proactive_toggle = cb

    # -- inbound methods (main.py → UI) --
    def notify_phone_connected(self):
        self._win._log_sig.emit("sys", "Phone connected via Remote Dashboard.")

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_level(self, value: float):
        """NEW: audio amplitude 0..1 → HUD waveform. Fed from main.py's mic and
        TTS taps (see _listen_audio / _play_audio)."""
        try:
            self._win._level_sig.emit(float(value))
        except Exception:
            pass

    def set_usage(self, data: dict):
        """API token/cost meter → HUD. Fed from main.py's usage tracker."""
        try:
            self._win._usage_sig.emit(dict(data))
        except Exception:
            pass

    def write_log(self, text: str):
        who, msg = _classify_log(text)
        self._win._log_sig.emit(who, msg)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        self._win._content_sig.emit(str(title)[:48], str(text)[:4000])

    def prompt_reconfig(self):
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def feed_wake_audio(self, indata):
        """Route dormant-mode mic frames to the wake-word detector (from main.py)."""
        self._win.feed_wake_audio(indata)

    def show_camera_frame(self, img_bytes: bytes):
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self):
        self._win.start_camera_stream()

    def stop_camera_stream(self):
        self._win.stop_camera_stream()

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
