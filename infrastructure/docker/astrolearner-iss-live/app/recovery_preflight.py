"""Synthetic loopback-only RTMP cut/recovery; run in --network none, no volumes."""
from __future__ import annotations

from dataclasses import replace
import json
import logging
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

from .config import Settings
from .controller import Controller
from .state import StateStore
from .youtube import Broadcast


class LocalYouTubeDouble:
    """No Google client, authorization file or external request is used."""
    def broadcast_status(self, broadcast_id):
        assert broadcast_id == "local-test"
        return {"life_cycle_status": "live", "privacy_status": "unlisted"}

    def stream_health(self, stream_id):
        assert stream_id == "local-stream"
        return {"stream_status": "active", "health_status": "good", "health_updated_at": None, "issues": []}


def probe_command(url: str) -> list[str]:
    parsed = urlsplit(url)
    if (parsed.scheme != "rtmp" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.username is not None or parsed.password is not None
            or parsed.path != "/live/local-test" or parsed.query or parsed.fragment):
        raise ValueError("Only loopback is permitted")
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-nostats",
            "-progress", "pipe:2", "-filter_threads", "1", "-re", "-f", "lavfi", "-i",
            "testsrc2=size=128x72:rate=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-c:v", "libx264", "-threads:v", "1", "-preset", "ultrafast", "-tune", "zerolatency",
            "-g", "60", "-b:v", "300k", "-c:a", "aac", "-threads:a", "1", "-b:a", "64k",
            "-rw_timeout", "15000000", "-f", "flv", url]


def run_probe() -> dict:
    with tempfile.TemporaryDirectory(prefix="iss-output-recovery-") as directory:
        root = Path(directory)
        settings = replace(Settings(), data_dir=root / "data", status_dir=root / "status",
                           dry_run=True, auto_start=False, camera_enabled=False,
                           source_url="", use_nasa_playlist=False, block_seconds=24,
                           privacy="unlisted", fps=30)
        controller = Controller(settings, StateStore(root / "status.json", "local-test"))
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        url = f"rtmp://127.0.0.1:{port}/live/local-test"
        processes = []
        receiver_ready = threading.Event()
        interrupted = threading.Event()
        worker_errors = []

        def receiver(number):
            process = subprocess.Popen([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-rw_timeout", "20000000",
                "-listen", "1", "-i", url, "-c", "copy", "-flush_packets", "1",
                "-f", "flv", str(root / f"received-{number}.flv"),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            return process

        first = receiver(1)
        def cut_and_restore():
            try:
                limit = time.monotonic() + 12
                path = root / "received-1.flv"
                while time.monotonic() < limit:
                    if path.exists() and path.stat().st_size > 1024:
                        break
                    if first.poll() is not None:
                        raise RuntimeError("Local receiver exited before test")
                    interrupted.wait(.05)
                else:
                    raise RuntimeError("No local packets received")
                interrupted.wait(1)
                first.kill()
                first.wait(timeout=3)
                receiver(2)
                receiver_ready.set()
            except Exception as exc:
                worker_errors.append(type(exc).__name__)
                controller.request_live_stop()

        worker = threading.Thread(target=cut_and_restore, daemon=True)
        worker.start()
        controller._ffmpeg_command = lambda output, **_: probe_command(output)
        controller.live_requested.set()
        started = time.monotonic()
        try:
            # The listener is local and never receives a YouTube key.
            interrupted.wait(.4)
            controller._run_broadcast(LocalYouTubeDouble(), Broadcast(
                "local-test", "local-stream", url, "https://www.youtube.com/watch?v=LOCALTEST00"))
            elapsed = time.monotonic() - started
            worker.join(timeout=3)
            state = controller.store.snapshot()
            second = root / "received-2.flv"
            checks = {
                "receiver_restored": receiver_ready.is_set() and not worker_errors,
                "transport_reconnected": state["reconnect_count"] >= 1,
                "packets_after_recovery": second.is_file() and second.stat().st_size > 1024,
                "same_video_retained": state["youtube_watch_url"].endswith("LOCALTEST00"),
                "original_limit_preserved": settings.block_seconds <= elapsed < settings.block_seconds + 8,
                "encoder_stopped": state["ffmpeg_running"] is False,
            }
            return {"publishing": False, "external_network": False, "checks": checks,
                    "passed": all(checks.values())}
        finally:
            interrupted.set()
            controller.request_live_stop()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=3)
            worker.join(timeout=3)


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        report = run_probe()
    except Exception as exc:
        report = {"publishing": False, "passed": False, "error_type": type(exc).__name__}
    print(json.dumps(report))
    if not report.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
