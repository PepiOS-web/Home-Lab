"""Render an original, offline lo-fi session; no downloads or external samples."""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import wave
from array import array
from pathlib import Path

THEMES = (
    ("Órbita tranquila", 72, ((45, "m"), (41, "M"), (48, "M"), (43, "d"))),
    ("Luz lunar", 68, ((50, "m"), (46, "M"), (41, "M"), (48, "d"))),
    ("Aurora", 76, ((48, "M"), (45, "m"), (41, "M"), (43, "d"))),
    ("Mar de la Tranquilidad", 66, ((52, "m"), (48, "M"), (43, "M"), (50, "d"))),
    ("Ventana a la Tierra", 74, ((43, "M"), (40, "m"), (48, "M"), (50, "d"))),
    ("Anillos de Saturno", 70, ((47, "m"), (43, "M"), (50, "M"), (45, "d"))),
    ("Polvo de estrellas", 78, ((41, "M"), (38, "m"), (46, "M"), (48, "d"))),
    ("Noche orbital", 67, ((42, "m"), (38, "M"), (45, "M"), (40, "d"))),
    ("Azul profundo", 73, ((46, "M"), (43, "m"), (39, "M"), (41, "d"))),
    ("Horizonte marciano", 80, ((48, "m"), (44, "M"), (39, "M"), (46, "d"))),
    ("Viaje a casa", 71, ((50, "M"), (47, "m"), (43, "M"), (45, "d"))),
    ("Amanecer en la ISS", 69, ((45, "m"), (48, "M"), (41, "M"), (43, "d"))),
)
VOICINGS = {"m": (12, 15, 19, 22, 26), "M": (12, 16, 19, 23, 26), "d": (12, 16, 19, 22, 26)}


def _pcm(samples: array) -> bytes:
    if sys.byteorder != "little":
        samples = array("h", samples)
        samples.byteswap()
    return samples.tobytes()


def _samples(raw: bytes) -> array:
    result = array("h")
    result.frombytes(raw)
    if sys.byteorder != "little":
        result.byteswap()
    return result


def _loop(theme: tuple, index: int, sample_rate: int) -> bytes:
    _, bpm, progression = theme
    beat = 60 / bpm
    length = round(32 * beat * sample_rate)
    omega = 2 * math.pi
    frequencies = [
        (440 * 2 ** ((root - 69) / 12),
         [440 * 2 ** ((root + interval - 69) / 12) for interval in VOICINGS[quality]])
        for root, quality in progression
    ]
    values = []
    squared = 0.0
    for frame in range(length):
        t = frame / sample_rate
        bar = int(t / (4 * beat))
        bass, chord = frequencies[(bar // 2) % 4]
        strike = t % (2 * beat)
        envelope = (1 - math.exp(-strike * 65)) * math.exp(-strike * 1.5)
        piano = sum(math.sin(omega * f * t) + .18 * math.sin(omega * f * 2 * t)
                    for f in chord) * envelope * .027
        bass_time = t % beat
        low = math.sin(omega * bass * t) * (1 - math.exp(-bass_time * 45)) * math.exp(-bass_time * 2) * .05
        # Swing the offbeats slightly; all melody notes come from the current chord.
        swung = (t + beat * .09) % beat
        note = chord[(int(t / beat) + bar + index) % len(chord)] * 2
        melody = 0.0
        if bar % 4 != 3 and int(t / beat) % 2 == index % 2:
            melody = math.sin(omega * note * t) * (1 - math.exp(-swung * 85)) * math.exp(-swung * 7) * .022
        position = t % beat
        beat_index = int(t / beat) % 4
        drums = 0.0
        if beat_index in (0, 2):
            drums = math.sin(omega * (54 * position - 28 * position * position)) * math.exp(-position * 22) * .065
        else:
            drums = (math.sin(omega * 185 * position) + .25 * math.sin(omega * 370 * position)) * math.exp(-position * 40) * .018
        seam = min(1.0, frame / (sample_rate * .008), (length - frame - 1) / (sample_rate * .008))
        pad = sum(math.sin(omega * f * t) for f in chord[:3]) * .005
        left = (piano + low + drums + pad + melody * .75) * seam
        right = (piano + low + drums + pad + melody) * seam
        values.extend((left, right))
        squared += left * left + right * right
    rms = math.sqrt(squared / (length * 2))
    # The current live mixer adds +12 dB (volume=4), yielding about -17 dBFS.
    gain = 10 ** (-29 / 20) / max(rms, 1e-9)
    return _pcm(array("h", (round(max(-.95, min(.95, value * gain)) * 32767) for value in values)))


def _crossfade(before: bytes, after: bytes) -> bytes:
    left, right = _samples(before), _samples(after)
    frames = len(left) // 2
    mixed = array("h")
    for frame in range(frames):
        progress = frame / max(1, frames - 1)
        for channel in range(2):
            pos = 2 * frame + channel
            mixed.append(round(left[pos] * (1 - progress) + right[pos] * progress))
    return _pcm(mixed)


def render_session(output: Path, seconds: int = 3600, tracks: int = 12, sample_rate: int = 24000) -> None:
    if tracks < 2 or tracks > len(THEMES) or seconds < tracks * 10 or sample_rate < 8000:
        raise ValueError("Use 2–12 tracks, at least 10 seconds per track and at least 8000 Hz")
    output.parent.mkdir(parents=True, exist_ok=True)
    total_frames = seconds * sample_rate
    fade_frames = min(5 * sample_rate, total_frames // (tracks * 4))
    fade_bytes = fade_frames * 4
    # Circular crossfade adds one overlap per theme, including last -> first.
    source_frames = total_frames + tracks * fade_frames
    base, remainder = divmod(source_frames, tracks)
    with tempfile.TemporaryDirectory(prefix="lofi-", dir=output.parent) as temporary:
        raw_path = Path(temporary) / "session.pcm"
        previous_tail = None
        first_head = None
        metadata = []
        cursor = 0
        with raw_path.open("wb") as raw:
            for index, theme in enumerate(THEMES[:tracks]):
                print(f"Tema {index + 1}/{tracks}: {theme[0]}", flush=True)
                loop = _loop(theme, index, sample_rate)
                frames = base + (index < remainder)
                size = frames * 4
                track = (loop * ((size + len(loop) - 1) // len(loop)))[:size]
                if first_head is None:
                    first_head = track[:fade_bytes]
                    raw.write(first_head)
                else:
                    raw.write(_crossfade(previous_tail, track[:fade_bytes]))
                raw.write(track[fade_bytes:-fade_bytes])
                previous_tail = track[-fade_bytes:]
                duration_frames = frames - fade_frames
                metadata.append({"title": theme[0], "bpm": theme[1], "start_seconds": cursor / sample_rate,
                                 "duration_seconds": duration_frames / sample_rate})
                cursor += duration_frames
            raw.write(previous_tail)
        temporary_wav = Path(temporary) / "session.wav"
        with raw_path.open("rb") as raw, wave.open(str(temporary_wav), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframesraw(_crossfade(previous_tail, first_head))
            raw.seek(fade_bytes)
            remaining = total_frames * 4 - fade_bytes
            while remaining:
                chunk = raw.read(min(262144, remaining))
                if not chunk:
                    raise RuntimeError("Incomplete session PCM")
                wav.writeframesraw(chunk)
                remaining -= len(chunk)
        with wave.open(str(temporary_wav), "rb") as check:
            if check.getnframes() != total_frames:
                raise RuntimeError("Incorrect playlist duration")
        temporary_wav.replace(output)
    output.with_suffix(".json").write_text(json.dumps({"duration_seconds": seconds,
        "sample_rate": sample_rate, "tracks": metadata,
        "origin": "Original procedural synthesis; no external recordings or samples",
        "loop": "Circular crossfade"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sesión lista: {seconds} s, {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/data/music/astrolearner-lofi-hour-v1.wav"))
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--tracks", type=int, default=12)
    parser.add_argument("--sample-rate", type=int, default=24000)
    args = parser.parse_args()
    render_session(args.output, args.seconds, args.tracks, args.sample_rate)
