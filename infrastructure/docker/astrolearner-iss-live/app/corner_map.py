"""Compact PNG orbital card, rendered for its actual on-screen size."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import io
import math

from PIL import Image, ImageDraw, ImageFont

from .media import _world_background, _xy

SIZE = (432, 304)


@lru_cache(maxsize=16)
def _font(size: int):
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf", "C:/Windows/Fonts/segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def position_state(state: dict, now: datetime) -> str:
    lat, lon = number(state.get("latitude")), number(state.get("longitude"))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return "unavailable"
    try:
        timestamp = datetime.fromisoformat(state.get("position_updated_at") or "")
        if timestamp.tzinfo is None:
            return "unavailable"
        age = (now - timestamp).total_seconds()
    except (ValueError, TypeError, OverflowError):
        return "unavailable"
    if age < -30:
        return "unavailable"
    return "fresh" if age <= 45 else "stale"


def render_corner_map(state: dict, track: tuple = (), now: datetime | None = None) -> tuple[bytes, str]:
    quality = position_state(state, now or datetime.now(timezone.utc))
    lat = number(state.get("latitude")) if quality != "unavailable" else None
    lon = number(state.get("longitude")) if quality != "unavailable" else None
    altitude, speed = number(state.get("altitude_km")), number(state.get("velocity_kmh"))
    clean_track = []
    for point in track[-120:]:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            continue
        a, b = number(point[0]), number(point[1])
        if a is not None and b is not None and -90 <= a <= 90 and -180 <= b <= 180:
            clean_track.append((a, b))
    return _render(lat, lon, altitude, speed, quality, tuple(clean_track)), quality


@lru_cache(maxsize=8)
def _render(lat, lon, altitude, speed, quality, track) -> bytes:
    # Draw at 2x and downsample once; source PNG is never JPEG-recompressed.
    scale = 2
    image = Image.new("RGB", (SIZE[0] * scale, SIZE[1] * scale), "#071321")
    draw = ImageDraw.Draw(image)
    def text(x, y, value, size=14, color="#eefcff"):
        draw.text((x * scale, y * scale), value, font=_font(size * scale), fill=color)
    text(10, 5, "ASTROLEARNER / ISS", 16)
    label, color = {"fresh": ("ACTUAL", "#80e3b2"), "stale": ("ANTERIOR", "#ffcc80"),
                    "unavailable": ("SIN DATOS", "#ffcc80")}[quality]
    text(333, 9, label, 11, color)
    world = _world_background(416 * scale, 208 * scale).copy()
    world_draw = ImageDraw.Draw(world)
    previous = None
    if quality != "unavailable":
        for a, b in track:
            point = _xy(b, a, world.width, world.height)
            if previous is not None and abs(b - previous[1]) < 180:
                world_draw.line((previous[2], point), fill="#35d9df", width=2 * scale)
            previous = (a, b, point)
        x, y = _xy(lon, lat, world.width, world.height)
        radius = 5 * scale
        world_draw.ellipse((x-radius*2, y-radius*2, x+radius*2, y+radius*2), outline="#44e0e7", width=scale)
        world_draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill="#ffffff", outline="#44e0e7", width=scale)
    image.paste(world, (8 * scale, 31 * scale))
    world.close()
    if quality == "unavailable":
        text(12, 244, "Esperando posicion orbital", 14, color)
        text(12, 266, "No se muestra una posicion inventada", 12, "#a4bdcc")
    else:
        text(12, 244, f"LAT {lat:+.2f}°    LON {lon:+.2f}°")
        alt = f"{altitude:.1f} km" if altitude is not None and altitude >= 0 else "--"
        vel = f"{speed:,.0f} km/h" if speed is not None and speed >= 0 else "--"
        text(12, 265, f"ALT {alt}    VEL {vel}")
    text(12, 289, "Mapa: Natural Earth  /  Trayectoria reciente", 9, "#91b3c6")
    result = image.resize(SIZE, Image.Resampling.LANCZOS)
    image.close()
    buffer = io.BytesIO()
    result.save(buffer, format="PNG", compress_level=3)
    result.close()
    return buffer.getvalue()
