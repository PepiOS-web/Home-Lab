from __future__ import annotations

import hashlib
import math
import struct
import subprocess
import wave
from pathlib import Path


def _run(command: list[str], *, timeout: int = 1800) -> None:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr[-4000:] if result.stderr else "sin diagnóstico"
        raise RuntimeError(f"Falló {' '.join(command[:3])}: {stderr}")


def ambient_seed(seed_text: str) -> int:
    return int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:8], 16)


def _pad_tone(root: float, time_seconds: float) -> float:
    return (
        0.115 * math.sin(2 * math.pi * root * time_seconds)
        + 0.060 * math.sin(2 * math.pi * root * 1.5 * time_seconds + 0.4)
        + 0.035 * math.sin(2 * math.pi * root * 2.0 * time_seconds + 1.1)
    )


def generate_ambient_track(path: Path, duration: float, seed_text: str) -> int:
    """Generate a deterministic, original ambient pad without third-party audio."""
    sample_rate = 48_000
    total_samples = max(1, round(duration * sample_rate))
    seed = ambient_seed(seed_text)
    roots = (87.31, 110.0, 130.81, 98.0)
    root_offset = seed % len(roots)
    chunk_size = 4096

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)

        for start in range(0, total_samples, chunk_size):
            frames = bytearray()
            stop = min(start + chunk_size, total_samples)
            for sample_index in range(start, stop):
                t = sample_index / sample_rate
                section_duration = 12.0
                section = int(t // section_duration)
                section_position = t % section_duration
                current_root = roots[(section + root_offset) % len(roots)]
                next_root = roots[(section + root_offset + 1) % len(roots)]
                crossfade = max(
                    0.0,
                    min(1.0, (section_position - 8.0) / 4.0),
                )
                crossfade = crossfade * crossfade * (3.0 - 2.0 * crossfade)
                fade_in = min(1.0, t / 3.0)
                fade_out = min(1.0, max(0.0, duration - t) / 4.0)
                envelope = fade_in * fade_out
                pulse = 0.72 + 0.28 * math.sin(2 * math.pi * 0.045 * t)
                tone = (1.0 - crossfade) * _pad_tone(
                    current_root, t
                ) + crossfade * _pad_tone(next_root, t)
                value = envelope * pulse * tone
                sample = max(-32767, min(32767, round(value * 32767)))
                frames.extend(struct.pack("<h", sample))
            output.writeframesraw(frames)
    return seed


def mix_voice_and_music(
    input_video: Path,
    music: Path,
    output: Path,
    *,
    music_volume: float,
    ffmpeg_threads: int,
) -> None:
    filter_graph = (
        "[0:a]loudnorm=I=-16:LRA=11:TP=-1.5[voice];"
        f"[1:a]highpass=f=55,lowpass=f=1800,volume={music_volume:.3f}[music];"
        "[music][voice]sidechaincompress="
        "threshold=0.020:ratio=8:attack=45:release=650[ducked];"
        "[voice][ducked]amix=inputs=2:duration=first:"
        "dropout_transition=0:normalize=0,"
        "alimiter=limit=0.80:level=false[aout]"
    )
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_video),
            "-i",
            str(music),
            "-filter_complex",
            filter_graph,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-threads",
            str(ffmpeg_threads),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def normalize_voice_only(
    input_video: Path,
    output: Path,
    *,
    ffmpeg_threads: int,
) -> None:
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_video),
            "-c:v",
            "copy",
            "-threads",
            str(ffmpeg_threads),
            "-af",
            "loudnorm=I=-16:LRA=11:TP=-1.5",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
