import http.client
import json
import math
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import wave
from array import array
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app import stream_upgrade_preflight as probe
from app.stream_dashboard import StreamDashboard


@pytest.fixture
def music(tmp_path):
    path = tmp_path / "tone.wav"
    samples = array("h")
    for index in range(16000):
        value = round(1800 * math.sin(index / 8000 * 2 * math.pi * 220))
        samples.extend((value, value))
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(samples.tobytes())
    return path


def valid_media(seconds=3):
    return {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280,
                         "height": 720, "r_frame_rate": "30/1"},
                        {"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": str(seconds + .023)}}


def valid_timestamps(seconds=3):
    return {"frames": [{"best_effort_timestamp_time": str(round(.023 + index / 30, 3))}
                       for index in range(seconds * 30)]}


def test_valid_output_geometry_codecs_frame_cadence_and_duration():
    result = probe._validate_media(valid_media(), valid_timestamps(), 3)
    assert result["fps"] == 30
    assert result["video_frames"] == 90
    assert result["width"] == 1280 and result["height"] == 720
    assert result["max_frame_gap_seconds"] == .034


@pytest.mark.parametrize("change", ["dimensions", "fps", "audio", "codec", "duration", "nan"])
def test_invalid_encoded_media_fails_closed(change):
    media = valid_media()
    if change == "dimensions":
        media["streams"][0]["width"] = 640
    elif change == "fps":
        media["streams"][0]["r_frame_rate"] = "12/1"
    elif change == "audio":
        media["streams"].pop()
    elif change == "codec":
        media["streams"][1]["codec_name"] = "mp3"
    else:
        media["format"]["duration"] = "nan" if change == "nan" else "1"
    with pytest.raises(probe.ProbeError):
        probe._validate_media(media, valid_timestamps(), 3)


@pytest.mark.parametrize("change", ["missing", "duplicate", "gap", "backwards", "invalid"])
def test_missing_duplicate_or_discontinuous_video_timestamps_are_rejected(change):
    stamps = valid_timestamps()
    if change == "missing":
        stamps["frames"] = stamps["frames"][:-3]
    elif change == "duplicate":
        stamps["frames"][10] = stamps["frames"][9]
    elif change == "gap":
        stamps["frames"][10]["best_effort_timestamp_time"] = "1.0"
    elif change == "backwards":
        stamps["frames"].reverse()
    else:
        stamps["frames"] = [None]
    with pytest.raises(probe.ProbeError):
        probe._validate_media(valid_media(), stamps, 3)


def test_actual_controller_graph_is_borrowed_without_constructor_or_remote_destinations(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.Controller, "__init__", lambda *args, **kwargs: pytest.fail("Controller constructed"))
    # The production Linux font is assumed for this unit-only graph inspection.
    monkeypatch.setattr(Path, "is_file", lambda path: path.as_posix() == probe.LINUX_FONT)
    label, output, music = tmp_path / "label.txt", tmp_path / "probe.flv", tmp_path / "tone.wav"
    command, adapted = probe._command("isolated-ffmpeg", music, output, label, 30, StreamDashboard())
    assert not adapted
    assert command[0] == "isolated-ffmpeg"
    assert command[-1] == str(output)
    assert [command[index + 1] for index, value in enumerate(command) if value == "-r"] == ["30", "30", "30"]
    assert [command[index + 1] for index, value in enumerate(command) if value == "-t"] == ["30"]
    graph = command[command.index("-filter_complex") + 1]
    assert "vstack=inputs=2" in graph
    assert "scale=1280:576" in graph
    assert "volume=4.0" in graph
    assert "[2:a]" in graph
    assert not any(value.startswith(("rtmp://", "rtmps://", "https://")) for value in command)


def test_loopback_mjpeg_server_has_fixed_routes_and_never_waits_for_real_camera():
    frames = probe._frames(3, StreamDashboard())
    stopped = threading.Event()
    server = probe._server(frames, stopped, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request("GET", "/video.mjpeg")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("multipart/x-mixed-replace")
        assert b"Content-Type: image/jpeg" in response.read(100)
        assert frames.camera_sent > 0
    finally:
        connection.close()
        stopped.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    assert not worker.is_alive()


def test_decoder_errors_are_fixed_and_never_reflect_stderr(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 1, b"", b"PRIVATE_URL_OR_TOKEN"))
    with pytest.raises(probe.ProbeError, match="^ffmpeg_or_ffprobe_failed$"):
        probe._run(["ffmpeg"], 3)


def test_process_deadline_and_output_limits(monkeypatch):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("PRIVATE_COMMAND", 3)
    monkeypatch.setattr(subprocess, "run", timed_out)
    with pytest.raises(probe.ProbeError, match="^process_timeout$"):
        probe._run(["ffmpeg"], 3)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 0, b"X" * (probe.MAX_PROCESS_OUTPUT + 1), b""))
    with pytest.raises(probe.ProbeError, match="^process_output_limit$"):
        probe._run(["ffmpeg"], 3)


@pytest.mark.parametrize("mean,peak", [(-40, -12), (-18, 0), (-18, -.05)])
def test_audio_too_quiet_or_clipping_fails(mean, peak, tmp_path, monkeypatch):
    output = f"mean_volume: {mean} dB\nmax_volume: {peak} dB\n".encode()
    monkeypatch.setattr(probe, "_run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, b"", output))
    with pytest.raises(probe.ProbeError, match="audio_too_quiet_or_clipping"):
        probe._audio_levels("ffmpeg", tmp_path / "output.flv")


def test_measured_audio_levels_are_not_called_lufs(tmp_path, monkeypatch):
    output = b"mean_volume: -17.3 dB\nmax_volume: -1.2 dB\n"
    monkeypatch.setattr(probe, "_run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, b"", output))
    assert probe._audio_levels("ffmpeg", tmp_path / "output.flv") == {
        "audio_mean_dbfs": -17.3, "audio_sample_peak_dbfs": -1.2}


@pytest.mark.parametrize("seconds", [0, 2, 31, True, "30"])
def test_probe_duration_is_bounded_before_any_network_or_process(music, seconds):
    with pytest.raises(probe.ProbeError, match="probe_seconds_out_of_range"):
        probe.run_preflight(music, seconds)


def test_invalid_music_is_rejected_before_binary_or_server_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_binary", lambda *args: pytest.fail("binary setup must not run"))
    with pytest.raises(probe.ProbeError, match="invalid_probe_music"):
        probe.run_preflight(tmp_path / "missing.wav")


def test_success_report_is_explicitly_synthetic_nonpublishing_and_server_is_closed(music, monkeypatch):
    closed = []
    frames = probe._frames(3, StreamDashboard())
    frames.camera_sent = frames.map_sent = frames.dashboard_sent = 1
    server = SimpleNamespace(serve_forever=lambda: None, shutdown=lambda: closed.append("shutdown"),
                             server_close=lambda: closed.append("closed"))
    monkeypatch.setattr(probe, "_binary", lambda value, code: value)
    monkeypatch.setattr(probe, "_ffprobe_binary", lambda *args: "ffprobe")
    monkeypatch.setattr(probe, "_frames", lambda *args: frames)
    monkeypatch.setattr(probe, "_server", lambda *args: server)
    monkeypatch.setattr(probe, "_command", lambda *args: (["ffmpeg"], False))
    monkeypatch.setattr(probe, "_run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, b"", b"speed=1.0x\n"))
    monkeypatch.setattr(probe, "_probe_json", lambda *args, **kwargs:
                        valid_timestamps() if len(args) > 2 and args[2] else valid_media())
    monkeypatch.setattr(probe, "_audio_levels", lambda *args, **kwargs: {"audio_mean_dbfs": -17, "audio_sample_peak_dbfs": -1})
    monkeypatch.setattr(probe, "_source_transition", lambda *args, **kwargs: True)
    result = probe.run_preflight(music, seconds=3)
    assert result["status"] == "passed"
    assert result["publishing"] is False
    assert result["external_network"] is False
    assert result["source"] == "synthetic_camera_to_map"
    assert result["final_progress_speed"] == 1.0
    assert closed == ["shutdown", "closed"]
    assert str(music) not in json.dumps(result)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg/ffprobe not installed")
def test_real_isolated_720p30_graph_and_synthetic_switch(music):
    with socket.socket() as check:
        try:
            check.bind(("127.0.0.1", probe.PORT))
        except OSError:
            pytest.skip("Isolated loopback probe port is occupied")
    result = probe.run_preflight(music, seconds=3)
    assert result["status"] == "passed"
    assert result["video_frames"] == 90
    assert result["synthetic_source_transition"] is True
    assert result["audio_codec"] == "aac"
