from dataclasses import replace
from datetime import UTC, datetime, timedelta
import ast
import hashlib
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock
import shutil
import wave

import pytest

from app.config import Settings
from app.controller import Controller, FFmpegConnectionError, connection_failure_reason
from app.state import StateStore
from app.youtube import Broadcast, BroadcastUnavailableError


@pytest.fixture
def recovery(monkeypatch, tmp_path):
    settings = replace(Settings(), data_dir=tmp_path / "data", status_dir=tmp_path / "status",
                       dry_run=False, auto_start=False, source_url="https://example.invalid/recorded",
                       fps=30, block_seconds=400)
    controller = Controller(settings, StateStore(tmp_path / "status.json", "test"))
    controller.live_requested.set()
    clock = SimpleNamespace(now=1000.0, waits=[])
    monkeypatch.setattr("app.controller.time.monotonic", lambda: clock.now)

    def wait(seconds):
        clock.waits.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(controller, "_wait_while_live", wait)
    youtube = Mock()
    youtube.broadcast_status.return_value = {"life_cycle_status": "live", "privacy_status": settings.privacy}
    broadcast = Broadcast("original-id", "original-stream", "rtmp://example.invalid/SECRET", "https://www.youtube.com/watch?v=abcdefghijk")
    return controller, clock, youtube, broadcast


def test_reconnect_reuses_video_stream_key_clock_and_music_position(recovery, monkeypatch):
    controller, clock, youtube, broadcast = recovery
    calls = []

    def ffmpeg(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) <= 2:
            clock.now += 20
            controller.store.update(ffmpeg_out_time_seconds=20.0)
            raise FFmpegConnectionError(224, "broken_pipe")
        clock.now = kwargs["block_deadline"]

    monkeypatch.setattr(controller, "_run_ffmpeg", ffmpeg)
    controller._run_broadcast(youtube, broadcast)
    assert len(calls) == 3
    assert all(c[0] == (broadcast.rtmp_url, broadcast.watch_url, youtube, "original-id", "original-stream") for c in calls)
    assert {c[1]["block_deadline"] for c in calls} == {1400}
    assert len({c[1]["block_started_at"] for c in calls}) == 1
    assert [c[1]["music_offset_seconds"] for c in calls] == [0, 20, 40]
    assert controller.store.snapshot()["reconnect_count"] == 2
    assert controller.store.snapshot()["youtube_watch_url"] == broadcast.watch_url
    youtube.create.assert_not_called()
    youtube.complete.assert_not_called()
    assert youtube.broadcast_status.call_count == 2


def test_long_outage_backs_off_and_waits_for_original_limit_without_new_video(recovery, monkeypatch):
    controller, clock, youtube, broadcast = recovery
    calls = []
    def offline(*args, **kwargs):
        calls.append(kwargs["block_deadline"])
        clock.now += 1
        controller.store.update(ffmpeg_out_time_seconds=None)
        raise FFmpegConnectionError(224)
    monkeypatch.setattr(controller, "_run_ffmpeg", offline)
    controller._run_broadcast(youtube, broadcast)
    assert 60 in clock.waits
    assert clock.now == 1400
    assert len(calls) < 20 and set(calls) == {1400}
    assert controller.live_requested.is_set()
    youtube.create.assert_not_called()
    youtube.complete.assert_not_called()


def test_stop_during_retry_never_restarts_encoder(recovery, monkeypatch):
    controller, _, youtube, broadcast = recovery
    ffmpeg = Mock(side_effect=FFmpegConnectionError(224))
    monkeypatch.setattr(controller, "_run_ffmpeg", ffmpeg)
    monkeypatch.setattr(controller, "_wait_while_live", lambda _: controller.request_live_stop())
    controller._run_broadcast(youtube, broadcast)
    assert ffmpeg.call_count == 1
    youtube.broadcast_status.assert_not_called()
    assert not controller.live_requested.is_set()


@pytest.mark.parametrize("change", ["stop", "deadline"])
def test_stop_or_limit_during_google_query_prevents_another_encoder(recovery, monkeypatch, change):
    controller, clock, youtube, broadcast = recovery
    ffmpeg = Mock(side_effect=FFmpegConnectionError(224))
    monkeypatch.setattr(controller, "_run_ffmpeg", ffmpeg)
    def query(_):
        if change == "stop": controller.request_live_stop()
        else: clock.now = 1400
        return {"life_cycle_status": "live", "privacy_status": controller.settings.privacy}
    youtube.broadcast_status.side_effect = query
    controller._run_broadcast(youtube, broadcast)
    assert ffmpeg.call_count == 1


@pytest.mark.parametrize("response", [None,
    {"life_cycle_status": "complete", "privacy_status": "unlisted"},
    {"life_cycle_status": "revoked", "privacy_status": "unlisted"},
    {"life_cycle_status": "live", "privacy_status": "private"},
])
def test_closed_missing_or_changed_privacy_cannot_be_recovered(recovery, monkeypatch, response):
    controller, _, youtube, broadcast = recovery
    ffmpeg = Mock(side_effect=FFmpegConnectionError(224))
    monkeypatch.setattr(controller, "_run_ffmpeg", ffmpeg)
    youtube.broadcast_status.return_value = response
    with pytest.raises(BroadcastUnavailableError): controller._run_broadcast(youtube, broadcast)
    assert ffmpeg.call_count == 1
    youtube.create.assert_not_called()


def test_google_transport_failure_waits_without_leaking_or_creating_video(recovery, monkeypatch, caplog):
    controller, clock, youtube, broadcast = recovery
    calls = []
    def ffmpeg(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1: raise FFmpegConnectionError(224)
        clock.now = kwargs["block_deadline"]
    ffmpeg = Mock(side_effect=ffmpeg)
    monkeypatch.setattr(controller, "_run_ffmpeg", ffmpeg)
    youtube.broadcast_status.side_effect = [OSError("https://private/SECRET"),
        {"life_cycle_status": "live", "privacy_status": controller.settings.privacy}]
    controller._run_broadcast(youtube, broadcast)
    assert ffmpeg.call_count == 2 and youtube.broadcast_status.call_count == 2
    assert "SECRET" not in caplog.text
    youtube.create.assert_not_called()


def test_actual_controller_rotates_only_after_original_deadline(recovery, monkeypatch):
    controller, clock, youtube, broadcast = recovery
    monkeypatch.setattr(controller.stop_event, "wait", lambda _: False)
    monkeypatch.setattr("app.controller.YouTubeLive", lambda *args: youtube)
    youtube.create.return_value = broadcast
    attempts = []
    def encoder(*args, **kwargs):
        attempts.append(kwargs["block_deadline"])
        if len(attempts) == 1:
            clock.now += 100
            controller.store.update(ffmpeg_out_time_seconds=100)
            raise FFmpegConnectionError(224)
        clock.now = kwargs["block_deadline"]
    monkeypatch.setattr(controller, "_run_ffmpeg", encoder)
    gaps = []
    def gap():
        assert clock.now == 1400
        assert youtube.create.call_count == 1 and youtube.complete.call_count == 1
        gaps.append(clock.now)
        # End this test after proving the scheduled rotation branch is reached.
        controller.live_requested.clear()
        controller.stop_event.set()
    monkeypatch.setattr(controller, "_gap", gap)
    controller.run()
    assert attempts == [1400, 1400] and gaps == [1400]
    youtube.complete.assert_called_once_with("original-id")


def test_non_transport_failure_stops_instead_of_creating_duplicate(recovery, monkeypatch):
    controller, _, youtube, broadcast = recovery
    monkeypatch.setattr("app.controller.YouTubeLive", lambda *args: youtube)
    youtube.create.return_value = broadcast
    monkeypatch.setattr(controller, "_run_ffmpeg", Mock(side_effect=RuntimeError("filter failed")))
    # The first startup wait succeeds; the second idle iteration exits the loop.
    def wait(timeout=None):
        if not controller.live_requested.is_set(): controller.stop_event.set()
        return False
    monkeypatch.setattr(controller.stop_event, "wait", wait)
    monkeypatch.setattr(controller.live_requested, "wait", wait)
    controller.run()
    assert youtube.create.call_count == 1
    assert not controller.live_requested.is_set()
    assert controller.store.snapshot()["status"] == "error"


@pytest.mark.parametrize("code,detail,reason", [
    (224, "", "broken_pipe"), (-32, "", "broken_pipe"),
    (1, "Broken pipe rtmp://private/SECRET", "broken_pipe"),
    (1, "Connection reset by peer", "connection_reset"),
    (1, "Connection timed out", "connection_timeout"),
    (1, "Input/output error", "input_output_error"),
    (218, "Error reinitializing filters!", None),
    (224, "out of memory and Broken pipe", None),
])
def test_recovery_classifies_only_transport_failures(code, detail, reason):
    assert connection_failure_reason(code, detail) == reason


def test_music_seek_is_bounded_to_real_wav_and_output_timeout_is_not_an_input_option(recovery):
    controller, _, _, broadcast = recovery
    controller.music_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(controller.music_path), "wb") as audio:
        audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0" * 4 * 8000 * 2)
    command = controller._ffmpeg_command(broadcast.rtmp_url, music_offset_seconds=7.5)
    music = command.index(str(controller.music_path))
    assert command[music-3:music] == ["-ss", "1.500000", "-i"]
    assert command[-5:] == ["-rw_timeout", "15000000", "-f", "flv", broadcast.rtmp_url]
    assert "-rw_timeout" not in controller._ffmpeg_command("local-test.flv")
    controller.music_session = Mock()
    controller.music_session.playback.return_value = {}
    controller.store.update(ffmpeg_running=True)
    controller._parse_progress("out_time_us=3000000", datetime.now(UTC), True, music_offset_seconds=7.5)
    controller.music_session.playback.assert_called_once_with(10.5)


def test_limit_really_creates_next_video_after_gap_not_after_network_cut(recovery, monkeypatch):
    controller, clock, youtube, broadcast = recovery
    monkeypatch.setattr(controller.stop_event, "wait", lambda _: False)
    monkeypatch.setattr("app.controller.YouTubeLive", lambda *args: youtube)
    second = Broadcast("next-id", "next-stream", "rtmp://example.invalid/NEXT", "https://www.youtube.com/watch?v=ijklmnopqrs")
    youtube.create.side_effect = [broadcast, second]
    attempts = []
    def encoder(*args, **kwargs):
        attempts.append((args[3], kwargs["block_deadline"]))
        if len(attempts) == 1:
            clock.now += 100
            controller.store.update(ffmpeg_out_time_seconds=100)
            raise FFmpegConnectionError(224)
        clock.now = kwargs["block_deadline"]
    monkeypatch.setattr(controller, "_run_ffmpeg", encoder)
    gaps = []
    def gap():
        gaps.append(clock.now)
        if len(gaps) == 1:
            assert youtube.create.call_count == 1
            youtube.complete.assert_called_once_with("original-id")
            clock.now += controller.settings.gap_seconds
        else:
            controller.live_requested.clear()
            controller.stop_event.set()
    monkeypatch.setattr(controller, "_gap", gap)
    controller.run()
    assert attempts == [("original-id", 1400), ("original-id", 1400), ("next-id", 1890)]
    assert [c.args[0] for c in youtube.complete.call_args_list] == ["original-id", "next-id"]
    assert gaps == [1400, 1890]


def test_loopback_probe_rejects_external_destinations():
    from app.recovery_preflight import probe_command
    with pytest.raises(ValueError): probe_command("rtmp://external.example/live/key")
    with pytest.raises(ValueError): probe_command("rtmp://127.0.0.1:12345@external.example/live/local-test")
    command = probe_command("rtmp://127.0.0.1:12345/live/local-test")
    assert "testsrc2=size=128x72:rate=30" in command
    assert command[-5:-1] == ["-rw_timeout", "15000000", "-f", "flv"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="Requires local FFmpeg; operator runs the isolated probe in Docker")
def test_real_loopback_rtmp_cut_and_recovery():
    from app.recovery_preflight import run_probe
    result = run_probe()
    assert result["publishing"] is False and result["passed"] is True


def test_installer_hashes_preserve_configuration_and_require_isolated_probe(assert_current_or_multistream_successor):
    root = Path(__file__).parents[1]
    source = (root.parents[1] / "maintenance" / "install-live-output-recovery.sh").read_text(encoding="utf-8")
    block = re.search(r"<<'PY'\n(.*?)\nPY", source, re.S).group(1)
    tree = ast.parse(block)
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "files" for t in n.targets))
    files = ast.literal_eval(assignment.value)
    assert set(files) == {"app/controller.py", "app/youtube.py", "app/state.py", "app/recovery_preflight.py"}
    for name, (_, digest) in files.items():
        assert_current_or_multistream_successor(root, name, digest)
    assert source.index("stopped ||") < source.index("install -o martin")
    assert source.index("--network none") < source.index("up -d --no-deps --force-recreate")
    assert "--cap-drop ALL" in source and "--read-only" in source
    assert "-v " not in source and "--mount" not in source
    assert "original_runtime" in source and "cmp -s .env" in source
    assert "/start" not in source and "/stop" not in source
