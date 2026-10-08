from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class LiveState:
    status: str = "iniciando"
    mode: str = "simulacion"
    live_requested: bool = False
    control_ready: bool = False
    source_status: str = "sin configurar"
    source_label: str = ""
    block_started_at: str | None = None
    next_restart_at: str | None = None
    elapsed_seconds: int = 0
    remaining_seconds: int = 0
    bitrate: str = "0 kbit/s"
    fps: float = 0.0
    dropped_frames: int = 0
    music_track: str = "AstroLearner Lo-Fi (Rhodes suave, sin ruido blanco)"
    youtube_watch_url: str = ""
    last_error: str = ""
    restart_count: int = 0
    updated_at: str = ""
    latitude: float | None = None
    longitude: float | None = None
    altitude_km: float | None = None
    velocity_kmh: float | None = None
    visual_source: str = "NASA EPIC / DSCOVR"
    visual_updated_at: str | None = None


class StateStore:
    def __init__(self, destination: Path, source_label: str) -> None:
        self.destination = destination
        self._lock = threading.Lock()
        self._state = LiveState(source_label=source_label, updated_at=utc_now())

    def update(self, **values: Any) -> dict[str, Any]:
        with self._lock:
            for key, value in values.items():
                if not hasattr(self._state, key):
                    raise AttributeError(key)
                setattr(self._state, key, value)
            self._state.updated_at = utc_now()
            payload = asdict(self._state)
            self._write_atomic(payload)
            return payload

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._state)

    def _write_atomic(self, payload: dict[str, Any]) -> None:
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix="status-", suffix=".json", dir=self.destination.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, self.destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
