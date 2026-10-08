from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta

import httpx
from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError

from .audio_preview import create_music_preview
from .config import Settings
from .control_page import create_control_page
from .media import create_ambient_music, render_earth_frame, render_map
from .state import StateStore
from .youtube import BroadcastUnavailableError, YouTubeLive

LOG = logging.getLogger(__name__)
PROGRESS = re.compile(r"(?P<key>frame|fps|bitrate|drop_frames)=(?P<value>.*)")
FFMPEG_STATUS = re.compile(r"^[A-Za-z0-9_]+=")


class Controller:
    def __init__(self, settings: Settings, store: StateStore) -> None:
        self.settings = settings
        self.store = store
        self.stop_event = threading.Event()
        self.live_requested = threading.Event()
        if settings.auto_start and not settings.dry_run:
            self.live_requested.set()
        self.process: subprocess.Popen[str] | None = None
        self.map_path = settings.status_dir / "map.png"
        self.earth_path = settings.status_dir / "earth.jpg"
        self.music_path = settings.data_dir / "music" / "astrolearner-lofi-v3.wav"
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
        create_ambient_music(self.music_path)
        create_music_preview(self.music_path, self.settings.status_dir)
        create_control_page(self.settings.status_dir)
        self.store.update(
            control_ready=bool(self.settings.control_token) and not self.settings.dry_run
        )
        render_earth_frame(
            None, self.earth_path, self.settings.width, self.settings.height
        )
        if (
            self.settings.use_nasa_playlist
            and self.settings.nasa_loop_video.is_file()
        ):
            self.store.update(
                visual_source="NASA Image and Video Library + EPIC / DSCOVR"
            )
        self._map_thread.start()
        self._earth_thread.start()
        self._thread.start()

    def request_live_start(self) -> None:
        if self.settings.dry_run:
            raise RuntimeError("La emisión está bloqueada mientras siga activo dry-run")
        if not self.settings.source_url and not (
            self.settings.use_nasa_playlist and self.settings.nasa_loop_video.is_file()
        ):
            raise RuntimeError("No hay una fuente visual disponible")
        if not self.settings.youtube_token.is_file():
            raise RuntimeError("Falta la autorización OAuth de YouTube")
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
        )

    def request_live_stop(self) -> None:
        was_requested = self.live_requested.is_set()
        self.live_requested.clear()
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
        )

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self._thread.join(timeout=15)
        self._map_thread.join(timeout=5)
        self._earth_thread.join(timeout=5)

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
                lat = float(data["latitude"])
                lon = float(data["longitude"])
                altitude = float(data.get("altitude", altitude))
                velocity = float(data.get("velocity", 0.0))
                self.position_track.append((lat, lon))
                self.store.update(
                    latitude=round(lat, 3),
                    longitude=round(lon, 3),
                    altitude_km=round(altitude, 1),
                    velocity_kmh=round(velocity, 1),
                )
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
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
                self.store.update(
                    status="simulación lista",
                    mode="simulacion",
                    source_status=(
                        "fuente visual configurada"
                        if self.settings.source_url
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
                if not self.settings.source_url and not (
                    self.settings.use_nasa_playlist
                    and self.settings.nasa_loop_video.is_file()
                ):
                    raise RuntimeError("Falta ISS_LIVE_SOURCE_URL")
                youtube = YouTubeLive(
                    self.settings.youtube_token,
                    self.settings.privacy,
                    self.settings.source_label,
                )
                broadcast = youtube.create(self.settings.block_seconds)
                if not self.live_requested.is_set():
                    youtube.complete(broadcast.broadcast_id)
                    self._mark_live_stopped()
                    continue
                created_blocks += 1
                self._run_ffmpeg(
                    broadcast.rtmp_url,
                    broadcast.watch_url,
                    youtube,
                    broadcast.broadcast_id,
                )
                youtube.complete(broadcast.broadcast_id)
            except Exception as exc:
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
                    live_requested=self.live_requested.is_set(),
                )
                if (
                    self.settings.max_blocks
                    and created_blocks >= self.settings.max_blocks
                ):
                    self.live_requested.clear()
                    continue
                self._wait_while_live(min(self.settings.gap_seconds, 300))
                continue

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

    def _wait_while_live(self, seconds: int) -> None:
        for _ in range(seconds):
            if self.stop_event.is_set() or not self.live_requested.is_set():
                return
            self.stop_event.wait(1)

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
    ) -> None:
        start = datetime.now(UTC)
        end = start + timedelta(seconds=self.settings.block_seconds)
        self.store.update(
            status="conectando",
            mode="youtube",
            source_status="conectando",
            block_started_at=start.isoformat(),
            next_restart_at=end.isoformat(),
            youtube_watch_url=watch_url,
            last_error="",
        )
        command = self._ffmpeg_command(output_url)
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.process.stderr is not None
        deadline = time.monotonic() + self.settings.block_seconds
        diagnostics: deque[str] = deque(maxlen=32)
        streaming_started_at = time.monotonic()
        last_youtube_check = 0.0
        youtube_live = False
        missing_broadcast_checks = 0
        verification_error = ""
        for raw_line in self.process.stderr:
            if (
                self.stop_event.is_set()
                or not self.live_requested.is_set()
                or time.monotonic() >= deadline
            ):
                self.process.terminate()
                break
            line = raw_line.strip()
            now = time.monotonic()
            if now - last_youtube_check >= 10:
                last_youtube_check = now
                try:
                    state = youtube.broadcast_status(broadcast_id)
                except (HttpError, TransportError, OSError, TimeoutError) as exc:
                    LOG.warning("Could not verify YouTube broadcast lifecycle: %s", exc)
                else:
                    if state is None:
                        missing_broadcast_checks += 1
                        if missing_broadcast_checks >= 2:
                            verification_error = (
                                "YouTube ya no encuentra la emisión creada; "
                                "se detuvo el envío para evitar un falso directo."
                            )
                    else:
                        missing_broadcast_checks = 0
                        lifecycle = state["life_cycle_status"]
                        privacy = state["privacy_status"]
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
                        elif now - streaming_started_at > 180:
                            verification_error = (
                                "YouTube no confirmó el estado live en 3 minutos "
                                f"(estado actual: {lifecycle})."
                            )
                    if verification_error:
                        self.process.terminate()
                        break
            if line and not FFMPEG_STATUS.match(line):
                # FFmpeg can include its output URL in diagnostics. Never persist
                # or log the RTMP URL because it contains the YouTube stream key.
                safe_line = line.replace(output_url, "[RTMP REDACTADO]")
                diagnostics.append(safe_line[-500:])
            self._parse_progress(line, start, youtube_live)
        return_code = self.process.wait(timeout=20)
        if verification_error:
            raise BroadcastUnavailableError(verification_error)
        if (
            time.monotonic() < deadline
            and not self.stop_event.is_set()
            and self.live_requested.is_set()
        ):
            detail = " | ".join(diagnostics)
            message = f"FFmpeg terminó antes de tiempo (código {return_code})"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message)

    def _parse_progress(self, line: str, start: datetime, youtube_live: bool) -> None:
        match = PROGRESS.fullmatch(line)
        if not match:
            return
        key, value = match.group("key"), match.group("value")
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
        if key == "fps":
            try:
                values["fps"] = float(value)
            except ValueError:
                pass
        elif key == "bitrate":
            values["bitrate"] = value
        elif key == "drop_frames":
            try:
                values["dropped_frames"] = int(value)
            except ValueError:
                pass
        self.store.update(**values)

    def _ffmpeg_command(self, output_url: str) -> list[str]:
        interval = self.settings.map_interval_seconds
        duration = self.settings.map_seconds
        use_nasa_video = (
            self.settings.use_nasa_playlist
            and self.settings.nasa_loop_video.is_file()
        )
        # Use one pre-normalized MP4 rather than a multi-file concat input.
        # NASA source clips have different stream parameters; switching files
        # in FFmpeg caused the live pipeline to terminate at the ~15-minute seam.
        use_vaapi_decode = False
        if use_nasa_video:
            source_input = [
                "-stream_loop",
                "-1",
                "-re",
                "-i",
                str(self.settings.nasa_loop_video),
            ]
            if use_vaapi_decode:
                source_input += [
                    "-hwaccel",
                    "vaapi",
                    "-hwaccel_device",
                    "va",
                    "-hwaccel_output_format",
                    "vaapi",
                ]
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
        graph = (
            source_filter
            +
            f"[1:v]setpts=PTS-STARTPTS,scale="
            f"{self.settings.width}:{self.settings.height}[map];"
            f"[base][map]overlay=enable='lt(mod(t,{interval}),{duration})'[video];"
            f"[2:a]asetpts=PTS-STARTPTS,volume={self.settings.music_volume},"
            "aresample=48000[audio]"
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
            + source_input
            + [
                "-r",
                "1",
                "-f",
                "mjpeg",
                "-i",
                "http://127.0.0.1:8092/map.mjpeg",
                "-stream_loop",
                "-1",
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
            + ["-f", "flv", output_url]
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
