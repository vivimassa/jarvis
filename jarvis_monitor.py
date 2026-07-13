"""
jarvis_monitor.py — telemetry sampler for the HUD.

    pip install psutil

Optional, and worth it:
    pip install nvidia-ml-py     # NVIDIA GPU load + temp (real, reliable)
    pip install wmi              # Windows CPU temp, via LibreHardwareMonitor

Emits a dict once per second:
    {cpu, mem, gpu, cputemp, gputemp, net_down, net_up, procs, uptime}
Values are None when a sensor isn't readable. Pass the dict straight to the
HUD's telemetry() — it renders None as a dim N/A rather than a fake zero.

------------------------------------------------------------------
READ THIS ABOUT CPU TEMPERATURE ON WINDOWS
------------------------------------------------------------------
There is no supported user-space API for it. psutil.sensors_temperatures()
returns {} on Windows — it is Linux/macOS only. Reading the CPU's thermal
sensor requires a kernel driver. Your options, in order of sanity:

  1. Install LibreHardwareMonitor, run it, and leave it running. It loads a
     signed driver and publishes readings to the WMI namespace
     root\\LibreHardwareMonitor. This module reads that. Free, reliable, but
     LHM must be running (it needs admin) or you get None.
       -> https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
       -> add it to Task Scheduler "at log on, run with highest privileges"
          if you want it up before JARVIS starts.

  2. MSAcpi_ThermalZoneTemperature via WMI. Needs admin, and on most consumer
     desktops it reports an ACPI thermal zone (roughly motherboard) rather
     than CPU package — a number that looks plausible and is wrong. Tried as
     a fallback here, but don't trust it if option 1 is available.

  3. Nothing. Return None, HUD shows N/A. This is a fine outcome.

GPU temp is easy by comparison: NVML gives it to you directly on NVIDIA. AMD
needs LHM too.
------------------------------------------------------------------
"""

import time
import threading
import platform

import psutil

IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------- GPU (NVML)
_nvml = None
_gpu_handle = None
try:
    import pynvml
    pynvml.nvmlInit()
    _gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    _nvml = pynvml
except Exception:
    _nvml = None


def _gpu():
    """(load %, temp °C) or (None, None)."""
    if not _nvml:
        return None, None
    try:
        util = _nvml.nvmlDeviceGetUtilizationRates(_gpu_handle).gpu
        temp = _nvml.nvmlDeviceGetTemperature(_gpu_handle, _nvml.NVML_TEMPERATURE_GPU)
        return float(util), float(temp)
    except Exception:
        return None, None


# ------------------------------------------------------- CPU temp (the hard one)
_lhm = None
if IS_WINDOWS:
    try:
        import wmi
        _lhm = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        _lhm.Sensor()          # probe — raises if LHM isn't running
    except Exception:
        _lhm = None


def _cpu_temp():
    """°C or None."""
    # Linux / macOS — psutil handles it
    if not IS_WINDOWS:
        try:
            temps = psutil.sensors_temperatures()
        except Exception:
            return None
        for key in ("coretemp", "k10temp", "cpu_thermal", "zenpower", "acpitz"):
            if key in temps and temps[key]:
                return float(temps[key][0].current)
        return None

    # Windows — LibreHardwareMonitor over WMI
    if _lhm:
        try:
            best = None
            for s in _lhm.Sensor():
                if s.SensorType != "Temperature":
                    continue
                name = (s.Name or "")
                # "CPU Package" is the one you want; "Core #n" as backup
                if "CPU Package" in name:
                    return float(s.Value)
                if "Core" in name and best is None:
                    best = float(s.Value)
            return best
        except Exception:
            pass

    # Windows — ACPI fallback. Needs admin. Frequently not the CPU. See header.
    try:
        import wmi
        w = wmi.WMI(namespace="root\\wmi")
        z = w.MSAcpi_ThermalZoneTemperature()[0]
        return (z.CurrentTemperature / 10.0) - 273.15   # decikelvin -> °C
    except Exception:
        return None


# ---------------------------------------------------------------- the sampler
class Monitor:
    """
    Monitor(on_sample=callback).start()

    callback receives one dict per interval, on a background thread. If you
    are feeding a Qt widget, do NOT touch the UI from inside it — emit a
    signal, or use QMetaObject.invokeMethod, and let the main thread render.
    """

    def __init__(self, on_sample, interval=1.0):
        self.on_sample = on_sample
        self.interval = interval
        self._stop = threading.Event()
        self._started = time.time()
        self._last_net = psutil.net_io_counters()
        self._last_t = time.time()
        psutil.cpu_percent(interval=None)   # prime — first call always reads 0

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _uptime(self):
        s = int(time.time() - self._started)
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"

    def _net(self):
        """(down_bytes_per_sec, up_bytes_per_sec) — counter deltas over real
        elapsed time, not over self.interval, because sleep() lies."""
        now = time.time()
        cur = psutil.net_io_counters()
        dt = max(1e-6, now - self._last_t)
        down = (cur.bytes_recv - self._last_net.bytes_recv) / dt
        up   = (cur.bytes_sent - self._last_net.bytes_sent) / dt
        self._last_net, self._last_t = cur, now
        return max(0.0, down), max(0.0, up)

    def _loop(self):
        while not self._stop.wait(self.interval):
            gpu_load, gpu_temp = _gpu()
            down, up = self._net()
            try:
                self.on_sample({
                    "cpu":      psutil.cpu_percent(interval=None),
                    "mem":      psutil.virtual_memory().percent,
                    "gpu":      gpu_load,
                    "cputemp":  _cpu_temp(),
                    "gputemp":  gpu_temp,
                    "net_down": down,
                    "net_up":   up,
                    "procs":    len(psutil.pids()),
                    "uptime":   self._uptime(),
                })
            except Exception as e:
                print("[monitor] sample failed:", e)


# ---------------------------------------------------------------- wiring it up
"""
In your Qt window, push each sample into the page as JSON:

    import json
    from PyQt6.QtCore import QObject, pyqtSignal

    class Telemetry(QObject):
        sample = pyqtSignal(dict)          # thread-safe hop to the main thread

    tele = Telemetry()
    tele.sample.connect(
        lambda d: view.page().runJavaScript(f"telemetry({json.dumps(d)})")
    )
    Monitor(on_sample=tele.sample.emit).start()

And the states, from wherever main.py already knows them:

    view.page().runJavaScript("setState('thinking')")   # tool dispatch begins
    view.page().runJavaScript("setState('speaking')")   # first TTS chunk out
    view.page().runJavaScript("setState('listening')")  # turn complete
    view.page().runJavaScript(f"setLevel({amp:.3f})")   # audio callback, ~30Hz

Threshold alerts are better decided in Python than JS — you have the history:

    if d["cputemp"] and d["cputemp"] > 90:
        view.page().runJavaScript("setState('alert')")
"""

if __name__ == "__main__":
    def show(d):
        print(
            f"cpu {d['cpu']:5.1f}%  mem {d['mem']:5.1f}%  "
            f"gpu {d['gpu'] if d['gpu'] is not None else '  n/a'}  "
            f"cputemp {d['cputemp'] if d['cputemp'] is not None else 'n/a'}  "
            f"gputemp {d['gputemp'] if d['gputemp'] is not None else 'n/a'}  "
            f"down {d['net_down']/1024:8.1f} KB/s  up {d['net_up']/1024:7.1f} KB/s"
        )

    print("sampling — ctrl-c to stop")
    print("cpu temp source:",
          "LibreHardwareMonitor" if _lhm else
          ("psutil" if not IS_WINDOWS else "none (see header)"))
    print("gpu source:", "NVML" if _nvml else "none")
    Monitor(on_sample=show).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
