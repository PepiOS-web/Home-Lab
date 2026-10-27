"""Bounded, local MJPEG failover without restarting the publishing encoder.

Only an explicitly authorised, direct HTTP(S) camera input is accepted. Camera
URLs and decoder diagnostics are deliberately never included in public status.
Fresh frame arrivals, rather than image brightness, determine camera health:
the orbital night is not a signal failure.
"""

from __future__ import annotations

import io
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

MAX_JPEG_BYTES = 2 * 1024 * 1024
READ_BYTES = 64 * 1024
MAX_INPUT_PIXELS = 16_777_216
TERMINATE_GRACE_SECONDS = 5.0
_MODES = {"auto", "fallback", "map"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iter_jpegs(
    stream: BinaryIO, max_frame_bytes: int = MAX_JPEG_BYTES
) -> Iterator[bytes]:
    """Parse an MJPEG pipe incrementally without retaining an unbounded frame.

    Oversized or incomplete images are discarded. Keeping the last byte when
    seeking the next SOI also handles markers split across pipe reads.
    """
    if max_frame_bytes < 4:
        raise ValueError("JPEG size limit must be at least four bytes")
    pending = bytearray()
    while True:
        chunk = stream.read(min(READ_BYTES, max_frame_bytes))
        if not chunk:
            return
        pending.extend(chunk)
        while pending:
            start = pending.find(b"\xff\xd8")
            if start < 0:
                pending[:] = pending[-1:] if pending[-1:] == b"\xff" else b""
                break
            if start:
                del pending[:start]
            end = pending.find(b"\xff\xd9", 2)
            nested = pending.find(b"\xff\xd8", 2)
            if nested >= 0 and (end < 0 or nested < end):
                del pending[:nested]
                continue
            if end >= 0:
                length = end + 2
                if length <= max_frame_bytes:
                    yield bytes(pending[:length])
                del pending[:length]
                continue
            if len(pending) > max_frame_bytes:
                pending[:] = pending[-1:] if pending[-1:] == b"\xff" else b""
            break


class VideoSwitcher:
    """Decode sources into latest-frame caches; ``frame`` never waits for IO.

    There are at most two decoding subprocesses: one camera and one local
    backup. The publishing FFmpeg and its audio are managed by the controller,
    not by this class. ``on_status`` must not raise; failures are nevertheless
    isolated so the public status sink cannot break video delivery.
    """

    def __init__(
        self,
        settings: Any,
        on_status: Callable[[dict[str, Any]], None],
        map_frame: Callable[[], bytes | None],
    ) -> None:
        self.settings = settings
        self._on_status = on_status
        self._map_frame = map_frame
        self._clock = time.monotonic
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started = False
        self._recorded_worker_started = False
        self._mode = str(getattr(settings, "camera_mode", "auto"))
        if self._mode not in _MODES:
            raise ValueError("Camera mode must be auto, fallback or map")
        self._url = str(getattr(settings, "camera_url", "")).strip()
        self._authorised = bool(getattr(settings, "camera_authorized", False))
        if self._url:
            parsed = urlsplit(self._url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or any(ord(character) < 32 for character in self._url)
            ):
                raise ValueError("Camera input must be a direct HTTP(S) URL")
        self._timeout = float(getattr(settings, "camera_timeout_seconds", 8))
        self._stable = float(getattr(settings, "camera_stable_seconds", 15))
        self._retry = float(getattr(settings, "camera_retry_seconds", 30))
        if not (
            0 < self._timeout <= 120
            and 0 <= self._stable <= 300
            and 1 <= self._retry <= 900
        ):
            raise ValueError("Invalid camera failover timing")
        self._backup = Path(settings.nasa_loop_video)
        self._backup_enabled = bool(settings.use_nasa_playlist)
        self._frames: dict[str, bytes | None] = {"camera": None, "recorded": None}
        self._received: dict[str, float | None] = {"camera": None, "recorded": None}
        self._received_at: dict[str, str | None] = {"camera": None, "recorded": None}
        self._processes: dict[str, subprocess.Popen[bytes] | None] = {
            "camera": None,
            "recorded": None,
        }
        self._reader_started: dict[str, float | None] = {
            "camera": None,
            "recorded": None,
        }
        self._terminate_requested: dict[
            str, tuple[subprocess.Popen[bytes], float] | None
        ] = {"camera": None, "recorded": None}
        self._running = {"camera": False, "recorded": False}
        self._errors = {"camera": False, "recorded": False}
        self._camera_stable_since: float | None = None
        self._video_mode = "map"
        self._switch_count = 0
        self._switch_at: str | None = None
        self._last_emitted: dict[str, Any] | None = None
        self._last_emitted_at = float("-inf")
        self._last_emit_attempt_at = float("-inf")
        self._status_emit_failed = False
        self._status_emit_in_progress = False
        self._placeholder = self._make_placeholder()

    def start(self) -> None:
        with self._lock:
            if self._started or self._stop.is_set():
                return
            self._started = True
            # Start a local reader only when a configured backup really exists.
            sources = []
            if self._backup_enabled and self._backup.is_file():
                sources.append("recorded")
                self._recorded_worker_started = True
            if self._url and self._authorised:
                sources.append("camera")
            for source in sources:
                worker = threading.Thread(
                    target=self._reader,
                    args=(source,),
                    name=f"iss-video-{source}",
                    daemon=True,
                )
                self._threads.append(worker)
                worker.start()
        self.frame()

    def set_recorded_enabled(self, enabled: bool) -> None:
        """Change only the local backup; never disable camera recovery or publishing."""
        if type(enabled) is not bool:
            raise ValueError("Recorded fallback must be a boolean")
        process = None
        with self._lock:
            self._backup_enabled = enabled
            if not enabled:
                process = self._processes["recorded"]
                self._running["recorded"] = False
                self._frames["recorded"] = None
                if process is not None:
                    self._terminate_requested["recorded"] = (process, self._clock())
            elif (self._started and not self._recorded_worker_started
                    and not self._stop.is_set() and self._backup.is_file()):
                self._recorded_worker_started = True
                worker = threading.Thread(target=self._reader, args=("recorded",),
                                          name="iss-video-recorded", daemon=True)
                self._threads.append(worker)
                worker.start()
        if process is not None:
            self._terminate(process)
        self.frame()

    def stop(self) -> None:
        with self._lock:
            # Serialise stop with the final check + subprocess creation below.
            # No decoder can be launched after stop has acquired this lock.
            self._stop.set()
            processes = [
                process for process in self._processes.values() if process is not None
            ]
            workers = list(self._threads)
        # Signal both first, so the normal readers can drain/finish concurrently.
        for process in processes:
            self._terminate(process)
        for worker in workers:
            worker.join(timeout=6)
        for process in processes:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        for worker in workers:
            if worker.is_alive():
                worker.join(timeout=1)
        with self._lock:
            self._running = {"camera": False, "recorded": False}
            self._camera_stable_since = None
            self._terminate_requested = {"camera": None, "recorded": None}

    def set_mode(self, mode: str) -> None:
        if mode not in _MODES:
            raise ValueError("Camera mode must be auto, fallback or map")
        with self._lock:
            self._mode = mode
            self._camera_stable_since = None
            processes = [
                process
                for source, process in self._processes.items()
                if process is not None
                and (mode == "map" or (source == "camera" and mode != "auto"))
            ]
            for source, process in self._processes.items():
                if process is not None and process in processes:
                    self._terminate_requested[source] = (process, self._clock())
                    self._running[source] = False
        for process in processes:
            self._terminate(process)
        self.frame()

    def frame(self) -> bytes:
        """Return the latest usable frame or a cached emergency JPEG.

        The consumer calls this at its fixed output FPS. This also advances the
        freshness watchdog, so a stuck decoder can be stopped without letting
        its blocking stdout reader delay failover.
        """
        now = self._clock()
        stop_readers: list[subprocess.Popen[bytes]] = []
        kill_readers: list[tuple[str, subprocess.Popen[bytes]]] = []
        with self._lock:
            for source, process in self._processes.items():
                if process is None:
                    continue
                termination = self._terminate_requested[source]
                if termination is not None and termination[0] is process:
                    if now - termination[1] >= TERMINATE_GRACE_SECONDS:
                        if process.poll() is None:
                            kill_readers.append((source, process))
                        # A new process must get a new watchdog deadline, never
                        # inherit an escalation for an older reader object.
                        self._terminate_requested[source] = None
                    continue
                if not self._running[source]:
                    continue
                last = self._received[source]
                started = self._reader_started[source]
                reference = (
                    max(value for value in (last, started) if value is not None)
                    if (last is not None or started is not None)
                    else None
                )
                if reference is not None and now - reference > self._timeout:
                    self._running[source] = False
                    self._errors[source] = True
                    if source == "camera":
                        self._camera_stable_since = None
                    self._terminate_requested[source] = (process, now)
                    stop_readers.append(process)
            camera_fresh = self._fresh("camera", now)
            if not self._url:
                camera_state, reason = "unconfigured", "camera_unconfigured"
            elif self._mode != "auto" or not self._authorised:
                camera_state, reason = "disabled", "camera_disabled"
            elif not camera_fresh:
                if self._received["camera"] is not None:
                    camera_state, reason = "stale", "camera_stale"
                elif self._errors["camera"]:
                    camera_state, reason = "error", "camera_error"
                else:
                    camera_state, reason = "connecting", "camera_connecting"
            elif (
                self._camera_stable_since is None
                or now - self._camera_stable_since < self._stable
            ):
                camera_state, reason = "recovering", "camera_unstable"
            else:
                camera_state, reason = "live", ""
            if self._mode == "map":
                selected, payload, reason = "map", None, "map_requested"
            elif camera_state == "live" and self._mode == "auto":
                selected, payload = "camera", self._frames["camera"]
            elif self._backup_enabled and self._fresh("recorded", now):
                selected, payload = "recorded", self._frames["recorded"]
                if self._mode == "fallback":
                    reason = "recorded_requested"
            else:
                selected, payload = "map", None
                if self._mode == "fallback":
                    reason = "recorded_unavailable"
            if selected != self._video_mode:
                self._video_mode = selected
                self._switch_count += 1
                self._switch_at = _utc_now()
            status = {
                "camera_configured": bool(self._url and self._authorised),
                "camera_available": camera_fresh
                and self._mode == "auto"
                and self._authorised,
                "camera_state": camera_state,
                "camera_last_frame_at": self._received_at["camera"],
                "video_mode": selected,
                "video_fallback_reason": reason,
                "video_switch_count": self._switch_count,
                "video_switch_at": self._switch_at,
            }
        for process in stop_readers:
            self._terminate(process)
        for source, process in kill_readers:
            try:
                if process.poll() is None:
                    process.kill()
            except OSError:
                # Try again after another bounded grace period if killing the
                # same reader failed. Never kill its possible replacement.
                with self._lock:
                    if self._processes[source] is process:
                        self._terminate_requested[source] = (process, now)
        if payload is None:
            try:
                payload = self._map_frame()
            except Exception:  # noqa: BLE001 - isolate the externally supplied rendering callback
                # A failed map render/file read must not end the live publisher.
                payload = None
            if (
                not payload
                or not payload.startswith(b"\xff\xd8")
                or not payload.endswith(b"\xff\xd9")
            ):
                payload = self._placeholder
                status["video_fallback_reason"] = "map_unavailable"
        self._emit_status(status, now)
        return payload

    def _fresh(self, source: str, now: float) -> bool:
        received = self._received[source]
        started = self._reader_started[source]
        return bool(
            self._running[source]
            and self._frames[source] is not None
            and received is not None
            and (started is None or received >= started)
            and 0 <= now - received <= self._timeout
        )

    def _accept_frame(self, source: str, payload: bytes) -> None:
        now = self._clock()
        with self._lock:
            if self._stop.is_set():
                return
            previous = self._received[source]
            if source == "camera" and (
                self._camera_stable_since is None
                or previous is None
                or now - previous > self._timeout
            ):
                self._camera_stable_since = now
            self._frames[source] = payload
            self._received[source] = now
            self._received_at[source] = _utc_now()
            self._errors[source] = False

    def _reader(self, source: str) -> None:
        while not self._stop.is_set():
            with self._lock:
                allowed = (
                    self._mode == "auto" if source == "camera"
                    else self._mode != "map" and self._backup_enabled
                )
            if not allowed:
                self._stop.wait(0.5)
                continue
            process: subprocess.Popen[bytes] | None = None
            try:
                # No shell and no stderr logging: network URLs may be signed.
                with self._lock:
                    if self._stop.is_set():
                        break
                    allowed = (
                        self._mode == "auto"
                        if source == "camera"
                        else self._mode != "map" and self._backup_enabled
                    )
                    if not allowed:
                        continue
                    process = subprocess.Popen(
                        self._command(source),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        bufsize=0,
                    )
                    self._processes[source] = process
                    self._terminate_requested[source] = None
                    self._running[source] = True
                    self._reader_started[source] = self._clock()
                    if source == "camera":
                        self._camera_stable_since = None
                if process.stdout is not None and not self._stop.is_set():
                    for payload in iter_jpegs(process.stdout):
                        if self._stop.is_set():
                            break
                        self._accept_frame(source, payload)
            except (OSError, ValueError):
                # Do not stringify the exception: Popen errors can expose args.
                with self._lock:
                    self._errors[source] = True
            finally:
                if process is not None:
                    self._dispose(process)
                with self._lock:
                    if self._processes[source] is process:
                        self._processes[source] = None
                        self._terminate_requested[source] = None
                    self._running[source] = False
                    self._errors[source] = not self._stop.is_set()
                    if source == "camera":
                        self._camera_stable_since = None
            self._stop.wait(self._retry)

    def _command(self, source: str) -> list[str]:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-max_alloc",
            "67108864",
            "-filter_threads",
            "1",
            "-filter_complex_threads",
            "1",
            "-threads",
            "1",
            "-max_pixels",
            str(MAX_INPUT_PIXELS),
        ]
        if source == "camera":
            command += [
                "-rw_timeout",
                str(int(self._timeout * 1_000_000)),
                "-protocol_whitelist",
                "http,https,tcp,tls,crypto",
                "-fflags",
                "+genpts",
                "-i",
                self._url,
            ]
        else:
            command += [
                "-protocol_whitelist",
                "file",
                "-stream_loop",
                "-1",
                "-re",
                "-fflags",
                "+genpts",
                "-i",
                str(self._backup),
            ]
        width, height, fps = (
            self.settings.width,
            self.settings.height,
            self.settings.fps,
        )
        command += [
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            (
                f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
            ),
            "-threads",
            "1",
            "-c:v",
            "mjpeg",
            "-pix_fmt",
            "yuvj420p",
            "-q:v",
            "5",
            "-f",
            "mjpeg",
            "pipe:1",
        ]
        return command

    def _emit_status(self, status: dict[str, Any], now: float) -> None:
        with self._lock:
            if self._status_emit_in_progress or (
                self._status_emit_failed and now - self._last_emit_attempt_at < 1
            ):
                return
            previous = self._last_emitted
            structural = {
                key: value
                for key, value in status.items()
                if key != "camera_last_frame_at"
            }
            previous_structural = (
                None
                if previous is None
                else {
                    key: value
                    for key, value in previous.items()
                    if key != "camera_last_frame_at"
                }
            )
            if (status == previous and not self._status_emit_failed) or (
                structural == previous_structural
                and now - self._last_emit_attempt_at < 1
            ):
                return
            self._last_emit_attempt_at = now
            self._status_emit_in_progress = True
        try:
            self._on_status(dict(status))
        except Exception:  # noqa: BLE001 - status sink must never interrupt frame delivery
            # Status persistence is independent of frame delivery.
            with self._lock:
                self._status_emit_in_progress = False
                self._status_emit_failed = True
            return
        with self._lock:
            self._last_emitted = dict(status)
            self._last_emitted_at = now
            self._status_emit_in_progress = False
            self._status_emit_failed = False

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            pass

    @classmethod
    def _dispose(cls, process: subprocess.Popen[bytes]) -> None:
        cls._terminate(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
        finally:
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass

    def _make_placeholder(self) -> bytes:
        image = Image.new("RGB", (self.settings.width, self.settings.height), "#051a2b")
        draw = ImageDraw.Draw(image)
        draw.text(
            (30, self.settings.height // 2 - 15),
            "Camara ISS no disponible",
            fill="#ddedf2",
        )
        draw.text(
            (30, self.settings.height // 2 + 10),
            "Esperando mapa o video de respaldo",
            fill="#8bb8c8",
        )
        destination = io.BytesIO()
        image.save(destination, format="JPEG", quality=85, subsampling=2)
        return destination.getvalue()
