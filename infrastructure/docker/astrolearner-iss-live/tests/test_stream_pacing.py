"""Regressions for hidden-map frame synchronization and MJPEG cadence."""

import asyncio
import importlib
import sys
from dataclasses import replace

import pytest

from app.config import Settings
from app.controller import Controller
from app.state import StateStore


@pytest.mark.parametrize("source", ["camera", "recorded", "external"])
@pytest.mark.parametrize("encoder", ["libx264", "h264_vaapi"])
@pytest.mark.parametrize("map_seconds", [0, 5])
@pytest.mark.parametrize("fps", [12, 20, 30])
def test_map_input_exists_only_when_map_overlay_is_enabled(
    tmp_path, source, encoder, map_seconds, fps
):
    recorded = tmp_path / "recorded.mp4"
    recorded.touch()
    settings = replace(
        Settings(),
        data_dir=tmp_path / "data",
        status_dir=tmp_path / "status",
        dry_run=True,
        auto_start=False,
        camera_enabled=source == "camera",
        camera_url="https://camera.invalid/live?key=private-camera-key",
        use_nasa_playlist=source != "external",
        nasa_loop_video=recorded,
        source_url="https://source.invalid/video.m3u8",
        encoder=encoder,
        map_seconds=map_seconds,
        map_interval_seconds=600,
        width=1280,
        height=720,
        fps=fps,
    )
    controller = Controller(
        settings, StateStore(tmp_path / "status.json", "test source")
    )
    command = controller._ffmpeg_command("local-test.flv")
    graph = command[command.index("-filter_complex") + 1]
    input_ends = [index for index, value in enumerate(command) if value == "-i"]
    inputs = [command[index + 1] for index in input_ends]

    expected_source = {
        "camera": "http://127.0.0.1:8092/video.mjpeg",
        "recorded": str(recorded),
        "external": settings.source_url,
    }[source]
    assert inputs[0] == expected_source
    assert inputs[-1] == str(controller.music_path)
    assert "[0:v]" in graph
    assert command[command.index("-c:v") + 1] == encoder
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-g") + 1] == str(fps * 2)
    output = command[input_ends[-1] + 2:]
    assert output[output.index("-r") + 1] == str(fps)
    assert "[audio]" in command
    assert "asetpts=PTS-STARTPTS" in graph
    assert "aresample=48000[audio]" in graph

    if map_seconds == 0:
        # A disabled overlay must not remain as an input to framesync: its slow
        # 1 FPS JPEG producer otherwise throttles the primary video and audio.
        assert inputs == [expected_source, str(controller.music_path)]
        assert "http://127.0.0.1:8092/map.mjpeg" not in command
        assert "overlay=" not in graph
        assert "[map]" not in graph
        assert "[1:v]" not in graph
        assert "[1:a]asetpts=PTS-STARTPTS" in graph
        assert "[2:a]" not in graph
    else:
        assert inputs == [
            expected_source,
            "http://127.0.0.1:8092/map.mjpeg",
            str(controller.music_path),
        ]
        assert "[1:v]setpts=PTS-STARTPTS,scale=1280:720[map]" in graph
        assert "[base][map]overlay=enable='lt(mod(t,600),5)'[video]" in graph
        assert "[2:a]asetpts=PTS-STARTPTS" in graph

    if encoder == "h264_vaapi":
        assert ";[video]format=nv12,hwupload[encoded]" in graph
        assert command[command.index("-map") + 1] == "[encoded]"
        assert "-preset" not in command
        assert command[command.index("-init_hw_device") + 1] == "vaapi=va:/dev/dri/renderD128"
    else:
        assert command[command.index("-map") + 1] == "[video]"
        assert command[command.index("-preset") + 1] == "ultrafast"
        assert "hwupload" not in graph

    if source == "camera":
        assert "private-camera-key" not in " ".join(command)
        # Decoder/encoder bounds must remain attached to the correct inputs,
        # even when removing the map changes the audio stream index.
        start = 1
        for index, end in enumerate(input_ends):
            group = command[start:end]
            option = "-threads:a" if index == len(input_ends) - 1 else "-threads:v"
            assert group[group.index(option) + 1] == "1"
            start = end + 2
        assert output[output.index("-threads:a") + 1] == "1"
        assert output[output.index("-threads:v") + 1] == ("2" if encoder == "libx264" else "1")
    elif source == "recorded":
        first_input_options = command[:input_ends[0]]
        assert "-re" in first_input_options
        assert first_input_options[first_input_options.index("-stream_loop") + 1] == "-1"
        assert "setpts=PTS-STARTPTS" in graph
    else:
        assert command[command.index("-reconnect") + 1] == "1"


@pytest.fixture
def main_module(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("ISS_LIVE_DRY_RUN", "true")
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    monkeypatch.setenv("ISS_LIVE_CAMERA_ENABLED", "false")
    previous = sys.modules.pop("app.main", None)
    module = importlib.import_module("app.main")
    yield module
    sys.modules.pop("app.main", None)
    if previous is not None:
        sys.modules["app.main"] = previous


@pytest.mark.parametrize("kind", ["map", "earth"])
def test_mjpeg_encoding_time_does_not_accumulate_in_frame_interval(
    main_module, monkeypatch, tmp_path, kind
):
    clock = {"now": 100.0}
    sleeps = []
    opened = []

    class ConvertedImage:
        def save(self, buffer, **kwargs):
            clock["now"] += 0.2
            buffer.write(b"\xff\xd8test-jpeg\xff\xd9")

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    class OpenedImage:
        def __init__(self):
            self.closed = False
            opened.append(self)

        def convert(self, mode):
            assert mode == "RGB"
            return ConvertedImage()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

    async def fake_sleep(seconds):
        assert seconds >= 0
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(main_module.Image, "open", lambda path: OpenedImage())
    monkeypatch.setattr(main_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)

    async def consume():
        response = main_module._mjpeg(tmp_path / "frame.png", kind)
        iterator = response.body_iterator
        times = []
        try:
            for _ in range(4):
                chunk = await anext(iterator)
                assert b"test-jpeg" in chunk
                assert all(image.closed for image in opened)
                times.append(clock["now"])
        finally:
            await iterator.aclose()
        return times

    times = asyncio.run(consume())
    assert times == pytest.approx([100.2, 101.2, 102.2, 103.2])
    assert sleeps == pytest.approx([0.8, 0.8, 0.8])
    assert len(opened) == 4
