import io
import os
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from app.camera_preflight import _LocalVideoServer, _duration, _jpeg, run_probe
from app.config import Settings
from app.controller import Controller
from app.state import StateStore


@pytest.mark.parametrize("width,height,fps", [(0, 180, 12), (321, 180, 12), (320, 180, 0), (4000, 2160, 12)])
def test_synthetic_probe_rejects_bad_geometry_without_spawning(monkeypatch, width, height, fps):
    monkeypatch.setattr("app.camera_preflight.subprocess.Popen", lambda *args, **kwargs: pytest.fail("Unexpected process"))
    with pytest.raises(ValueError):
        run_probe("unused", width, height, fps)


def test_progress_duration_handles_crlf_and_unavailable_values():
    assert _duration(b"out_time_us=N/A\r\n") == 0
    assert _duration(b"out_time_us=1000000\r\nout_time_us=2021333\r\n") == 2.021333


def test_synthetic_jpeg_has_known_geometry():
    with Image.open(io.BytesIO(_jpeg(320, 180, "red"))) as frame:
        assert frame.size == (320, 180)


@pytest.mark.skipif(not os.getenv("FFMPEG_TEST_BINARY"), reason="Optional local FFmpeg binary")
@pytest.mark.parametrize("map_seconds", [0, 5])
def test_real_controller_graph_includes_map_labels_and_continuous_audio(tmp_path, monkeypatch, map_seconds):
    """Exercise the actual new output graph, not just the stand-alone selector."""
    binary = os.environ["FFMPEG_TEST_BINARY"]
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    settings = replace(
        Settings(), camera_enabled=True, width=320, height=180, fps=12,
        map_seconds=map_seconds, map_interval_seconds=600, encoder="libx264",
    )
    controller = Controller(settings, StateStore(settings.status_dir / "state.json", "synthetic"))
    controller._video_source_status({"video_mode": "recorded"})
    controller.music_path.parent.mkdir(parents=True)
    # This is generated test audio, not a real recording or microphone.
    subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000", "-t", "1", "-c:a", "pcm_s16le",
                    str(controller.music_path)], check=True, capture_output=True, timeout=15)
    map_path = tmp_path / "map.jpg"
    Image.new("RGB", (320, 180), "green").save(map_path)
    stop = threading.Event()
    server = _LocalVideoServer(lambda: _jpeg(320, 180, "blue"), stop, 12)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        output = tmp_path / "root-graph.flv"
        command = controller._ffmpeg_command(str(output))
        command[0] = binary
        command[command.index("http://127.0.0.1:8092/video.mjpeg")] = server.url
        map_url = "http://127.0.0.1:8092/map.mjpeg"
        assert (map_url in command) is bool(map_seconds)
        if map_url in command:
            index = command.index(map_url)
            command[index - 5:index + 1] = ["-loop", "1", "-framerate", "1", "-i", str(map_path)]
        graph_index = command.index("-filter_complex") + 1
        if os.name == "nt":
            # Use a real Windows font while retaining the production filter.
            command[graph_index] = command[graph_index].replace(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "'C\\:/Windows/Fonts/arial.ttf'"
            )
        # The real camera command must now bound its own threads. Do not hide
        # production omissions by adding decoder/filter limits in this test.
        command[1:1] = ["-y"]
        command[-3:-3] = ["-t", "3", "-shortest"]
        result = subprocess.run(command, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr.decode(errors="replace")[-2000:]
        decoded = subprocess.run([binary, "-hide_banner", "-loglevel", "info", "-i", str(output),
                                  "-map", "0:v:0", "-map", "0:a:0", "-progress", "pipe:1",
                                  "-f", "null", "-"], capture_output=True, timeout=10)
        assert decoded.returncode == 0
        assert b"Video: h264" in decoded.stderr and b"Audio: aac" in decoded.stderr
        assert _duration(decoded.stdout) >= 2.9
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
