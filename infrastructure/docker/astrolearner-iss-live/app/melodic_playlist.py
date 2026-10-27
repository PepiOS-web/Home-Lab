"""Compose an original piano/ambient session offline, without samples or downloads.

Python 3.12's standard-library audioop does the PCM mixing in C. Memory is
bounded by one track (maximum ten minutes), not the complete one-hour session.
This is an offline preparation command: never call it in the live encoder loop.

The existing stream mixer uses volume=4. This renderer therefore targets -29
dBFS sample RMS and limits sample peaks to 0.22 BEFORE that gain. These are
sample RMS/peak measurements, NOT a claimed LUFS or encoded true-peak value.
"""
from __future__ import annotations

import argparse
import audioop
import json
import math
import sys
import tempfile
import wave
from array import array
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

VERSION = "melodic-piano-ambient-v1"
TARGET_RMS_DBFS = -29.0
PEAK_CEILING = 0.22
RECOMMENDED_MIXER_GAIN = 4.0
MAX_SECONDS = 7200
MAX_TRACK_SECONDS = 600
MAX_SAMPLE_RATE = 48000


@dataclass(frozen=True)
class Theme:
    title: str
    root: int
    minor: bool
    bpm: int


THEMES = (
    Theme("Ventana azul", 48, False, 64),
    Theme("Primer amanecer", 50, False, 66),
    Theme("Órbita de cristal", 45, True, 62),
    Theme("Luz sobre el océano", 43, False, 68),
    Theme("Horizonte tranquilo", 53, False, 63),
    Theme("Entre las estrellas", 50, True, 60),
    Theme("Regreso a la Tierra", 48, False, 67),
    Theme("Aurora lejana", 47, True, 65),
    Theme("Mares de la noche", 46, False, 61),
    Theme("Gravedad suave", 52, True, 66),
    Theme("Un planeta, un hogar", 55, False, 64),
    Theme("Hasta el próximo amanecer", 45, True, 62),
)
SECTIONS = ((0.0, "intro"), (.10, "A"), (.34, "A variation"),
            (.52, "B"), (.72, "A return"), (.91, "outro"))
MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
# Original short motifs are a starting point; register, endings, rhythm,
# density and accompaniment develop across the track instead of copying PCM.
MOTIF_A = ((4, 2, 1), (2, 4, 5), (5, 4, 2), (1, 2, 0))
MOTIF_B = ((7, 5, 4), (6, 4, 2), (5, 3, 4), (2, 1, 0))


@dataclass(frozen=True)
class Note:
    start: float
    duration: float
    midi: int
    instrument: str
    velocity: float
    pan: float
    section: str


def _degree(root: int, scale: tuple[int, ...], degree: int) -> int:
    octave, position = divmod(degree, 7)
    return root + octave * 12 + scale[position]


def _section(fraction: float) -> str:
    return next(name for start, name in reversed(SECTIONS) if fraction >= start)


def _score(theme: Theme, duration: float, index: int = 0) -> tuple[Note, ...]:
    """Return a deterministic complete score; no rendered phrase is repeated."""
    beat = 60 / theme.bpm
    bar_seconds = 4 * beat
    scale = MINOR if theme.minor else MAJOR
    bars = math.ceil(duration / bar_seconds)
    notes = []
    for bar in range(bars):
        start = bar * bar_seconds
        section = _section(min(.99999, start / duration))
        phrase, phrase_bar = divmod(bar, 4)
        # A deliberately changes inversion/ending every phrase; B uses a
        # different harmonic order and melodic contour, not an octave duplicate.
        progression = (0, 5, 3, 4) if section != "B" else (3, 0, 4, 5)
        chord_degree = progression[(bar // 2 + index) % 4]
        root = _degree(theme.root - 12, scale, chord_degree)
        chord = tuple(_degree(theme.root, scale, chord_degree + n) for n in (0, 2, 4, 6))
        intensity = .65 if section in {"intro", "outro"} else (1.0 if section == "B" else .86)
        # A slow bass pulse and feathered chord voicing leave space for piano.
        notes.append(Note(start + .025, beat * 2.9, root, "bass", .54 * intensity, -.05, section))
        if section not in {"intro", "outro"}:
            notes.append(Note(start + 2.04 * beat, beat * 1.8, root + 7, "bass", .27, .05, section))
        inversion = (phrase + index) % 3
        for voice in range(3):
            pitch = chord[(voice + inversion) % 4]
            notes.append(Note(start + voice * .065, beat * 3.6, pitch, "piano",
                              (.30 - voice * .028) * intensity, -.32 + voice * .25, section))
        if bar % 2 == 0:
            for voice in (0, 2):
                notes.append(Note(start, min(10.0, 8 * beat), chord[voice], "pad",
                                  .20 * intensity, -.48 if voice == 0 else .48, section))
        if section == "intro" and bar % 2 == 0:
            continue
        motif = MOTIF_B if section == "B" else MOTIF_A
        contour = motif[(phrase_bar + index) % 4]
        rhythm = ((.30, 1.10), (1.67, .70), (2.66, 1.25))
        if section == "A variation":
            rhythm = ((.52, 1.45), (2.23, .65), (3.02, .72))
        for position, (offset, length) in enumerate(rhythm):
            if section == "outro" and position == 1:
                continue
            degree = contour[position]
            if section == "A return":
                degree += 7 if phrase % 2 == 0 else 0
            if position == 2 and phrase_bar == 3:
                degree = (0, 2, 4, 1)[phrase % 4]
            # Small, deterministic musical timing changes; never random noise.
            human = .012 * math.sin((bar + 1) * (position + 2) + index)
            velocity = (.64 + .055 * math.sin(bar * .71 + position)) * intensity
            notes.append(Note(start + offset * beat + human, length * beat,
                              _degree(theme.root + 12, scale, degree), "piano",
                              velocity, .12 + .08 * math.sin(bar * .33), section))
    return tuple(note for note in notes if note.start < duration)


def _pcm(values: array) -> bytes:
    if sys.byteorder != "little":
        values = array("h", values)
        values.byteswap()
    return values.tobytes()


def _samples(raw: bytes) -> array:
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


@lru_cache(maxsize=48)
def _tone(instrument: str, midi: int, sample_rate: int) -> bytes:
    """Synthesise one reusable instrument note, not a reusable music phrase."""
    seconds = {"piano": 5.0, "bass": 3.2, "pad": 10.0}[instrument]
    count = round(seconds * sample_rate)
    omega = 2 * math.pi * 440 * 2 ** ((midi - 69) / 12)
    sine, exp = math.sin, math.exp
    result = array("h")
    for frame in range(count):
        t = frame / sample_rate
        phase = omega * t
        if instrument == "piano":
            # Faster-decaying higher partials and slight inharmonicity give a
            # soft piano-like attack, without a downloaded instrument/sample.
            sound = (sine(phase) * exp(-t * .96)
                     + .30 * sine(phase * 2.001) * exp(-t * 1.9)
                     + .11 * sine(phase * 3.004) * exp(-t * 2.7)
                     + .035 * sine(phase * 4.008) * exp(-t * 4.0))
            sound *= (1 - exp(-t * 110)) * .22
        elif instrument == "bass":
            sound = (sine(phase) + .16 * sine(phase * 2))
            sound *= (1 - exp(-t * 38)) * exp(-t * 1.45) * .22
        else:
            envelope = min(1.0, t / .8, (seconds - t) / 1.8)
            sound = (sine(phase) + .35 * sine(phase * 1.0015) + .12 * sine(phase * 2))
            sound *= max(0.0, envelope) * .12
        result.append(round(sound * 32767))
    return _pcm(result)


def _note_pcm(note: Note, sample_rate: int) -> bytes:
    template = _tone(note.instrument, note.midi, sample_rate)
    frames = min(len(template) // 2, max(1, round(note.duration * sample_rate)))
    sample = template[:frames * 2]
    # Every truncated note gets a release, rather than a discontinuity/click.
    release_frames = min(frames, round(sample_rate * .10))
    release = _samples(sample[-release_frames * 2:])
    for i in range(release_frames):
        release[i] = round(release[i] * (release_frames - i - 1) / max(1, release_frames - 1))
    sample = sample[:-release_frames * 2] + _pcm(release)
    left = note.velocity * math.sqrt((1 - note.pan) / 2)
    right = note.velocity * math.sqrt((1 + note.pan) / 2)
    return audioop.tostereo(sample, 2, left, right)


def _dbfs(value: float) -> float:
    return round(20 * math.log10(max(value, 1e-12)), 3)


def _render_track(path: Path, theme: Theme, duration_frames: int, sample_rate: int,
                  index: int) -> dict:
    buffer = bytearray(duration_frames * 4)
    score = _score(theme, duration_frames / sample_rate, index)
    for note in score:
        start = max(0, round(note.start * sample_rate)) * 4
        signal = _note_pcm(note, sample_rate)
        length = min(len(signal), len(buffer) - start)
        if length > 0:
            buffer[start:start + length] = audioop.add(buffer[start:start + length], signal[:length], 2)
    rms = audioop.rms(buffer, 2) / 32768
    peak = audioop.max(buffer, 2) / 32768
    gain = min(10 ** (TARGET_RMS_DBFS / 20) / max(rms, 1e-12),
               PEAK_CEILING / max(peak, 1e-12))
    # Small PCM rounding margin guarantees the advertised <= 0.22 sample peak.
    gain *= .9995
    with path.open("wb") as raw:
        for offset in range(0, len(buffer), 262144):
            raw.write(audioop.mul(buffer[offset:offset + 262144], 2, gain))
    return {
        "sample_rms_dbfs": _dbfs(rms * gain),
        "sample_peak_dbfs": _dbfs(peak * gain),
        "piano_notes": sum(note.instrument == "piano" for note in score),
        "arrangement": [{"section": section, "start_fraction": start} for start, section in SECTIONS],
    }


def _crossfade(before: bytes, after: bytes) -> bytes:
    if len(before) != len(after) or len(before) % 4:
        raise ValueError("Crossfade inputs must have equal stereo PCM16 lengths")
    a, b = _samples(before), _samples(after)
    frames = len(a) // 2
    result = array("h")
    for frame in range(frames):
        fraction = frame / max(1, frames - 1)
        for channel in range(2):
            index = 2 * frame + channel
            result.append(round(a[index] * (1 - fraction) + b[index] * fraction))
    return _pcm(result)


def render_session(output: Path, seconds: int = 3600, tracks: int = 12,
                   sample_rate: int = 24000, *, overwrite: bool = False,
                   theme_offset: int = 0) -> dict:
    """Prepare WAV/manifest with atomic file replacements, leaving old music alone.

    The WAV is PCM16 stereo; its JSON is compatible with MusicSession.from_audio.
    One extra crossfade tail is rendered per track; all scheduled track lengths
    still sum exactly to the requested duration, including the circular seam.
    """
    if (isinstance(seconds, bool) or not isinstance(seconds, int)
            or isinstance(tracks, bool) or not isinstance(tracks, int)
            or isinstance(sample_rate, bool) or not isinstance(sample_rate, int)
            or isinstance(theme_offset, bool) or not isinstance(theme_offset, int)
            or not 0 <= theme_offset < len(THEMES)
            or not 1 <= tracks <= len(THEMES)
            or not tracks * 10 <= seconds <= MAX_SECONDS
            or seconds / tracks > MAX_TRACK_SECONDS
            or not 8000 <= sample_rate <= MAX_SAMPLE_RATE):
        raise ValueError("Use 1–12 tracks, 10–600 s per track, <=7200 s total, and 8000–48000 Hz")
    output = Path(output)
    manifest_path = output.with_suffix(".json")
    if output.suffix.lower() != ".wav":
        raise ValueError("Output must have a .wav extension")
    if not overwrite and (output.exists() or manifest_path.exists()):
        raise FileExistsError("Output or manifest already exists; choose a new filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    total_frames = seconds * sample_rate
    base, remainder = divmod(total_frames, tracks)
    lengths = [base + int(index < remainder) for index in range(tracks)]
    fade_frames = min(5 * sample_rate, min(lengths) // 5)
    fade_bytes = fade_frames * 4
    metadata = []
    cursor = 0
    with tempfile.TemporaryDirectory(prefix="melodic-offline-", dir=output.parent) as temporary:
        directory = Path(temporary)
        paths = []
        for index in range(tracks):
            theme_index = (index + theme_offset) % len(THEMES)
            theme = THEMES[theme_index]
            print(f"Componiendo {index + 1}/{tracks}: {theme.title}", flush=True)
            path = directory / f"{index:02}.pcm"
            stats = _render_track(path, theme, lengths[index] + fade_frames, sample_rate, theme_index)
            paths.append(path)
            metadata.append({"title": theme.title, "bpm": theme.bpm,
                             "start_seconds": cursor / sample_rate,
                             "duration_seconds": lengths[index] / sample_rate, **stats})
            cursor += lengths[index]
        wav_path = directory / "session.wav"
        squared_sum = 0.0
        measured_samples = 0
        measured_peak = 0

        def write(wav: wave.Wave_write, raw: bytes) -> None:
            nonlocal squared_sum, measured_samples, measured_peak
            if raw:
                samples = len(raw) // 2
                squared_sum += audioop.rms(raw, 2) ** 2 * samples
                measured_samples += samples
                measured_peak = max(measured_peak, audioop.max(raw, 2))
                wav.writeframesraw(raw)

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for index, path in enumerate(paths):
                with paths[index - 1].open("rb") as previous, path.open("rb") as current:
                    previous.seek(lengths[index - 1] * 4)
                    write(wav, _crossfade(previous.read(fade_bytes), current.read(fade_bytes)))
                    remaining = lengths[index] * 4 - fade_bytes
                    while remaining:
                        chunk = current.read(min(262144, remaining))
                        if not chunk:
                            raise RuntimeError("Incomplete composed track")
                        write(wav, chunk)
                        remaining -= len(chunk)
        with wave.open(str(wav_path), "rb") as check:
            if check.getnframes() != total_frames or check.getnchannels() != 2:
                raise RuntimeError("Incorrect rendered playlist dimensions")
        if measured_peak / 32768 > PEAK_CEILING:
            raise RuntimeError("Rendered audio exceeds the pre-mixer sample peak contract")
        manifest = {
            "version": VERSION, "duration_seconds": seconds, "sample_rate": sample_rate,
            "tracks": metadata,
            "origin": "Original procedural piano/ambient composition; no external recordings or samples",
            "loop": "Circular five-second linear crossfade (shortened for short demos)",
            "crossfade_seconds": fade_frames / sample_rate,
            "recommended_mixer_gain": RECOMMENDED_MIXER_GAIN,
            "target_sample_rms_dbfs_before_gain": TARGET_RMS_DBFS,
            "measured_sample_rms_dbfs_before_gain": _dbfs(math.sqrt(squared_sum / measured_samples) / 32768),
            "measured_sample_peak_dbfs_before_gain": _dbfs(measured_peak / 32768),
            "sample_peak_ceiling_before_gain": PEAK_CEILING,
            "loudness_note": "RMS/sample peaks, not LUFS or encoded true peak; verify the final AAC mixer separately",
            "preparation": "Offline only; no network, models, copyrighted songs or external audio samples",
        }
        temporary_manifest = directory / "session.json"
        temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Use a NEW versioned output filename for deployment. A running FFmpeg
        # input must never be replaced underneath it; switch next session only.
        wav_path.replace(output)
        temporary_manifest.replace(manifest_path)
    print(f"Sesión preparada: {seconds} s, {output}", flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/data/music/astrolearner-melodic-hour-v1.wav"))
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--tracks", type=int, default=12)
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--theme-offset", type=int, default=0, help="Start with another original theme (0–11)")
    args = parser.parse_args()
    try:
        render_session(args.output, args.seconds, args.tracks, args.sample_rate, theme_offset=args.theme_offset)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
