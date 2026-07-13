# JARVIS — Setup notes

Personal fork of [FatihMakes/Mark-XLVIII](https://github.com/FatihMakes/Mark-XLVIII),
re-skinned with a web HUD and packaged for Windows. This file records every step
actually needed to get it running on this machine (Windows 11, Python 3.12).

## Machine baseline (verified)

- **Python 3.12.10** (`py -3.12`) — required; do **not** use 3.13 (PyAudio-class
  deps and others break). This project actually uses `sounddevice`, not PyAudio.
- **NVIDIA GeForce RTX 5080**, driver 576.88 → GPU load/temp work via NVML.
- CPU temperature needs **LibreHardwareMonitor** running as admin (see below);
  until then the HUD shows `N/A` for CPU CORE — that is correct behaviour.

## From-scratch setup

```powershell
# 1. Virtual environment (Python 3.12)
py -3.12 -m venv .venv
.venv\Scripts\activate

# 2. Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Playwright browsers (needed by browser-automation actions)
python -m playwright install

# 4. Run
python main.py
```

On first launch a setup overlay asks for your **Gemini API key** (Google AI
Studio — the free tier includes the Live API). Paste it there; it is written to
`config/api_keys.json` (git-ignored) — later moved to `%APPDATA%\JARVIS\` when
packaged.

## What upstream's requirements were missing / what this fork added

Upstream `requirements.txt` is knowingly incomplete. On this machine the only
genuinely missing pieces were the GUI stack (upstream imports PyQt6 in `ui.py`
but never lists it). Added and **pinned** in `requirements.txt`:

| Package | Why | Version |
|---|---|---|
| `PyQt6` | the UI (upstream omitted it) | 6.11.0 |
| `PyQt6-WebEngine` | web HUD host (`QWebEngineView`) | 6.11.0 |
| `nvidia-ml-py` | GPU load/temp via NVML (optional) | 13.610.43 |
| `wmi` | CPU temp via LibreHardwareMonitor (win32, optional) | 1.5.1 |
| `pyinstaller` | packaging (`--onedir`) | 6.21.0 |

No PyAudio wheel wall appeared — audio is `sounddevice`, whose Windows wheel
bundles PortAudio. All 19 `actions/` modules, `memory`, `core`, `ui`, and `main`
import cleanly with the list above.

## CPU temperature (LibreHardwareMonitor)

`psutil.sensors_temperatures()` returns `{}` on Windows — there is no user-space
CPU-temp API. The working path (wired in `jarvis_monitor.py`):

1. Install **LibreHardwareMonitor** and run it **as admin** (it loads a signed
   driver and publishes to the `root\LibreHardwareMonitor` WMI namespace).
2. To have it up before JARVIS: add it to Task Scheduler *at logon, highest
   privileges, +10 s* (JARVIS starts at +30 s). See `install_autostart.ps1`.

If LHM isn't running, CPU CORE shows `N/A` — leave it, that's honest.

## Config & data locations

- **Dev (running from source):** `config/api_keys.json`, `config/settings.json`,
  `memory/`.
- **Packaged exe:** `%APPDATA%\JARVIS\` holds `api_keys.json`, `settings.json`,
  `memory\`, and `logs\`. The exe is safe to delete and rebuild without losing
  keys or memory.

## Wake word ("Hey Jarvis")

Uses **openWakeWord** (open-source, no key). First run downloads ~6 MB of ONNX
models into the package cache (bundled into the exe). JARVIS is **dormant** until
it hears "Hey Jarvis", then listens; after ~12 s of silence it returns to
standby. Nothing is streamed anywhere until the wake word fires. Falls back to
always-listening if the detector can't start.

## Briefing

- Every startup: greeting + time + **date**, then **weather** for the device's
  location (IP geolocation → Open-Meteo, both keyless — follows a laptop
  anywhere).
- **News**: spoken **once per day, mornings only** (05:00–11:00 GMT+7). Tunable in
  `main.py` (`BRIEFING_TZ_OFFSET_H`, `BRIEFING_START_HOUR`, `BRIEFING_END_HOUR`).

## Packaging (exe)

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Produces `dist\JARVIS\JARVIS.exe` (a `--onedir` bundle — ship the whole folder).
Notes:
- Keys/memory/logs live in `%APPDATA%\JARVIS\`, **not** next to the exe — the exe
  is safe to delete and rebuild without losing them. First launch shows a setup
  overlay for the Gemini key (or seed `%APPDATA%\JARVIS\config\api_keys.json`).
- **Antivirus**: a mic+keyboard app can trip Defender. Add an exclusion for the
  install folder if it gets quarantined.

## Autostart (30 s after logon)

```powershell
# from the install folder (where dist\JARVIS lives), or pass -ExePath
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
powershell -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1   # to remove
```

Registers a Task Scheduler task: **at logon, +30 s delay**, current user, no
admin, survives battery, restarts on failure. If **LibreHardwareMonitor** is
installed it also registers `JARVIS-LHM` (logon +10 s, admin) so CPU temperature
reads before JARVIS starts.

## Baseline verification (Phase 0)

Automated setup is verified: venv builds, all deps install, every module imports,
NVML detects the RTX 5080, Playwright browsers install. The **voice round-trip**
(speak → JARVIS replies) requires a live mic and your Gemini key, so run
`python main.py`, enter the key, and confirm a spoken exchange
(`LISTENING → THINKING → SPEAKING → LISTENING`).
