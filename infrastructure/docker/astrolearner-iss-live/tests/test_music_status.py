import json
import wave

import pytest

from app.music_status import MAX_MANIFEST_BYTES, MusicSession


def make_audio(tmp_path, *, seconds=4, sample_rate=8_000):
    path = tmp_path / "lofi.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\0" * (seconds * sample_rate * 4))
    return path


def valid_manifest():
    return {
        "duration_seconds": 4,
        "sample_rate": 8_000,
        "tracks": [
            {"title": "Órbita tranquila", "start_seconds": 0, "duration_seconds": 2},
            {"title": "Luz lunar", "start_seconds": 2, "duration_seconds": 2},
        ],
        "origin": "Original procedural synthesis",
        "loop": "Circular crossfade",
    }


def write_manifest(path, manifest):
    path.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def session(tmp_path):
    path = make_audio(tmp_path)
    write_manifest(path, valid_manifest())
    result = MusicSession.from_audio(path)
    assert result is not None
    return result


def test_actual_track_and_session_progress(tmp_path):
    music = session(tmp_path)
    assert music.playback(1.5) == {
        "music_track": "Órbita tranquila",
        "music_track_index": 1,
        "music_track_count": 2,
        "music_track_elapsed_seconds": 1.5,
        "music_track_duration_seconds": 2.0,
        "music_session_elapsed_seconds": 1.5,
        "music_session_duration_seconds": 4.0,
    }


@pytest.mark.parametrize("seconds,index,elapsed,session_elapsed", [
    (0, 1, 0, 0), (1.999, 1, 1.999, 1.999), (2, 2, 0, 2),
    (3.5, 2, 1.5, 3.5), (4, 1, 0, 0), (6, 2, 0, 2),
    (40.25, 1, 0.25, 0.25),
])
def test_boundaries_and_circular_loop(tmp_path, seconds, index, elapsed, session_elapsed):
    status = session(tmp_path).playback(seconds)
    assert status["music_track_index"] == index
    assert status["music_track_elapsed_seconds"] == pytest.approx(elapsed)
    assert status["music_session_elapsed_seconds"] == pytest.approx(session_elapsed)


def test_session_is_cached_not_reread_for_each_frame(tmp_path):
    path = make_audio(tmp_path)
    write_manifest(path, valid_manifest())
    music = MusicSession.from_audio(path)
    path.with_suffix(".json").unlink()
    path.unlink()
    assert music.playback(2)["music_track"] == "Luz lunar"


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf"), float("-inf"), True, "1", None])
def test_invalid_playback_times_never_publish_false_progress(tmp_path, seconds):
    with pytest.raises(ValueError):
        session(tmp_path).playback(seconds)


@pytest.mark.parametrize("contents", [
    "{", "[]", "null", "{}", "\xff", "x" * (MAX_MANIFEST_BYTES + 1),
    "[" * 5_000 + "]" * 5_000,
], ids=["broken", "array", "null", "empty-object", "non-utf8", "oversized", "deep-nesting"])
def test_invalid_or_oversized_json_is_optional(tmp_path, contents):
    path = make_audio(tmp_path)
    path.with_suffix(".json").write_bytes(contents.encode("latin-1"))
    assert MusicSession.from_audio(path) is None


@pytest.mark.parametrize("field,value", [
    ("title", ""), ("title", " " * 10), ("title", "x" * 201),
    ("title", "Track\nsecond"), ("title", "Track\x00"),
    ("title", "Track\u202ereversed"), ("title", True),
    ("start_seconds", True), ("start_seconds", -1), ("start_seconds", "0"),
    ("start_seconds", float("nan")), ("start_seconds", float("inf")),
    ("duration_seconds", True), ("duration_seconds", 0),
    ("duration_seconds", -1), ("duration_seconds", float("inf")),
])
def test_invalid_track_values_are_rejected(tmp_path, field, value):
    path = make_audio(tmp_path)
    manifest = valid_manifest()
    manifest["tracks"][0][field] = value
    write_manifest(path, manifest)
    assert MusicSession.from_audio(path) is None


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(duration_seconds=5),
    lambda data: data.update(duration_seconds=True),
    lambda data: data.update(duration_seconds=float("nan")),
    lambda data: data.update(tracks=[]),
    lambda data: data.update(tracks="not tracks"),
    lambda data: data["tracks"].__setitem__(0, None),
    lambda data: data["tracks"].reverse(),
    lambda data: data["tracks"][1].update(start_seconds=2.5),
    lambda data: data["tracks"][1].update(start_seconds=1.5),
    lambda data: data["tracks"][1].update(duration_seconds=1.5),
    lambda data: data["tracks"][1].update(duration_seconds=2.5),
])
def test_mismatched_or_noncontiguous_sessions_are_rejected(tmp_path, mutate):
    path = make_audio(tmp_path)
    manifest = valid_manifest()
    mutate(manifest)
    write_manifest(path, manifest)
    assert MusicSession.from_audio(path) is None


def test_subsample_rounding_is_tolerated_and_end_matches_wav(tmp_path):
    path = make_audio(tmp_path)
    manifest = valid_manifest()
    manifest["duration_seconds"] += 0.00005
    manifest["tracks"][0]["start_seconds"] += 0.00005
    manifest["tracks"][1]["start_seconds"] += 0.00005
    manifest["tracks"][1]["duration_seconds"] += 0.00005
    write_manifest(path, manifest)
    music = MusicSession.from_audio(path)
    assert music is not None
    assert music.duration_seconds == 4
    assert music.playback(0)["music_track_elapsed_seconds"] == 0
    assert music.playback(2)["music_track_elapsed_seconds"] == 0
    assert music.playback(2)["music_track_duration_seconds"] == 2
    assert music.playback(4)["music_track_index"] == 1


def test_single_track_manifest_can_loop(tmp_path):
    path = make_audio(tmp_path)
    write_manifest(path, {"duration_seconds": 4, "tracks": [
        {"title": "Single track", "start_seconds": 0, "duration_seconds": 4},
    ]})
    music = MusicSession.from_audio(path)
    assert music is not None
    assert music.playback(5)["music_track_count"] == 1
    assert music.playback(5)["music_track_elapsed_seconds"] == 1


def test_missing_audio_or_manifest_does_not_break_live(tmp_path):
    path = make_audio(tmp_path)
    assert MusicSession.from_audio(path) is None
    write_manifest(path, valid_manifest())
    path.unlink()
    assert MusicSession.from_audio(path) is None


@pytest.mark.parametrize("contents", [b"", b"not audio"])
def test_invalid_wav_is_optional(tmp_path, contents):
    path = tmp_path / "lofi.wav"
    path.write_bytes(contents)
    write_manifest(path, valid_manifest())
    assert MusicSession.from_audio(path) is None


def test_empty_wav_is_optional(tmp_path):
    path = make_audio(tmp_path, seconds=0)
    write_manifest(path, valid_manifest())
    assert MusicSession.from_audio(path) is None
