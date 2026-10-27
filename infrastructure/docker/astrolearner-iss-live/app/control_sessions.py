"""Private, revocable browser sessions; never publish credentials in /status."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path

from .control_auth import ControlAuthError

COOKIE_NAME = "__Secure-astrolearner-live-control"
COOKIE_PATH = "/iss-live/control/"
SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_SESSIONS = 128


class ControlSessions:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, int]:
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or self.path.stat().st_size > 32768:
            raise ValueError("Invalid session store")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or len(value) > MAX_SESSIONS:
            raise ValueError("Invalid session store")
        now = time.time()
        result = {}
        for key, expiry in value.items():
            if not re.fullmatch(r"[a-f0-9]{64}", key) or type(expiry) is not int:
                raise ValueError("Invalid session store")
            if expiry > now:
                result[key] = expiry
        return result

    def _save(self, sessions: dict[str, int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".control-session-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(sessions, output, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _digest(value: str, expected: str) -> str:
        # Rotation of the control token invalidates every existing session.
        return hmac.new(expected.encode("utf-8"), b"iss-live-session-v1\0" + value.encode("ascii"),
                        hashlib.sha256).hexdigest()

    def valid(self, value: str, expected: str) -> bool:
        if not expected or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            return False
        try:
            with self._lock:
                return self._load().get(self._digest(value, expected), 0) > time.time()
        except (OSError, ValueError, TypeError):
            raise ControlAuthError(503, "Sesiones no disponibles; no se han desbloqueado los controles") from None

    def create(self, expected: str, previous: str = "") -> str:
        if not expected:
            raise ControlAuthError(503, "Controles no configurados")
        try:
            with self._lock:
                sessions = self._load()
                if re.fullmatch(r"[A-Za-z0-9_-]{43}", previous):
                    sessions.pop(self._digest(previous, expected), None)
                while len(sessions) >= MAX_SESSIONS:
                    sessions.pop(min(sessions, key=sessions.get))
                value = secrets.token_urlsafe(32)
                sessions[self._digest(value, expected)] = int(time.time()) + SESSION_SECONDS
                self._save(sessions)
                return value
        except (OSError, ValueError, TypeError):
            raise ControlAuthError(503, "No se pudo guardar la sesión; los controles siguen bloqueados") from None

    def revoke(self, value: str, expected: str) -> None:
        if not expected or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            return
        try:
            with self._lock:
                sessions = self._load()
                sessions.pop(self._digest(value, expected), None)
                self._save(sessions)
        except (OSError, ValueError, TypeError):
            raise ControlAuthError(503, "No se pudo cerrar la sesión; vuelve a intentarlo") from None
