"""Private Starvios configuration and one-encode, isolated FIFO outputs.

No platform API, cookies, OAuth credentials or stream keys are returned to the
portal. Only the documented Cloudflare ingest endpoint is accepted.
"""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

SERVER = "rtmps://live.cloudflare.com:443/live/"
WATCH_URL = "https://starvios.com/astrolearnerspace"
FIFO_OPTIONS = (
    "queue_size=120:attempt_recovery=1:recover_any_error=1:"
    "max_recovery_attempts=0:recovery_wait_time=5:"
    "recovery_wait_streamtime=0:drop_pkts_on_overflow=1:restart_with_keyframe=1"
)
KEY = re.compile(r"[A-Za-z0-9_-]{32,512}\Z")


@dataclass(frozen=True)
class Destination:
    enabled: bool = False
    key: str = field(default="", repr=False)

    @property
    def url(self) -> str:
        return SERVER + self.key

    def public(self) -> dict:
        return {"enabled": self.enabled, "configured": bool(self.key),
                "server": SERVER, "watch_url": WATCH_URL,
                "remote_verified": False}


class StarviosStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> Destination:
        with self._lock:
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                if self.path.is_symlink():
                    raise ValueError
                fd = os.open(self.path, flags)
                with os.fdopen(fd, "r", encoding="utf-8") as handle:
                    info = os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                        raise ValueError
                    if os.name != "nt" and info.st_mode & 0o077:
                        raise ValueError
                    data = json.loads(handle.read(4097))
                if (not isinstance(data, dict) or set(data) != {"enabled", "key"}
                        or type(data["enabled"]) is not bool
                        or not isinstance(data["key"], str)
                        or (data["key"] and not KEY.fullmatch(data["key"]))
                        or (data["enabled"] and not data["key"])):
                    raise ValueError
                return Destination(data["enabled"], data["key"])
            except FileNotFoundError:
                return Destination()
            except (OSError, ValueError, UnicodeError):
                raise ValueError("Configuración privada de Starvios no válida; revisar archivo y permisos") from None

    def save(self, *, enabled: bool, key: str | None = None,
             rotated_key_confirmed: bool = False) -> Destination:
        with self._lock:
            if key is not None and (not isinstance(key, str) or not KEY.fullmatch(key)):
                raise ValueError("Clave de Starvios no válida")
            if key is not None and not rotated_key_confirmed:
                raise ValueError("Regenera la clave expuesta y confirma que introduces la nueva")
            current = self.load()
            value = Destination(enabled, current.key if key is None else key)
            if enabled and not value.key:
                raise ValueError("Falta una clave nueva de Starvios")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".starvios-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"enabled": enabled, "key": value.key}, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return value


def _tee_url(url: str) -> str:
    # URLs are not shell commands. Escape the tee filename parser separately;
    # do not allow control characters or muxer-option injection.
    if not url.startswith(("rtmp://", "rtmps://")) or any(
        c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url
    ):
        raise ValueError("Destino RTMP no válido")
    return "".join("\\" + c if c in "\\'|[]" else c for c in url)


def tee_output(primary: str, secondary: str) -> list[str]:
    outputs = "|".join(
        "[f=flv:onfail=ignore:flvflags=no_duration_filesize:rw_timeout=15000000]" + _tee_url(url)
        for url in (primary, secondary)
    )
    return ["-flags:v", "+global_header+cgop", "-flags:a", "+global_header",
            "-f", "tee", "-use_fifo", "1", "-fifo_options", FIFO_OPTIONS, outputs]


def redact_output(line: str, *urls: str) -> str:
    for url in urls:
        if url:
            # FFmpeg may report a bare key or an escaped tee filename.
            line = line.replace(url, "[RTMP REDACTADO]")
            key = url.rsplit("/", 1)[-1]
            if key:
                line = line.replace(key, "[CLAVE PRIVADA]")
    return re.sub(r"rtmps?://[^\s]+", "[RTMP REDACTADO]", line)
