from __future__ import annotations

import io
import queue
import subprocess
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from app import video_switcher
from app.video_switcher import MAX_INPUT_PIXELS, VideoSwitcher, iter_jpegs

CAMERA = b"\xff\xd8camera\xff\xd9"
RECORDED = b"\xff\xd8recorded\xff\xd9"
MAP = b"\xff\xd8map\xff\xd9"


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def settings(tmp_path, **overrides):
    values = {
        "camera_url": "https://camera.example/live.m3u8?secret=private",
        "camera_authorized": True,
        "camera_timeout_seconds": 8,
        "camera_stable_seconds": 15,
        "camera_retry_seconds": 30,
        "camera_mode": "auto",
        "width": 320,
        "height": 180,
        "fps": 12,
        "nasa_loop_video": tmp_path / "backup.mp4",
        "use_nasa_playlist": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def switcher(tmp_path, **overrides):
    reports = []
    result = VideoSwitcher(settings(tmp_path, **overrides), reports.append, lambda: MAP)
    clock = Clock()
    result._clock = clock
    return result, clock, reports


def receive(result, source, payload):
    result._running[source] = True
    result._accept_frame(source, payload)


def make_camera_stable(result, clock):
    receive(result, "camera", CAMERA)
    for moment in (105, 110, 115):
        clock.now = moment
        receive(result, "camera", CAMERA)


@pytest.mark.parametrize(
    "parts",
    [
        [CAMERA],
        [CAMERA[:1], CAMERA[1:4], CAMERA[4:-1], CAMERA[-1:]],
        [b"junk", CAMERA, b"noise", RECORDED],
    ],
)
def test_parser_accepts_partial_reads_and_multiple_images(parts):
    class Stream:
        def read(self, _size):
            return parts.pop(0) if parts else b""

    expected = [CAMERA, RECORDED] if b"noise" in parts else [CAMERA]
    assert list(iter_jpegs(Stream())) == expected


def test_parser_discards_oversized_and_recovers_at_next_image():
    source = b"\xff\xd8" + b"x" * 70 + b"\xff\xd9" + CAMERA
    assert list(iter_jpegs(io.BytesIO(source), max_frame_bytes=32)) == [CAMERA]


def test_parser_discards_incomplete_image_and_resynchronises():
    assert list(iter_jpegs(io.BytesIO(b"noise\xff\xd8broken" + CAMERA))) == [CAMERA]
    assert list(iter_jpegs(io.BytesIO(b"\xff\xd8truncated"))) == []


def test_parser_discards_unbounded_junk_without_large_reads():
    class Junk:
        remaining = 10_000

        def read(self, size):
            assert size <= 32
            self.remaining -= size
            return b"x" * size if self.remaining > 0 else b""

    assert list(iter_jpegs(Junk(), max_frame_bytes=32)) == []


def test_parser_requires_a_realistic_limit():
    with pytest.raises(ValueError):
        list(iter_jpegs(io.BytesIO(CAMERA), max_frame_bytes=3))


@pytest.mark.parametrize("source", ["camera", "recorded"])
def test_both_decoders_normalize_pixel_format_across_switches(tmp_path, source):
    result, _, _ = switcher(tmp_path)
    command = result._command(source)
    assert command[command.index("-pix_fmt") + 1] == "yuvj420p"


def test_initial_fallback_is_map_and_no_url_is_exposed(tmp_path):
    result, _, reports = switcher(tmp_path)
    assert result.frame() == MAP
    assert reports[-1]["video_mode"] == "map"
    assert reports[-1]["camera_state"] == "connecting"
    assert "camera.example" not in str(reports)
    assert "private" not in str(reports)


def test_recorded_backup_is_used_while_camera_connects(tmp_path):
    result, _, reports = switcher(tmp_path)
    receive(result, "recorded", RECORDED)
    assert result.frame() == RECORDED
    assert reports[-1]["video_mode"] == "recorded"
    assert reports[-1]["video_fallback_reason"] == "camera_connecting"


def test_camera_requires_continuous_stability_before_return(tmp_path):
    result, clock, reports = switcher(tmp_path)
    receive(result, "recorded", RECORDED)
    receive(result, "camera", CAMERA)
    assert result.frame() == RECORDED
    assert reports[-1]["camera_state"] == "recovering"
    for moment in (105, 110, 114):
        clock.now = moment
        receive(result, "recorded", RECORDED)
        receive(result, "camera", CAMERA)
        assert result.frame() == RECORDED
    clock.now = 115
    receive(result, "camera", CAMERA)
    assert result.frame() == CAMERA
    assert reports[-1]["camera_state"] == "live"
    assert reports[-1]["video_fallback_reason"] == ""
    assert reports[-1]["video_switch_count"] == 2


def test_camera_stale_switches_to_recorded_and_retains_last_receipt(tmp_path):
    result, clock, reports = switcher(tmp_path)
    make_camera_stable(result, clock)
    assert result.frame() == CAMERA
    last_receipt = reports[-1]["camera_last_frame_at"]
    clock.now = 124
    receive(result, "recorded", RECORDED)
    assert result.frame() == RECORDED
    assert reports[-1]["camera_available"] is False
    assert reports[-1]["camera_state"] == "stale"
    assert reports[-1]["camera_last_frame_at"] == last_receipt


def test_stability_restarts_after_gap_even_if_frame_was_not_polled(tmp_path):
    result, clock, reports = switcher(tmp_path)
    receive(result, "camera", CAMERA)
    clock.now = 107
    receive(result, "camera", CAMERA)
    clock.now = 116
    receive(result, "camera", CAMERA)
    clock.now = 123
    receive(result, "camera", CAMERA)
    assert result.frame() == MAP
    assert reports[-1]["camera_state"] == "recovering"
    clock.now = 130
    receive(result, "camera", CAMERA)
    assert result.frame() == MAP
    clock.now = 131
    receive(result, "camera", CAMERA)
    assert result.frame() == CAMERA


def test_identical_or_black_frames_are_not_treated_as_a_cut(tmp_path):
    result, clock, reports = switcher(tmp_path)
    image = Image.new("RGB", (320, 180), "black")
    encoded = io.BytesIO()
    image.save(encoded, "JPEG")
    payload = encoded.getvalue()
    for moment in (100, 105, 110, 115):
        clock.now = moment
        receive(result, "camera", payload)
    assert result.frame() == payload
    assert reports[-1]["camera_state"] == "live"


def test_stale_recorded_falls_back_to_map(tmp_path):
    result, clock, reports = switcher(tmp_path)
    receive(result, "recorded", RECORDED)
    assert result.frame() == RECORDED
    clock.now += 9
    assert result.frame() == MAP
    assert reports[-1]["video_mode"] == "map"


@pytest.mark.parametrize("provider", [lambda: None, lambda: b"invalid"])
def test_missing_map_returns_cached_valid_emergency_jpeg(tmp_path, provider):
    result = VideoSwitcher(settings(tmp_path), lambda _: None, provider)
    payload = result.frame()
    assert payload == result.frame()
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (320, 180)
        assert image.format == "JPEG"


def test_map_callback_error_is_not_a_publishing_error(tmp_path):
    def broken_map():
        raise OSError("missing map")

    reports = []
    result = VideoSwitcher(settings(tmp_path), reports.append, broken_map)
    assert result.frame().startswith(b"\xff\xd8")
    assert reports[-1]["video_fallback_reason"] == "map_unavailable"


def test_status_sink_failure_cannot_break_video(tmp_path):
    def broken_sink(_status):
        raise OSError("unavailable disk")

    result = VideoSwitcher(settings(tmp_path), broken_sink, lambda: MAP)
    assert result.frame() == MAP


def test_timestamp_reports_are_throttled_but_mode_changes_are_immediate(
    tmp_path, monkeypatch
):
    result, clock, reports = switcher(tmp_path)
    sequence = iter([f"time-{value}" for value in range(100)])
    monkeypatch.setattr(video_switcher, "_utc_now", lambda: next(sequence))
    receive(result, "camera", CAMERA)
    result.frame()
    assert len(reports) == 1
    for moment in (100.1, 100.2, 100.8):
        clock.now = moment
        receive(result, "camera", CAMERA)
        result.frame()
    assert len(reports) == 1
    clock.now = 101
    receive(result, "camera", CAMERA)
    result.frame()
    assert len(reports) == 2
    receive(result, "recorded", RECORDED)
    result.frame()
    assert len(reports) == 3
    assert reports[-1]["video_mode"] == "recorded"


@pytest.mark.parametrize("mode, expected", [("fallback", RECORDED), ("map", MAP)])
def test_forced_modes_never_select_camera(tmp_path, mode, expected):
    result, clock, reports = switcher(tmp_path, camera_mode=mode)
    make_camera_stable(result, clock)
    receive(result, "recorded", RECORDED)
    assert result.frame() == expected
    assert reports[-1]["camera_state"] == "disabled"
    assert not reports[-1]["camera_available"]


def test_camera_needs_explicit_authorisation(tmp_path):
    result, clock, reports = switcher(tmp_path, camera_authorized=False)
    make_camera_stable(result, clock)
    assert result.frame() == MAP
    assert reports[-1]["camera_state"] == "disabled"
    assert not reports[-1]["camera_configured"]


def test_unconfigured_camera_is_distinct_from_disabled(tmp_path):
    result, _, reports = switcher(tmp_path, camera_url="", camera_authorized=False)
    assert result.frame() == MAP
    assert reports[-1]["camera_state"] == "unconfigured"
    assert not reports[-1]["camera_configured"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "concat:http://camera/a|file:/etc/passwd",
        "rtsp://camera/live",
        "https://user:password@camera/live",
        "https://camera/live#fragment",
        "http://",
        "https://camera/live\nsecret",
    ],
)
def test_rejects_unsafe_urls_without_echoing_them(tmp_path, url):
    with pytest.raises(ValueError, match="direct HTTP") as captured:
        VideoSwitcher(settings(tmp_path, camera_url=url), lambda _: None, lambda: MAP)
    assert url not in str(captured.value)


@pytest.mark.parametrize(
    "option,value",
    [
        ("camera_timeout_seconds", 0),
        ("camera_stable_seconds", -1),
        ("camera_retry_seconds", 0),
        ("camera_timeout_seconds", float("nan")),
    ],
)
def test_timing_is_bounded(tmp_path, option, value):
    with pytest.raises(ValueError, match="timing"):
        switcher(tmp_path, **{option: value})


def test_decoder_commands_are_bounded_and_network_cannot_open_local_files(tmp_path):
    result, _, _ = switcher(tmp_path)
    camera = result._command("camera")
    whitelist = camera[camera.index("-protocol_whitelist") + 1].split(",")
    assert "file" not in whitelist
    assert "pipe" not in whitelist
    assert camera[camera.index("-rw_timeout") + 1] == "8000000"
    assert camera[camera.index("-max_pixels") + 1] == str(MAX_INPUT_PIXELS)
    assert camera[camera.index("-filter_threads") + 1] == "1"
    assert camera[-2:] == ["mjpeg", "pipe:1"]
    local = result._command("recorded")
    assert local[local.index("-protocol_whitelist") + 1] == "file"
    assert local[local.index("-stream_loop") + 1] == "-1"
    assert "-re" in local
    assert "-an" in camera and "-an" in local
    assert "320:180" in camera[camera.index("-vf") + 1]


class Process:
    def __init__(self, stream=None):
        self.stdout = stream or io.BytesIO()
        self.returncode = None
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = -15

    def kill(self):
        self.killed += 1
        self.returncode = -9

    def wait(self, timeout):
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


def test_watchdog_stops_frozen_reader_without_blocking_frame(tmp_path):
    result, clock, reports = switcher(tmp_path)
    process = Process()
    result._processes["camera"] = process
    result._reader_started["camera"] = clock.now
    result._running["camera"] = True
    clock.now += 9
    assert result.frame() == MAP
    assert process.terminated == 1
    assert reports[-1]["camera_state"] == "error"


def test_restarted_reader_gets_a_full_connection_timeout(tmp_path):
    result, clock, _ = switcher(tmp_path)
    receive(result, "camera", CAMERA)
    clock.now += 100
    process = Process()
    result._processes["camera"] = process
    result._reader_started["camera"] = clock.now
    result._camera_stable_since = None
    assert result.frame() == MAP
    assert process.terminated == 0
    clock.now += 9
    result.frame()
    assert process.terminated == 1


def test_watchdog_escalates_after_grace_without_waiting_or_killing_replacement(
    tmp_path,
):
    result, clock, _ = switcher(tmp_path)
    process = Process()
    process.wait = lambda _timeout: pytest.fail("frame must never wait for a process")

    def ignore_termination():
        process.terminated += 1

    process.terminate = ignore_termination
    result._processes["camera"] = process
    result._reader_started["camera"] = clock.now
    result._running["camera"] = True
    clock.now = 109
    assert result.frame() == MAP
    assert process.terminated == 1
    assert process.killed == 0
    clock.now = 113.99
    assert result.frame() == MAP
    assert process.killed == 0
    clock.now = 114
    assert result.frame() == MAP
    assert process.killed == 1
    replacement = Process()
    result._processes["camera"] = replacement
    result._reader_started["camera"] = clock.now
    result._running["camera"] = True
    clock.now = 115
    result.frame()
    assert replacement.terminated == 0
    assert replacement.killed == 0


def test_camera_reader_recovers_after_watchdog_kills_hung_process(
    tmp_path, monkeypatch
):
    result, clock, reports = switcher(tmp_path)
    created = [threading.Event(), threading.Event()]
    retry_waiting = threading.Event()
    release_retry = threading.Event()
    replacement_received = threading.Event()

    class RetryGate:
        stopped = threading.Event()

        def is_set(self):
            return self.stopped.is_set()

        def set(self):
            self.stopped.set()
            release_retry.set()

        def wait(self, delay):
            assert delay == 30
            retry_waiting.set()
            release_retry.wait(2)
            return self.is_set()

    class Stream:
        def __init__(self, replacement=False):
            self.chunks = queue.Queue()
            self.closed = False
            self.replacement = replacement
            self.reads = 0

        def read(self, _size):
            self.reads += 1
            if self.replacement and self.reads == 2:
                replacement_received.set()
            return self.chunks.get(timeout=2)

        def close(self):
            self.closed = True

    hung_stream = Stream()
    recovered_stream = Stream(replacement=True)
    recovered_stream.chunks.put(CAMERA)
    hung = Process(hung_stream)
    recovered = Process(recovered_stream)

    def ignore_termination():
        hung.terminated += 1

    def kill_hung():
        hung.killed += 1
        hung.returncode = -9
        hung_stream.chunks.put(b"")

    def stop_recovered():
        recovered.terminated += 1
        recovered.returncode = -15
        recovered_stream.chunks.put(b"")

    hung.terminate = ignore_termination
    hung.kill = kill_hung
    recovered.terminate = stop_recovered
    processes = [hung, recovered]
    calls = []

    def popen(*_args, **_kwargs):
        index = len(calls)
        calls.append(index)
        created[index].set()
        return processes[index]

    result._stop = RetryGate()
    monkeypatch.setattr(video_switcher.subprocess, "Popen", popen)
    try:
        result.start()
        assert created[0].wait(1)
        clock.now = 109
        assert result.frame() == MAP
        assert hung.terminated == 1
        clock.now = 114
        assert result.frame() == MAP
        assert hung.killed == 1
        assert retry_waiting.wait(1)
        clock.now = 144
        release_retry.set()
        assert created[1].wait(1)
        assert replacement_received.wait(1)
        assert result.frame() == MAP
        assert reports[-1]["camera_state"] == "recovering"
        for moment in (149, 154, 159):
            clock.now = moment
            result._accept_frame("camera", CAMERA)
        assert result.frame() == CAMERA
        assert reports[-1]["camera_state"] == "live"
    finally:
        result.stop()
    assert calls == [0, 1]
    assert all(not worker.is_alive() for worker in result._threads)


def test_failed_static_status_retries_once_per_second_and_commits_only_on_success(
    tmp_path,
):
    clock = Clock()
    attempts = []

    def sink(status):
        attempts.append((clock.now, status))
        if len(attempts) == 1:
            raise OSError("temporary disk failure")

    result = VideoSwitcher(settings(tmp_path, camera_url=""), sink, lambda: MAP)
    result._clock = clock
    result.frame()
    assert len(attempts) == 1
    assert result._last_emitted is None
    assert result._status_emit_failed
    for moment in (100.01, 100.1, 100.8, 100.99):
        clock.now = moment
        result.frame()
    assert len(attempts) == 1
    clock.now = 101
    result.frame()
    assert len(attempts) == 2
    assert attempts[0][1] == attempts[1][1]
    assert result._last_emitted == attempts[1][1]
    assert not result._status_emit_failed
    clock.now = 102
    result.frame()
    assert len(attempts) == 2  # A successfully persisted static state needs no retry.


def test_permanent_status_failure_does_not_retry_at_video_fps(tmp_path):
    result, clock, _ = switcher(tmp_path)
    attempts = []

    def sink(_status):
        attempts.append(clock.now)
        raise OSError("disk still unavailable")

    result._on_status = sink
    for index in range(25):
        clock.now = 100 + index / 12
        result.frame()
    assert attempts == [100, 101, 102]
    assert result._last_emitted is None


def test_failed_new_mode_keeps_previous_successful_status_until_retry(tmp_path):
    result, clock, _ = switcher(tmp_path)
    result.frame()
    previous = result._last_emitted.copy()
    attempts = []

    def sink(status):
        attempts.append(status.copy())
        if len(attempts) == 1:
            raise OSError("transient failure")

    result._on_status = sink
    receive(result, "recorded", RECORDED)
    result.frame()
    assert result._last_emitted == previous
    assert result._last_emitted["video_mode"] == "map"
    clock.now += 1
    result.frame()
    assert result._last_emitted["video_mode"] == "recorded"
    assert len(attempts) == 2


def test_failed_reader_waits_before_retry_and_never_exports_exception(
    tmp_path, monkeypatch
):
    result, _, reports = switcher(tmp_path)
    calls = []

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        raise OSError("https://camera.example/?secret=veryprivate")

    class StopAfterRetry:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, delay):
            assert delay == 30
            self.stopped = True

    result._stop = StopAfterRetry()
    monkeypatch.setattr(video_switcher.subprocess, "Popen", fail)
    result._reader("camera")
    assert len(calls) == 1
    assert calls[0][1]["stderr"] == subprocess.DEVNULL
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    result.frame()
    assert reports[-1]["camera_state"] == "error"
    assert "veryprivate" not in str(reports)


def test_start_stop_are_idempotent_and_stop_closes_reader(tmp_path, monkeypatch):
    result, _, _ = switcher(tmp_path)
    finished = threading.Event()
    created = threading.Event()

    class BlockingStream:
        closed = False

        def read(self, _size):
            finished.wait(2)
            return b""

        def close(self):
            self.closed = True

    stream = BlockingStream()
    process = Process(stream)
    original_terminate = process.terminate

    def terminate():
        original_terminate()
        finished.set()

    process.terminate = terminate
    calls = []

    def popen(*args, **kwargs):
        calls.append(args)
        created.set()
        return process

    monkeypatch.setattr(video_switcher.subprocess, "Popen", popen)
    result.start()
    assert created.wait(1)
    result.start()
    result.stop()
    result.stop()
    result.start()
    assert len(calls) == 1
    assert stream.closed
    assert all(not worker.is_alive() for worker in result._threads)


def test_no_source_process_for_unauthorised_camera_or_missing_backup(
    tmp_path, monkeypatch
):
    result, _, _ = switcher(tmp_path, camera_authorized=False)
    monkeypatch.setattr(
        video_switcher.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("must not launch"),
    )
    result.start()
    result.stop()
    assert result._threads == []


def test_stopping_prevents_late_frames_from_becoming_available(tmp_path):
    result, _, _ = switcher(tmp_path)
    result.stop()
    receive(result, "camera", CAMERA)
    assert result._frames["camera"] is None


def test_dispose_kills_a_decoder_that_ignores_termination():
    process = Process()
    calls = []

    def wait(timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return -9

    process.wait = wait
    VideoSwitcher._dispose(process)
    assert process.terminated == 1
    assert process.killed == 1
    assert calls == [5, 5]
    assert process.stdout.closed


def test_switching_to_map_terminates_both_optional_decoders(tmp_path):
    result, clock, reports = switcher(tmp_path)
    make_camera_stable(result, clock)
    camera = Process()
    recorded = Process()
    result._processes = {"camera": camera, "recorded": recorded}
    result.set_mode("map")
    assert camera.terminated == 1
    assert recorded.terminated == 1
    assert result.frame() == MAP
    assert reports[-1]["video_fallback_reason"] == "map_requested"


def test_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        switcher(tmp_path, camera_mode="untrusted")
    result, _, _ = switcher(tmp_path)
    with pytest.raises(ValueError, match="mode"):
        result.set_mode("untrusted")
