import hashlib
import inspect
import json
import math
import wave
from array import array

import pytest

from app import melodic_playlist as music
from app.music_status import MusicSession


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    path = tmp_path_factory.mktemp("melodic") / "session.wav"
    manifest = music.render_session(path, seconds=21, tracks=2, sample_rate=8000)
    return path, manifest


def read_samples(path):
    with wave.open(str(path), "rb") as audio:
        raw = audio.readframes(audio.getnframes())
    return music._samples(raw)


def test_default_is_one_hour_twelve_tracks_without_rendering():
    parameters = inspect.signature(music.render_session).parameters
    assert parameters["seconds"].default == 3600
    assert parameters["tracks"].default == 12
    assert len(music.THEMES) == 12
    assert len({theme.title for theme in music.THEMES}) == 12


def test_exact_pcm16_stereo_duration_and_manifest(rendered):
    path, manifest = rendered
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 2
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 8000
        assert audio.getnframes() == 168000
        assert audio.getcomptype() == "NONE"
    assert json.loads(path.with_suffix(".json").read_text(encoding="utf-8")) == manifest
    assert sum(track["duration_seconds"] for track in manifest["tracks"]) == 21
    assert manifest["tracks"][1]["start_seconds"] == 10.5
    session = MusicSession.from_audio(path)
    assert session is not None
    assert session.playback(10.5)["music_track"] == music.THEMES[1].title
    assert session.playback(21)["music_track_index"] == 1


def test_gain_contract_sample_peaks_and_non_silence(rendered):
    path, manifest = rendered
    samples = read_samples(path)
    peak = max(abs(value) for value in samples) / 32768
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
    assert 0.008 < rms < .05
    assert peak <= music.PEAK_CEILING
    assert peak * music.RECOMMENDED_MIXER_GAIN < .89
    assert manifest["recommended_mixer_gain"] == 4
    assert "not LUFS" in manifest["loudness_note"]
    assert manifest["measured_sample_peak_dbfs_before_gain"] <= 20 * math.log10(.22) + .001


def test_arrangement_has_distinct_sections_and_development():
    score = music._score(music.THEMES[0], 300)
    assert {note.section for note in score} == {name for _, name in music.SECTIONS}
    a = {note.midi for note in score if note.section == "A" and note.instrument == "piano"}
    b = {note.midi for note in score if note.section == "B" and note.instrument == "piano"}
    assert a != b
    # The algorithm constructs the whole score; later bars do not reuse an
    # identical 24-second PCM loop or an unchanging accompaniment inversion.
    opening = [note.midi for note in score if 33 <= note.start < 57 and note.instrument == "piano"]
    later = [note.midi for note in score if 129 <= note.start < 153 and note.instrument == "piano"]
    assert opening != later
    assert all(note.instrument in {"piano", "bass", "pad"} for note in score)
    assert music._score(music.THEMES[0], 300) == score


def test_deterministic_render_and_no_simple_periodic_pcm(rendered, tmp_path):
    path, _ = rendered
    second = tmp_path / "repeat.wav"
    music.render_session(second, seconds=21, tracks=2, sample_rate=8000)
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    samples = read_samples(path)
    assert samples[8000 * 4:8000 * 6] != samples[8000 * 8:8000 * 10]


def test_linear_crossfade_and_circular_seam(rendered):
    a = music._pcm(array("h", [1000, -1000] * 4))
    b = music._pcm(array("h", [-1000, 1000] * 4))
    crossfade = music._samples(music._crossfade(a, b))
    assert crossfade[:2] == array("h", [1000, -1000])
    assert crossfade[-2:] == array("h", [-1000, 1000])
    assert all(abs(value) <= 1000 for value in crossfade)
    path, _ = rendered
    samples = read_samples(path)
    # The last tail continues into the first circular crossfade; it is not a
    # restart to silence or a hard cut from one unrelated sample to another.
    assert abs(samples[-2] - samples[0]) < 3000
    assert abs(samples[-1] - samples[1]) < 3000


def test_new_filename_required_preserves_existing_audio(rendered):
    path, _ = rendered
    before = hashlib.sha256(path.read_bytes()).digest()
    with pytest.raises(FileExistsError):
        music.render_session(path, seconds=21, tracks=2, sample_rate=8000)
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.parametrize("settings", [
    {"seconds": 0}, {"seconds": True}, {"seconds": 9}, {"seconds": 601, "tracks": 1},
    {"seconds": 7201, "tracks": 12}, {"tracks": 0}, {"tracks": 13}, {"tracks": True},
    {"sample_rate": 7999}, {"sample_rate": 48001}, {"sample_rate": True},
    {"theme_offset": -1}, {"theme_offset": 12}, {"theme_offset": True},
])
def test_bounded_inputs_rejected_without_creating_output(tmp_path, settings):
    defaults = {"seconds": 20, "tracks": 1, "sample_rate": 8000}
    defaults.update(settings)
    path = tmp_path / "invalid.wav"
    with pytest.raises(ValueError):
        music.render_session(path, **defaults)
    assert not path.exists()


def test_crossfade_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        music._crossfade(b"\0" * 4, b"\0" * 8)
    with pytest.raises(ValueError):
        music._crossfade(b"\0" * 2, b"\0" * 2)
