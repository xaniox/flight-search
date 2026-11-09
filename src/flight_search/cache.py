"""Small JSON disk cache with TTL, used for both search phases."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "flight-search"


def parse_duration(value: str) -> timedelta:
    """Parse ``12h``, ``30m``, ``45s`` or ``0`` into a timedelta."""
    text = value.strip().lower()
    if text in {"0", "off", "none"}:
        return timedelta(0)
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if text[-1:] in units:
        number = text[:-1]
        unit = units[text[-1]]
    else:
        number, unit = text, 3600
    try:
        return timedelta(seconds=float(number) * unit)
    except ValueError as exc:
        raise ValueError(f"Invalid duration {value!r}") from exc


@dataclass(slots=True)
class Cache:
    directory: Path
    ttl: timedelta
    enabled: bool = True
    stats: CacheStats = field(default_factory=CacheStats)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)

    @property
    def active(self) -> bool:
        return self.enabled and self.ttl.total_seconds() > 0

    def _hit(self) -> None:
        with self._lock:
            self.stats.hits += 1

    def _miss(self) -> None:
        with self._lock:
            self.stats.misses += 1

    def _write(self) -> None:
        with self._lock:
            self.stats.writes += 1

    @staticmethod
    def _hash(key: dict[str, Any]) -> str:
        payload = json.dumps(key, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _path(self, key: dict[str, Any]) -> Path:
        return self.directory / f"{self._hash(key)}.json"

    def get(self, key: dict[str, Any]) -> Any | None:
        if not self.active:
            self._miss()
            return None
        path = self._path(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._miss()
            return None
        try:
            created = datetime.fromisoformat(raw["created"])
        except (KeyError, ValueError):
            self._miss()
            return None
        if datetime.now(timezone.utc) - created > self.ttl:
            self._miss()
            return None
        self._hit()
        return raw.get("payload")

    def put(self, key: dict[str, Any], payload: Any) -> None:
        if not self.active:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {
            "created": datetime.now(timezone.utc).isoformat(),
            "key": key,
            "payload": payload,
        }
        fd, tmp_name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False)
            os.replace(tmp_name, self._path(key))
            self._write()
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
