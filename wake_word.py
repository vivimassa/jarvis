"""
wake_word.py — on-device "Hey Jarvis" wake word (openWakeWord, no key/signup).

Fully local: nothing is streamed anywhere; JARVIS stays dormant until it hears
"Hey Jarvis". The detector does NOT open its own microphone — it is fed 16 kHz
mono int16 frames from the main audio callback (the same low-latency path the
Gemini session uses), so there is no second mic stream and no extra buffering.

First run downloads a few small ONNX models (~6 MB) into the openwakeword cache;
afterwards it is offline.
"""

import time
import threading

import numpy as np


class WakeWordDetector:
    FRAME = 1280          # 80 ms @ 16 kHz — openWakeWord's expected chunk
    _NEED = FRAME * 2     # bytes (int16)

    def __init__(self, on_wake, keyword: str = "hey_jarvis",
                 threshold: float = 0.4, refractory_s: float = 1.0):
        import openwakeword
        from openwakeword.model import Model
        try:
            openwakeword.utils.download_models()   # no-op once cached
        except Exception:
            pass
        try:
            self._model = Model(wakeword_models=[keyword], inference_framework="onnx")
        except Exception:
            self._model = Model(inference_framework="onnx")
        self._on_wake = on_wake
        self._threshold = threshold
        self._refractory = refractory_s
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._enabled = False
        self._last = 0.0
        self._thread = threading.Thread(target=self._loop, daemon=True, name="wake-word")
        self._thread.start()

    def set_enabled(self, on: bool):
        """Enable while dormant; disable while actively listening/speaking."""
        self._enabled = on
        if not on:
            with self._lock:
                self._buf.clear()
            try:
                self._model.reset()   # drop stale audio context
            except Exception:
                pass

    def feed(self, pcm_bytes: bytes):
        """Called from the audio callback thread — fast, non-blocking."""
        if not self._enabled:
            return
        with self._lock:
            self._buf.extend(pcm_bytes)
            # guard against unbounded growth if the worker stalls
            if len(self._buf) > self._NEED * 20:
                del self._buf[:-self._NEED * 10]

    def _score(self, scores: dict) -> float:
        if not scores:
            return 0.0
        for k, v in scores.items():
            if "jarvis" in k:
                return float(v)
        return float(max(scores.values()))

    def _loop(self):
        while not self._stop.is_set():
            frame = None
            with self._lock:
                if len(self._buf) >= self._NEED:
                    frame = bytes(self._buf[:self._NEED])
                    del self._buf[:self._NEED]
            if frame is None:
                time.sleep(0.005)
                continue
            if not self._enabled:
                continue
            arr = np.frombuffer(frame, dtype=np.int16)
            try:
                score = self._score(self._model.predict(arr))
            except Exception:
                continue
            now = time.monotonic()
            if score >= self._threshold and (now - self._last) > self._refractory:
                self._last = now
                try:
                    self._on_wake()
                except Exception:
                    pass

    def stop(self):
        self._stop.set()
