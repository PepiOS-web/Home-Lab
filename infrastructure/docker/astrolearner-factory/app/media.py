from __future__ import annotations

import hashlib
import json
import math
import os
import random
import subprocess
import sys
import textwrap
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .audio import generate_ambient_track, mix_voice_and_music, normalize_voice_only
from .config import Settings
from .schemas import ContentPackage
from .visuals import make_science_visual

FONT_REGULAR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
BRAND_MAGENTA = (210, 0, 105)
BRAND_CYAN = (39, 209, 255)
BACKGROUND_TOP = (4, 8, 24)
BACKGROUND_BOTTOM = (19, 8, 42)


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 1800,
    input_text: str | None = None,
) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        input=input_text,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr[-4000:] if result.stderr else "sin diagnóstico"
        raise RuntimeError(f"Falló {' '.join(command[:3])}: {stderr}")


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe no pudo leer {path.name}: {result.stderr[-1000:]}")
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"Duración inválida para {path.name}")
    return duration


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    return ImageFont.truetype(str(path), size=size)


def _gradient(width: int, height: int) -> Image.Image:
    strip = Image.new("RGB", (1, height), BACKGROUND_TOP)
    pixels = strip.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(
            round(
                BACKGROUND_TOP[index] * (1 - ratio) + BACKGROUND_BOTTOM[index] * ratio
            )
            for index in range(3)
        )
        pixels[0, y] = color
    return strip.resize((width, height))


def _starfield(width: int, height: int, seed_text: str) -> Image.Image:
    image = _gradient(width, height)
    draw = ImageDraw.Draw(image)
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    for _ in range(max(140, (width * height) // 9000)):
        x = rng.randrange(width)
        y = rng.randrange(height)
        radius = rng.choice((1, 1, 1, 2, 2, 3))
        brightness = rng.randrange(130, 256)
        tint = rng.choice(((brightness, brightness, brightness), (150, 205, 255)))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=tint)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (width * 0.58, -height * 0.2, width * 1.18, height * 0.72),
        fill=(*BRAND_MAGENTA, 60),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(30, width // 24)))
    return Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")


def _wrap_for_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        left, _, right, _ = draw.textbbox((0, 0), candidate, font=font)
        if current and right - left > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: Iterable[str],
    font: ImageFont.FreeTypeFont,
    center_x: int,
    start_y: int,
    fill: tuple[int, int, int],
    spacing: int,
) -> int:
    y = start_y
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        width = box[2] - box[0]
        draw.text((center_x - width // 2, y), line, font=font, fill=fill)
        y += (box[3] - box[1]) + spacing
    return y


def make_slide(
    path: Path,
    *,
    brand: str,
    heading: str,
    subheading: str,
    width: int,
    height: int,
) -> None:
    image = _starfield(width, height, f"{heading}|{subheading}")
    draw = ImageDraw.Draw(image, "RGBA")
    margin = round(width * 0.08)
    panel_top = round(height * 0.18)
    panel_bottom = round(height * 0.82)
    draw.rounded_rectangle(
        (margin, panel_top, width - margin, panel_bottom),
        radius=max(24, width // 40),
        fill=(2, 5, 18, 195),
        outline=(*BRAND_CYAN, 140),
        width=max(2, width // 500),
    )
    draw.rectangle(
        (margin, panel_top, width - margin, panel_top + 8), fill=BRAND_MAGENTA
    )

    brand_font = _font(max(24, width // 42), bold=True)
    title_font = _font(max(38, width // 20), bold=True)
    body_font = _font(max(24, width // 36))
    draw.text((margin, round(height * 0.07)), brand, font=brand_font, fill=BRAND_CYAN)

    title_lines = _wrap_for_width(draw, heading, title_font, width - 2 * margin - 80)
    body_lines = _wrap_for_width(draw, subheading, body_font, width - 2 * margin - 110)
    y = _draw_centered_lines(
        draw,
        title_lines[:4],
        title_font,
        width // 2,
        round(height * 0.29),
        (255, 255, 255),
        max(10, height // 100),
    )
    _draw_centered_lines(
        draw,
        body_lines[:6],
        body_font,
        width // 2,
        y + max(22, height // 30),
        (210, 218, 235),
        max(8, height // 120),
    )
    image.save(path, format="PNG", optimize=True)


def make_thumbnail(path: Path, package: ContentPackage) -> None:
    image = _starfield(1280, 720, package.selected_title)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((55, 70, 1225, 650), radius=42, fill=(2, 5, 18, 205))
    draw.rectangle((55, 70, 75, 650), fill=BRAND_MAGENTA)
    brand_font = _font(38, bold=True)
    title_font = _font(82, bold=True)
    draw.text((105, 105), "ASTROLEARNER", font=brand_font, fill=BRAND_CYAN)
    lines = _wrap_for_width(draw, package.thumbnail_text.upper(), title_font, 990)
    _draw_centered_lines(draw, lines[:4], title_font, 640, 250, (255, 255, 255), 22)
    image.save(path, format="JPEG", quality=92, optimize=True)


def synthesize_speech(
    text: str,
    output: Path,
    settings: Settings,
) -> float:
    voice_model = settings.model_dir / f"{settings.tts_voice}.onnx"
    voice_config = settings.model_dir / f"{settings.tts_voice}.onnx.json"
    if not voice_model.is_file() or not voice_config.is_file():
        raise RuntimeError(
            f"Falta la voz {settings.tts_voice}. Ejecuta de nuevo bootstrap.sh"
        )
    _run(
        [
            sys.executable,
            "-m",
            "piper",
            "--model",
            settings.tts_voice,
            "--data-dir",
            str(settings.model_dir),
            "--output-file",
            str(output),
            "--sentence-silence",
            "0.16",
        ],
        timeout=600,
        input_text=f"{text}\n",
    )
    return _probe_duration(output)


def _format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(path: Path, entries: list[tuple[float, float, str]]) -> None:
    blocks: list[str] = []
    for index, (start, end, text) in enumerate(entries, start=1):
        wrapped = "\n".join(textwrap.wrap(text, width=52))
        blocks.append(
            f"{index}\n{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n{wrapped}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _render_segment(
    image: Path,
    audio: Path,
    output: Path,
    duration: float,
    width: int,
    height: int,
    settings: Settings,
) -> None:
    zoom_filter = (
        f"scale={width}:{height},"
        f"zoompan=z='min(pzoom+0.00025,1.055)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps=30,format=yuv420p"
    )
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(image),
            "-i",
            str(audio),
            "-vf",
            zoom_filter,
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-threads",
            str(settings.ffmpeg_threads),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def _concat_and_normalize(
    segment_files: list[Path], output: Path, settings: Settings
) -> dict[str, object] | None:
    work_dir = output.parent
    concat_file = work_dir / f"{output.stem}-concat.txt"
    raw_file = work_dir / f"{output.stem}-raw.mp4"
    concat_file.write_text(
        "".join(f"file '{path.name}'\n" for path in segment_files),
        encoding="utf-8",
    )
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file.name,
            "-c",
            "copy",
            raw_file.name,
        ],
        cwd=work_dir,
    )
    temporary = output.with_suffix(".tmp.mp4")
    music_metadata: dict[str, object] | None = None
    if settings.music_enabled and settings.music_volume > 0:
        duration = _probe_duration(raw_file)
        music_file = work_dir / f"{output.stem}-music.wav"
        seed = generate_ambient_track(music_file, duration, output.stem)
        mix_voice_and_music(
            raw_file,
            music_file,
            temporary,
            music_volume=settings.music_volume,
            ffmpeg_threads=settings.ffmpeg_threads,
        )
        music_metadata = {
            "type": "procedural_original",
            "generator": "AstroLearner Factory",
            "seed": seed,
            "volume": settings.music_volume,
            "file": f"render/{music_file.name}",
        }
    else:
        normalize_voice_only(
            raw_file,
            temporary,
            ffmpeg_threads=settings.ffmpeg_threads,
        )
    os.replace(temporary, output)
    concat_file.unlink(missing_ok=True)
    raw_file.unlink(missing_ok=True)
    return music_metadata


def _render_sequence(
    sequence: list[tuple[str, str, str, str]],
    output: Path,
    captions: Path,
    settings: Settings,
    *,
    width: int,
    height: int,
    prefix: str,
) -> dict[str, object]:
    work_dir = output.parent
    segment_files: list[Path] = []
    caption_entries: list[tuple[float, float, str]] = []
    resolved_kinds: list[str] = []
    clock = 0.0

    for index, (heading, narration, visual_direction, visual_kind) in enumerate(
        sequence, start=1
    ):
        image = work_dir / f"{prefix}-slide-{index:02d}.png"
        audio = work_dir / f"{prefix}-audio-{index:02d}.wav"
        video = work_dir / f"{prefix}-segment-{index:02d}.mp4"
        resolved_kind = make_science_visual(
            image,
            brand="ASTROLEARNER",
            heading=heading,
            visual_direction=visual_direction,
            visual_kind=visual_kind,
            width=width,
            height=height,
        )
        resolved_kinds.append(resolved_kind)
        duration = synthesize_speech(narration, audio, settings)
        _render_segment(image, audio, video, duration, width, height, settings)
        segment_files.append(video)
        caption_entries.append((clock, clock + duration, narration))
        clock += duration

    music_metadata = _concat_and_normalize(segment_files, output, settings)
    _write_srt(captions, caption_entries)
    return {"visual_kinds": resolved_kinds, "music": music_metadata}


def render_package(
    job_id: str,
    package: ContentPackage,
    job_dir: Path,
    settings: Settings,
) -> str:
    render_dir = job_dir / "render"
    render_dir.mkdir(parents=True, exist_ok=True)

    master = render_dir / "master-1080p.mp4"
    master_srt = render_dir / "master-es.srt"
    thumbnail = render_dir / "thumbnail.jpg"
    make_thumbnail(thumbnail, package)

    long_sequence = [
        (
            segment.heading,
            segment.narration,
            segment.visual_direction,
            segment.visual_kind,
        )
        for segment in package.segments
    ]
    long_metadata = _render_sequence(
        long_sequence,
        master,
        master_srt,
        settings,
        width=1920,
        height=1080,
        prefix="long",
    )

    short_outputs: list[Path] = []
    short_captions: list[Path] = []
    short_metadata: list[dict[str, object]] = []
    short_visuals = [
        package.segments[index % len(package.segments)] for index in range(3)
    ]
    for short_index, short in enumerate(package.shorts, start=1):
        prefix = f"short-{short_index:02d}"
        short_output = render_dir / f"{prefix}.mp4"
        short_srt = render_dir / f"{prefix}-es.srt"
        short_sequence = [
            (
                short.title,
                short.hook,
                short_visuals[0].visual_direction,
                short_visuals[0].visual_kind,
            ),
            (
                "La explicación",
                short.body,
                short_visuals[1].visual_direction,
                short_visuals[1].visual_kind,
            ),
            (
                "Sigue aprendiendo",
                short.call_to_action,
                short_visuals[2].visual_direction,
                short_visuals[2].visual_kind,
            ),
        ]
        short_metadata.append(
            _render_sequence(
                short_sequence,
                short_output,
                short_srt,
                settings,
                width=1080,
                height=1920,
                prefix=prefix,
            )
        )
        short_outputs.append(short_output)
        short_captions.append(short_srt)

    licenses = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "visuals": {
            "type": "procedural_scientific_original",
            "generator": "AstroLearner Factory/Pillow",
            "long_renderers": long_metadata["visual_kinds"],
            "short_renderers": [item["visual_kinds"] for item in short_metadata],
            "notice": "Ilustraciones esquemáticas originales; no están a escala.",
            "third_party_assets": [],
        },
        "voice": {
            "engine": "Piper",
            "engine_license": "GPL-3.0",
            "voice": settings.tts_voice,
            "dataset_license": "CC0",
            "model_card": "https://huggingface.co/rhasspy/piper-voices/blob/main/es/es_ES/davefx/medium/MODEL_CARD",
        },
        "music": {
            "license": "original_project_generated",
            "long": long_metadata["music"],
            "shorts": [item["music"] for item in short_metadata],
            "third_party_assets": [],
        },
    }
    (job_dir / "licenses.json").write_text(
        json.dumps(licenses, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "job_id": job_id,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "status": "review_required",
        "artifacts": {
            "master": "render/master-1080p.mp4",
            "master_captions": "render/master-es.srt",
            "thumbnail": "render/thumbnail.jpg",
            **{
                f"short_{index:02d}": f"render/{path.name}"
                for index, path in enumerate(short_outputs, start=1)
            },
            **{
                f"short_{index:02d}_captions": f"render/{path.name}"
                for index, path in enumerate(short_captions, start=1)
            },
        },
        "warning": (
            "Piloto con ilustraciones científicas originales y música procedural. "
            "Verificar diagramas, voz, mezcla y subtítulos antes de publicar."
        ),
    }
    (job_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    digest = hashlib.sha256()
    for artifact in (master, *short_outputs, thumbnail, master_srt, *short_captions):
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()
