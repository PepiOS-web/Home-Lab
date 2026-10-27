"""Check the deployed encoder's real-time cadence without publishing anything.

Run inside the application container only while the portal's live is stopped.
The existing local camera selector and music feed one temporary 30-second FLV;
there are no OAuth calls, controller instances or shared application-file writes.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import wave

from .browser_camera_preflight import PipelineDiagnostics
from .config import Settings
from .controller import Controller

DURATION = 30
ENCODE_TIMEOUT = 45
WARMUP_SECONDS = 5
MINIMUM_MEASUREMENT_SECONDS = 20
MINIMUM_FRAME_SPEED_RATIO = 0.985
STATUS_URL = "http://127.0.0.1:8092/api/status"
CAMERA_URL = "http://camera-browser:8093/camera.mjpeg"
MAX_STATUS_BYTES = 64 * 1024


class ProbeError(Exception):
    """Fixed, allowlisted reasons only: never attach external exception text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.diagnostics: dict = {}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("status_redirect_refused")


def read_status() -> dict:
    # Ignore HTTP proxy environment variables; a status check must stay local.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(STATUS_URL, timeout=2) as response:
        raw = response.read(MAX_STATUS_BYTES + 1)
    if len(raw) > MAX_STATUS_BYTES:
        raise ProbeError("status_response_too_large")
    state = json.loads(raw)
    if not isinstance(state, dict):
        raise ProbeError("status_invalid")
    return state


def require_stopped(state: object) -> None:
    if (not isinstance(state, dict) or state.get("live_requested") is not False
            or state.get("ffmpeg_running") is not False
            or state.get("status") == "en directo"):
        raise ProbeError("live_not_stopped")


def validate_probe_settings(settings: Settings) -> None:
    settings.validate()
    if (not settings.camera_enabled or settings.map_seconds != 0
            or settings.auto_start or not settings.camera_authorized
            or settings.camera_mode != "auto" or settings.camera_url != CAMERA_URL):
        raise ProbeError("unsupported_probe_configuration")


def select_music(settings: Settings) -> Path:
    """Mirror Controller's choice without instantiating it or generating music."""
    directory = settings.data_dir / "music"
    hourly = directory / "astrolearner-lofi-hour-v1.wav"
    try:
        with wave.open(str(hourly), "rb") as audio:
            rate = audio.getframerate()
            if (audio.getnchannels() == 2 and audio.getsampwidth() == 2
                    and rate > 0 and audio.getcomptype() == "NONE"
                    and abs(audio.getnframes() / rate - 3600) < 0.01):
                return hourly
    except (OSError, EOFError, wave.Error):
        pass
    fallback = directory / "astrolearner-lofi-v3.wav"
    try:
        with wave.open(str(fallback), "rb") as audio:
            if (audio.getnchannels() != 2 or audio.getsampwidth() != 2
                    or audio.getframerate() <= 0 or audio.getnframes() <= 0
                    or audio.getcomptype() != "NONE"):
                raise ProbeError("music_unavailable")
    except (OSError, EOFError, wave.Error):
        raise ProbeError("music_unavailable") from None
    return fallback


def probe_command(settings: Settings, music: Path, output: Path) -> list[str]:
    # Only these attributes are read by the actual production command builder.
    # Do not use Controller(...): its status/metadata helpers access shared files.
    context = SimpleNamespace(
        settings=settings, music_path=music,
        video_label_path=settings.status_dir / "video-source.txt",
    )
    command = Controller._ffmpeg_command(context, str(output))
    if (command[-1] != str(output) or output.suffix != ".flv"
            or not output.is_absolute()
            or "http://127.0.0.1:8092/map.mjpeg" in command):
        raise ProbeError("unsafe_probe_command")
    command[1:1] = ["-nostdin", "-y"]
    command[-1:-1] = ["-t", str(DURATION)]
    return command


def frame_speed_ratio(samples: list[tuple[float, int]], target_fps: int) -> tuple[float, float]:
    """Measure actual output frames/wall time after startup, not FFmpeg's fps UI."""
    if type(target_fps) is not int or target_fps <= 0:
        return 0.0, 0.0
    previous_time = -1.0
    previous_frames = -1
    selected = []
    for elapsed, frames in samples:
        if (not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
                or not math.isfinite(elapsed) or elapsed < 0 or elapsed < previous_time
                or type(frames) is not int or frames < 0 or frames < previous_frames):
            return 0.0, 0.0
        previous_time, previous_frames = elapsed, frames
        if elapsed >= WARMUP_SECONDS:
            selected.append((elapsed, frames))
    if len(selected) < 2:
        return 0.0, 0.0
    span = selected[-1][0] - selected[0][0]
    if span < MINIMUM_MEASUREMENT_SECONDS:
        return 0.0, max(0.0, span)
    return (selected[-1][1] - selected[0][1]) / (target_fps * span), span


def evaluate_progress(samples: list[tuple[float, int]], target_fps: int,
                      progress: dict[str, int], wall_seconds: float) -> tuple[dict, float, float]:
    ratio, span = frame_speed_ratio(samples, target_fps)
    frames = progress.get("frame", 0)
    video_seconds = progress.get("out_time_us", 0) / 1_000_000
    checks = {
        "measurement_span": span >= MINIMUM_MEASUREMENT_SECONDS,
        "real_time_frame_speed": math.isfinite(ratio) and ratio >= MINIMUM_FRAME_SPEED_RATIO,
        "output_frame_count": abs(frames - DURATION * target_fps) <= max(target_fps, 2),
        "output_duration": DURATION - 0.25 <= video_seconds <= DURATION + 0.25,
        "no_dropped_frames": progress.get("drop_frames") == 0,
        "wall_time": math.isfinite(wall_seconds) and 0 < wall_seconds <= ENCODE_TIMEOUT,
    }
    return checks, ratio, span


def inspect_output(output: Path, settings: Settings, diagnostics: PipelineDiagnostics) -> dict[str, bool]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,sample_rate:format=duration",
         "-of", "json", str(output)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
        check=False,
    )
    if result.returncode:
        diagnostics.observe(result.stderr)
        raise ProbeError("output_probe_failed")
    if len(result.stdout) > MAX_STATUS_BYTES:
        raise ProbeError("output_probe_invalid")
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        video = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
        duration = float(payload["format"]["duration"])
        return {
            "codecs": len(video) == len(audio) == 1
                and video[0].get("codec_name") == "h264" and audio[0].get("codec_name") == "aac",
            "geometry": len(video) == 1 and video[0].get("width") == settings.width
                and video[0].get("height") == settings.height,
            "audio_sample_rate": len(audio) == 1 and audio[0].get("sample_rate") == "48000",
            "container_duration": math.isfinite(duration) and DURATION - 0.25 <= duration <= DURATION + 0.25,
        }
    except (TypeError, KeyError, ValueError, AttributeError):
        raise ProbeError("output_probe_invalid") from None


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def run_probe(settings: Settings) -> dict:
    validate_probe_settings(settings)
    require_stopped(read_status())
    music = select_music(settings)
    diagnostics = PipelineDiagnostics()
    progress: dict[str, int] = {}
    samples: deque[tuple[float, int]] = deque(maxlen=256)
    progress_lock = threading.Lock()
    reader_error = threading.Event()
    with tempfile.TemporaryDirectory(prefix="iss-stream-pacing-") as temporary:
        output = Path(temporary) / "capture.flv"
        command = probe_command(settings, music, output)
        require_stopped(read_status())
        started = time.monotonic()
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1,
        )

        def drain() -> None:
            try:
                assert process.stderr is not None
                for raw in iter(lambda: process.stderr.readline(8193), ""):
                    line = raw.strip()
                    key, separator, value = line.partition("=")
                    if (separator and key in {"frame", "drop_frames", "out_time_us"}
                            and value.isascii() and value.isdecimal() and len(value) < 20):
                        with progress_lock:
                            number = int(value)
                            progress[key] = number
                            if key == "frame":
                                samples.append((time.monotonic() - started, number))
                    elif line:
                        diagnostics.observe(line)
            except Exception:
                reader_error.set()

        reader = threading.Thread(target=drain, name="local-pacing-progress", daemon=True)
        reader.start()
        camera_samples = 0
        next_check = 0.0
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= ENCODE_TIMEOUT:
                    raise ProbeError("encoder_timeout")
                if elapsed >= next_check:
                    state = read_status()
                    require_stopped(state)
                    if elapsed >= WARMUP_SECONDS and state.get("camera_available") is True and state.get("video_mode") == "camera":
                        camera_samples += 1
                    next_check = time.monotonic() - started + 1
                if reader_error.is_set():
                    raise ProbeError("progress_reader_failed")
                time.sleep(0.1)
            wall_seconds = time.monotonic() - started
            reader.join(timeout=2)
            if reader.is_alive() or reader_error.is_set():
                raise ProbeError("progress_reader_failed")
            if process.returncode:
                return {"status": "failed", "publishing": False, "target_fps": settings.fps,
                        "error_code": "local_encoder_failed", "exit_code": process.returncode,
                        **diagnostics.report()}
            require_stopped(read_status())
            with progress_lock:
                checks, ratio, span = evaluate_progress(list(samples), settings.fps, dict(progress), wall_seconds)
                frames = progress.get("frame", 0)
                video_seconds = progress.get("out_time_us", 0) / 1_000_000
            checks.update(inspect_output(output, settings, diagnostics))
            checks["camera_observed"] = camera_samples >= 1
            require_stopped(read_status())
            passed = all(checks.values())
            return {"status": "ok" if passed else "failed", "publishing": False,
                    "target_fps": settings.fps, "frames": frames,
                    "video_seconds": round(video_seconds, 3), "wall_seconds": round(wall_seconds, 3),
                    "frame_speed_ratio": round(ratio, 6), "minimum_frame_speed_ratio": MINIMUM_FRAME_SPEED_RATIO,
                    "measurement_seconds": round(span, 3), "camera_samples": camera_samples,
                    "checks": checks, "failed_checks": [name for name, ok in checks.items() if not ok],
                    "temporary_output_removed_on_exit": True}
        except ProbeError as exc:
            exc.diagnostics = diagnostics.report()
            raise
        except Exception as exc:
            # The fingerprint helps correlate failures without printing input
            # URLs, local credential paths, raw HTTP responses or subprocess logs.
            diagnostics.observe(type(exc).__name__)
            failure = ProbeError("local_probe_failed")
            failure.diagnostics = diagnostics.report()
            raise failure from None
        finally:
            _stop_process(process)
            reader.join(timeout=2)
            if process.stderr is not None and not reader.is_alive():
                process.stderr.close()


def main() -> None:
    try:
        report = run_probe(Settings())
    except Exception as exc:
        report = {"status": "failed", "publishing": False,
                  "error_code": exc.code if isinstance(exc, ProbeError) else "probe_configuration_or_io_failed",
                  "error_fingerprint": hashlib.sha256(type(exc).__name__.encode()).hexdigest()[:12],
                  **(exc.diagnostics if isinstance(exc, ProbeError) else {})}
    print(json.dumps(report, allow_nan=False), flush=True)
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
