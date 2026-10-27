from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import httpx
import pytest

from app.config import Settings
from app.controller import Controller
from app.state import StateStore
from app.youtube import BroadcastUnavailableError


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setenv("ISS_LIVE_DATA_DIR", str(tmp_path / "data"))
    settings = Settings()
    return Controller(settings, StateStore(tmp_path / "status.json", settings.source_label))


def test_frame_freshness_requires_increasing_count(controller):
    old = datetime.now(UTC) - timedelta(seconds=40)
    start = datetime.now(UTC)
    controller._parse_progress("frame=10", start, True, observed_at=old)
    controller._parse_progress("fps=12.0", start, True)
    controller._parse_progress("frame=10", start, True)
    controller._parse_progress("frame=9", start, True)
    state = controller.store.snapshot()
    assert state["ffmpeg_frame_count"] == 10
    assert state["last_frame_at"] == old.isoformat()
    assert state["last_progress_at"] != old.isoformat()
    controller._parse_progress("frame=11", start, True)
    assert controller.store.snapshot()["last_frame_at"] != old.isoformat()


@pytest.mark.parametrize("line", ["frame=N/A", "frame=-1", "fps=nan", "fps=inf", "out_time_us=N/A", "out_time_us=-1"])
def test_invalid_progress_cannot_make_a_fresh_signal(controller, line):
    controller._parse_progress(line, datetime.now(UTC), True)
    state = controller.store.snapshot()
    assert state["last_frame_at"] is None
    assert state["last_progress_at"] is None
    assert state["ffmpeg_out_time_seconds"] is None


def test_music_uses_output_time_not_wall_clock(controller):
    session = Mock()
    session.playback.return_value = {"music_track": "Luz lunar"}
    controller.music_session = session
    controller.store.update(ffmpeg_running=True)
    start = datetime.now(UTC) - timedelta(hours=9)
    controller._parse_progress("out_time_us=300500000", start, True)
    session.playback.assert_called_once_with(300.5)
    state = controller.store.snapshot()
    assert state["ffmpeg_out_time_seconds"] == 300.5
    assert state["music_playback_active"] is True
    assert state["music_track"] == "Luz lunar"
    controller._parse_progress("out_time_us=1000", start, True)
    assert controller.store.snapshot()["ffmpeg_out_time_seconds"] == 300.5


def test_health_error_keeps_old_check_time_and_hides_exception(controller):
    controller.store.update(youtube_checked_at="2026-01-01T00:00:00Z")
    youtube = Mock()
    youtube.stream_health.side_effect = OSError("rtmp://private.example/SECRET")
    controller._update_youtube_health(youtube, "private-stream-id")
    state = controller.store.snapshot()
    assert state["youtube_checked_at"] == "2026-01-01T00:00:00Z"
    assert state["youtube_check_error"]
    assert "SECRET" not in state["youtube_check_error"]


def test_missing_health_clears_previously_good_signal(controller):
    controller.store.update(youtube_health_status="good", youtube_stream_status="active")
    youtube = Mock()
    youtube.stream_health.return_value = None
    controller._update_youtube_health(youtube, "stream")
    state = controller.store.snapshot()
    assert state["youtube_health_status"] == "unknown"
    assert state["youtube_stream_status"] == "unknown"
    assert state["youtube_checked_at"]


class FakeProcess:
    def __init__(self, lines):
        self.stderr = iter(lines)
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        self.terminated = True
        return 1


def fake_youtube(controller):
    youtube = Mock()
    youtube.broadcast_status.return_value = {
        "life_cycle_status": "live", "privacy_status": controller.settings.privacy,
    }
    youtube.stream_health.return_value = {
        "stream_status": "active", "health_status": "good",
        "health_updated_at": datetime.now(UTC).isoformat(), "issues": [],
    }
    return youtube


def test_monitor_drains_progress_clears_playback_and_redacts_rtmp(monkeypatch, controller):
    url = "rtmp://example.invalid/PRIVATE-STREAM-KEY"
    process = FakeProcess(["frame=12\n", "out_time_us=1000000\n", f"Output error at {url}\n"])
    monkeypatch.setattr("app.controller.subprocess.Popen", lambda *args, **kwargs: process)
    controller.live_requested.set()
    youtube = fake_youtube(controller)
    with pytest.raises(RuntimeError, match="RTMP REDACTADO") as error:
        controller._run_ffmpeg(url, "https://www.youtube.com/watch?v=test", youtube, "broadcast", "stream")
    assert "PRIVATE-STREAM-KEY" not in str(error.value)
    state = controller.store.snapshot()
    assert state["ffmpeg_frame_count"] == 12
    assert state["last_frame_at"]
    assert state["ffmpeg_out_time_seconds"] == 1
    assert state["youtube_health_status"] == "good"
    assert state["ffmpeg_running"] is False
    assert state["music_playback_active"] is False
    youtube.broadcast_status.assert_called_once_with("broadcast")
    youtube.stream_health.assert_called_once_with("stream")


def test_complete_broadcast_terminates_without_health_call(monkeypatch, controller):
    process = FakeProcess(["frame=12\n"])
    monkeypatch.setattr("app.controller.subprocess.Popen", lambda *args, **kwargs: process)
    youtube = fake_youtube(controller)
    youtube.broadcast_status.return_value["life_cycle_status"] = "complete"
    controller.live_requested.set()
    with pytest.raises(BroadcastUnavailableError):
        controller._run_ffmpeg("rtmp://invalid/key", "watch", youtube, "broadcast", "stream")
    assert process.terminated
    assert controller.store.snapshot()["ffmpeg_running"] is False
    youtube.stream_health.assert_not_called()


def test_google_query_cannot_block_progress_or_revive_stopped_music(monkeypatch, controller):
    initial_progress = threading.Event()
    late_progress = threading.Event()
    release_late = threading.Event()

    def stderr():
        yield "frame=12\n"
        yield "out_time_us=1000000\n"
        initial_progress.set()
        assert release_late.wait(timeout=3)
        yield "frame=24\n"
        yield "out_time_us=2000000\n"
        late_progress.set()

    process = FakeProcess(stderr())
    monkeypatch.setattr("app.controller.subprocess.Popen", lambda *args, **kwargs: process)
    youtube = fake_youtube(controller)
    def lifecycle(_):
        # Reader must publish progress before the Google call returns, not after.
        assert initial_progress.wait(timeout=3)
        assert controller.store.snapshot()["ffmpeg_frame_count"] == 12
        assert controller.store.snapshot()["music_playback_active"] is True
        return {"life_cycle_status": "live", "privacy_status": controller.settings.privacy}
    def health(_):
        controller.request_live_stop()
        release_late.set()
        assert late_progress.wait(timeout=3)
        state = controller.store.snapshot()
        assert state["ffmpeg_frame_count"] == 12
        assert state["ffmpeg_out_time_seconds"] == 1
        assert state["music_playback_active"] is False
        assert state["status"] == "deteniendo"
        return None
    youtube.broadcast_status.side_effect = lifecycle
    youtube.stream_health.side_effect = health
    controller.live_requested.set()
    controller._run_ffmpeg("rtmp://invalid/key", "watch", youtube, "broadcast", "stream")
    assert controller.store.snapshot()["music_playback_active"] is False


@pytest.mark.parametrize("data", [
    {"latitude": "nan", "longitude": 10},
    {"latitude": 91, "longitude": 10},
    {"latitude": 10, "longitude": 181},
    {"latitude": 10, "longitude": 10, "timestamp": True},
])
def test_invalid_position_does_not_refresh_age_or_poison_map(monkeypatch, controller, data):
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
    monkeypatch.setattr("app.controller.httpx.get", lambda *args, **kwargs: response)
    drawn = []
    def render(*args):
        drawn.append(args)
        controller.stop_event.set()
    monkeypatch.setattr("app.controller.render_map", render)
    controller.update_position()
    assert controller.store.snapshot()["position_updated_at"] is None
    assert drawn[0][3:6] == (0, 0, 420)


def test_position_uses_source_timestamp_and_survives_next_failure(monkeypatch, controller):
    observed = datetime.now(UTC) - timedelta(minutes=2)
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        "latitude": 20, "longitude": -30, "altitude": 425, "velocity": 27000,
        "timestamp": observed.timestamp(),
    })
    requests = Mock(side_effect=[response, httpx.ConnectError("offline")])
    monkeypatch.setattr("app.controller.httpx.get", requests)
    drawn = []
    def render(*args):
        drawn.append(args)
        if len(drawn) == 2:
            controller.stop_event.set()
    monkeypatch.setattr("app.controller.render_map", render)
    monkeypatch.setattr(controller.stop_event, "wait", lambda seconds: None)
    controller.update_position()
    state = controller.store.snapshot()
    assert state["position_updated_at"] == observed.isoformat()
    assert state["latitude"] == 20
    assert drawn[0][3:6] == drawn[1][3:6]
