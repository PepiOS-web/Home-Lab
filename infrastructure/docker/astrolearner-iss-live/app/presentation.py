"""Small private, atomic presentation preferences; never contains credentials."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path


class PresentationStore:
    KEYS = {"dashboard_enabled", "recorded_fallback_enabled", "music_style"}

    def __init__(self, path: Path, recorded_default: bool = True) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._value = {"dashboard_enabled": False,
                       "recorded_fallback_enabled": recorded_default,
                       "music_style": "classic"}
        if path.is_file():
            with path.open("rb") as handle:
                raw = handle.read(4097)
            if len(raw) > 4096:
                raise ValueError("Preferencias de presentación demasiado grandes")
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ValueError("Preferencias de presentación no válidas") from None
            self._value = self.validate(value)

    @classmethod
    def validate(cls, value: dict) -> dict:
        if not isinstance(value, dict) or set(value) != cls.KEYS:
            raise ValueError("Preferencias de presentación no válidas")
        if (type(value["dashboard_enabled"]) is not bool
                or type(value["recorded_fallback_enabled"]) is not bool
                or type(value["music_style"]) is not str
                or value["music_style"] not in {"classic", "melodic"}):
            raise ValueError("Preferencias de presentación no válidas")
        return dict(value)

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self._value)

    def save(self, value: dict) -> dict:
        value = self.validate(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix="presentation-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(value, handle, ensure_ascii=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                self._value = value
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return dict(value)
