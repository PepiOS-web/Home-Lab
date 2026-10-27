from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from app import stream_pacing_probe as probe
from app.browser_camera_preflight import PipelineDiagnostics
from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    return replace(
        Settings(), data_dir=tmp_path / "data", status_dir=tmp_path / "status",
        camera_enabled=True, camera_authorized=True, camera_mode="auto",
        camera_url=probe.CAMERA_URL, auto_start=False, map_seconds=0,
        dry_run=False, encoder="libx264", width=1280, height=720, fps=20,
    )


@pytest.mark.parametrize("fps", [12, 20, 30])
def test_pace_uses_measured_frames_after_startup_not_ffmpeg_reported_fps(fps):
    # Ignore the warmup's intentionally slow startup, then exactly real time.
    samples = [(0.0, 0), (4.9, 10), (5.0, 20), (25.0, 20 + 20 * fps)]
    ratio, span = probe.frame_speed_ratio(samples, fps)
    assert ratio == pytest.approx(1.0)
    assert span == 20


def test_confirmed_hidden_map_throttle_is_rejected():
    fps = 20
    samples = [(5.0, 100), (30.0, 588)]  # 488/500 = 0.976, not >=0.985.
    checks, ratio, _ = probe.evaluate_progress(
        samples, fps, {"frame": 600, "drop_frames": 0, "out_time_us": 30_000_000}, 30.8
    )
    assert ratio == pytest.approx(0.976)
    assert checks["real_time_frame_speed"] is False
    assert checks["output_frame_count"] is True


@pytest.mark.parametrize("samples,fps", [
    ([], 20), ([(5.0, 1)], 20), ([(5.0, 1), (24.0, 381)], 20),
    ([(5.0, 100), (25.0, 99)], 20), ([(6.0, 100), (5.0, 101)], 20),
    ([(float("nan"), 100), (25.0, 500)], 20),
    ([(5.0, 100), (float("inf"), 500)], 20),
    ([(5.0, True), (25.0, 500)], 20),
    ([(5.0, 100), (25.0, 500)], 0),
    ([(5.0, 100), (25.0, 500)], True),
])
def test_pace_fails_closed_on_missing_short_or_invalid_measurement(samples, fps):
    assert probe.frame_speed_ratio(samples, fps)[0] == 0


def test_progress_checks_require_real_time_frames_duration_no_drops_and_wall_bound():
    samples = [(5.0, 100), (30.0, 600)]
    good = {"frame": 600, "drop_frames": 0, "out_time_us": 30_000_000}
    checks, ratio, span = probe.evaluate_progress(samples, 20, good, 30.5)
    assert all(checks.values()) and ratio == 1 and span == 25
    for key, value, failed in [
        ("frame", 200, "output_frame_count"),
        ("drop_frames", 1, "no_dropped_frames"),
        ("out_time_us", 5_000_000, "output_duration"),
    ]:
        checks, _, _ = probe.evaluate_progress(samples, 20, {**good, key: value}, 30.5)
        assert not checks[failed]
    checks, _, _ = probe.evaluate_progress(samples, 20, {"frame": 600, "out_time_us": 30_000_000}, 46)
    assert checks["no_dropped_frames"] is False
    assert checks["wall_time"] is False


@pytest.mark.parametrize("state", [
    None, {}, {"live_requested": False},
    {"live_requested": True, "ffmpeg_running": False},
    {"live_requested": False, "ffmpeg_running": True},
    {"live_requested": 0, "ffmpeg_running": 0},
    {"live_requested": False, "ffmpeg_running": False, "status": "en directo"},
])
def test_probe_refuses_unknown_requested_or_running_live(state):
    with pytest.raises(probe.ProbeError, match="live_not_stopped"):
        probe.require_stopped(state)


def test_explicit_stopped_state_is_accepted():
    probe.require_stopped({"live_requested": False, "ffmpeg_running": False, "status": "detenido"})


@pytest.mark.parametrize("changes", [
    {"camera_enabled": False}, {"camera_authorized": False},
    {"camera_mode": "fallback"}, {"map_seconds": 5}, {"auto_start": True},
    {"camera_url": "https://other.invalid/video.mjpeg"},
])
def test_unsupported_settings_refuse_before_status_or_subprocess(settings, changes, monkeypatch):
    status = Mock(side_effect=AssertionError("No status should be read"))
    process = Mock(side_effect=AssertionError("No process should start"))
    monkeypatch.setattr(probe, "read_status", status)
    monkeypatch.setattr(probe.subprocess, "Popen", process)
    with pytest.raises((probe.ProbeError, ValueError)):
        probe.run_probe(replace(settings, **changes))
    status.assert_not_called()
    process.assert_not_called()


def test_running_live_refuses_before_music_or_subprocess(settings, monkeypatch):
    monkeypatch.setattr(probe, "read_status", lambda: {"live_requested": True, "ffmpeg_running": True})
    music = Mock(side_effect=AssertionError("Do not inspect music while live"))
    process = Mock(side_effect=AssertionError("Do not start a second encoder"))
    monkeypatch.setattr(probe, "select_music", music)
    monkeypatch.setattr(probe.subprocess, "Popen", process)
    with pytest.raises(probe.ProbeError, match="live_not_stopped"):
        probe.run_probe(settings)
    music.assert_not_called()
    process.assert_not_called()


def test_starting_live_during_probe_terminates_only_the_local_test_encoder(settings, tmp_path, monkeypatch):
    stopped = {"live_requested": False, "ffmpeg_running": False}
    status = Mock(side_effect=[stopped, stopped, {"live_requested": True, "ffmpeg_running": True}])
    monkeypatch.setattr(probe, "read_status", status)
    monkeypatch.setattr(probe, "select_music", lambda _: tmp_path / "music.wav")
    process = Mock()
    process.stderr = io.StringIO("")
    process.poll.side_effect = [None, None]
    process.wait.return_value = 0
    monkeypatch.setattr(probe.subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(probe.ProbeError, match="live_not_stopped"):
        probe.run_probe(settings)
    assert status.call_count == 3
    process.terminate.assert_called_once()
    process.kill.assert_not_called()
    process.wait.assert_called_once_with(timeout=3)


def test_local_command_uses_actual_graph_without_constructing_controller(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(probe.Controller, "__init__", lambda *args: pytest.fail("Controller constructed"))
    output = tmp_path / "capture.flv"
    command = probe.probe_command(settings, tmp_path / "music.wav", output)
    assert command[-1] == str(output)
    assert "http://127.0.0.1:8092/video.mjpeg" in command
    assert "http://127.0.0.1:8092/map.mjpeg" not in command
    assert not any(value.startswith(("rtmp:", "rtmps:")) for value in command)
    assert "-nostdin" in command
    assert command[-3:-1] == ["-t", "30"]
    assert command[command.index("-r") + 1] == "20"
    assert "[1:a]" in command[command.index("-filter_complex") + 1]


@pytest.mark.parametrize("output", [Path("relative.flv"), Path("/tmp/not-flv.mp4")])
def test_probe_output_must_be_absolute_local_flv(settings, tmp_path, output):
    with pytest.raises(probe.ProbeError, match="unsafe_probe_command"):
        probe.probe_command(settings, tmp_path / "music.wav", output)


def test_music_selection_reads_existing_fallback_without_creating_shared_files(settings):
    music = settings.data_dir / "music" / "astrolearner-lofi-v3.wav"
    music.parent.mkdir(parents=True)
    with wave.open(str(music), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\x00" * 400)
    before = list(settings.data_dir.rglob("*"))
    assert probe.select_music(settings) == music
    assert list(settings.data_dir.rglob("*")) == before


def test_missing_music_fails_without_synthesizing_or_making_directories(settings):
    with pytest.raises(probe.ProbeError, match="music_unavailable"):
        probe.select_music(settings)
    assert not settings.data_dir.exists()


def test_hourly_music_choice_requires_valid_exact_hour_header(settings, monkeypatch):
    hourly = settings.data_dir / "music" / "astrolearner-lofi-hour-v1.wav"
    header = SimpleNamespace(
        getnchannels=lambda: 2, getsampwidth=lambda: 2, getframerate=lambda: 48000,
        getcomptype=lambda: "NONE", getnframes=lambda: 48000 * 3600,
    )
    context = Mock()
    context.__enter__ = Mock(return_value=header)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(probe.wave, "open", lambda *args: context)
    assert probe.select_music(settings) == hourly


def test_ffprobe_checks_expected_codecs_geometry_and_audio(settings, tmp_path, monkeypatch):
    result = SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
        ], "format": {"duration": "30.016"},
    }))
    run = Mock(return_value=result)
    monkeypatch.setattr(probe.subprocess, "run", run)
    assert all(probe.inspect_output(tmp_path / "capture.flv", settings, PipelineDiagnostics()).values())
    args, kwargs = run.call_args
    assert args[0][0] == "ffprobe"
    assert kwargs["timeout"] == 10
    assert kwargs["stdin"] == probe.subprocess.DEVNULL


def test_cli_never_prints_external_exception_or_credential_path(settings, monkeypatch, capsys):
    monkeypatch.setattr(probe, "Settings", lambda: settings)
    monkeypatch.setattr(probe, "run_probe", Mock(side_effect=ValueError("SECRET https://signed.invalid?key=PRIVATE")))
    with pytest.raises(SystemExit) as failure:
        probe.main()
    assert failure.value.code == 1
    printed = capsys.readouterr()
    report = json.loads(printed.out)
    assert report["status"] == "failed" and report["publishing"] is False
    assert "SECRET" not in printed.out and "PRIVATE" not in printed.out
    assert "signed.invalid" not in printed.out
    assert printed.err == ""
