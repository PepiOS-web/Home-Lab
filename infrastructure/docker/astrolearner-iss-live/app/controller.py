from __future__ import annotations

import json
import io
import logging
import math
import queue
import re
import subprocess
import threading
import time
import wave
import os
import tempfile
from collections import deque
from datetime import UTC, datetime, timedelta

import httpx
from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError
from PIL import Image, ImageDraw

from .config import Settings
from .broadcast_metadata import BroadcastMetadataStore, validate_metadata
from .audio_preview import create_music_preview
from .control_page import create_control_page
from .media import create_ambient_music, render_earth_frame, render_map
from .music_status import MusicSession
from .multistream import Destination, StarviosStore, redact_output, tee_output
from .state import StateStore
from .youtube import Broadcast, BroadcastUnavailableError, YouTubeLive
from .video_switcher import VideoSwitcher
from .presentation import PresentationStore
from .stream_dashboard import StreamDashboard
from .dashboard_sources import DashboardSources

LOG = logging.getLogger(__name__)
PROGRESS = re.compile(r"(?P<key>frame|fps|bitrate|drop_frames|out_time_us)=(?P<value>.*)")
FFMPEG_STATUS = re.compile(r"^[A-Za-z0-9_]+=")
YOUTUBE_RATE_LIMIT_COOLDOWN_SECONDS = 300
YOUTUBE_STARTUP_CHECK_SECONDS = 15
YOUTUBE_LIVE_CHECK_SECONDS = 60
OUTPUT_RECOVERY_SECONDS = 120
OUTPUT_RECOVERY_ATTEMPTS = 8
OUTPUT_RECOVERY_STABLE_SECONDS = 60


class FFmpegConnectionError(RuntimeError):
    """A retryable transport failure, with a safe fixed diagnostic reason."""

    def __init__(self, code: int, reason: str = "connection_error") -> None:
        self.reason = reason
        super().__init__(f"FFmpeg terminó antes de tiempo (código {code}): conexión interrumpida ({reason})")


def connection_failure_reason(code: int, detail: str) -> str | None:
    # Do not retry filter/codec/resource failures as though they were a network
    # outage. In particular, never hide the previous VAAPI filter failure.
    if re.search(r"error reinitializing filters|impossible to convert|out of memory|"
                 r"cannot allocate memory|pthread_create|unknown encoder", detail, re.I):
        return None
    # FFmpeg on Windows may return WSAECONNRESET numerically, without the
    # words "connection reset" (the local integration probe runs there too).
    if code in {-10054, 4294957242}:
        return "connection_reset"
    for reason, pattern in (
        ("broken_pipe", r"broken pipe"),
        ("connection_reset", r"connection reset|connection aborted"),
        ("connection_timeout", r"timed out|i/o timeout"),
        ("connection_unavailable", r"connection refused|network is unreachable|no route to host"),
        ("input_output_error", r"input/output error"),
    ):
        if re.search(pattern, detail, re.I):
            return reason
    return "broken_pipe" if code in {224, -32} else None


def _is_youtube_user_rate_limit_error(exc: Exception) -> bool:
    if not isinstance(exc, HttpError):
        return False
    try:
        payload = json.loads(exc.content.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error", {})
    details = error.get("errors", []) if isinstance(error, dict) else []
    return any(
        isinstance(detail, dict)
        and detail.get("reason") == "userRequestsExceedRateLimit"
        for detail in details
    )


class Controller:
    def __init__(self, settings: Settings, store: StateStore) -> None:
        self.settings = settings
        self.store = store
        self.stop_event = threading.Event()
        self.live_requested = threading.Event()
        self._progress_lock = threading.Lock()
        self._progress_enabled = threading.Event()
        self.youtube_rate_limit_until = 0.0
        self._metadata_lock = threading.RLock()
        self._active_broadcast_id: str | None = None
        self.metadata = BroadcastMetadataStore(
            settings.data_dir / "music" / "live-metadata.json", settings.source_label
        )
        self.starvios = StarviosStore(settings.data_dir / "music" / ".starvios.json")
        self._starvios_destination = Destination()
        if settings.auto_start and not settings.dry_run:
            self.live_requested.set()
        self.process: subprocess.Popen[str] | None = None
        self.map_path = settings.status_dir / "map.png"
        self.earth_path = settings.status_dir / "earth.jpg"
        self.video_label_path = settings.status_dir / "video-source.txt"
        self._video_map_stamp: tuple[int, int] | None = None
        self._video_map_jpeg: bytes | None = None
        self.presentation = PresentationStore(settings.data_dir / "music" / "presentation.json",
                                              settings.use_nasa_playlist)
        self.dashboard = StreamDashboard(width=max(640, settings.width), height=max(90, (settings.height // 5) // 2 * 2))
        self._dashboard_active = False
        emergency = Image.new("RGB", (self.dashboard.width, self.dashboard.height), "#071321")
        ImageDraw.Draw(emergency).text((16, 16), "Panel orbital sin actualizar | Esperando datos", fill="#ffffff")
        emergency_buffer = io.BytesIO()
        emergency.save(emergency_buffer, format="JPEG", quality=85)
        emergency.close()
        self.dashboard_jpeg: bytes | None = emergency_buffer.getvalue()
        self.dashboard_png: bytes | None = None
        self.space_sources = DashboardSources(settings.data_dir / "nasa" / "dashboard", self.stop_event)
        self._dashboard_thread = threading.Thread(target=self.update_dashboard, name="iss-dashboard", daemon=True)
        self._space_thread = threading.Thread(target=self.space_sources.run, name="space-snapshots", daemon=True)
        self.video_switcher = (
            VideoSwitcher(settings, self._video_source_status, self._map_video_frame)
            if settings.camera_enabled else None
        )
        if self.video_switcher is not None:
            self.video_switcher.set_recorded_enabled(self.presentation.snapshot()["recorded_fallback_enabled"])
        self.music_path = settings.data_dir / "music" / "astrolearner-lofi-v3.wav"
        hourly_music = settings.data_dir / "music" / "astrolearner-lofi-hour-v1.wav"
        if hourly_music.is_file():
            try:
                with wave.open(str(hourly_music), "rb") as audio:
                    if (
                        audio.getnchannels() == 2
                        and audio.getsampwidth() == 2
                        and abs(audio.getnframes() / audio.getframerate() - 3600) < 0.01
                    ):
                        self.music_path = hourly_music
            except (OSError, EOFError, wave.Error):
                LOG.warning("La sesión Lo-Fi de una hora no es válida; se usa la pista anterior")
        self.music_session = MusicSession.from_audio(self.music_path)
        self._classic_music_path = self.music_path
        self._select_music()
        self.position_track: deque[tuple[float, float]] = deque(maxlen=160)
        self._thread = threading.Thread(
            target=self.run, name="iss-live-controller", daemon=True
        )
        self._map_thread = threading.Thread(
            target=self.update_position, name="iss-position", daemon=True
        )
        self._earth_thread = threading.Thread(
            target=self.update_earth, name="nasa-epic", daemon=True
        )

    def start(self) -> None:
        # Isolated camera dry-runs cannot publish and do not need to synthesize
        # ten minutes of music just to inspect video or run the synthetic probe.
        if not (self.settings.camera_enabled and self.settings.dry_run):
            create_ambient_music(self.music_path)
            create_music_preview(self.music_path, self.settings.status_dir)
        if self.music_path.name == "astrolearner-lofi-hour-v1.wav":
            label = "AstroLearner Lo-Fi · 12 temas originales · sesión de 1 h en bucle"
            self.store.update(music_track=label, music_session=label)
        elif self.music_path.name == "astrolearner-melodic-hour-v1.wav":
            label = "AstroLearner · Piano orbital melódico · sesión de 1 h"
            self.store.update(music_track=label, music_session=label)
        create_control_page(self.settings.status_dir)
        self.store.update(
            control_ready=bool(self.settings.control_token) and not self.settings.dry_run,
            camera_enabled=self.settings.camera_enabled,
            camera_timeout_seconds=self.settings.camera_timeout_seconds,
        )
        render_earth_frame(
            None, self.earth_path, self.settings.width, self.settings.height
        )
        if (
            self.settings.use_nasa_playlist
            and self.settings.nasa_loop_video.is_file()
        ):
            self.store.update(
                visual_source="NASA Image and Video Library · vídeos grabados", video_mode="recorded",
            )
        elif not self.settings.camera_enabled:
            self.store.update(video_mode="external", visual_source=self.settings.source_label)
        self._map_thread.start()
        if self.video_switcher is not None:
            self._video_source_status({
                "camera_configured": bool(self.settings.camera_url and self.settings.camera_authorized),
                "camera_available": False,
                "camera_state": "connecting" if self.settings.camera_url and self.settings.camera_authorized else "unconfigured",
                "video_mode": "map", "video_fallback_reason": "starting",
            })
            self.video_switcher.start()
        else:
            self._earth_thread.start()
        self._thread.start()

    def _ensure_dashboard_workers(self) -> None:
        with self._metadata_lock:
            for worker in (self._dashboard_thread, self._space_thread):
                if worker.ident is None and not self.stop_event.is_set():
                    worker.start()

    def update_dashboard(self) -> None:
        while not self.stop_event.is_set():
            try:
                frame = self.dashboard.render(self.store.snapshot(),
                                              track=tuple(self.position_track.copy()),
                                              cards=self.space_sources.snapshot())
                if frame is not None:
                    self.dashboard_jpeg, self.dashboard_png = frame.jpeg, frame.png
            except Exception:
                # A failed optional data card cannot bring down the encoder.
                LOG.warning("Panel informativo temporalmente sin actualizar")
            self.stop_event.wait(1)

    def _select_music(self) -> None:
        """Freeze an already-rendered track at block start, never overwrite open audio."""
        candidate = self._classic_music_path
        if self.presentation.snapshot()["music_style"] == "melodic":
            melodic = self.settings.data_dir / "music" / "astrolearner-melodic-hour-v1.wav"
            session = self._hourly_music_session(melodic)
            if session is not None:
                candidate = melodic
        self.music_path = candidate
        self.music_session = MusicSession.from_audio(candidate)

    @staticmethod
    def _hourly_music_session(path):
        try:
            with wave.open(str(path), "rb") as audio:
                if audio.getnchannels() != 2 or audio.getsampwidth() != 2 or audio.getframerate() < 8000:
                    return None
            session = MusicSession.from_audio(path)
            return session if session is not None and abs(session.duration_seconds - 3600) < 0.01 else None
        except (OSError, EOFError, wave.Error):
            return None

    def presentation_snapshot(self) -> dict:
        value = self.presentation.snapshot()
        melodic = self._hourly_music_session(self.settings.data_dir / "music" / "astrolearner-melodic-hour-v1.wav")
        value.update(dashboard_active=self._dashboard_active,
                     music_active="melodic" if self.music_path.name == "astrolearner-melodic-hour-v1.wav" else "classic",
                     melodic_available=melodic is not None and abs(melodic.duration_seconds - 3600) < 0.01)
        return value

    def save_presentation(self, **value) -> dict:
        with self._metadata_lock:
            value = self.presentation.validate(value)
            if not self.settings.camera_enabled:
                raise RuntimeError("La nueva presentación necesita el selector de cámara habilitado")
            if value["dashboard_enabled"] and (self.settings.width < 640 or self.settings.height < 360):
                raise RuntimeError("El panel necesita una resolución de al menos 640×360")
            if value["music_style"] == "melodic":
                session = self._hourly_music_session(self.settings.data_dir / "music" / "astrolearner-melodic-hour-v1.wav")
                if session is None:
                    raise RuntimeError("Primero prepara y valida la sesión melódica de una hora")
            self.presentation.save(value)
            if self.video_switcher is not None:
                self.video_switcher.set_recorded_enabled(value["recorded_fallback_enabled"])
            result = self.presentation_snapshot()
            result["applies"] = {"recorded_fallback_enabled": "now", "dashboard_enabled": "next_block", "music_style": "next_block"}
            return result

    def _map_video_frame(self) -> bytes | None:
        """Cache the rendered map JPEG, not a new conversion per video frame."""
        try:
            info = self.map_path.stat()
            stamp = (info.st_mtime_ns, info.st_size)
            if stamp != self._video_map_stamp:
                with Image.open(self.map_path) as image:
                    image = image.convert("RGB")
                    if image.size != (self.settings.width, self.settings.height):
                        image = image.resize((self.settings.width, self.settings.height))
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG", quality=85, subsampling=2)
                self._video_map_jpeg = buffer.getvalue()
                self._video_map_stamp = stamp
        except (OSError, ValueError):
            pass
        return self._video_map_jpeg

    def _video_source_status(self, values: dict) -> None:
        # Public status/overlay contains only allowlisted diagnostic fields,
        # never the input URL or FFmpeg's free-form error messages.
        allowed = {
            "camera_configured", "camera_available", "camera_state", "camera_last_frame_at",
            "video_mode", "video_fallback_reason", "video_switch_count", "video_switch_at",
        }
        public = {key: value for key, value in values.items() if key in allowed}
        mode = public.get("video_mode")
        labels = {
            "camera": "Senal externa ISS | Puede incluir imagenes de reserva del proveedor",
            "recorded": "NASA | VIDEO GRABADO | Camara ISS no seleccionada o no disponible",
            "map": "MAPA ORBITAL | Camara ISS no seleccionada o no disponible",
        }
        visual_labels = {
            "camera": "Señal externa ISS · revisar indicaciones del proveedor",
            "recorded": "NASA Image and Video Library · vídeos grabados de respaldo",
            "map": "Mapa de seguimiento orbital ISS · respaldo",
        }
        if mode in labels:
            label = labels[mode]
            try:
                old_label = self.video_label_path.read_text(encoding="utf-8")
            except OSError:
                old_label = ""
            if old_label != label:
                self.video_label_path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix="video-label-", dir=self.video_label_path.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as output:
                        output.write(label)
                    os.replace(temporary, self.video_label_path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            public["visual_source"] = visual_labels[mode]
        self.store.update(**public)

    def request_live_start(self) -> None:
        with self._metadata_lock:
            try:
                self.starvios.load()
            except ValueError as exc:
                raise RuntimeError(str(exc)) from None
            self._request_live_start()

    def _request_live_start(self) -> None:
        if self.settings.dry_run:
            raise RuntimeError("La emisión está bloqueada mientras siga activo dry-run")
        if not self.settings.camera_enabled and not self.settings.source_url and not (
            self.settings.use_nasa_playlist and self.settings.nasa_loop_video.is_file()
        ):
            raise RuntimeError("No hay una fuente visual disponible")
        if not self.settings.youtube_token.is_file():
            raise RuntimeError("Falta la autorización OAuth de YouTube")
        retry_after = int(self.youtube_rate_limit_until - time.monotonic())
        if retry_after > 0:
            minutes = max(1, (retry_after + 59) // 60)
            raise RuntimeError(
                "YouTube aplicó un límite temporal de solicitudes; "
                f"espera al menos {minutes} min antes de volver a iniciar"
            )
        if self.live_requested.is_set():
            return
        self.live_requested.set()
        self.store.update(
            status="preparando emisión pública",
            mode="youtube",
            source_status="preparando",
            live_requested=True,
            last_error="",
            youtube_watch_url="",
            reconnect_count=0,
            last_reconnect_at=None,
            last_reconnect_reason="",
        )

    def metadata_snapshot(self) -> dict:
        with self._metadata_lock:
            return {
                **self.metadata.snapshot(),
                "active": bool(self._active_broadcast_id and self.live_requested.is_set()),
            }

    def starvios_snapshot(self) -> dict:
        with self._metadata_lock:
            return self.starvios.load().public()

    def save_starvios(self, **values) -> dict:
        with self._metadata_lock:
            if (self.live_requested.is_set() or self.store.snapshot()["ffmpeg_running"]
                    or (self.process is not None and self.process.poll() is None)):
                raise RuntimeError("Detén la emisión antes de cambiar los destinos")
            try:
                value = self.starvios.save(**values)
            except OSError:
                raise RuntimeError("No se pudo guardar la configuración privada de Starvios") from None
            self.store.update(starvios_enabled=value.enabled)
            return value.public()

    def save_metadata(
        self, title: str, description: str, apply_to_current: bool = False
    ) -> dict:
        value = validate_metadata(title, description)
        with self._metadata_lock:
            if apply_to_current and not (
                self._active_broadcast_id and self.live_requested.is_set()
                and not self.stop_event.is_set()
            ):
                raise RuntimeError("No hay un directo actual que actualizar")
            try:
                self.metadata.save(**value)
            except OSError as exc:
                raise RuntimeError("No se pudieron guardar los textos en el servidor") from exc
            if apply_to_current:
                try:
                    # Do not share the controller thread's Google transport.
                    youtube = YouTubeLive(
                        self.settings.youtube_token, self.settings.privacy,
                        self.settings.source_label,
                    )
                    youtube.update_metadata(self._active_broadcast_id, **value)
                except Exception as exc:
                    # A metadata failure must never stop FFmpeg or create a new live.
                    LOG.warning("No se pudo actualizar el título y descripción en YouTube (%s)", type(exc).__name__)
                    raise RuntimeError(
                        "Los textos se guardaron para próximos directos, pero YouTube "
                        "no pudo actualizar la emisión actual. No se ha interrumpido "
                        "el directo; espera antes de reintentar."
                    ) from exc
            return {
                **value, "applied_to_current": apply_to_current,
                "status": "actualizado" if apply_to_current else "guardado",
            }

    def _clear_active_broadcast(self) -> None:
        with self._metadata_lock:
            self._active_broadcast_id = None

    def request_live_stop(self) -> None:
        # Serialize stop against metadata writes: after stop returns, no request
        # can edit the completed video using an old status/watch URL.
        with self._metadata_lock:
            self._request_live_stop()

    def _request_live_stop(self) -> None:
        with self._progress_lock:
            was_requested = self.live_requested.is_set()
            self.live_requested.clear()
            self._progress_enabled.clear()
            self._active_broadcast_id = None
            process = self.process
            if process is not None and process.poll() is None:
                process.terminate()
            self.store.update(
                status="deteniendo" if was_requested else "simulación lista",
                mode="youtube" if was_requested else "simulacion",
                source_status="deteniendo" if was_requested else "fuente visual configurada",
                live_requested=False,
                remaining_seconds=0,
                next_restart_at=None,
                music_playback_active=False,
            )

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if self.video_switcher is not None:
            self.video_switcher.stop()
        for thread in (self._thread, self._map_thread, self._earth_thread,
                       self._dashboard_thread, self._space_thread):
            if thread.is_alive():
                thread.join(timeout=15 if thread is self._thread else 5)

    def update_earth(self) -> None:
        cache = self.settings.data_dir / "nasa" / "epic"
        cache.mkdir(parents=True, exist_ok=True)
        while not self.stop_event.is_set():
            try:
                response = httpx.get(
                    "https://epic.gsfc.nasa.gov/api/natural",
                    timeout=20,
                    follow_redirects=True,
                )
                response.raise_for_status()
                items = response.json()
                if not isinstance(items, list) or not items:
                    raise ValueError("NASA EPIC no devolvió imágenes")
                for item in items[-8:]:
                    if self.stop_event.is_set():
                        return
                    name = str(item["image"])
                    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                        raise ValueError("Identificador EPIC no válido")
                    captured = str(item["date"])
                    date = captured[:10].replace("-", "/")
                    image_url = (
                        f"https://epic.gsfc.nasa.gov/archive/natural/{date}/jpg/"
                        f"{name}.jpg"
                    )
                    source = cache / f"{name}.jpg"
                    if not source.exists():
                        temporary = source.with_suffix(".download")
                        size = 0
                        try:
                            with httpx.stream(
                                "GET",
                                image_url,
                                timeout=45,
                                follow_redirects=True,
                            ) as image:
                                image.raise_for_status()
                                if not image.headers.get(
                                    "content-type", ""
                                ).startswith("image/"):
                                    raise ValueError(
                                        "NASA EPIC devolvió contenido no gráfico"
                                    )
                                with temporary.open("wb") as output:
                                    for chunk in image.iter_bytes():
                                        size += len(chunk)
                                        if size > 25 * 1024 * 1024:
                                            raise ValueError(
                                                "Imagen NASA EPIC demasiado grande"
                                            )
                                        output.write(chunk)
                        except Exception:
                            temporary.unlink(missing_ok=True)
                            raise
                        temporary.replace(source)
                    render_earth_frame(
                        source,
                        self.earth_path,
                        self.settings.width,
                        self.settings.height,
                        captured,
                    )
                    if not (
                        self.settings.use_nasa_playlist
                        and self.settings.nasa_loop_video.is_file()
                    ):
                        self.store.update(
                            visual_source="NASA EPIC / DSCOVR",
                            visual_updated_at=captured,
                        )
                    if self.stop_event.wait(30):
                        return
            except (httpx.HTTPError, KeyError, TypeError, ValueError, OSError) as exc:
                LOG.warning("NASA EPIC imagery unavailable: %s", exc)
                if not (
                    self.settings.use_nasa_playlist
                    and self.settings.nasa_loop_video.is_file()
                ):
                    self.store.update(
                        visual_source="NASA EPIC temporalmente no disponible"
                    )
            self.stop_event.wait(900)

    def update_position(self) -> None:
        lat = lon = 0.0
        altitude = 420.0
        velocity: float | None = None
        while not self.stop_event.is_set():
            try:
                response = httpx.get(
                    self.settings.position_url, timeout=10, follow_redirects=True
                )
                response.raise_for_status()
                data = response.json()
                new_lat = float(data["latitude"])
                new_lon = float(data["longitude"])
                new_altitude = float(data.get("altitude", altitude))
                new_velocity = float(data.get("velocity", 0.0))
                if not all(math.isfinite(value) for value in (new_lat, new_lon, new_altitude, new_velocity)):
                    raise ValueError("Datos orbitales no finitos")
                if not -90 <= new_lat <= 90 or not -180 <= new_lon <= 180:
                    raise ValueError("Coordenadas orbitales fuera de rango")
                observed_at = datetime.now(UTC)
                if "timestamp" in data:
                    timestamp = data["timestamp"]
                    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                        raise ValueError("Fecha orbital no válida")
                    observed_at = datetime.fromtimestamp(timestamp, UTC)
                    if observed_at > datetime.now(UTC) + timedelta(seconds=30):
                        raise ValueError("Fecha orbital futura")
                lat, lon, altitude, velocity = new_lat, new_lon, new_altitude, new_velocity
                self.position_track.append((lat, lon))
                self.store.update(
                    latitude=round(lat, 3),
                    longitude=round(lon, 3),
                    altitude_km=round(altitude, 1),
                    velocity_kmh=round(velocity, 1),
                    position_updated_at=observed_at.isoformat(),
                )
            except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
                LOG.warning("ISS position unavailable: %s", exc)
            render_map(
                self.map_path,
                self.settings.width,
                self.settings.height,
                lat,
                lon,
                altitude,
                list(self.position_track),
                velocity,
            )
            self.stop_event.wait(15)

    def run(self) -> None:
        created_blocks = 0
        while not self.stop_event.is_set():
            if not self.live_requested.is_set():
                if self.store.snapshot().get("status") == "error":
                    # Keep the last failure visible until a new start is requested.
                    self.store.update(
                        mode="simulacion",
                        live_requested=False,
                        bitrate="simulado",
                        fps=float(self.settings.fps),
                        remaining_seconds=0,
                        next_restart_at=None,
                    )
                else:
                    self.store.update(
                        status="simulación lista",
                        mode="simulacion",
                        source_status=(
                            "fuente visual configurada"
                            if self.settings.camera_enabled or self.settings.source_url
                            or (
                                self.settings.use_nasa_playlist
                                and self.settings.nasa_loop_video.is_file()
                            )
                            else "pendiente de fuente"
                        ),
                        live_requested=False,
                        bitrate="simulado",
                        fps=float(self.settings.fps),
                        remaining_seconds=0,
                        next_restart_at=None,
                        youtube_watch_url="",
                    )
                self.live_requested.wait(timeout=1)
                continue

            # Let Uvicorn finish binding the local MJPEG endpoint before FFmpeg starts.
            if self.stop_event.wait(3):
                return
            if not self.live_requested.is_set():
                continue
            youtube: YouTubeLive | None = None
            broadcast = None
            try:
                if not self.settings.camera_enabled and not self.settings.source_url and not (
                    self.settings.use_nasa_playlist
                    and self.settings.nasa_loop_video.is_file()
                ):
                    raise RuntimeError("Falta ISS_LIVE_SOURCE_URL")
                youtube = YouTubeLive(
                    self.settings.youtube_token,
                    self.settings.privacy,
                    self.settings.source_label,
                )
                with self._metadata_lock:
                    if not self.live_requested.is_set():
                        continue
                    metadata = self.metadata.snapshot()
                    broadcast = youtube.create(self.settings.block_seconds, **metadata)
                    self._active_broadcast_id = broadcast.broadcast_id
                if not self.live_requested.is_set():
                    youtube.complete(broadcast.broadcast_id)
                    self._mark_live_stopped()
                    continue
                created_blocks += 1
                self._run_broadcast(youtube, broadcast)
                self._clear_active_broadcast()
                youtube.complete(broadcast.broadcast_id)
            except Exception as exc:
                self._clear_active_broadcast()
                if isinstance(exc, BroadcastUnavailableError):
                    self.live_requested.clear()
                    if youtube is not None and broadcast is not None:
                        try:
                            youtube.complete(broadcast.broadcast_id)
                        except Exception:
                            LOG.exception("Could not close unavailable YouTube broadcast")
                    LOG.error("YouTube broadcast verification failed: %s", exc)
                    self.store.update(
                        status="error",
                        mode="simulacion",
                        last_error=str(exc),
                        source_status="error",
                        live_requested=False,
                        remaining_seconds=0,
                        next_restart_at=None,
                        youtube_watch_url="",
                    )
                    continue
                if _is_youtube_user_rate_limit_error(exc):
                    self.live_requested.clear()
                    self.youtube_rate_limit_until = (
                        time.monotonic() + YOUTUBE_RATE_LIMIT_COOLDOWN_SECONDS
                    )
                    if self.process is not None and self.process.poll() is None:
                        self.process.terminate()
                    message = (
                        "YouTube alcanzó el límite temporal de solicitudes. "
                        "Se detuvo el directo y no habrá reintentos automáticos; "
                        "espera al menos 5 minutos antes de intentarlo una sola vez. "
                        f"Detalle: {exc}"
                    )
                    LOG.error("Stopping live after YouTube rate limit: %s", exc)
                    self.store.update(
                        status="error",
                        mode="simulacion",
                        last_error=message,
                        source_status="error",
                        live_requested=False,
                        remaining_seconds=0,
                        next_restart_at=None,
                        youtube_watch_url="",
                    )
                    continue
                if not self.live_requested.is_set() and not self.stop_event.is_set():
                    if youtube is not None and broadcast is not None:
                        try:
                            youtube.complete(broadcast.broadcast_id)
                        except Exception:
                            LOG.exception("Could not close stopped YouTube broadcast")
                    self._mark_live_stopped()
                    continue
                LOG.exception("Live block failed")
                if youtube is not None and broadcast is not None:
                    try:
                        youtube.complete(broadcast.broadcast_id)
                    except Exception:
                        LOG.exception("Could not close failed YouTube broadcast")
                self.store.update(
                    status="error",
                    last_error=str(exc),
                    source_status="error",
                    live_requested=False,
                    remaining_seconds=0,
                    next_restart_at=None,
                )
                # An unrecoverable error is not permission to create a different
                # public video. Only normal block expiry rotates the broadcast.
                self.live_requested.clear()
                continue
            finally:
                self._clear_active_broadcast()

            if not self.live_requested.is_set():
                self._mark_live_stopped()
                continue
            if (
                self.settings.max_blocks
                and created_blocks >= self.settings.max_blocks
            ):
                self.store.update(
                    status="bloque finalizado",
                    source_status="detenida",
                    mode="simulacion",
                    live_requested=False,
                    remaining_seconds=0,
                    next_restart_at=None,
                )
                self.live_requested.clear()
                continue
            self._gap()

    def _mark_live_stopped(self) -> None:
        self.store.update(
            status="detenido",
            mode="simulacion",
            source_status="detenida",
            live_requested=False,
            remaining_seconds=0,
            next_restart_at=None,
            youtube_watch_url="",
        )

    def _wait_while_live(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0, seconds)
        while self.live_requested.is_set() and not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.stop_event.wait(min(1, remaining))

    def _run_broadcast(self, youtube: YouTubeLive, broadcast: Broadcast) -> None:
        """Reconnect the same broadcast, never reset its original block clock."""
        self._dashboard_active = (self.settings.camera_enabled and self.settings.width >= 640
                                  and self.settings.height >= 360 and self.presentation.snapshot()["dashboard_enabled"])
        if self._dashboard_active:
            self._ensure_dashboard_workers()
        self._select_music()
        self.store.update(music_session=("AstroLearner · Piano orbital melódico · 1 h"
                                        if self.music_path.name == "astrolearner-melodic-hour-v1.wav"
                                        else "AstroLearner Lo-Fi · sesión original"))
        # Freeze the optional destination for this block. Portal changes are
        # refused while requested/running; local file edits take effect next block.
        self._starvios_destination = self.starvios.load()
        if self._starvios_destination.enabled and self.settings.encoder != "libx264":
            raise RuntimeError("El multistream requiere libx264 para el perfil CBR validado")
        self.store.update(starvios_enabled=self._starvios_destination.enabled)
        start = datetime.now(UTC)
        deadline = time.monotonic() + self.settings.block_seconds
        failures = 0
        recovery_started: float | None = None
        missing = 0
        media_offset = 0.0
        send = True
        self.store.update(reconnect_count=0, last_reconnect_at=None, last_reconnect_reason="")
        while self.live_requested.is_set() and not self.stop_event.is_set():
            if time.monotonic() >= deadline:
                return
            if send:
                attempt_started = time.monotonic()
                try:
                    self._run_ffmpeg(broadcast.rtmp_url, broadcast.watch_url, youtube,
                                     broadcast.broadcast_id, broadcast.stream_id,
                                     block_started_at=start, block_deadline=deadline,
                                     music_offset_seconds=media_offset)
                    if (self.live_requested.is_set() and not self.stop_event.is_set()
                            and time.monotonic() < deadline):
                        raise RuntimeError("El envío terminó antes del límite sin una parada solicitada; no se creará otra emisión.")
                    return
                except FFmpegConnectionError as exc:
                    if not self.live_requested.is_set() or self.stop_event.is_set() or time.monotonic() >= deadline:
                        return
                    # Count a new outage after a stable minute, rather than
                    # exhausting a lifetime limit on occasional short cuts.
                    encoded = self.store.snapshot().get("ffmpeg_out_time_seconds")
                    if (time.monotonic() - attempt_started >= OUTPUT_RECOVERY_STABLE_SECONDS
                            and isinstance(encoded, (float, int)) and math.isfinite(encoded)
                            and encoded >= OUTPUT_RECOVERY_STABLE_SECONDS):
                        failures = 0
                        recovery_started = None
                    if recovery_started is None:
                        recovery_started = time.monotonic()
                    if isinstance(encoded, (float, int)) and math.isfinite(encoded) and encoded > 0:
                        media_offset += encoded
                    self.store.update(last_reconnect_reason=exc.reason)
                    LOG.warning("Output connection interrupted (%s); retaining same YouTube broadcast", exc.reason)
                    send = False

            now = time.monotonic()
            assert recovery_started is not None
            if now >= deadline:
                return
            # A prolonged outage backs off to one attempt per minute. It does
            # not finalize the video or reset its original 10h50 block clock.
            slow = failures >= OUTPUT_RECOVERY_ATTEMPTS or now - recovery_started >= OUTPUT_RECOVERY_SECONDS
            failures += 1
            state = self.store.snapshot()
            self.store.update(
                status="recuperando el mismo directo" if not slow else "sin conexión; reintentando el mismo directo",
                source_status="reconectando",
                youtube_watch_url=broadcast.watch_url, live_requested=True,
                block_started_at=start.isoformat(),
                next_restart_at=(start + timedelta(seconds=self.settings.block_seconds)).isoformat(),
                elapsed_seconds=int(now - (deadline - self.settings.block_seconds)),
                remaining_seconds=max(0, int(deadline - now)),
                ffmpeg_running=False, music_playback_active=False,
                reconnect_count=state["reconnect_count"] + 1,
                last_reconnect_at=datetime.now(UTC).isoformat(),
                youtube_check_error="Recuperando la salida; la última confirmación de YouTube puede estar desactualizada",
                last_error="Conexión interrumpida; intentando recuperar esta misma emisión",
            )
            LOG.warning("Recovering same YouTube broadcast (attempt %d)", failures)
            self._wait_while_live(min(60 if slow else min(5 * failures, 30), deadline - now))
            if not self.live_requested.is_set() or self.stop_event.is_set() or time.monotonic() >= deadline:
                return
            try:
                current = youtube.broadcast_status(broadcast.broadcast_id)
            except (HttpError, TransportError, OSError, TimeoutError) as exc:
                if _is_youtube_user_rate_limit_error(exc):
                    raise
                # If Google cannot confirm the original video, don't publish to
                # a different one or guess that it is safe to send.
                LOG.warning("Could not verify broadcast for recovery (%s)", type(exc).__name__)
                continue
            if not self.live_requested.is_set() or self.stop_event.is_set() or time.monotonic() >= deadline:
                return
            if current is None:
                missing += 1
                if missing >= 2:
                    raise BroadcastUnavailableError("YouTube no encuentra la emisión original; no se creará otra automáticamente.")
                continue
            missing = 0
            if current["privacy_status"] != self.settings.privacy:
                raise BroadcastUnavailableError("La privacidad de la emisión original ha cambiado; recuperación cancelada.")
            if current["life_cycle_status"] in {"complete", "revoked"}:
                raise BroadcastUnavailableError("YouTube ya cerró la emisión original; no puede recuperarse ni se creará otra automáticamente.")
            send = True

    def _run_simulation(self) -> None:
        restart_count = 0
        while not self.stop_event.is_set():
            start = datetime.now(UTC)
            end = start + timedelta(seconds=self.settings.block_seconds)
            self.store.update(
                status="simulación lista",
                mode="simulacion",
                source_status=(
                    "fuente visual configurada"
                    if self.settings.source_url
                    else "pendiente de fuente"
                ),
                block_started_at=start.isoformat(),
                next_restart_at=end.isoformat(),
                last_error="",
                restart_count=restart_count,
            )
            while datetime.now(UTC) < end and not self.stop_event.wait(1):
                elapsed = int((datetime.now(UTC) - start).total_seconds())
                self.store.update(
                    elapsed_seconds=elapsed,
                    remaining_seconds=max(0, self.settings.block_seconds - elapsed),
                    bitrate="simulado",
                    fps=float(self.settings.fps),
                )
            restart_count += 1
            self._gap(restart_count)

    def _run_ffmpeg(
        self,
        output_url: str,
        watch_url: str,
        youtube: YouTubeLive,
        broadcast_id: str,
        stream_id: str,
        *, block_started_at: datetime | None = None, block_deadline: float | None = None,
        music_offset_seconds: float = 0,
    ) -> None:
        start = block_started_at or datetime.now(UTC)
        end = start + timedelta(seconds=self.settings.block_seconds)
        self.store.update(
            status="conectando",
            mode="youtube",
            source_status="conectando",
            block_started_at=start.isoformat(),
            next_restart_at=end.isoformat(),
            youtube_watch_url=watch_url,
            last_error="",
            ffmpeg_frame_count=0,
            last_frame_at=None,
            last_progress_at=None,
            ffmpeg_out_time_seconds=None,
            music_playback_active=False,
            music_track_index=None,
            music_track_count=0,
            music_track_elapsed_seconds=None,
            music_track_duration_seconds=None,
            music_session_elapsed_seconds=None,
            music_session_duration_seconds=None,
            youtube_lifecycle_status="unknown",
            youtube_privacy_status="unknown",
            youtube_stream_status="unknown",
            youtube_health_status="unknown",
            youtube_checked_at=None,
            youtube_health_updated_at=None,
            youtube_health_issues=[],
            youtube_check_error="",
        )
        command = self._ffmpeg_command(output_url, music_offset_seconds=music_offset_seconds)
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.process.stderr is not None
        self.store.update(ffmpeg_running=True,
                          starvios_output_active=self._starvios_destination.enabled and not self.settings.dry_run,
                          starvios_remote_verified=False)
        self._progress_enabled.set()
        process = self.process
        youtube_confirmed = threading.Event()
        # Drain stderr independently of the bounded Google requests. A slow
        # health query must not fill FFmpeg's pipe and interrupt the stream.
        lines: queue.Queue[tuple[str, datetime] | None] = queue.Queue(maxsize=512)

        def read_lines() -> None:
            def enqueue(item: tuple[str, datetime] | None) -> None:
                try:
                    lines.put_nowait(item)
                except queue.Full:
                    # Keep recent progress rather than an unbounded diagnostic
                    # backlog; this is observability, not a video/audio buffer.
                    try:
                        lines.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        lines.put_nowait(item)
                    except queue.Full:
                        pass

            try:
                for raw_line in process.stderr:
                    line = raw_line.strip()
                    observed_at = datetime.now(UTC)
                    # Publish real progress even while the controller is waiting
                    # for Google. Stop is serialized so old progress cannot undo
                    # the user's stop or revive music on a terminated process.
                    with self._progress_lock:
                        if (self._progress_enabled.is_set() and self.live_requested.is_set()
                                and not self.stop_event.is_set()):
                            self._parse_progress(line, start, youtube_confirmed.is_set(), observed_at=observed_at,
                                                 music_offset_seconds=music_offset_seconds)
                    if line and not FFMPEG_STATUS.match(line):
                        enqueue((line, observed_at))
            finally:
                enqueue(None)

        reader = threading.Thread(target=read_lines, name="ffmpeg-progress", daemon=True)
        reader.start()
        deadline = block_deadline if block_deadline is not None else time.monotonic() + self.settings.block_seconds
        diagnostics: deque[str] = deque(maxlen=32)
        streaming_started_at = time.monotonic()
        last_youtube_check = 0.0
        youtube_live = False
        missing_broadcast_checks = 0
        verification_error = ""
        try:
            while True:
                now = time.monotonic()
                if (
                    self.stop_event.is_set()
                    or not self.live_requested.is_set()
                    or now >= deadline
                ):
                    process.terminate()
                    break
                interval = YOUTUBE_LIVE_CHECK_SECONDS if youtube_live else YOUTUBE_STARTUP_CHECK_SECONDS
                if now - last_youtube_check >= interval:
                    last_youtube_check = now
                    try:
                        state = youtube.broadcast_status(broadcast_id)
                    except (HttpError, TransportError, OSError, TimeoutError) as exc:
                        LOG.warning("Could not verify YouTube lifecycle (%s)", type(exc).__name__)
                        self.store.update(youtube_check_error="No se pudo consultar YouTube; la última confirmación puede estar desactualizada")
                        if not youtube_live and now - streaming_started_at > 180:
                            verification_error = (
                                "No se pudo confirmar con la API de YouTube que la "
                                "emisión esté visible tras 3 minutos."
                            )
                    else:
                        if state is None:
                            youtube_confirmed.clear()
                            missing_broadcast_checks += 1
                            self.store.update(youtube_lifecycle_status="missing", youtube_check_error="YouTube no encuentra la emisión")
                            if missing_broadcast_checks >= 2:
                                verification_error = (
                                    "YouTube ya no encuentra la emisión creada; "
                                    "se detuvo el envío para evitar un falso directo."
                                )
                        else:
                            missing_broadcast_checks = 0
                            lifecycle = state["life_cycle_status"]
                            privacy = state["privacy_status"]
                            self.store.update(youtube_lifecycle_status=lifecycle, youtube_privacy_status=privacy)
                            if privacy != self.settings.privacy:
                                verification_error = (
                                    "La privacidad de la emisión en YouTube no coincide "
                                    f"con la configuración ({privacy})."
                                )
                            elif lifecycle in {"complete", "revoked"}:
                                verification_error = (
                                    "YouTube marcó la emisión como "
                                    f"{lifecycle}; se detuvo el envío."
                                )
                            elif lifecycle == "live":
                                youtube_live = True
                                youtube_confirmed.set()
                            else:
                                youtube_live = False
                                youtube_confirmed.clear()
                                if now - streaming_started_at > 180:
                                    verification_error = (
                                        "YouTube no confirmó el estado live en 3 minutos "
                                        f"(estado actual: {lifecycle})."
                                    )
                            if not verification_error:
                                self._update_youtube_health(youtube, stream_id)
                    if verification_error:
                        youtube_confirmed.clear()
                        process.terminate()
                        break
                if self.stop_event.is_set() or not self.live_requested.is_set():
                    process.terminate()
                    break
                try:
                    item = lines.get(timeout=1)
                except queue.Empty:
                    if process.poll() is not None and not reader.is_alive():
                        break
                    continue
                if item is None:
                    break
                line, observed_at = item
                if line and not FFMPEG_STATUS.match(line):
                    # RTMP URLs contain the private YouTube stream key.
                    diagnostics.append(redact_output(line, output_url,
                                       self._starvios_destination.url if self._starvios_destination.enabled else "")[-500:])
            # Infinite FIFO recovery must not postpone Stop or the original
            # block limit while flushing an unavailable destination.
            try:
                return_code = process.wait(timeout=3 if self._starvios_destination.enabled else 20)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=5)
        finally:
            with self._progress_lock:
                self._progress_enabled.clear()
                self.store.update(ffmpeg_running=False, music_playback_active=False,
                                  starvios_output_active=False)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3 if self._starvios_destination.enabled else 20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            reader.join(timeout=2)
        if verification_error:
            raise BroadcastUnavailableError(verification_error)
        if (
            time.monotonic() < deadline
            and not self.stop_event.is_set()
            and self.live_requested.is_set()
        ):
            detail = " | ".join(diagnostics)
            reason = connection_failure_reason(return_code, detail)
            if reason is not None:
                raise FFmpegConnectionError(return_code, reason)
            message = f"FFmpeg terminó antes de tiempo (código {return_code})"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message)

    def _update_youtube_health(self, youtube: YouTubeLive, stream_id: str) -> None:
        try:
            health = youtube.stream_health(stream_id)
        except (HttpError, TransportError, OSError, TimeoutError) as exc:
            LOG.warning("Could not read YouTube ingest health (%s)", type(exc).__name__)
            self.store.update(youtube_check_error="No se pudo consultar la salud de la señal en YouTube")
            return
        if health is None:
            self.store.update(
                youtube_checked_at=datetime.now(UTC).isoformat(),
                youtube_stream_status="unknown", youtube_health_status="unknown",
                youtube_health_updated_at=None, youtube_health_issues=[],
                youtube_check_error="YouTube no encuentra la entrada de vídeo",
            )
            return
        self.store.update(
            youtube_checked_at=datetime.now(UTC).isoformat(),
            youtube_stream_status=health["stream_status"],
            youtube_health_status=health["health_status"],
            youtube_health_updated_at=health["health_updated_at"],
            youtube_health_issues=health["issues"], youtube_check_error="",
        )

    def _parse_progress(
        self, line: str, start: datetime, youtube_live: bool,
        *, observed_at: datetime | None = None,
        music_offset_seconds: float = 0,
    ) -> None:
        match = PROGRESS.fullmatch(line)
        if not match:
            return
        key, value = match.group("key"), match.group("value")
        observed_at = observed_at or datetime.now(UTC)
        state = self.store.snapshot()
        elapsed = int((datetime.now(UTC) - start).total_seconds())
        values = {
            "status": (
                "en directo"
                if youtube_live
                else "señal enviada; esperando confirmación de YouTube"
            ),
            "source_status": (
                "disponible" if youtube_live else "verificando en YouTube"
            ),
            "elapsed_seconds": elapsed,
            "remaining_seconds": max(0, self.settings.block_seconds - elapsed),
        }
        if key == "frame":
            try:
                frame = int(value)
            except ValueError:
                return
            if frame < 0:
                return
            if frame > state["ffmpeg_frame_count"]:
                values["ffmpeg_frame_count"] = frame
                values["last_frame_at"] = observed_at.isoformat()
        elif key == "out_time_us":
            try:
                seconds = int(value) / 1_000_000
            except (ValueError, OverflowError):
                return
            if not math.isfinite(seconds) or seconds < 0:
                return
            if state["ffmpeg_out_time_seconds"] is not None and seconds < state["ffmpeg_out_time_seconds"]:
                return
            values["ffmpeg_out_time_seconds"] = seconds
            values["music_playback_active"] = state["ffmpeg_running"]
            if self.music_session is not None:
                values.update(self.music_session.playback(seconds + music_offset_seconds))
        elif key == "fps":
            try:
                fps = float(value)
            except ValueError:
                return
            if not math.isfinite(fps) or fps < 0:
                return
            values["fps"] = fps
        elif key == "bitrate":
            values["bitrate"] = value
        elif key == "drop_frames":
            try:
                values["dropped_frames"] = int(value)
            except ValueError:
                return
        values["last_progress_at"] = observed_at.isoformat()
        self.store.update(**values)

    def _ffmpeg_command(self, output_url: str, *, music_offset_seconds: float = 0) -> list[str]:
        music_seek = []
        if music_offset_seconds > 0:
            # Resume at the last encoded music position, not elapsed wall time;
            # the outage itself must not pretend that music was transmitted.
            try:
                with wave.open(str(self.music_path), "rb") as audio:
                    duration = audio.getnframes() / audio.getframerate()
                if duration > 0:
                    music_seek = ["-ss", f"{music_offset_seconds % duration:.6f}"]
            except (OSError, EOFError, wave.Error, ZeroDivisionError):
                pass
        interval = self.settings.map_interval_seconds
        duration = self.settings.map_seconds
        use_nasa_video = (
            self.settings.use_nasa_playlist
            and self.settings.nasa_loop_video.is_file()
        )
        # Use one normalized video instead of switching stream parameters at
        # NASA concat seams, which previously ended the live FFmpeg process.
        use_vaapi_decode = False
        if self.settings.camera_enabled:
            # The local selector always produces normalized MJPEG at a fixed
            # rate. Camera reconnects never close the outbound encoder/audio.
            source_input = [
                "-threads:v", "1",
                "-r", str(self.settings.fps), "-f", "mpjpeg",
                "-analyzeduration", "0", "-probesize", "32", "-i",
                "http://127.0.0.1:8092/video.mjpeg",
            ]
            # Textfile contains only our fixed labels. Escape the file path for
            # FFmpeg's filter parser (also used by isolated Windows tests).
            label_path = str(self.video_label_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            source_filter = (
                "[0:v]setsar=1,setpts=PTS-STARTPTS,"
                "drawbox=x=0:y=ih-48:w=iw:h=48:color=black@0.60:t=fill,"
                "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
                f"textfile='{label_path}':reload=1:"
                "fontcolor=white:fontsize=18:x=24:y=main_h-34[base];"
            )
        elif use_nasa_video:
            source_input = [
                "-stream_loop",
                "-1",
                "-re",
                "-fflags",
                "+genpts",
            ]
            if use_vaapi_decode:
                source_input += [
                    # The NASA concat playlist switches files every 15 minutes.
                    # Keep the normalized graph alive across the seam; FFmpeg's
                    # default reinit can reconnect VAAPI/software filters badly.
                    "-reinit_filter",
                    "0",
                    "-hwaccel",
                    "vaapi",
                    "-hwaccel_device",
                    "va",
                    "-hwaccel_output_format",
                    "vaapi",
                ]
            source_input += ["-i", str(self.settings.nasa_loop_video)]
            input_scale = (
                "hwdownload,format=nv12,"
                f"fps=fps={self.settings.fps},"
                f"scale={self.settings.width}:{self.settings.height}:"
                "force_original_aspect_ratio=decrease"
                if use_vaapi_decode
                else f"fps=fps={self.settings.fps},"
                f"scale={self.settings.width}:{self.settings.height}:"
                "force_original_aspect_ratio=decrease"
            )
            source_filter = (
                f"[0:v]{input_scale},"
                f"pad={self.settings.width}:{self.settings.height}:"
                "(ow-iw)/2:(oh-ih)/2:black,"
                "setpts=PTS-STARTPTS,"
                "drawbox=x=0:y=ih-48:w=iw:h=48:color=black@0.60:t=fill,"
                "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
                "text='NASA Image and Video Library | Video grabado | Posicion ISS en tiempo real':"
                "fontcolor=white:fontsize=20:x=24:y=main_h-34[base];"
            )
        else:
            source_input = [
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
                "-i",
                self.settings.source_url,
            ]
            source_filter = (
                f"[0:v]fps=fps={self.settings.fps},"
                f"scale={self.settings.width}:{self.settings.height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={self.settings.width}:{self.settings.height}:"
                "(ow-iw)/2:(oh-ih)/2:black[base];"
            )
        # An invisible overlay still participates in FFmpeg framesync. Omit
        # its input completely when disabled, rather than letting a nominal
        # 1 FPS map throttle the main camera and accumulate ingest delay.
        show_dashboard = bool(getattr(self, "_dashboard_active", False))
        show_map = duration > 0 and not show_dashboard
        audio_input = 2 if show_map or show_dashboard else 1
        graph = source_filter
        if show_dashboard:
            panel_height = self.dashboard.height
            scene_height = self.settings.height - panel_height
            graph += (
                f"[base]scale={self.settings.width}:{scene_height}:force_original_aspect_ratio=decrease,"
                f"pad={self.settings.width}:{scene_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[scene];"
                f"[1:v]fps={self.settings.fps},setpts=PTS-STARTPTS,format=yuv420p[hud];"
                "[scene][hud]vstack=inputs=2:shortest=0[video];"
            )
        elif show_map:
            graph += (
                f"[1:v]setpts=PTS-STARTPTS,scale="
                f"{self.settings.width}:{self.settings.height}[map];"
                f"[base][map]overlay=enable='lt(mod(t,{interval}),{duration})'[video];"
            )
        else:
            graph += "[base]null[video];"
        limiter = "alimiter=limit=0.89:level=false," if show_dashboard else ""
        graph += (
            f"[{audio_input}:a]asetpts=PTS-STARTPTS,volume={self.settings.music_volume},"
            f"{limiter}aresample=48000[audio]"
        )
        encoder_options = (
            [
                "-init_hw_device",
                "vaapi=va:/dev/dri/renderD128",
                "-filter_hw_device",
                "va",
            ]
            if self.settings.encoder == "h264_vaapi"
            else []
        )
        video_map = "[video]"
        video_codec = self.settings.encoder
        if self.settings.encoder == "h264_vaapi":
            graph += ";[video]format=nv12,hwupload[encoded]"
            video_map = "[encoded]"
        return (
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-nostats",
                "-progress",
                "pipe:2",
            ]
            + encoder_options
            # The camera selector already runs two bounded input decoders. Do
            # not let the output graph create per-core pools on top of them.
            + (["-filter_threads", "1", "-filter_complex_threads", "1"]
               if self.settings.camera_enabled else [])
            + source_input
            # Repeat a cached JPEG at the SAME cadence as the main source. Data
            # and raster rendering update independently at 1 Hz, not this pipe.
            + (["-threads:v", "1", "-r", str(self.settings.fps), "-f", "mpjpeg",
                "-analyzeduration", "0", "-probesize", "32", "-i",
                "http://127.0.0.1:8092/dashboard.mjpeg"] if show_dashboard else [])
            + ((["-threads:v", "1"] if self.settings.camera_enabled else []) + [
                "-r",
                "1",
                "-f",
                "mjpeg",
                "-i",
                "http://127.0.0.1:8092/map.mjpeg",
            ] if show_map else [])
            + [
                "-stream_loop",
                "-1",
            ]
            + (["-threads:a", "1", "-re"] if self.settings.camera_enabled else [])
            + music_seek
            + [
                "-i",
                str(self.music_path),
                "-filter_complex",
                graph,
                "-map",
                video_map,
                "-map",
                "[audio]",
                "-c:v",
                video_codec,
                "-r",
                str(self.settings.fps),
                "-g",
                str(self.settings.fps * 2),
                "-c:a",
                "aac",
                "-b:a",
                self.settings.audio_bitrate,
                "-ar",
                "48000",
            ]
            + (["-threads:v", "2" if self.settings.encoder == "libx264" else "1",
                "-threads:a", "1"] if self.settings.camera_enabled else [])
            + (
                [
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    "ultrafast",
                    "-tune",
                    "zerolatency",
                    "-b:v",
                    self.settings.video_bitrate,
                    "-maxrate",
                    self.settings.video_bitrate,
                    "-bufsize",
                    self.settings.video_buffer_size,
                ]
                if self.settings.encoder == "libx264"
                else ["-rc_mode", "CQP", "-qp", "24", "-profile:v", "high"]
            )
            + (["-minrate", self.settings.video_bitrate, "-x264-params", "nal-hrd=cbr:force-cfr=1",
                "-sc_threshold", "0", "-keyint_min", str(self.settings.fps * 2), "-bf", "0"]
               + tee_output(output_url, self._starvios_destination.url)
               if output_url.startswith(("rtmp://", "rtmps://"))
               and self._starvios_destination.enabled and not self.settings.dry_run
               else (["-rw_timeout", "15000000"] if output_url.startswith(("rtmp://", "rtmps://")) else [])
               + ["-f", "flv", output_url])
        )

    def _gap(self, restart_count: int | None = None) -> None:
        current = (
            self.store.snapshot()["restart_count"]
            if restart_count is None
            else restart_count
        )
        self.store.update(
            status="pausa programada",
            remaining_seconds=self.settings.gap_seconds,
            live_requested=self.live_requested.is_set(),
            restart_count=int(current) + (0 if restart_count is not None else 1),
        )
        for remaining in range(self.settings.gap_seconds, 0, -1):
            if self.stop_event.is_set() or not self.live_requested.is_set():
                break
            self.stop_event.wait(1)
            self.store.update(remaining_seconds=remaining - 1)
