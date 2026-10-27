"""Presentation integration without running threads, synthesis or real APIs."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import struct
import sys
from unittest.mock import Mock
import wave

from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from app.config import Settings
from app.controller import Controller
from app.music_status import MusicSession
from app.presentation import PresentationStore
from app.state import StateStore

PREFERENCES = {"dashboard_enabled": True, "recorded_fallback_enabled": False, "music_style": "classic"}
HEADERS = {"Authorization": "Bearer " + "d" * 64, "Origin": "https://portal.home.arpa"}


def music(path: Path, seconds: int = 3600, *, valid_manifest: bool = True) -> Path:
    """A logically complete, zero-filled PCM fixture, without hour-sized RAM.

    Truncating the new file extends it with zeros; those are valid silent PCM
    samples and its data length really matches the WAV header. This fixture
    never runs music synthesis or a subprocess.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data_size = seconds * 8000 * 4
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + data_size, b"WAVE",
                         b"fmt ", 16, 1, 2, 8000, 32000, 4, 16, b"data", data_size)
    with path.open("wb") as audio:
        audio.write(header)
        audio.truncate(len(header) + data_size)
    manifest = {"duration_seconds": seconds, "tracks": [{
        "title": "Piano de prueba", "start_seconds": 0, "duration_seconds": seconds,
    }]}
    path.with_suffix(".json").write_text(json.dumps(manifest) if valid_manifest else "{", encoding="utf-8")
    return path


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ISS_LIVE_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("ISS_LIVE_CONTROL_TOKEN", "d" * 64)
    monkeypatch.setenv("ISS_LIVE_AUTO_START", "false")
    settings = replace(Settings(), camera_enabled=True, camera_authorized=True,
                       camera_url="http://camera.example.invalid/video.mjpeg", fps=30,
                       width=1280, height=720, use_nasa_playlist=True, camera_mode="auto")
    settings.status_dir.mkdir(parents=True)
    # Constructor only: no lifespan/start means no subprocesses or network.
    return Controller(settings, StateStore(settings.status_dir / "status.json", "Test public source"))


def test_preferences_roundtrip_is_strict_atomic_and_private(tmp_path):
    path = tmp_path / "private" / "presentation.json"
    store = PresentationStore(path)
    assert store.snapshot() == {"dashboard_enabled": False, "recorded_fallback_enabled": True, "music_style": "classic"}
    assert store.save(PREFERENCES) == PREFERENCES
    assert PresentationStore(path).snapshot() == PREFERENCES
    returned = store.snapshot()
    returned["dashboard_enabled"] = False
    assert store.snapshot() == PREFERENCES
    assert json.loads(path.read_text(encoding="utf-8")) == PREFERENCES
    assert list(path.parent.glob("presentation-*")) == []


@pytest.mark.parametrize("invalid", [
    None, [], "classic", {}, {**PREFERENCES, "token": "PRIVATE"},
    {**PREFERENCES, "dashboard_enabled": 1}, {**PREFERENCES, "dashboard_enabled": "false"},
    {**PREFERENCES, "recorded_fallback_enabled": 0}, {**PREFERENCES, "recorded_fallback_enabled": None},
    {**PREFERENCES, "music_style": True}, {**PREFERENCES, "music_style": "https://private/key"},
])
def test_preferences_reject_wrong_shapes_and_types_without_writing(tmp_path, invalid):
    path = tmp_path / "presentation.json"
    store = PresentationStore(path)
    with pytest.raises(ValueError, match="Preferencias"):
        store.save(invalid)
    assert not path.exists()


def test_atomic_replace_failure_preserves_last_good_preferences_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "presentation.json"
    store = PresentationStore(path)
    original = store.snapshot()
    store.save(original)
    contents = path.read_bytes()
    monkeypatch.setattr("app.presentation.os.replace", Mock(side_effect=OSError("disk error")))
    with pytest.raises(OSError):
        store.save(PREFERENCES)
    assert path.read_bytes() == contents
    assert store.snapshot() == original
    assert list(tmp_path.glob("presentation-*")) == []


@pytest.mark.parametrize("contents", [b"{", b"[]", b"null", b"x" * 4097, b"\xff"])
def test_corrupt_or_oversized_preferences_fail_closed(tmp_path, contents):
    path = tmp_path / "presentation.json"
    path.write_bytes(contents)
    with pytest.raises(ValueError):
        PresentationStore(path)


def test_disabling_recorded_backup_is_immediate_without_disabling_camera_recovery(prepared):
    selector = prepared.video_switcher
    clock = [100.0]
    selector._clock = lambda: clock[0]
    map_frame = b"\xff\xd8MAP\xff\xd9"
    selector._map_frame = lambda: map_frame
    selector._running["recorded"] = True
    selector._accept_frame("recorded", b"RECORDED")
    assert selector.frame() == b"RECORDED"
    prepared._active_broadcast_id = "unchanged-broadcast"
    classic = prepared.music_path
    saved = prepared.save_presentation(**PREFERENCES)
    assert selector.frame() == map_frame
    assert selector._mode == "auto" and selector._url == prepared.settings.camera_url
    assert saved["applies"] == {"recorded_fallback_enabled": "now", "dashboard_enabled": "next_block", "music_style": "next_block"}
    assert prepared._dashboard_active is False
    assert prepared.music_path == classic
    assert prepared._active_broadcast_id == "unchanged-broadcast"
    assert not prepared.live_requested.is_set() and prepared.process is None
    # Fresh camera frames still recover automatically after the stability gate.
    for moment in (100.0, 105.0, 110.0, 115.0):
        clock[0] = moment
        selector._running["camera"] = True
        selector._accept_frame("camera", b"CAMERA")
    assert selector.frame() == b"CAMERA"
    assert prepared.store.snapshot()["video_mode"] == "camera"


def test_melodic_preference_only_selects_a_valid_hour_at_next_block(prepared):
    melodic = music(prepared.settings.data_dir / "music" / "astrolearner-melodic-hour-v1.wav")
    assert MusicSession.from_audio(melodic).duration_seconds == 3600
    original = prepared.music_path
    result = prepared.save_presentation(**{**PREFERENCES, "music_style": "melodic"})
    assert result["music_style"] == "melodic" and result["music_active"] == "classic"
    assert result["melodic_available"] is True
    assert prepared.music_path == original  # no rewriting/changing active audio
    prepared._select_music()  # same selection hook used at the next block start
    assert prepared.music_path == melodic
    assert prepared.music_session.duration_seconds == 3600
    assert prepared.presentation_snapshot()["music_active"] == "melodic"
    prepared.save_presentation(**PREFERENCES)
    assert prepared.music_path == melodic
    prepared._select_music()
    assert prepared.music_path == original


@pytest.mark.parametrize("seconds,valid", [(30, True), (3599, True), (3601, True), (3600, False)])
def test_short_mismatched_or_invalid_melodic_audio_is_not_offered_or_applied(prepared, seconds, valid):
    music(prepared.settings.data_dir / "music" / "astrolearner-melodic-hour-v1.wav", seconds, valid_manifest=valid)
    assert prepared.presentation_snapshot()["melodic_available"] is False
    original = prepared.presentation.snapshot()
    with pytest.raises(RuntimeError, match="sesión melódica"):
        prepared.save_presentation(**{**PREFERENCES, "music_style": "melodic"})
    assert prepared.presentation.snapshot() == original
    prepared.presentation.save({**PREFERENCES, "music_style": "melodic"})
    prepared._select_music()
    assert prepared.music_path == prepared._classic_music_path


def test_missing_hour_is_not_generated_by_saving_or_selecting_preferences(prepared, monkeypatch):
    synth = Mock(side_effect=AssertionError("must not synthesize in request"))
    monkeypatch.setattr("app.controller.create_ambient_music", synth)
    with pytest.raises(RuntimeError):
        prepared.save_presentation(**{**PREFERENCES, "music_style": "melodic"})
    prepared._select_music()
    synth.assert_not_called()


def test_dashboard_graph_uses_three_correct_inputs_and_same_30fps_cadence(prepared):
    prepared._dashboard_active = True
    command = prepared._ffmpeg_command("local-validation.flv")
    inputs = [command[index + 1] for index, token in enumerate(command) if token == "-i"]
    assert inputs == ["http://127.0.0.1:8092/video.mjpeg", "http://127.0.0.1:8092/dashboard.mjpeg", str(prepared.music_path)]
    assert "http://127.0.0.1:8092/map.mjpeg" not in command
    assert [command[index + 1] for index, token in enumerate(command) if token == "-r"] == ["30", "30", "30"]
    graph = command[command.index("-filter_complex") + 1]
    assert "scale=1280:576:force_original_aspect_ratio=decrease" in graph
    assert "pad=1280:576:(ow-iw)/2:(oh-ih)/2" in graph
    assert "[1:v]fps=30,setpts=PTS-STARTPTS,format=yuv420p[hud]" in graph
    assert "[scene][hud]vstack=inputs=2:shortest=0[video]" in graph
    assert "[2:a]asetpts=PTS-STARTPTS" in graph
    assert prepared.dashboard.height + 576 == prepared.settings.height
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-c:a") + 1] == "aac"


def test_legacy_graph_stays_unchanged_until_next_block(prepared):
    prepared.save_presentation(**PREFERENCES)
    assert not prepared._dashboard_active
    command = prepared._ffmpeg_command("local-validation.flv")
    assert "http://127.0.0.1:8092/dashboard.mjpeg" not in command
    assert "http://127.0.0.1:8092/map.mjpeg" in command


@pytest.fixture
def api(monkeypatch, prepared):
    sys.modules.pop("app.main", None)
    module = importlib.import_module("app.main")
    monkeypatch.setattr(module, "controller", prepared)
    monkeypatch.setattr(module, "settings", prepared.settings)
    monkeypatch.setattr(module, "store", prepared.store)
    # Intentionally do not enter TestClient lifespan: no controller.start().
    yield TestClient(module.app), module
    sys.modules.pop("app.main", None)


def test_presentation_get_requires_auth_and_is_not_cached(api):
    client, _ = api
    assert client.get("/presentation").status_code == 401
    response = client.get("/presentation", headers={"Authorization": HEADERS["Authorization"]})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["dashboard_active"] is False


@pytest.mark.parametrize("method,headers,status", [
    ("get", {**HEADERS, "Origin": "https://evil.invalid"}, 403),
    ("post", {}, 403),
    ("post", {"Authorization": HEADERS["Authorization"]}, 403),
    ("post", {**HEADERS, "Authorization": "Bearer wrong"}, 401),
    ("post", {**HEADERS, "Origin": "https://evil.invalid"}, 403),
])
def test_presentation_bad_authorization_or_origin_never_writes(api, method, headers, status):
    client, main = api
    response = client.request(method.upper(), "/presentation", headers=headers, json=PREFERENCES)
    assert response.status_code == status
    assert not main.controller.presentation.path.exists()
    assert not main.controller.live_requested.is_set()


def test_presentation_save_does_not_start_publish_threads_or_change_active_graph(api):
    client, main = api
    response = client.post("/presentation", headers=HEADERS, json=PREFERENCES)
    assert response.status_code == 200
    assert response.json()["applies"]["dashboard_enabled"] == "next_block"
    assert response.json()["recorded_fallback_enabled"] is False
    assert main.controller._dashboard_thread.ident is None and main.controller._space_thread.ident is None
    assert main.controller._dashboard_active is False
    assert main.controller.process is None and not main.controller.live_requested.is_set()


@pytest.mark.parametrize("body", [
    {**PREFERENCES, "dashboard_enabled": "false"}, {**PREFERENCES, "recorded_fallback_enabled": 0},
    {**PREFERENCES, "music_style": "PRIVATE_SECRET_TOKEN"},
    {**PREFERENCES, "rtmp_key": "PRIVATE_SECRET_TOKEN"},
])
def test_presentation_validation_never_reflects_input_or_private_values(api, body):
    client, main = api
    response = client.post("/presentation", headers=HEADERS, json=body)
    assert response.status_code == 422
    assert "PRIVATE_SECRET_TOKEN" not in response.text and "input_value" not in response.text
    assert not main.controller.presentation.path.exists()


def test_presentation_oversized_body_is_rejected_without_reflection(api):
    client, main = api
    response = client.post("/presentation", headers=HEADERS, content=b"PRIVATE_SECRET_TOKEN" + b"x" * 4096)
    assert response.status_code == 413 and "PRIVATE_SECRET_TOKEN" not in response.text
    assert not main.controller.presentation.path.exists()


@pytest.mark.parametrize("base_url,headers", [
    ("https://portal.home.arpa", {}),
    ("http://127.0.0.1:8092", {"X-Forwarded-For": "10.0.0.1"}),
    ("http://127.0.0.1:8092", {"Forwarded": "for=10.0.0.1"}),
    ("http://127.0.0.1:8092", {"Sec-Fetch-Site": "cross-site"}),
])
def test_dashboard_transport_is_local_only_not_exposed_by_portal_proxy(api, base_url, headers):
    _, main = api
    main.controller._dashboard_active = True
    client = TestClient(main.app, base_url=base_url)
    assert client.get("/dashboard.mjpeg", headers=headers).status_code == 403


def test_dashboard_pipe_repeats_cached_frame_without_rendering_30fps(api, monkeypatch):
    _, main = api
    main.controller._dashboard_active = True
    now = datetime.now(timezone.utc)
    main.controller.dashboard_jpeg = main.controller.dashboard.render(main.store.snapshot(), now=now).jpeg
    main.controller.dashboard.render = Mock(side_effect=AssertionError("must not render in video pipe"))
    request = Request({"type": "http", "method": "GET", "path": "/dashboard.mjpeg", "scheme": "http",
                       "headers": [(b"host", b"127.0.0.1:8092")], "query_string": b"",
                       "server": ("127.0.0.1", 8092), "client": ("127.0.0.1", 1234)})

    async def consume():
        response = await main.dashboard_video(request)
        iterator = response.body_iterator
        frames = [await anext(iterator) for _ in range(2)]
        await iterator.aclose()
        return response, frames

    response, frames = asyncio.run(consume())
    assert response.headers["cache-control"] == "no-store"
    assert frames[0] == frames[1] and main.controller.dashboard_jpeg in frames[0]
    assert not main.controller.live_requested.is_set()
