"""Structured NDJSON file logger for UCX sidecars.

Writes NDJSON log lines to %LocalAppData%/UniversalConverterX/logs/
with daily rotation and configurable retention. Gated behind the
UCX_VERBOSE_LOGGING env var (default off, zero-cost when disabled).

Usage::

    from ucx_log import sidecar_logger

    log = sidecar_logger("videocrush")
    log.info("starting compression", input=path, crf=18)
    log.warn("output truncated", delta_seconds=4.2)
    log.error("ffmpeg exited non-zero", code=1)

Log levels: debug, info, warn, error. When verbose is off, only
warn/error reach disk. The ring buffer always populates so a crash
bundle (C# side) has meaningful tail context.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import orjson
    def _dumps(obj: Any) -> str:
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, default=str)


_VERBOSE = os.environ.get("UCX_VERBOSE_LOGGING", "").lower() in ("1", "true", "yes")
_RETENTION_DAYS = 7
_RING_SIZE = 500


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA", "")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "UniversalConverterX" / "logs"


def _prune_old(directory: Path, retention_days: int) -> None:
    try:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)
        for f in directory.glob("sidecar-*.ndjson"):
            try:
                date_str = f.stem.split("-", 1)[1][:8]
                file_date = datetime.datetime.strptime(date_str, "%Y%m%d")
                if file_date < cutoff:
                    f.unlink(missing_ok=True)
            except (ValueError, IndexError):
                pass
    except Exception:
        pass


class SidecarLogger:
    __slots__ = ("_engine", "_dir", "_file", "_ring", "_ring_idx", "_verbose", "_pruned")

    def __init__(self, engine: str, verbose: bool = _VERBOSE) -> None:
        self._engine = engine
        self._dir = _log_dir()
        self._file = None
        self._ring: list[str] = []
        self._ring_idx = 0
        self._verbose = verbose
        self._pruned = False

    def _ensure_file(self) -> Any:
        if self._file is not None:
            return self._file
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            if not self._pruned:
                _prune_old(self._dir, _RETENTION_DAYS)
                self._pruned = True
            today = datetime.datetime.now().strftime("%Y%m%d")
            path = self._dir / f"sidecar-{today}-{self._engine}.ndjson"
            self._file = open(path, "a", encoding="utf-8")
            return self._file
        except Exception:
            return None

    def _write(self, level: str, message: str, **fields: Any) -> None:
        record = {
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "level": level,
            "engine": self._engine,
            "message": message,
            **fields,
        }
        line = _dumps(record)

        if len(self._ring) < _RING_SIZE:
            self._ring.append(line)
        else:
            self._ring[self._ring_idx % _RING_SIZE] = line
        self._ring_idx += 1

        disk_levels = {"warn", "error"} if not self._verbose else {"debug", "info", "warn", "error"}
        if level not in disk_levels:
            return

        f = self._ensure_file()
        if f is not None:
            try:
                f.write(line + "\n")
                f.flush()
            except Exception:
                pass

    def debug(self, message: str, **fields: Any) -> None:
        self._write("debug", message, **fields)

    def info(self, message: str, **fields: Any) -> None:
        self._write("info", message, **fields)

    def warn(self, message: str, **fields: Any) -> None:
        self._write("warn", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self._write("error", message, **fields)

    @property
    def ring_tail(self) -> list[str]:
        if len(self._ring) < _RING_SIZE:
            return list(self._ring)
        start = self._ring_idx % _RING_SIZE
        return self._ring[start:] + self._ring[:start]

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None


def sidecar_logger(engine: str) -> SidecarLogger:
    return SidecarLogger(engine)
