from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .config import Settings
from .controller import Controller
from .media import render_map
from .state import StateStore


def main() -> None:
    output = Path("/tmp/astrolearner-preflight.flv")
    state_path = Path("/tmp/astrolearner-preflight-status.json")
    output.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)

    settings = Settings()
    if settings.encoder == "h264_vaapi":
        va_info = subprocess.run(
            [
                "vainfo",
                "--display",
                "drm",
                "--device",
                "/dev/dri/renderD128",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        capabilities = va_info.stdout + va_info.stderr
        if (
            va_info.returncode != 0
            or "VAProfileH264High" not in capabilities
            or "VAEntrypointEncSlice" not in capabilities
        ):
            print(capabilities[-4000:])
            raise SystemExit("Preflight VAAPI: no se detecta codificación H.264")
        print("Preflight VAAPI: Intel iHD anuncia H.264 EncSlice")

    store = StateStore(state_path, settings.source_label)
    map_frame = Path("/tmp/astrolearner-preflight-map.png")
    render_map(map_frame, settings.width, settings.height, 0, 0, 420)
    command = Controller(settings, store)._ffmpeg_command(str(output))
    command.insert(1, "-y")
    command[command.index("-loglevel") + 1] = "warning"
    # Keep the preflight input at the beginning of the normalized MP4. Seeking
    # near EOF together with -stream_loop stalls FFmpeg on this host; the live
    # command itself loops normally (verified independently with a 30s decode).
    map_url = "http://127.0.0.1:8092/map.mjpeg"
    map_index = command.index(map_url)
    command[map_index - 5 : map_index + 1] = [
        "-loop",
        "1",
        "-framerate",
        "30",
        "-i",
        str(map_frame),
    ]
    test_seconds = 30
    # Measure processing throughput, not the real-time input throttle used by
    # the actual broadcast. Startup cost is also amortized across a longer run.
    if "-re" in command:
        command.remove("-re")
    command[-3:-3] = ["-t", str(test_seconds)]

    try:
        started = time.monotonic()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if exc.stderr:
                print(exc.stderr)
            raise SystemExit("Preflight FFmpeg excedió 90 segundos") from None
        if result.returncode != 0:
            print(result.stderr)
            raise SystemExit(f"Preflight FFmpeg falló: {result.returncode}")
        if not output.is_file() or output.stat().st_size < 100_000:
            raise SystemExit("Preflight FFmpeg no produjo un vídeo válido")
        elapsed = time.monotonic() - started
        realtime_speed = test_seconds / elapsed
        print(f"Preflight pipeline completo: {realtime_speed:.2f}x tiempo real")
        if realtime_speed < 1.05:
            raise SystemExit(
                f"Preflight vídeo demasiado lento: {realtime_speed:.2f}x tiempo real; "
                "se requiere al menos 1.05x para un directo continuo estable"
            )
        print(f"Preflight FFmpeg: OK ({output.stat().st_size} bytes)")
        print(f"Preflight vídeo: OK ({realtime_speed:.2f}x tiempo real)")

        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels",
                "-of",
                "default=noprint_wrappers=1",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if probe.returncode != 0 or "codec_name=aac" not in probe.stdout:
            raise SystemExit("Preflight audio falló: no se encontró pista AAC")

        levels = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(output),
                "-ss",
                "10",
                "-map",
                "0:a:0",
                "-t",
                "5",
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", levels.stderr)
        if (
            levels.returncode != 0
            or mean is None
            or not -25 <= float(mean.group(1)) <= -12
        ):
            raise SystemExit(
                "Preflight audio falló: falta nivel audible o el audio está saturado"
            )
        print(f"Preflight audio AAC: OK (nivel medio {mean.group(1)} dBFS)")
    finally:
        output.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
        map_frame.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
