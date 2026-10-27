"""Two local RTMP receivers, independent cuts, no credentials or external URLs."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time

from .multistream import tee_output
from .recovery_preflight import probe_command


def local_url(port: int) -> str:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Invalid local port")
    return f"rtmp://127.0.0.1:{port}/live/local-test"


def run_probe() -> dict:
    processes = []
    checks = {}
    with tempfile.TemporaryDirectory(prefix="iss-multistream-") as directory:
        root = Path(directory)

        def port():
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                return reserve.getsockname()[1]

        first_port = port()
        second_port = port()
        while second_port == first_port:
            second_port = port()
        a, b = local_url(first_port), local_url(second_port)

        def receiver(url, filename):
            # Validate again using the same loopback-only whitelist as the
            # original recovery probe. No settings, secrets or platform APIs.
            probe_command(url)
            path = root / filename
            child = subprocess.Popen([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-rw_timeout", "15000000", "-listen", "1", "-i", url,
                "-c", "copy", "-flush_packets", "1", "-f", "flv", str(path),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(child)
            return child, path

        def size(path):
            return path.stat().st_size if path.is_file() else 0

        def wait_for(test, limit=15):
            until = time.monotonic() + limit
            while time.monotonic() < until:
                if test():
                    return
                if encoder.poll() is not None:
                    raise RuntimeError("Local encoder exited")
                time.sleep(.1)
            raise RuntimeError("Local receiver timed out")

        def kill(child):
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)

        left, left_path = receiver(a, "a1.flv")
        # Synthetic 128x72 media, not the camera or music on the server.
        command = probe_command(a)[:-5] + ["-map", "0:v:0", "-map", "1:a:0"] + tee_output(a, b)
        time.sleep(.5)
        log = open(root / "probe.log", "w", encoding="utf-8")
        encoder = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
        processes.append(encoder)
        try:
            wait_for(lambda: size(left_path) > 2048)
            before = size(left_path)
            time.sleep(3)
            checks["youtube_starts_without_starvios"] = size(left_path) > before + 1024
            right, right_path = receiver(b, "b1.flv")
            wait_for(lambda: size(left_path) > 2048 and size(right_path) > 2048)
            checks["both_received"] = True
            kill(right)
            before = size(left_path)
            time.sleep(3)
            checks["youtube_continues_during_starvios_cut"] = left.poll() is None and size(left_path) > before + 1024
            right2, right2_path = receiver(b, "b2.flv")
            wait_for(lambda: size(right2_path) > 2048)
            checks["starvios_reconnected"] = True
            kill(left)
            before = size(right2_path)
            time.sleep(3)
            checks["starvios_continues_during_youtube_cut"] = right2.poll() is None and size(right2_path) > before + 1024
            left2, left2_path = receiver(a, "a2.flv")
            wait_for(lambda: size(left2_path) > 2048)
            checks["youtube_reconnected"] = True
            checks["same_encoder_process"] = encoder.poll() is None
            return {"publishing": False, "external_network": False,
                    "checks": checks, "passed": all(checks.values())}
        finally:
            # Stop explicitly; FIFO retries are intentionally unlimited until
            # the production controller's original block deadline or user Stop.
            for child in reversed(processes):
                kill(child)
            log.close()


def main():
    try:
        report = run_probe()
    except Exception as exc:
        report = {"publishing": False, "passed": False, "error_type": type(exc).__name__}
    print(json.dumps(report))
    if not report.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
