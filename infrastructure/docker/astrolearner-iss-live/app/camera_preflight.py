"""Local-only, non-publishing integration probe for the camera failover gateway.

Run ``python -m app.camera_preflight``. All inputs are synthetic and all HTTP
listeners bind to 127.0.0.1 on ephemeral ports. No Settings, OAuth files, real
camera, YouTube client, RTMP connection or production state are loaded. The
temporary H.264/AAC output is removed after validation.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from PIL import Image

from .video_switcher import VideoSwitcher


def _jpeg(width: int, height: int, color: str) -> bytes:
    destination = io.BytesIO()
    Image.new("RGB", (width, height), color).save(destination, "JPEG", quality=85)
    return destination.getvalue()


class _LocalVideoServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        frame: Callable[[], bytes | None],
        stop: threading.Event,
        fps: int,
        available: threading.Event | None = None,
    ) -> None:
        self.frame = frame
        self.stop_signal = stop
        self.fps = fps
        self.available = available
        self.clients = 0
        self._clients_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _VideoHandler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/video.mjpeg"


class _VideoHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        server: _LocalVideoServer = self.server  # type: ignore[assignment]
        if self.path != "/video.mjpeg":
            self.send_error(404)
            return
        if server.available is not None and not server.available.is_set():
            self.send_error(503)
            return
        self.connection.settimeout(2)
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        with server._clients_lock:
            server.clients += 1
        deadline = time.monotonic()
        try:
            while not server.stop_signal.is_set():
                if server.available is not None and not server.available.is_set():
                    return
                payload = server.frame()
                if payload:
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(payload)).encode("ascii")
                        + b"\r\n\r\n" + payload + b"\r\n"
                    )
                    self.wfile.flush()
                deadline += 1 / server.fps
                server.stop_signal.wait(max(0, deadline - time.monotonic()))
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with server._clients_lock:
                server.clients -= 1
            self.close_connection = True

    def log_message(self, _format: str, *args: Any) -> None:
        # The probe prints one bounded JSON report, not per-frame HTTP messages.
        pass


def _run(command: list[str], timeout: float = 12) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
        check=False,
    )
    if result.returncode:
        details = result.stderr.decode("utf-8", errors="replace")[-1200:].strip()
        raise RuntimeError(f"Local FFmpeg check failed ({result.returncode}): {details}")
    return result


def _duration(progress: bytes) -> float:
    values = re.findall(rb"(?m)^out_time_us=(\d+)\r?$", progress)
    return int(values[-1]) / 1_000_000 if values else 0.0


def run_probe(ffmpeg: str, width: int = 320, height: int = 180, fps: int = 12) -> dict[str, Any]:
    if not 160 <= width <= 1920 or not 90 <= height <= 1080 or width % 2 or height % 2:
        raise ValueError("Probe dimensions must be even, between 160x90 and 1920x1080")
    if not 2 <= fps <= 30:
        raise ValueError("Probe FPS must be between 2 and 30")
    started = time.monotonic()
    stop = threading.Event()
    available = threading.Event()
    available.set()
    statuses: list[dict[str, Any]] = []
    state_changed = threading.Condition()
    servers: list[_LocalVideoServer] = []
    serving: list[_LocalVideoServer] = []
    workers: list[threading.Thread] = []
    publisher: subprocess.Popen[bytes] | None = None
    switcher: VideoSwitcher | None = None

    def on_status(status: dict[str, Any]) -> None:
        with state_changed:
            statuses.append({"seconds": round(time.monotonic() - started, 3), **status})
            state_changed.notify_all()

    def wait_for_mode(mode: str, timeout: float = 9) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert switcher is not None
            switcher.frame()
            with state_changed:
                if statuses and statuses[-1]["video_mode"] == mode:
                    return
            if publisher is not None and publisher.poll() is not None:
                error = publisher.stderr.read() if publisher.stderr is not None else b""
                raise RuntimeError(
                    "Local output encoder stopped early: "
                    + error.decode("utf-8", errors="replace")[-1200:]
                )
            stop.wait(0.05)
        raise RuntimeError(f"Synthetic failover did not reach {mode!r} within {timeout:g}s")

    def hold(seconds: float) -> None:
        # Keep freshness evaluation independent of an HTTP consumer or read buffer.
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            assert switcher is not None
            switcher.frame()
            stop.wait(min(0.05, max(0, deadline - time.monotonic())))

    class _ProbeSwitcher(VideoSwitcher):
        def _command(self, source: str) -> list[str]:
            command = super()._command(source)
            command[0] = ffmpeg
            return command

    with tempfile.TemporaryDirectory(prefix="iss-camera-probe-") as directory:
        temporary = Path(directory)
        backup = temporary / "synthetic-recorded.mp4"
        output = temporary / "synthetic-continuous.flv"
        _run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"color=c=0x164ac0:s={width}x{height}:r={fps}",
            "-t", "2", "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-threads", "1", "-pix_fmt", "yuv420p", str(backup),
        ])
        red = _jpeg(width, height, "#d43b3b")
        green = _jpeg(width, height, "#288644")
        camera_server = _LocalVideoServer(lambda: red, stop, fps, available)
        servers.append(camera_server)
        settings = SimpleNamespace(
            camera_enabled=True, camera_mode="auto", camera_url=camera_server.url,
            camera_authorized=True, camera_timeout_seconds=0.75,
            camera_stable_seconds=0.75, camera_retry_seconds=1,
            # Short timings are intentional for this synthetic test only. They
            # are not saved and do not weaken production Settings validation.
            nasa_loop_video=backup, use_nasa_playlist=True,
            width=width, height=height, fps=fps,
        )
        switcher = _ProbeSwitcher(settings, on_status, lambda: green)
        gateway_server = _LocalVideoServer(switcher.frame, stop, fps)
        servers.append(gateway_server)
        try:
            for server in servers:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                workers.append(worker)
                worker.start()
                serving.append(server)
            switcher.start()
            publisher = subprocess.Popen([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-filter_threads", "1", "-threads", "1",
                "-f", "mpjpeg", "-r", str(fps), "-analyzeduration", "0",
                "-probesize", "32", "-i", gateway_server.url,
                "-re", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-threads", "1", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-c:a", "aac", "-b:a", "96k", "-ar", "48000",
                "-shortest", "-t", "32", "-f", "flv", str(output),
            ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            wait_for_mode("camera")
            hold(2)
            available.clear()
            wait_for_mode("recorded")
            hold(2)
            available.set()
            wait_for_mode("camera")
            hold(2)
            switcher.set_mode("map")
            wait_for_mode("map", timeout=2)
            hold(2)
            # End only this synthetic HTTP input; -shortest finalizes the local
            # encoder's one output, including its continuous AAC audio track.
            stop.set()
            _, publisher_error = publisher.communicate(timeout=8)
            if publisher.returncode:
                raise RuntimeError(
                    "Local continuous encoder failed: "
                    + publisher_error.decode("utf-8", errors="replace")[-1200:]
                )
            switcher.stop()

            video = _run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-i", str(output), "-map", "0:v:0", "-an", "-progress", "pipe:1",
                "-f", "null", "-",
            ])
            audio = _run([
                ffmpeg, "-hide_banner", "-loglevel", "info", "-nostdin",
                "-i", str(output), "-map", "0:a:0", "-vn",
                "-af", "silencedetect=noise=-50dB:duration=0.2", "-progress", "pipe:1",
                "-f", "null", "-",
            ])
            samples = _run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-i", str(output), "-map", "0:v:0", "-an", "-threads", "1",
                "-vf", "fps=2,scale=1:1:flags=area", "-pix_fmt", "rgb24",
                "-f", "rawvideo", "pipe:1",
            ]).stdout
            metadata = _run([
                ffmpeg, "-hide_banner", "-loglevel", "info", "-nostdin",
                "-i", str(output), "-t", "0", "-f", "null", "-",
            ]).stderr.decode("utf-8", errors="replace")
            frame_matches = re.findall(rb"(?m)^frame=(\d+)\r?$", video.stdout)
            frames = int(frame_matches[-1]) if frame_matches else 0
            video_duration = _duration(video.stdout)
            audio_duration = _duration(audio.stdout)
            events: list[str] = []
            for status in statuses:
                if not events or events[-1] != status["video_mode"]:
                    events.append(status["video_mode"])
            required = ["camera", "recorded", "camera", "map"]
            cursor = 0
            for event in events:
                if cursor < len(required) and event == required[cursor]:
                    cursor += 1
            color_events: list[str] = []
            for index in range(0, len(samples) - 2, 3):
                pixel = samples[index:index + 3]
                dominant = max(range(3), key=pixel.__getitem__)
                name = ("camera", "map", "recorded")[dominant]
                if max(pixel) - min(pixel) > 35 and (
                    not color_events or color_events[-1] != name
                ):
                    color_events.append(name)
            color_cursor = 0
            for event in color_events:
                if color_cursor < len(required) and event == required[color_cursor]:
                    color_cursor += 1
            if cursor != len(required) or color_cursor != len(required):
                raise RuntimeError(
                    f"Incomplete failover evidence: states={events}, encoded_colors={color_events}"
                )
            if video_duration < 8 or audio_duration < 8 or frames < fps * 8:
                raise RuntimeError("Synthetic output contains too few video frames or audio samples")
            # Check final alignment as well as silence: neither a successful
            # decoder nor one encoder alone proves continuous synchronized AV.
            if abs(video_duration - audio_duration) > 0.5:
                raise RuntimeError(
                    "Video and continuous AAC durations diverged by more than 0.5s: "
                    f"video={video_duration:.3f}s, audio={audio_duration:.3f}s, frames={frames}"
                )
            if b"silence_start:" in audio.stderr:
                raise RuntimeError("A silence gap was detected in the synthetic continuous AAC audio")
            if abs(frames - video_duration * fps) > fps:
                raise RuntimeError("Decoded frame count is inconsistent with continuous fixed-FPS video")
            if "Video: h264" not in metadata or "Audio: aac" not in metadata:
                raise RuntimeError("Expected H.264 video and AAC audio were not found")
            return {
                "status": "ok", "synthetic_only": True, "publishing": False,
                "external_camera_tested": False, "server_capacity_tested": False,
                "size": f"{width}x{height}", "fps": fps,
                "events": events, "encoded_color_events": color_events,
                "output_encoder_instances": 1, "video_codec": "h264", "audio_codec": "aac",
                "decoded_frames": frames, "video_seconds": round(video_duration, 3),
                "audio_seconds": round(audio_duration, 3),
                "audio_silence_gaps": 0,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "temporary_output_removed": True,
            }
        finally:
            stop.set()
            if publisher is not None and publisher.poll() is None:
                publisher.terminate()
                try:
                    publisher.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    publisher.kill()
                    publisher.wait(timeout=3)
            if publisher is not None and publisher.stderr is not None:
                publisher.stderr.close()
            if switcher is not None:
                switcher.stop()
            for server in servers:
                if server in serving:
                    server.shutdown()
                server.server_close()
            for worker in workers:
                worker.join(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Local FFmpeg executable")
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args()
    try:
        result = run_probe(args.ffmpeg, args.width, args.height, args.fps)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({
            "status": "failed", "synthetic_only": True, "publishing": False,
            "error": str(exc),
        }, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
