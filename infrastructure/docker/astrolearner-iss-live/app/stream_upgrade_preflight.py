"""Isolated 720p30 camera/HUD/audio probe; only loopback HTTP, never publishing.

Run in a separate container with --network none. Port 8092 must be free in that
container. The probe borrows Controller._ffmpeg_command without constructing a
Controller, starting its workers, loading OAuth or contacting any provider.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import wave

from PIL import Image, ImageDraw

from .config import Settings
from .controller import Controller
from .stream_dashboard import StreamDashboard

WIDTH, HEIGHT, FPS = 1280, 720, 30
PORT = 8092
MAX_PROCESS_OUTPUT = 2 * 1024 * 1024
LINUX_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


class ProbeError(ValueError):
    """Fixed diagnostic codes only; do not expose commands, paths or stderr."""


@dataclass
class ProbeFrames:
    camera: bytes
    map: bytes
    dashboard: bytes
    switch_after: float
    started: float
    camera_sent: int = 0
    map_sent: int = 0
    dashboard_sent: int = 0


def _jpeg(color: str, label: str) -> bytes:
    with Image.new("RGB", (WIDTH, HEIGHT), color) as image:
        draw = ImageDraw.Draw(image)
        draw.text((45, 45), label, fill="white")
        if label == "SYNTHETIC MAP FALLBACK":
            for x in range(0, WIDTH, 100):
                draw.line((x, 0, x, HEIGHT), fill="#61c5b1", width=2)
            for y in range(0, HEIGHT, 100):
                draw.line((0, y, WIDTH, y), fill="#61c5b1", width=2)
        result = io.BytesIO()
        image.save(result, "JPEG", quality=87)
        return result.getvalue()


def _frames(seconds: int, dashboard: StreamDashboard) -> ProbeFrames:
    hud = dashboard.render({"video_mode": "camera", "music_playback_active": False})
    if hud is None:
        raise ProbeError("dashboard_not_ready")
    return ProbeFrames(_jpeg("#173a84", "SYNTHETIC CAMERA"),
                       _jpeg("#096750", "SYNTHETIC MAP FALLBACK"),
                       hud.jpeg, seconds / 2, time.monotonic())


def _server(frames: ProbeFrames, stopped: threading.Event, port: int = PORT) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:
            pass

        def handle(self) -> None:
            try:
                super().handle()
            except (OSError, TimeoutError):
                pass

        def do_GET(self) -> None:
            self.connection.settimeout(3)
            if self.path not in {"/video.mjpeg", "/dashboard.mjpeg"}:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            deadline = time.monotonic()
            try:
                while not stopped.is_set():
                    if self.path == "/dashboard.mjpeg":
                        image = frames.dashboard
                        frames.dashboard_sent += 1
                    elif time.monotonic() - frames.started < frames.switch_after:
                        image = frames.camera
                        frames.camera_sent += 1
                    else:
                        image = frames.map
                        frames.map_sent += 1
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(image)).encode("ascii") + b"\r\n\r\n" + image + b"\r\n")
                    self.wfile.flush()
                    deadline += 1 / FPS
                    now = time.monotonic()
                    if deadline < now - 1 / FPS:
                        deadline = now
                    stopped.wait(max(0, deadline - now))
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.block_on_close = False
    return server


def _binary(value: str, code: str) -> str:
    resolved = shutil.which(value)
    if resolved is None:
        candidate = Path(value)
        if candidate.is_file():
            resolved = str(candidate.resolve())
    if resolved is None:
        raise ProbeError(code)
    return resolved


def _ffprobe_binary(ffmpeg: str, requested: str | None) -> str:
    if requested:
        return _binary(requested, "ffprobe_not_found")
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if Path(ffmpeg).suffix.lower() == ".exe" else "ffprobe")
    return _binary(str(sibling) if sibling.is_file() else "ffprobe", "ffprobe_not_found")


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ProbeError("process_timeout") from None
    except OSError:
        raise ProbeError("process_start_failed") from None
    if len(result.stdout) > MAX_PROCESS_OUTPUT or len(result.stderr) > MAX_PROCESS_OUTPUT:
        raise ProbeError("process_output_limit")
    if result.returncode:
        raise ProbeError("ffmpeg_or_ffprobe_failed")
    return result


def _probe_json(ffprobe: str, path: Path, frames: bool = False, timeout: float = 15) -> dict:
    command = [ffprobe, "-v", "error"]
    if frames:
        command += ["-select_streams", "v:0", "-show_frames",
                    "-show_entries", "frame=best_effort_timestamp_time"]
    else:
        command += ["-count_frames", "-show_streams", "-show_format"]
    result = _run(command + ["-of", "json", str(path)], timeout)
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise ProbeError("invalid_ffprobe_output") from None
    if not isinstance(value, dict):
        raise ProbeError("invalid_ffprobe_output")
    return value


def _number(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ProbeError("invalid_media_number") from None
    if not math.isfinite(result):
        raise ProbeError("invalid_media_number")
    return result


def _rate(value) -> float:
    if not isinstance(value, str) or not re.fullmatch(r"\d+/\d+", value):
        raise ProbeError("invalid_frame_rate")
    numerator, denominator = map(int, value.split("/"))
    if denominator == 0:
        raise ProbeError("invalid_frame_rate")
    return numerator / denominator


def _validate_media(metadata: dict, timestamps: dict, seconds: int) -> dict:
    streams = metadata.get("streams", [])
    if not isinstance(streams, list) or not all(isinstance(stream, dict) for stream in streams):
        raise ProbeError("invalid_ffprobe_output")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise ProbeError("missing_audio_or_video")
    video, audio = videos[0], audios[0]
    if (video.get("codec_name") != "h264" or audio.get("codec_name") != "aac"
            or video.get("width") != WIDTH or video.get("height") != HEIGHT
            or abs(_rate(video.get("r_frame_rate")) - FPS) > .01):
        raise ProbeError("incorrect_output_format")
    duration = _number(metadata.get("format", {}).get("duration"))
    if abs(duration - seconds) > .25:
        raise ProbeError("incorrect_output_duration")
    entries = timestamps.get("frames", [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ProbeError("invalid_ffprobe_output")
    stamps = [_number(item.get("best_effort_timestamp_time")) for item in entries]
    if abs(len(stamps) - seconds * FPS) > 2 or len(stamps) < 2:
        raise ProbeError("incorrect_output_frame_count")
    gaps = [after - before for before, after in zip(stamps, stamps[1:])]
    # FLV uses millisecond ticks, so 30 FPS alternates 33/34 ms timestamps.
    if any(gap <= 0 or abs(gap - 1 / FPS) > .004 for gap in gaps):
        raise ProbeError("video_timestamp_gap")
    return {"width": WIDTH, "height": HEIGHT, "fps": FPS,
            "duration_seconds": round(duration, 3), "video_frames": len(stamps),
            "video_codec": "h264", "audio_codec": "aac",
            "max_frame_gap_seconds": round(max(gaps), 6)}


def _audio_levels(ffmpeg: str, path: Path, timeout: float = 15) -> dict:
    result = _run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path), "-vn",
                   "-af", "volumedetect", "-f", "null", "-"], timeout)
    text = result.stderr.decode("utf-8", errors="replace")
    values = {}
    for key in ("mean_volume", "max_volume"):
        match = re.search(rf"\b{key}:\s*(-?\d+(?:\.\d+)?)\s*dB", text)
        if match is None:
            raise ProbeError("audio_level_unavailable")
        values[key] = float(match[1])
    if values["mean_volume"] < -35 or values["max_volume"] > -.1:
        raise ProbeError("audio_too_quiet_or_clipping")
    return {"audio_mean_dbfs": values["mean_volume"], "audio_sample_peak_dbfs": values["max_volume"]}


def _source_transition(ffmpeg: str, path: Path, seconds: int, timeout: float = 15) -> bool:
    before, after = int(seconds * FPS * .25), int(seconds * FPS * .80)
    selection = f"select=eq(n\\,{before})+eq(n\\,{after}),scale=1:1"
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
                   "-an", "-vf", selection, "-fps_mode", "passthrough", "-frames:v", "2",
                   "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], timeout)
    if len(result.stdout) != 6:
        raise ProbeError("transition_sample_unavailable")
    distance = math.sqrt(sum((result.stdout[index] - result.stdout[index + 3]) ** 2 for index in range(3)))
    if distance < 25:
        raise ProbeError("synthetic_source_did_not_change")
    return True


def _command(ffmpeg: str, music: Path, output: Path, label: Path, seconds: int,
             dashboard: StreamDashboard) -> tuple[list[str], bool]:
    settings = Settings(width=WIDTH, height=HEIGHT, fps=FPS, camera_enabled=True,
                        map_seconds=0, encoder="libx264", dry_run=True, auto_start=False,
                        music_volume=4.0)
    context = SimpleNamespace(settings=settings, music_path=music, video_label_path=label,
                              dashboard=dashboard, _dashboard_active=True,
                              _starvios_destination=SimpleNamespace(enabled=False, url=""))
    command = Controller._ffmpeg_command(context, str(output))
    command[0] = ffmpeg
    command[-3:-3] = ["-t", str(seconds)]
    filter_index = command.index("-filter_complex") + 1
    font_adapted = False
    if not Path(LINUX_FONT).is_file():
        windows_font = Path("C:/Windows/Fonts/arial.ttf")
        if not windows_font.is_file():
            raise ProbeError("probe_font_unavailable")
        escaped = str(windows_font).replace("\\", "/").replace(":", "\\:")
        command[filter_index] = command[filter_index].replace("fontfile=" + LINUX_FONT,
                                                                         "fontfile='" + escaped + "'")
        font_adapted = True
    inputs = [command[index + 1] for index, argument in enumerate(command[:-1]) if argument == "-i"]
    if inputs != ["http://127.0.0.1:8092/video.mjpeg", "http://127.0.0.1:8092/dashboard.mjpeg", str(music)]:
        raise ProbeError("unexpected_probe_input")
    if command[-1] != str(output) or any(value.startswith(("rtmp://", "rtmps://", "https://")) for value in command):
        raise ProbeError("unexpected_probe_destination")
    return command, font_adapted


def run_preflight(music: Path, seconds: int = 30, ffmpeg: str = "ffmpeg",
                  ffprobe: str | None = None) -> dict:
    if type(seconds) is not int or not 3 <= seconds <= 30:
        raise ProbeError("probe_seconds_out_of_range")
    music = Path(music).resolve()
    try:
        with wave.open(str(music), "rb") as audio:
            if (audio.getnchannels() != 2 or audio.getsampwidth() != 2
                    or audio.getnframes() <= 0 or audio.getframerate() <= 0):
                raise ProbeError("invalid_probe_music")
    except (OSError, EOFError, wave.Error):
        raise ProbeError("invalid_probe_music") from None
    ffmpeg = _binary(ffmpeg, "ffmpeg_not_found")
    ffprobe = _ffprobe_binary(ffmpeg, ffprobe)
    dashboard = StreamDashboard(WIDTH, 144)
    frames = _frames(seconds, dashboard)
    stopped = threading.Event()
    try:
        server = _server(frames, stopped)
    except OSError:
        raise ProbeError("isolated_loopback_port_in_use") from None
    worker = threading.Thread(target=server.serve_forever, name="isolated-stream-probe", daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="iss-stream-preflight-") as temporary:
            directory = Path(temporary)
            label = directory / "source.txt"
            label.write_text("ISOLATED SYNTHETIC SOURCE | NEVER PUBLISHING\n", encoding="ascii")
            output = directory / "probe.flv"
            command, adapted = _command(ffmpeg, music, output, label, seconds, dashboard)
            frames.started = time.monotonic()
            started = time.monotonic()
            deadline = started + min(90, seconds * 2 + 15)

            def budget(maximum: float = 15) -> float:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeError("process_timeout")
                return min(maximum, remaining)

            result = _run(command, budget(90))
            elapsed = time.monotonic() - started
            report = _validate_media(_probe_json(ffprobe, output, timeout=budget()),
                                     _probe_json(ffprobe, output, True, timeout=budget()), seconds)
            report.update(_audio_levels(ffmpeg, output, timeout=budget()))
            report["synthetic_source_transition"] = _source_transition(ffmpeg, output, seconds, timeout=budget())
            if frames.camera_sent == 0 or frames.map_sent == 0 or frames.dashboard_sent == 0:
                raise ProbeError("synthetic_sources_not_consumed")
            if elapsed > seconds / .85 + 2:
                raise ProbeError("encoder_below_realtime")
            progress = result.stderr.decode("utf-8", errors="replace")
            speed = re.findall(r"(?m)^speed=\s*(\d+(?:\.\d+)?)x\s*$", progress)
            report.update(status="passed", publishing=False, external_network=False,
                          graph="Controller._ffmpeg_command", source="synthetic_camera_to_map",
                          wall_seconds=round(elapsed, 3), wall_fps=round(report["video_frames"] / max(elapsed, 1e-9), 2),
                          final_progress_speed=float(speed[-1]) if speed else None,
                          windows_font_adapted=adapted,
                          note="Synthetic isolated probe; does not verify external camera, OAuth or remote ingest")
            return report
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--music", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe")
    args = parser.parse_args()
    try:
        report = run_preflight(args.music, args.seconds, args.ffmpeg, args.ffprobe)
    except ProbeError as error:
        report = {"status": "failed", "publishing": False, "external_network": False, "error_code": str(error)}
    except Exception:
        report = {"status": "failed", "publishing": False, "external_network": False, "error_code": "unexpected_probe_failure"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
