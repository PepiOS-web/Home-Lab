"""Real-source, local-file camera test. No OAuth and no publishing endpoint."""
from __future__ import annotations

from array import array
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from urllib.request import urlopen
import wave

from app.config import Settings
from app.controller import Controller
from app.state import StateStore

DURATION = 100
HOURLY_MUSIC = Path("/production-music/astrolearner-lofi-hour-v1.wav")
MINIMUM_FRAME_SPEED_RATIO = 0.985
PIPELINE_SIGNALS = {
    "thread_creation_failed": ("pthread_create", "can't create thread", "cannot create thread", "failed to create thread"),
    "resource_unavailable": ("resource temporarily unavailable", "not enough resources"),
    "encoder_initialization": ("error while opening encoder", "could not open encoder", "error initializing output stream"),
    "filter_configuration": ("error reinitializing filters", "failed to configure output pad", "error initializing complex filters"),
    "input_decode": ("invalid data found", "error during decoding", "error submitting packet to decoder"),
    "storage_full": ("no space left on device", "disk quota exceeded"),
    "permission_denied": ("permission denied",),
    "input_unavailable": ("connection refused", "error opening input", "server returned 403", "server returned 503"),
    "external_library": ("generic error in an external library",),
    "empty_output": ("nothing was written into output file",),
}


class PipelineDiagnostics:
    """Keep a hash and fixed indicators, never stderr text or media URLs."""
    def __init__(self) -> None:
        self.signals: set[str] = set()
        self.fingerprint = hashlib.sha256()

    def observe(self, line: str) -> None:
        self.fingerprint.update(line.encode(errors="replace"))
        lowered = line.lower()
        for name, markers in PIPELINE_SIGNALS.items():
            if any(marker in lowered for marker in markers):
                self.signals.add(name)

    def report(self) -> dict:
        return {"error_signals": [name for name in PIPELINE_SIGNALS if name in self.signals],
                "error_fingerprint": self.fingerprint.hexdigest()[:12]}


def resource_snapshot(root: Path = Path("/sys/fs/cgroup")) -> dict[str, int | None]:
    """Read only selected numeric cgroup-v2 counters; unavailable is not zero."""
    def count(name: str, key: str | None = None) -> int | None:
        try:
            content = (root / name).read_text()
            value = content.strip() if key is None else dict(line.split() for line in content.splitlines()).get(key, "")
            return int(value) if value.isascii() and value.isdecimal() and len(value) < 20 else None
        except (OSError, ValueError):
            return None

    return {"pids_current": count("pids.current"), "pids_limit": count("pids.max"),
            "pids_limit_hits": count("pids.events", "max"),
            "oom_kills": count("memory.events", "oom_kill")}


def read_json(url: str) -> dict:
    with urlopen(url, timeout=2) as response:
        return json.load(response)


def source_sequence_ok(events: list[str]) -> bool:
    # Need a real camera, a fallback AFTER it, and a recovered real camera.
    wanted = iter(("camera", "recorded", "camera"))
    next_value = next(wanted)
    for event in events:
        if event == next_value:
            next_value = next(wanted, None)
            if next_value is None:
                return True
    return False


def make_audio(destination: Path) -> None:
    samples = array("h", (int(4000 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(48000)))
    if __import__("sys").byteorder != "little":
        samples.byteswap()
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(samples.tobytes())


def select_audio(destination: Path, kind: str) -> tuple[Path, str]:
    if kind == "tone":
        make_audio(destination)
        return destination, "test_tone"
    if kind != "hourly":
        raise ValueError("Tipo de audio de prueba no permitido")
    try:
        with wave.open(str(HOURLY_MUSIC), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if (audio.getnchannels() != 2 or audio.getsampwidth() != 2
                    or rate <= 0 or abs(frames / rate - 3600) > .01
                    or audio.getcomptype() != "NONE"):
                raise ValueError("La sesion Lo-Fi de prueba no es valida")
            audio.setpos(frames - 1)
            if len(audio.readframes(1)) != 4:
                raise ValueError("La sesion Lo-Fi de prueba esta incompleta")
    except (OSError, EOFError, wave.Error):
        raise ValueError("No se puede leer la sesion Lo-Fi para la prueba") from None
    return HOURLY_MUSIC, "hourly_lofi_read_only"


def measured_output_rate(samples: list[tuple[float, int]], fps: int) -> tuple[float, float]:
    """Actual output frames/wall time after startup; not FFmpeg's reported fps."""
    selected = []
    last_time, last_frames = -1.0, -1
    if type(fps) is not int or fps <= 0:
        return 0.0, 0.0
    for elapsed, frames in samples:
        if (not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
                or not math.isfinite(elapsed) or elapsed < last_time
                or type(frames) is not int or frames < last_frames):
            return 0.0, 0.0
        last_time, last_frames = elapsed, frames
        if elapsed >= 5:
            selected.append((elapsed, frames))
    if len(selected) < 2:
        return 0.0, 0.0
    span = selected[-1][0] - selected[0][0]
    if span < 20:
        return 0.0, max(0.0, span)
    return (selected[-1][1] - selected[0][1]) / (fps * span), span


def main() -> None:
    settings = Settings()
    settings.validate()
    if not settings.dry_run or not settings.camera_enabled:
        raise SystemExit("Esta prueba solo admite staging con dry-run y selector de cámara")
    if settings.camera_url != "http://camera-browser:8093/camera.mjpeg":
        raise SystemExit("La prueba solo admite el puente de captura aislado")
    # This application must never gain publishing credentials in staging.
    if settings.youtube_token.exists():
        raise SystemExit("Prueba cancelada: se encontraron credenciales de publicación")
    expect_esa_map = os.getenv("ISS_CAMERA_PROBE_EXPECT_MAP", "none") == "esa"

    with tempfile.TemporaryDirectory(prefix="iss-browser-probe-") as temporary:
        directory = Path(temporary)
        audio, output = directory / "tone.wav", directory / "capture.flv"
        audio, audio_source = select_audio(audio, os.getenv("ISS_CAMERA_PROBE_MUSIC", "tone"))
        controller = Controller(replace(settings, map_interval_seconds=30, map_seconds=0 if expect_esa_map else 5),
                                StateStore(directory / "probe-state.json", "Prueba local"))
        controller.music_path = audio
        command = controller._ffmpeg_command(str(output))
        command[-1:-1] = ["-t", str(DURATION)]
        progress: dict[str, str] = {}
        frame_samples: list[tuple[float, int]] = []
        diagnostics = PipelineDiagnostics()
        initial_resources = resource_snapshot()
        started = time.monotonic()
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                   text=True, bufsize=1)

        def drain() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                key, separator, value = line.strip().partition("=")
                if separator and key in {"frame", "out_time_us", "drop_frames", "speed"}:
                    progress[key] = value
                    if key == "frame" and value.isascii() and value.isdecimal() and len(value) < 20:
                        frame_samples.append((time.monotonic() - started, int(value)))
                elif line.strip():
                    diagnostics.observe(line.strip())

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        events: list[str] = []
        samples: list[float] = []
        map_samples = 0
        target_matches = True
        try:
            while process.poll() is None and time.monotonic() - started < DURATION + 15:
                try:
                    state = read_json("http://127.0.0.1:8092/api/status")
                    mode = state.get("video_mode", "unknown")
                    if not events or events[-1] != mode:
                        events.append(mode)
                        print(json.dumps({"source": mode, "elapsed": round(time.monotonic() - started, 1)}), flush=True)
                except Exception:
                    pass
                try:
                    capture = read_json("http://camera-browser:8093/health")
                    target_matches = target_matches and capture.get("target_fps") == settings.fps
                    if capture.get("ready") and capture.get("captured_frames", 0) > 20:
                        samples.append(float(capture["capture_fps"]))
                        if capture.get("map_source") == "esa" and capture.get("map_ready"):
                            map_samples += 1
                except Exception:
                    pass  # Expected during the deliberate sidecar stop.
                time.sleep(1)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                raise RuntimeError("Pipeline demasiado lento o bloqueado; no activar producción")
            reader.join(timeout=2)
            elapsed = time.monotonic() - started
            if process.returncode:
                print(json.dumps({"status": "failed", "publishing": False, "error_stage": "local_pipeline",
                                  "exit_code": process.returncode, "wall_seconds": round(elapsed, 2),
                                  "resources_before": initial_resources, "resources_after": resource_snapshot(),
                                  **diagnostics.report()}), flush=True)
                raise SystemExit(1)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
                                   capture_output=True, text=True, timeout=10, check=True)
            streams = json.loads(probe.stdout)["streams"]
            video = next(stream for stream in streams if stream["codec_type"] == "video")
            audio_stream = next(stream for stream in streams if stream["codec_type"] == "audio")
            frames = int(progress.get("frame", "0"))
            duration = int(progress.get("out_time_us", "0")) / 1_000_000
            capture_fps = sum(samples) / len(samples) if samples else 0
            frame_ratio, measurement_seconds = measured_output_rate(frame_samples, settings.fps)
            # The generated playlist intentionally fades in. Inspect the rest
            # for gaps across source switches instead of rejecting that intro.
            audio_checked_after = 10 if audio_source == "hourly_lofi_read_only" else 0
            silence = subprocess.run(["ffmpeg", "-v", "info", "-i", str(output), "-vn", "-af",
                                      f"atrim=start={audio_checked_after},silencedetect=noise=-50dB:d=0.2", "-f", "null", "-"],
                                     capture_output=True, text=True, timeout=20, check=True)
            silence_gaps = silence.stderr.count("silence_start:")
            checks = {"camera_fallback_recovery": source_sequence_ok(events),
                      "capture_target_matches": target_matches and bool(samples),
                      "output_frame_count": frames >= DURATION * settings.fps * 0.97,
                      "output_duration": duration >= DURATION - 1,
                      "wall_time": elapsed <= DURATION + 12,
                      "capture_fps": capture_fps >= settings.fps * 0.95,
                      "real_time_output": frame_ratio >= MINIMUM_FRAME_SPEED_RATIO,
                      "continuous_audio": silence_gaps == 0,
                      "codecs": video["codec_name"] == "h264" and audio_stream["codec_name"] == "aac",
                      "geometry": video["width"] == settings.width and video["height"] == settings.height,
                      "no_dropped_frames": int(progress.get("drop_frames", "0")) == 0,
                      "esa_map": not expect_esa_map or map_samples > 0}
            passed = all(checks.values())
            print(json.dumps({"status": "ok" if passed else "failed", "publishing": False,
                              "target_fps": settings.fps,
                              "source_events": events, "frames": frames, "video_seconds": round(duration, 2),
                              "wall_seconds": round(elapsed, 2), "mean_capture_fps": round(capture_fps, 2),
                              "minimum_capture_fps": settings.fps * 0.95, "capture_samples": len(samples),
                              "frame_speed_ratio": round(frame_ratio, 6),
                              "minimum_frame_speed_ratio": MINIMUM_FRAME_SPEED_RATIO,
                              "measured_output_fps": round(frame_ratio * settings.fps, 3),
                              "measurement_seconds": round(measurement_seconds, 3),
                              "audio_source": audio_source, "audio_checked_after_seconds": audio_checked_after,
                              "esa_map_samples": map_samples, "checks": checks,
                              "failed_checks": [name for name, value in checks.items() if not value],
                              "audio_silence_gaps": silence_gaps, "output_encoder_instances": 1,
                              "geometry": [video["width"], video["height"]],
                              "temporary_output_removed_on_exit": True}), flush=True)
            if not passed:
                raise SystemExit(1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            reader.join(timeout=2)
            if process.stderr is not None:
                process.stderr.close()


if __name__ == "__main__":
    main()
