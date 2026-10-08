from __future__ import annotations

import math
import struct
import wave
import json
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

# Bound decoder memory even if an upstream image contains malicious dimensions.
Image.MAX_IMAGE_PIXELS = 40_000_000

CONTINENTS = [
    [(-168, 70), (-130, 72), (-105, 50), (-82, 24), (-100, 15), (-125, 30), (-150, 58)],
    [(-82, 12), (-48, 8), (-35, -10), (-55, -55), (-72, -40)],
    [
        (-10, 36),
        (12, 72),
        (65, 70),
        (105, 52),
        (145, 48),
        (178, 65),
        (165, 8),
        (105, 5),
        (55, 25),
        (32, 35),
    ],
    [(-18, 35), (18, 38), (50, 10), (42, -35), (15, -35), (-10, 5)],
    [(112, -10), (154, -12), (150, -42), (116, -35)],
    [(-72, 84), (-20, 82), (-42, 60)],
]

COUNTRIES = Path(__file__).with_name("data") / "ne_10m_admin_0_countries.geojson"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _xy(lon: float, lat: float, width: int, height: int) -> tuple[float, float]:
    return ((lon + 180) / 360 * width, (90 - lat) / 180 * height)


@lru_cache(maxsize=1)
def _country_rings() -> tuple[tuple[tuple[tuple[float, float], ...], ...], ...]:
    """Load Natural Earth 1:10m country geometry once, not once per map frame."""
    if not COUNTRIES.is_file():
        return ()
    with COUNTRIES.open("r", encoding="utf-8") as source:
        collection = json.load(source)
    polygons = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") == "Polygon":
            coordinates = [coordinates]
        elif geometry.get("type") != "MultiPolygon":
            continue
        for polygon in coordinates:
            rings = []
            for ring in polygon:
                # A little screen-space thinning keeps the detailed coastlines
                # crisp at 1080p without repeatedly rasterizing sub-pixel points.
                points = tuple((float(point[0]), float(point[1])) for point in ring)
                if len(points) >= 4:
                    rings.append(points)
            if rings:
                polygons.append(tuple(rings))
    return tuple(polygons)


@lru_cache(maxsize=2)
def _world_background(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), "#061321")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / max(height - 1, 1)
        draw.line((0, y, width, y), fill=(5, int(20 + 15 * blend), int(38 + 23 * blend)))

    # Subtle graticule, with a brighter equator and prime meridian.
    for glon in range(-180, 181, 30):
        x, _ = _xy(glon, 0, width, height)
        draw.line((x, 0, x, height), fill="#19364a", width=max(1, width // 1920))
    for glat in range(-60, 61, 30):
        _, y = _xy(0, glat, width, height)
        draw.line((0, y, width, y), fill="#19364a", width=max(1, width // 1920))
    x, _ = _xy(0, 0, width, height)
    _, y = _xy(0, 0, width, height)
    draw.line((x, 0, x, height), fill="#29495b", width=max(1, width // 1280))
    draw.line((0, y, width, y), fill="#29495b", width=max(1, width // 1280))

    polygons = _country_rings()
    if polygons:
        for polygon in polygons:
            outer = [_xy(lon, lat, width, height) for lon, lat in polygon[0]]
            draw.polygon(outer, fill="#244b50")
            # Country outlines double as detailed coastlines at this scale.
            draw.line(outer, fill="#5d9990", width=max(1, width // 1920), joint="curve")
            for hole in polygon[1:]:
                draw.polygon(
                    [_xy(lon, lat, width, height) for lon, lat in hole],
                    fill="#0a1b2a",
                )
    else:
        for polygon in CONTINENTS:
            draw.polygon(
                [_xy(lon, lat, width, height) for lon, lat in polygon],
                fill="#244b50",
                outline="#5d9990",
            )
    return image


def render_map(
    path: Path,
    width: int,
    height: int,
    lat: float,
    lon: float,
    altitude: float,
    track: list[tuple[float, float]] | None = None,
    velocity: float | None = None,
) -> None:
    image = _world_background(width, height).copy()
    draw = ImageDraw.Draw(image, "RGBA")
    scale = max(1, width // 1920)
    if track and len(track) > 1:
        segment: list[tuple[float, float]] = []
        previous_lon: float | None = None
        for track_lat, track_lon in track:
            xy = _xy(track_lon, track_lat, width, height)
            if segment and previous_lon is not None and abs(track_lon - previous_lon) > 180:
                if len(segment) > 1:
                    draw.line(segment, fill=(49, 224, 229, 180), width=5 * scale, joint="curve")
                segment = []
            segment.append(xy)
            previous_lon = track_lon
        if len(segment) > 1:
            draw.line(segment, fill=(49, 224, 229, 180), width=5 * scale, joint="curve")

    x, y = _xy(lon, lat, width, height)
    radius = max(9, width // 100)
    draw.ellipse((x-radius*3, y-radius*3, x+radius*3, y+radius*3), fill=(36, 205, 228, 28))
    draw.ellipse((x-radius*2, y-radius*2, x+radius*2, y+radius*2), outline=(77, 227, 239, 220), width=3*scale)
    draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill="#f1ffff", outline="#30d3df", width=3*scale)
    draw.line((x + radius, y, min(width - 20, x + radius * 8), y - radius * 2), fill=(220, 251, 255, 230), width=2*scale)
    draw.rounded_rectangle((36, 28, width - 36, 126), radius=22, fill=(3, 12, 25, 205), outline=(74, 150, 170, 150), width=2)
    draw.text((62, 42), "ASTROLEARNER  /  ISS ORBIT TRACKER", font=_font(max(22, width // 48)), fill="#f4fbff")
    draw.text((64, 82), "SEGUIMIENTO ORBITAL EN TIEMPO REAL  ·  MAPA NATURAL EARTH 1:10m", font=_font(max(14, width // 90)), fill="#87cbd2")

    panel_top = height - max(154, height // 7)
    draw.rounded_rectangle((36, panel_top, width - 36, height - 30), radius=20, fill=(3, 12, 25, 218), outline=(74, 150, 170, 150), width=2)
    col_width = (width - 130) // 4
    details = [
        ("LATITUD", f"{lat:+.3f}°"),
        ("LONGITUD", f"{lon:+.3f}°"),
        ("ALTITUD", f"{altitude:.1f} km"),
        ("VELOCIDAD", f"{velocity:,.0f} km/h" if velocity is not None else "~27,600 km/h"),
    ]
    for index, (label, value) in enumerate(details):
        left = 62 + index * col_width
        draw.text((left, panel_top + 23), label, font=_font(max(13, width // 110)), fill="#80b9c4")
        draw.text((left, panel_top + 54), value, font=_font(max(22, width // 60)), fill="#effcff")
    draw.text((62, height - 53), "Trayectoria reciente  ·  Datos orbitales actualizados cada 15 s  ·  Mapa: Natural Earth", font=_font(max(12, width // 120)), fill="#86abb7")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.png")
    image.save(temporary, format="PNG")
    temporary.replace(path)


def render_earth_frame(
    source: Path | None,
    destination: Path,
    width: int,
    height: int,
    captured_at: str = "",
) -> None:
    if source is not None and source.exists():
        with Image.open(source) as original:
            image = ImageOps.fit(
                original.convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
            )
    else:
        image = Image.new("RGB", (width, height), "#020817")
        draw = ImageDraw.Draw(image)
        for y in range(height):
            shade = int(28 * y / height)
            draw.line((0, y, width, y), fill=(2, 8 + shade, 23 + shade))

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (28, 24, width - 28, 112), radius=18, fill=(2, 8, 23, 190)
    )
    draw.text(
        (52, 39),
        "ASTROLEARNER · LA TIERRA DESDE EL ESPACIO",
        font=_font(max(24, width // 34)),
        fill="#ffffff",
    )
    draw.rounded_rectangle(
        (28, height - 105, width - 28, height - 24),
        radius=18,
        fill=(2, 8, 23, 200),
    )
    credit = "NASA EPIC / DSCOVR · Imagen reciente · No es una cámara de la ISS"
    draw.text(
        (52, height - 88),
        credit,
        font=_font(max(17, width // 54)),
        fill="#bcecff",
    )
    if captured_at:
        draw.text(
            (52, height - 56),
            f"Capturada: {captured_at} UTC",
            font=_font(max(15, width // 64)),
            fill="#ffffff",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.jpg")
    image.save(temporary, format="JPEG", quality=90, optimize=True)
    temporary.replace(destination)


def create_ambient_music(
    path: Path, seconds: int = 600, sample_rate: int = 24_000
) -> None:
    if path.exists() and path.stat().st_size > 100_000:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # A quiet, instrumental lo-fi loop: warm electric-piano voicings, rounded
    # bass, and a very soft tonal beat. No samples, hiss, or white-noise layer.
    chords = [
        # Am9, Fmaj9, Cmaj9, G6/9; fundamentals weighted for a mellow Rhodes tone.
        [(55.00, 0.050), (220.00, 0.050), (261.63, 0.032), (329.63, 0.024), (392.00, 0.016), (493.88, 0.008)],
        [(43.65, 0.050), (174.61, 0.050), (220.00, 0.032), (261.63, 0.024), (329.63, 0.016), (392.00, 0.008)],
        [(32.70, 0.050), (196.00, 0.050), (246.94, 0.032), (261.63, 0.024), (329.63, 0.016), (392.00, 0.008)],
        [(49.00, 0.050), (196.00, 0.050), (246.94, 0.032), (293.66, 0.024), (329.63, 0.016), (440.00, 0.008)],
    ]
    phases = [[0.0] * len(chord) for chord in chords]
    phase_steps = [
        [2 * math.pi * frequency / sample_rate for frequency, _ in chord]
        for chord in chords
    ]
    beat_seconds = 60.0 / 72.0
    bar_seconds = beat_seconds * 4
    chord_seconds = bar_seconds * 4
    transition_seconds = beat_seconds * 1.5
    melody = (659.25, 587.33, 523.25, 587.33, 493.88, 587.33, 659.25, 587.33)
    melody_phase = 0.0
    kick_phase = 0.0
    rim_phase = 0.0
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        chunk = bytearray()
        total = seconds * sample_rate
        for index in range(total):
            t = index / sample_rate
            fade = min(1.0, t / 8.0, (seconds - t) / 8.0)
            slow = 0.78 + 0.22 * math.sin(2 * math.pi * t / 47.0)
            chord_index = min(len(chords) - 1, int(t / chord_seconds))
            value = 0.0
            if t % chord_seconds < transition_seconds and chord_index > 0:
                progress = (t % chord_seconds) / transition_seconds
                previous_index = chord_index - 1
                old_value = 0.0
                for pos, (_, amplitude) in enumerate(chords[previous_index]):
                    phases[previous_index][pos] += phase_steps[previous_index][pos]
                    old_value += math.sin(phases[previous_index][pos]) * amplitude
                new_value = 0.0
                for pos, (_, amplitude) in enumerate(chords[chord_index]):
                    phases[chord_index][pos] += phase_steps[chord_index][pos]
                    new_value += math.sin(phases[chord_index][pos]) * amplitude
                value = old_value * (1 - progress) + new_value * progress
            else:
                for pos, (_, amplitude) in enumerate(chords[chord_index]):
                    phases[chord_index][pos] += phase_steps[chord_index][pos]
                    value += math.sin(phases[chord_index][pos]) * amplitude

            # Sparse, low-level Rhodes motif: one short note every other bar.
            bar_position = t % bar_seconds
            bar_number = int(t / bar_seconds)
            if bar_number % 2 == 0 and bar_position < 0.42:
                note_index = (bar_number // 2 + chord_index * 2) % len(melody)
                melody_phase += 2 * math.pi * melody[note_index] / sample_rate
                value += math.sin(melody_phase) * math.exp(-bar_position * 7) * 0.018

            # Muted kick on beats 1/3 and a soft pitched rim on beats 2/4.
            beat_position = t % beat_seconds
            beat_number = int(t / beat_seconds) % 4
            if beat_position < 0.18 and beat_number in {0, 2}:
                kick_frequency = 48 - 12 * beat_position / 0.18
                kick_phase += 2 * math.pi * kick_frequency / sample_rate
                value += math.sin(kick_phase) * math.exp(-beat_position * 24) * 0.035
            elif beat_position < 0.10 and beat_number in {1, 3}:
                rim_phase += 2 * math.pi * 185 / sample_rate
                value += math.sin(rim_phase) * math.exp(-beat_position * 45) * 0.012

            sample = int(max(-1, min(1, value * slow * fade * 0.82)) * 32767)
            chunk.extend(struct.pack("<hh", sample, sample))
            if len(chunk) >= 262_144:
                output.writeframesraw(chunk)
                chunk.clear()
        if chunk:
            output.writeframesraw(chunk)
