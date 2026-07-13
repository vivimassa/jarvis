# JARVIS — Implementation Brief

Build spec for Claude Code. Personal, single-machine, non-commercial project.

## What this is

A fork of [FatihMakes/Mark-XLVIII](https://github.com/FatihMakes/Mark-XLVIII) — a
voice assistant built on the Gemini Live API (PyQt6 UI, Python 3.11/3.12,
Windows target). The upstream logic is good; the UI is not. This project:

1. Replaces the PyQt-painted UI with a web-based HUD (`jarvis_hud.html`,
   provided) rendered in a `QWebEngineView`.
2. Adds real telemetry (`jarvis_monitor.py`, provided): CPU/GPU load, CPU/GPU
   temperature, network throughput.
3. Adds a startup briefing: date, weather, news.
4. Ships as a double-clickable `.exe` with a system tray icon.
5. Autostarts 30 seconds after Windows logon.

Everything the upstream repo does — voice, system control, vision, memory,
reminders, web search, interrupt — must keep working. This is a re-skin plus
packaging, not a rewrite.

## Ground rules

- **Do not rewrite `main.py`'s Gemini session loop.** Read it, understand the
  event points, hook into them. If a change to `main.py` seems necessary,
  make the smallest one that works and say why in the commit message.
- **Two provided files are the design source of truth:** `jarvis_hud.html` and
  `jarvis_monitor.py`. Don't redesign them. Wire them in.
- **Python 3.12.** Not 3.13 — PyAudio and several deps break.
- **Everything in a venv.** Never touch global site-packages.
- **API keys live in `config/api_keys.json`, never in code, never in the exe.**
- Personal use only. CC BY-NC 4.0 upstream. Nothing here gets published.

---

## Phase 0 — Environment

Fork, clone, and get upstream running **unmodified** before changing anything.
If the voice loop doesn't work at baseline, nothing after this matters.

```
git clone https://github.com/<user>/Mark-XLVIII.git jarvis
cd jarvis
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python setup.py        # first-run config wizard
python main.py
```

Expected friction, handle it and document what you did in `SETUP.md`:

- `requirements.txt` is knowingly incomplete upstream. Expect
  `ModuleNotFoundError` and install as you go. **Pin every package you add**
  and commit the updated `requirements.txt`.
- **PyAudio** is the usual first wall on Windows. If `pip install pyaudio`
  fails, get a prebuilt wheel (`pipwin`, or the matching cp312 wheel).
- Confirm the microphone is picked up and a round-trip voice exchange works.

Additional deps this project needs:

```
psutil                 # telemetry
nvidia-ml-py           # GPU load/temp — NVIDIA only, optional
wmi                    # Windows CPU temp via LibreHardwareMonitor, optional
PyQt6-WebEngine        # the HUD host
pyinstaller            # packaging
requests               # weather/news
```

**Deliverable:** upstream runs, voice works, `SETUP.md` documents every extra
step actually needed on this machine.

---

## Phase 1 — HUD integration

Replace `ui.py` with a `QWebEngineView` host. Keep the old file as `ui_legacy.py`
until Phase 1 is verified, then delete it.

### Files

```
hud/
  jarvis_hud.html      # provided — do not redesign
  fonts/               # SELF-HOSTED. see note below.
  icon.ico             # tray + exe icon
ui_web.py              # new: host window + QWebChannel bridge
jarvis_monitor.py      # provided — telemetry sampler
```

### Fonts — do this first, it's a trap

`jarvis_hud.html` currently pulls Rajdhani and Share Tech Mono from Google
Fonts over the network. In a packaged offline app that silently falls back to
an ugly default and the HUD looks broken for no obvious reason.

Download both as `.woff2` into `hud/fonts/`, replace the `<link>` with
`@font-face` rules using relative paths. Verify by disconnecting the network
and reloading.

### The bridge contract

Python → JS. These four functions already exist in the HUD; call them via
`page().runJavaScript(...)`:

| Call | When | Notes |
|---|---|---|
| `setState('idle'\|'listening'\|'thinking'\|'speaking'\|'alert')` | session state changes | see mapping below |
| `setLevel(0.0–1.0)` | audio callback, ~30Hz | mic amplitude while listening, TTS amplitude while speaking |
| `log('you'\|'jarvis'\|'sys'\|'alert', text)` | every transcript line | JS escapes it; still pass clean strings |
| `telemetry({...})` | 1Hz from `Monitor` | keys: `cpu, mem, gpu, cputemp, gputemp, net_down, net_up, procs, uptime`. `None` → renders `N/A`. Don't fake zeros. |

JS → Python, over `QWebChannel`. The HUD currently `console.log`s these; replace
with bridge calls:

| Signal | Trigger |
|---|---|
| `command(text)` | user pressed Enter in the command input |
| `interrupt()` | ESC key or the INTERRUPT button |

`interrupt()` must hit the **same** code path as upstream's existing interrupt
(drain audio queue, set flag, clear turn). Don't reimplement it.

### State mapping

Find these moments in `main.py` and fire `setState` at each:

- `idle` — before the Gemini session connects; after a clean disconnect.
- `listening` — session live, no active turn. The default resting state.
- `thinking` — a turn has been received and a tool call is dispatching, or
  Gemini is generating before the first audio chunk arrives. This is what the
  radar sweep is for.
- `speaking` — first TTS audio chunk goes to the output stream. Back to
  `listening` when the queue drains or an interrupt fires.
- `alert` — decided in Python, not JS: a telemetry threshold breach (CPU temp
  > 90°C, memory > 92%), or a reconnect failure. Return to the previous state
  after ~4s or when the condition clears.

Colour is carried automatically: cyan listening, amber thinking, **green
speaking**, crimson alert. Don't add per-state colour logic in Python.

### Threading

`Monitor` calls back on a daemon thread. **Never touch Qt from it.** Hop to the
main thread with a signal:

```python
class Telemetry(QObject):
    sample = pyqtSignal(dict)

tele = Telemetry()
tele.sample.connect(lambda d: view.page().runJavaScript(f"telemetry({json.dumps(d)})"))
Monitor(on_sample=tele.sample.emit).start()
```

Same discipline for `setLevel` from the audio callback — that runs on the audio
thread. Signal, don't call directly.

### Window

- Frameless: `Qt.FramelessWindowHint`. The default title bar is the single
  ugliest thing about the current build.
- Draggable by the header region (implement `mousePressEvent`/`mouseMoveEvent`,
  or a JS drag region reporting to Python).
- **Transparency: try it, but don't fight it.** `QWebEngineView` +
  `WA_TranslucentBackground` is unreliable on Windows — often black boxes or
  compositing artefacts. If it misbehaves after one honest attempt, ship an
  opaque `#04070c` window. The HUD is designed to look right either way. Do not
  spend hours here.
- Remember window position and size across runs (`QSettings`).

**Deliverable:** the HUD renders, all five states fire from real session events,
the waveform reacts to real audio, telemetry is live, typing a command and
pressing ESC both reach Python.

---

## Phase 2 — Startup briefing

On launch, JARVIS speaks a briefing. Upstream already has a two-phase briefing
and `actions/weather_report.py` / `actions/web_search.py` — **use them.** Do not
write a second weather client.

Content, in order:

1. Greeting appropriate to local time ("Good morning, sir").
2. Today's date, spoken naturally.
3. Weather: current conditions and today's forecast for the configured city.
4. Two or three news headlines from `actions/web_search.py` in `news` mode.

Requirements:

- **The briefing must never block startup.** Fetch on a background thread. If
  weather or news fails or times out (5s cap each), speak the rest and log the
  failure to the HUD as a `sys` line. A briefing that hangs on a dead API is
  worse than no briefing.
- Each item also gets written to the HUD transcript via `log('jarvis', ...)`.
- City and briefing on/off go in `config/api_keys.json` (or a sibling
  `config/settings.json` — your call, document it).
- Respect upstream's language detection. Don't hardcode English.

**Deliverable:** cold start → HUD appears → greeting, date, weather, headlines,
spoken and logged, with graceful degradation when a source is down.

---

## Phase 3 — Executable + tray

### Packaging

PyInstaller, **`--onedir`, not `--onefile`.** QtWebEngine ships
`QtWebEngineProcess.exe` plus a large resource bundle; onefile unpacks all of it
to a temp dir on every launch, which is slow and fragile. Onedir starts fast and
is far easier to debug. Ship a desktop shortcut to the exe inside the dir.

```
pyinstaller ^
  --noconsole ^
  --onedir ^
  --name JARVIS ^
  --icon hud/icon.ico ^
  --add-data "hud;hud" ^
  --add-data "core/prompt.txt;core" ^
  --collect-all PyQt6.QtWebEngineCore ^
  main.py
```

Known issues to expect and solve:

- **QtWebEngine hooks.** If `QtWebEngineProcess.exe` or the ICU/locale data is
  missing from the bundle, the HUD renders blank white. `--collect-all` is the
  blunt fix; a proper hook file is cleaner. Verify by running the built exe from
  a directory *other* than the project root.
- **Resource paths break inside the bundle.** `__file__` doesn't point where you
  think. Add a helper and use it for *every* asset load (HTML, fonts, icon,
  prompt.txt):
  ```python
  def resource(rel):
      base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
      return os.path.join(base, rel)
  ```
- **`config/api_keys.json` must NOT be bundled.** Read it from
  `%APPDATA%\JARVIS\api_keys.json`. On first run, if it's absent, launch the
  setup wizard and write it there. The exe must be safe to delete and rebuild
  without losing keys.
- **Memory store** likewise goes to `%APPDATA%\JARVIS\memory\`, not next to the
  exe. Same reasoning.
- **Antivirus false positives** are likely — a PyInstaller onefile binary that
  hooks the keyboard and controls the mouse is exactly what a keylogger looks
  like. Onedir reduces this. If Defender quarantines it, add an exclusion.
- Upstream's subprocess `CREATE_NO_WINDOW` monkey-patch must survive packaging.
  Verify no console flashes on reminders or system commands.

### Tray icon

`QSystemTrayIcon`. This is what makes it feel like software rather than a script:

- Left click: show/hide the HUD.
- Menu: `Show HUD` / `Mute microphone` / `Restart session` / `Open logs` / `Quit`.
- **Closing the window hides to tray. Only `Quit` exits.**
- Tooltip shows current state.

### Single instance

A named mutex or a lock file. Two instances = two Gemini sessions = two mics =
JARVIS talking to itself. Second launch should surface the existing window and
exit.

### Global hotkey

Optional but wanted: `Ctrl+Alt+J` toggles the HUD from anywhere. `keyboard` or
`pynput`. If it needs admin, skip it — not worth elevating the whole app.

**Deliverable:** `JARVIS.exe` double-clicks to a working assistant. Closing the
window hides to tray. Quitting from the tray fully exits — no orphaned
`QtWebEngineProcess.exe` and no held microphone.

---

## Phase 4 — Autostart

**Task Scheduler, not the Startup folder.** The Startup folder can't delay, and
the app needs the network stack and audio devices up before it initialises.

Ship `install_autostart.ps1` and `uninstall_autostart.ps1`:

- Trigger: **At log on** (current user), **delay 30 seconds**.
- Action: the exe. Working directory: the install dir.
- Do **not** "run with highest privileges" unless something genuinely requires
  it. The app doesn't. Running an always-on mic-and-mouse process as admin is
  not a trade worth making.
- Conditions: uncheck "stop if the computer switches to battery power" and
  "start only if on AC power" — laptops will otherwise silently skip it.
- Settings: "if the task fails, restart every 1 minute, up to 3 times."
- Make it idempotent — re-running the installer updates rather than duplicates.

If CPU temperature is wanted (see below), LibreHardwareMonitor also needs to
autostart, *with* highest privileges, *before* JARVIS. Sequence it: LHM at logon
+ 10s, JARVIS at logon + 30s.

**Deliverable:** reboot → 30s later JARVIS is in the tray, HUD up, briefing
spoken. Uninstall script cleanly removes the task.

---

## Sensors — what actually works

Don't waste time discovering these:

- **Network** — `psutil.net_io_counters()` deltas. Works everywhere. Already
  implemented in `jarvis_monitor.py`.
- **CPU / memory / process count** — psutil. Fine.
- **GPU load + temp** — NVML (`nvidia-ml-py`) on NVIDIA. Reliable. AMD needs
  LibreHardwareMonitor.
- **CPU temperature on Windows** — *there is no supported user-space API.*
  `psutil.sensors_temperatures()` returns `{}` on Windows; it's Linux/macOS
  only. Reading the thermal sensor needs a kernel driver. The working path:
  install **LibreHardwareMonitor**, run it as admin, read the
  `root\LibreHardwareMonitor` WMI namespace. `jarvis_monitor.py` already does
  this. If LHM isn't running, the value is `None` and the HUD shows `N/A` —
  **this is correct behaviour, leave it.** There's an
  `MSAcpi_ThermalZoneTemperature` fallback in the module; treat its output as
  untrustworthy (usually a motherboard zone, not the CPU package).
- **FPS** — measured inside the HUD's own render loop. It is the HUD's frame
  rate, *not* any game's. Reading another process's FPS needs
  RTSS/PresentMon-level hooks and is out of scope. Its real use: catching frame
  drops when the reactor gets heavier.

---

## Non-negotiables

- **Nothing destructive runs on a voice command without confirmation.** The
  upstream action modules can delete files, send messages, and control the
  mouse. An LLM misinterpreting a mumble must not be able to empty a folder.
  Audit `actions/file_controller.py`, `actions/send_message.py`, and
  `actions/computer_control.py`; gate anything irreversible behind an explicit
  spoken confirmation. If a scheduled/daily task path is added later, hardcode
  those steps in Python — do not let the model choose them.
- **Mic is live whenever the app runs.** It autostarts and sits in the tray, so
  that's most of the day. The tray mute must actually stop capture, not just
  ignore the samples.
- **Log to a file** (`%APPDATA%\JARVIS\logs\`, rotating). With `--noconsole`
  there is no stderr; without logs, a crash is a black box.
- **Graceful shutdown.** Close the Gemini session, stop the audio streams, join
  the monitor thread. A leaked `QtWebEngineProcess.exe` after quit is a bug.

---

## Acceptance checklist

- [ ] Upstream voice loop works unmodified (Phase 0)
- [ ] HUD renders in `QWebEngineView`, fonts load with the network off
- [ ] All five states fire from real session events; speaking is green
- [ ] Waveform reacts to real mic and TTS amplitude
- [ ] CPU/mem/GPU/net live at 1Hz; CPU temp reads via LHM or shows `N/A`
- [ ] Typed command reaches Gemini; ESC interrupts within ~100ms
- [ ] Briefing speaks date + weather + headlines, degrades gracefully on failure
- [ ] `JARVIS.exe` runs from a copied folder on a clean path
- [ ] Tray: show/hide, mute, quit. Window close hides, doesn't exit
- [ ] Single instance enforced
- [ ] Reboot → autostarts after 30s, briefing plays
- [ ] Quit leaves no orphan processes and releases the microphone
- [ ] `SETUP.md` documents every dependency actually needed on this machine

---

## Suggested commit sequence

1. `chore: fork baseline, pin requirements, document setup`
2. `feat: QWebEngineView HUD host + QWebChannel bridge`
3. `feat: wire session states, audio level, transcript to HUD`
4. `feat: telemetry monitor (cpu/gpu/temp/network)`
5. `feat: startup briefing — date, weather, news`
6. `feat: system tray, single instance, graceful shutdown`
7. `build: PyInstaller onedir packaging`
8. `feat: autostart install/uninstall scripts`
9. `docs: SETUP.md`

Work in that order. Each step should leave the app runnable.
