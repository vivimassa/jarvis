"""
applog.py — rotating file logging.

Under --noconsole packaging there is no stderr, so a crash would be a black box.
This tees stdout/stderr into %APPDATA%\\JARVIS\\logs\\jarvis.log (rotating), and
still writes to the console when one exists (dev).
"""

import sys
import logging
from logging.handlers import RotatingFileHandler

import paths


class _Tee:
    def __init__(self, logger, level, orig):
        self._logger = logger
        self._level = level
        self._orig = orig
        self._buf = ""

    def write(self, s):
        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass
        try:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._logger.log(self._level, line)
        except Exception:
            pass

    def flush(self):
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass

    # Make this a well-behaved stream so libraries that introspect stdout/stderr
    # (uvicorn, rich, etc.) don't choke.
    def isatty(self):
        return False

    def writable(self):
        return True

    @property
    def encoding(self):
        return getattr(self._orig, "encoding", "utf-8") or "utf-8"

    def fileno(self):
        if self._orig is not None and hasattr(self._orig, "fileno"):
            return self._orig.fileno()
        raise OSError("_Tee has no fileno")


_done = False


def setup_logging():
    global _done
    if _done:
        return
    _done = True
    paths.ensure_dirs()
    logfile = str(paths.LOGS_DIR / "jarvis.log")
    logger = logging.getLogger("jarvis")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = RotatingFileHandler(logfile, maxBytes=1_000_000, backupCount=5,
                                encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    sys.stdout = _Tee(logger, logging.INFO, sys.stdout)
    sys.stderr = _Tee(logger, logging.ERROR, sys.stderr)
    logger.info("=== JARVIS starting ===")
    return logfile
