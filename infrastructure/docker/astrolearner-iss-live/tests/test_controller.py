from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import Settings
from app.controller import Controller
from app.state import StateStore


def test_nasa_loop_video_is_read_at_realtime_without_source_seams(
    monkeypatch, tmp_path: Path
):
    loop_video = tmp_path / "astrolearner-nasa-loop.mp4"
    loop_video.touch()
    monkeypatch.setenv("ISS_LIVE_USE_NASA_PLAYLIST", "true")
    monkeypatch.setenv("ISS_LIVE_NASA_LOOP_VIDEO", str(loop_video))
    monkeypatch.setenv("ISS_LIVE_FPS", "12")

    settings = Settings()
    store = StateStore(tmp_path / "status.json", settings.source_label)
    command = Controller(settings, store)._ffmpeg_command("rtmp://example.invalid/key")
    graph = command[command.index("-filter_complex") + 1]

    assert command.index("-re") < command.index("-i")
    assert "-stream_loop" in command
    assert command[command.index("-stream_loop") + 1] == "-1"
    assert str(loop_video) in command
    assert "concat" not in command
    assert "setpts=PTS-STARTPTS" in graph
    assert "asetpts=PTS-STARTPTS" in graph
    assert "drawbox=x=0:y=ih-48:w=iw:h=48" in graph
    assert "y=main_h-34" in graph
    map_input = command.index("http://127.0.0.1:8092/map.mjpeg")
    assert command[map_input - 5 : map_input] == ["-r", "1", "-f", "mjpeg", "-i"]


def test_nasa_loop_video_is_read_at_realtime_in_safe_fallback(monkeypatch, tmp_path):
    loop_video = tmp_path / "astrolearner-nasa-loop.mp4"
    loop_video.touch()
    monkeypatch.setenv("ISS_LIVE_USE_NASA_PLAYLIST", "true")
    monkeypatch.setenv("ISS_LIVE_NASA_LOOP_VIDEO", str(loop_video))
    monkeypatch.setenv("ISS_LIVE_DRY_RUN", "true")
    monkeypatch.setenv("ISS_LIVE_WIDTH", "1280")
    monkeypatch.setenv("ISS_LIVE_HEIGHT", "720")
    monkeypatch.setenv("ISS_LIVE_FPS", "15")

    settings = Settings()
    command = Controller(
        settings, StateStore(tmp_path / "status.json", settings.source_label)
    )._ffmpeg_command("rtmp://example.invalid/key")

    assert settings.dry_run is True
    assert settings.width == 1280
    assert settings.height == 720
    assert settings.fps == 15
    assert "-preset" in command
    assert command[command.index("-preset") + 1] == "ultrafast"


def test_vaapi_encoder_uses_only_the_intel_render_node(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_ENCODER", "h264_vaapi")
    monkeypatch.setenv("ISS_LIVE_FPS", "12")
    loop_video = tmp_path / "astrolearner-nasa-loop.mp4"
    loop_video.touch()
    monkeypatch.setenv("ISS_LIVE_USE_NASA_PLAYLIST", "true")
    monkeypatch.setenv("ISS_LIVE_NASA_LOOP_VIDEO", str(loop_video))
    settings = Settings()
    command = Controller(
        settings, StateStore(tmp_path / "status.json", settings.source_label)
    )._ffmpeg_command("rtmp://example.invalid/key")
    graph = command[command.index("-filter_complex") + 1]

    assert settings.encoder == "h264_vaapi"
    assert command[command.index("-init_hw_device") + 1] == (
        "vaapi=va:/dev/dri/renderD128"
    )
    assert "-hwaccel" not in command
    assert command[command.index("-c:v") + 1] == "h264_vaapi"
    assert command[command.index("-map") + 1] == "[encoded]"
    assert "format=nv12,hwupload[encoded]" in graph
    assert "-preset" not in command
    assert command[command.index("-rc_mode") + 1] == "CQP"
    assert command[command.index("-qp") + 1] == "24"
    assert "-maxrate" not in command
    assert "[0:v]fps=fps=12,scale=1280:720" in graph
    assert "hwdownload" not in graph
    assert "scale_vaapi" not in graph


def test_invalid_encoder_is_rejected(monkeypatch):
    monkeypatch.setenv("ISS_LIVE_ENCODER", "h264_nvenc")
    with pytest.raises(ValueError):
        Settings().validate()


def test_manual_live_controls_toggle_state_without_starting_a_stream(
    monkeypatch, tmp_path: Path
):
    loop_video = tmp_path / "astrolearner-nasa-loop.mp4"
    loop_video.touch()
    token = tmp_path / "youtube-token.json"
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ISS_LIVE_DRY_RUN", "false")
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    monkeypatch.setenv("ISS_LIVE_USE_NASA_PLAYLIST", "true")
    monkeypatch.setenv("ISS_LIVE_NASA_LOOP_VIDEO", str(loop_video))
    monkeypatch.setenv("ISS_LIVE_YOUTUBE_TOKEN", str(token))

    settings = Settings()
    store = StateStore(tmp_path / "status.json", settings.source_label)
    controller = Controller(settings, store)

    assert not controller.live_requested.is_set()
    controller.request_live_start()
    assert controller.live_requested.is_set()
    assert store.snapshot()["live_requested"] is True

    controller.request_live_stop()
    assert not controller.live_requested.is_set()
    assert store.snapshot()["live_requested"] is False


def test_dry_run_blocks_manual_start(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ISS_LIVE_DRY_RUN", "true")
    settings = Settings()
    controller = Controller(
        settings, StateStore(tmp_path / "status.json", settings.source_label)
    )

    with pytest.raises(RuntimeError, match="dry-run"):
        controller.request_live_start()


def test_progress_is_not_reported_live_before_youtube_confirms(tmp_path: Path):
    settings = Settings()
    store = StateStore(tmp_path / "status.json", settings.source_label)
    controller = Controller(settings, store)

    controller._parse_progress("fps=12.0", datetime.now(UTC), youtube_live=False)

    status = store.snapshot()
    assert status["status"] == "señal enviada; esperando confirmación de YouTube"
    assert status["source_status"] == "verificando en YouTube"

    controller._parse_progress("fps=12.0", datetime.now(UTC), youtube_live=True)
    assert store.snapshot()["status"] == "en directo"


def test_stopping_clears_stale_youtube_watch_url(tmp_path: Path):
    settings = Settings()
    store = StateStore(tmp_path / "status.json", settings.source_label)
    store.update(youtube_watch_url="https://www.youtube.com/watch?v=old-video")
    controller = Controller(settings, store)

    controller._mark_live_stopped()

    assert store.snapshot()["youtube_watch_url"] == ""
