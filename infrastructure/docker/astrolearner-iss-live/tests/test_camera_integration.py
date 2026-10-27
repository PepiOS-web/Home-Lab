import asyncio
import importlib
import io
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image
from starlette.requests import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.controller import Controller
from app.state import StateStore


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    settings = replace(Settings(), camera_enabled=True)
    settings.status_dir.mkdir(parents=True)
    return Controller(settings, StateStore(settings.status_dir / "status.json", settings.source_label))


def test_camera_mode_overrides_existing_downloaded_video(prepared, tmp_path):
    recorded = tmp_path / "recorded.mp4"
    recorded.touch()
    prepared.settings = replace(prepared.settings, nasa_loop_video=recorded)
    command = prepared._ffmpeg_command("rtmp://example.invalid/private")
    assert "http://127.0.0.1:8092/video.mjpeg" in command
    assert str(recorded) not in command
    assert "http://127.0.0.1:8092/map.mjpeg" in command
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-c:a") + 1] == "aac"
    graph = command[command.index("-filter_complex") + 1]
    assert "reload=1" in graph
    assert "textfile=" in graph
    assert "asetpts=PTS-STARTPTS" in graph
    audio_index = command.index(str(prepared.music_path))
    assert command[audio_index - 2:audio_index] == ["-re", "-i"]


def test_camera_source_never_reaches_publishing_command(prepared):
    prepared.settings = replace(prepared.settings, camera_url="https://camera.example/live?key=PRIVATE")
    command = prepared._ffmpeg_command("rtmp://example.invalid/private")
    assert "PRIVATE" not in " ".join(command)
    assert "camera.example" not in " ".join(command)


@pytest.mark.parametrize('fps', [20, 30])
def test_higher_fps_reaches_selector_input_and_encoder_without_changing_geometry(prepared, fps):
    prepared.settings = replace(prepared.settings, fps=fps)
    command = prepared._ffmpeg_command("local-test.flv")
    # Camera input and encoder change together; the small orbital map stays 1 FPS.
    assert [command[index + 1] for index, value in enumerate(command) if value == "-r"] == [str(fps), "1", str(fps)]
    assert command[command.index("-c:v") + 1] == "libx264"
    assert (prepared.settings.width, prepared.settings.height) == (1280, 720)


def test_camera_output_bounds_each_decoder_filter_pool_and_encoder(prepared):
    command = prepared._ffmpeg_command("local-test.flv")
    input_ends = [index for index, value in enumerate(command) if value == "-i"]
    start = 1
    for index, end in enumerate(input_ends):
        group = command[start:end]
        option = "-threads:v" if index < 2 else "-threads:a"
        assert group[group.index(option) + 1] == "1"
        start = end + 2
    output = command[start:]
    assert output[output.index("-threads:v") + 1] == "2"
    assert output[output.index("-threads:a") + 1] == "1"
    for option in ("-filter_threads", "-filter_complex_threads"):
        assert command[command.index(option) + 1] == "1"


def test_thread_bounds_do_not_change_the_existing_non_camera_pipeline(prepared):
    prepared.settings = replace(prepared.settings, camera_enabled=False)
    command = prepared._ffmpeg_command("local-test.flv")
    assert not any(option in command for option in ("-threads:v", "-threads:a", "-filter_threads", "-filter_complex_threads"))


def test_source_callback_drops_private_fields_and_labels_recordings(prepared):
    prepared._video_source_status({
        "video_mode": "recorded", "camera_state": "stale",
        "video_fallback_reason": "camera_stale", "camera_url": "https://private/key",
        "rtmp_url": "rtmp://private/key", "stderr": "SECRET",
    })
    state = prepared.store.snapshot()
    assert state["video_mode"] == "recorded"
    assert "grabados" in state["visual_source"]
    assert "SECRET" not in json.dumps(state)
    assert "private/key" not in json.dumps(state)
    label = prepared.video_label_path.read_text(encoding="utf-8")
    assert "VIDEO GRABADO" in label
    assert "PRIVATE" not in label
    prepared._video_source_status({"video_mode": "camera", "camera_state": "live"})
    label = prepared.video_label_path.read_text(encoding="utf-8")
    assert "Senal externa ISS" in label
    assert "DIRECTO" not in label  # Upstream may itself show a recorded fallback.


def test_map_conversion_cached_between_position_renders(prepared, monkeypatch):
    Image.new("RGB", (1280, 720), "green").save(prepared.map_path)
    with pytest.MonkeyPatch.context() as patch:
        open_image = Image.open
        calls = Mock(wraps=open_image)
        patch.setattr("app.controller.Image.open", calls)
        first = prepared._map_video_frame()
        second = prepared._map_video_frame()
    assert calls.call_count == 1
    assert first is second
    with Image.open(io.BytesIO(first)) as image:
        assert image.size == (1280, 720)
    prepared.map_path.unlink()
    assert prepared._map_video_frame() is first


def test_disabled_camera_is_not_instantiated(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_CAMERA_ENABLED", "false")
    controller = Controller(Settings(), StateStore(tmp_path / "state.json", "test"))
    assert controller.video_switcher is None


def test_shutdown_safe_with_unstarted_optional_threads(prepared):
    prepared.video_switcher = Mock()
    prepared.shutdown()
    prepared.video_switcher.stop.assert_called_once()


def test_isolated_camera_dry_run_does_not_synthesize_music(prepared, monkeypatch):
    prepared.settings = replace(prepared.settings, dry_run=True)
    prepared.video_switcher = Mock()
    prepared._thread = Mock()
    prepared._map_thread = Mock()
    prepared._earth_thread = Mock()
    synth = Mock()
    preview = Mock()
    monkeypatch.setattr("app.controller.create_ambient_music", synth)
    monkeypatch.setattr("app.controller.create_music_preview", preview)
    prepared.start()
    synth.assert_not_called()
    preview.assert_not_called()
    prepared.video_switcher.start.assert_called_once()
    prepared._earth_thread.start.assert_not_called()


@pytest.fixture
def main_app(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("ISS_LIVE_CAMERA_ENABLED", "false")
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    sys.modules.pop("app.main", None)
    module = importlib.import_module("app.main")
    yield module
    sys.modules.pop("app.main", None)


def test_video_endpoint_disabled_does_not_start_reader(main_app):
    response = asyncio.run(main_app.selected_video(local_request()))
    assert response.status_code == 503
    assert not main_app.controller.live_requested.is_set()


def local_request():
    return Request({
        "type": "http", "method": "GET", "path": "/video.mjpeg", "scheme": "http",
        "headers": [(b"host", b"127.0.0.1:8092")], "query_string": b"",
        "server": ("127.0.0.1", 8092), "client": ("127.0.0.1", 12345),
    })


@pytest.mark.parametrize("base_url,headers", [
    ("https://portal.home.arpa", {}),
    ("http://127.0.0.1:8092", {"X-Forwarded-For": "10.0.0.1"}),
    ("http://127.0.0.1:8092", {"X-Forwarded-Host": "portal.home.arpa"}),
    ("http://127.0.0.1:8092", {"Sec-Fetch-Site": "cross-site"}),
])
def test_gateway_is_not_exposed_through_portal_or_cross_site(main_app, base_url, headers):
    main_app.controller.video_switcher = Mock()
    client = TestClient(main_app.app, base_url=base_url)
    assert client.get("/video.mjpeg", headers=headers).status_code == 403
    main_app.controller.video_switcher.frame.assert_not_called()


def test_endpoint_keeps_same_stream_when_selector_changes(main_app):
    switcher = Mock()
    frames = [b"\xff\xd8camera\xff\xd9", b"\xff\xd8recorded\xff\xd9", b"\xff\xd8map\xff\xd9"]
    switcher.frame.side_effect = frames
    main_app.controller.video_switcher = switcher

    async def consume():
        response = await main_app.selected_video(local_request())
        iterator = response.body_iterator
        chunks = [await anext(iterator) for _ in range(3)]
        await iterator.aclose()
        return chunks

    chunks = asyncio.run(consume())
    assert all(frame in chunk for frame, chunk in zip(frames, chunks))
    assert not main_app.controller.live_requested.is_set()
    assert main_app.controller.process is None


def test_camera_start_can_use_map_even_without_downloaded_video(prepared, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    prepared.settings = replace(prepared.settings, dry_run=False, youtube_token=token,
                                nasa_loop_video=tmp_path / "missing.mp4", source_url="")
    prepared.request_live_start()
    assert prepared.store.snapshot()["live_requested"] is True
    prepared.request_live_stop()
