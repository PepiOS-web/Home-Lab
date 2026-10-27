"""Read the existing lo-fi manifest once and locate tracks on the output timeline."""
from __future__ import annotations

import json
import math
import unicodedata
import wave
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_MANIFEST_BYTES = 64 * 1024
MAX_TRACKS = 256
MAX_TITLE_CHARACTERS = 200


def _number(value: Any, *, positive: bool = False) -> float:
    # bool is a subclass of int, but is never a valid duration or start time.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid music time")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError("Invalid music time")
    return number


def _title(value: Any) -> str:
    if not isinstance(value, str) or len(value) > MAX_TITLE_CHARACTERS:
        raise ValueError("Invalid music title")
    # Includes line breaks, surrogate code points and invisible bidi controls.
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value):
        raise ValueError("Invalid music title")
    title = value.strip()
    if not title:
        raise ValueError("Invalid music title")
    return title


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


@dataclass(frozen=True)
class _Track:
    title: str
    start_seconds: float
    duration_seconds: float


@dataclass(frozen=True)
class MusicSession:
    duration_seconds: float
    tracks: tuple[_Track, ...]

    @classmethod
    def from_audio(cls, path: Path) -> MusicSession | None:
        """Return a cached session, or None when its WAV/manifest is unavailable or invalid.

        Duration comes from the WAV header, not a claimed JSON value. Unknown
        descriptive manifest fields are ignored; they never become instructions.
        No audio samples are loaded and no music is generated or modified.
        """
        try:
            with path.with_suffix(".json").open("rb") as manifest_file:
                raw = manifest_file.read(MAX_MANIFEST_BYTES + 1)
            if len(raw) > MAX_MANIFEST_BYTES:
                return None
            manifest = json.loads(raw.decode("utf-8"), parse_constant=_invalid_constant)
            if not isinstance(manifest, dict):
                return None
            declared_duration = _number(manifest.get("duration_seconds"), positive=True)
            entries = manifest.get("tracks")
            if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_TRACKS:
                return None

            with wave.open(str(path), "rb") as audio:
                sample_rate = audio.getframerate()
                frames = audio.getnframes()
                if sample_rate <= 0 or frames <= 0 or audio.getcomptype() != "NONE":
                    return None
                duration = frames / sample_rate
            tolerance = max(1 / sample_rate, 1e-6)
            if abs(declared_duration - duration) > tolerance:
                return None

            tracks = []
            cursor = 0.0
            for entry in entries:
                if not isinstance(entry, dict):
                    return None
                title = _title(entry.get("title"))
                start = _number(entry.get("start_seconds"))
                length = _number(entry.get("duration_seconds"), positive=True)
                if abs(start - cursor) > tolerance:
                    return None
                # Canonicalize harmless sub-sample rounding in adjacent starts.
                tracks.append(_Track(title, cursor, length))
                cursor += length
                if not math.isfinite(cursor) or cursor > duration + tolerance:
                    return None
            if abs(cursor - duration) > tolerance:
                return None

            # The final track ends exactly at the actual WAV loop boundary.
            last = tracks[-1]
            final_duration = duration - last.start_seconds
            if final_duration <= 0:
                return None
            tracks[-1] = _Track(last.title, last.start_seconds, final_duration)
            return cls(duration, tuple(tracks))
        except (OSError, ValueError, TypeError, OverflowError, RecursionError, wave.Error, EOFError):
            return None

    def playback(self, seconds: float) -> dict[str, str | int | float]:
        """Locate music using encoded media time, not wall-clock time.

        The caller should clear playback when no actual signal is being emitted.
        Invalid timeline values raise ValueError rather than publishing NaN or
        pretending that the first track is playing.
        """
        elapsed = _number(seconds) % self.duration_seconds
        index = bisect_right(tuple(track.start_seconds for track in self.tracks), elapsed) - 1
        track = self.tracks[index]
        return {
            "music_track": track.title,
            "music_track_index": index + 1,
            "music_track_count": len(self.tracks),
            "music_track_elapsed_seconds": elapsed - track.start_seconds,
            "music_track_duration_seconds": track.duration_seconds,
            "music_session_elapsed_seconds": elapsed,
            "music_session_duration_seconds": self.duration_seconds,
        }
