"""Small, honest broadcast HUD rendered at most once per UTC second.

This module does not fetch URLs, read credentials, inspect the publishing
connection, or composite/re-encode the 30 FPS camera. The encoder can overlay
the cached JPEG as a separate input, preserving one encoder and continuous
audio. A caller may repeat ``DashboardFrame.jpeg`` at its output cadence.

All labels use an explicit allowlist of public telemetry fields. External
camera frames are never advertised as independently verified live pictures:
the provider may itself be showing archive material.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import io
import math
import threading
from typing import Any
import warnings

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .corner_map import number, position_state
from .media import _world_background, _xy

DEFAULT_SIZE = (1280, 144)
MAX_CARD_BYTES = 2 * 1024 * 1024
MAX_CARD_PIXELS = 16_777_216
CARD_KEYS = ("sun", "earth", "moon", "aurora")
_CARD_TITLES = {"sun": "SOL", "earth": "TIERRA", "moon": "LUNA", "aurora": "AURORAS"}
_SOURCE_LABELS = {
    "camera": ("SEÑAL EXTERNA", "El proveedor puede mostrar imágenes de archivo"),
    "recorded": ("VÍDEO GRABADO", "Imágenes de archivo · no son la cámara actual"),
    "map": ("MAPA DE RESPALDO", "Cámara no disponible · seguimos la órbita"),
}


@dataclass(frozen=True)
class SpaceCard:
    """Already downloaded thumbnail; ``observed_at`` is its observation UTC.

    These bytes must be supplied by a bounded, separate background worker.
    The renderer never downloads a URL or trusts a downloaded filename. Keep
    the last good image on network errors and pass ``state='stale'`` so its
    age and the warning remain visible. ``credit`` is a short, public source
    attribution, not a URL. For auroras this field may instead be the forecast
    valid time, up to six hours ahead; it is never described as an observation.
    """

    key: str
    image: bytes | None = None
    observed_at: str | None = None
    state: str = "available"
    credit: str = ""


@dataclass(frozen=True)
class DashboardFrame:
    png: bytes
    jpeg: bytes
    width: int
    height: int
    position_state: str
    source_label: str
    position_age_seconds: int | None
    text_lines: tuple[str, ...]


@lru_cache(maxsize=24)
def _font(size: int, bold: bool = False):
    names = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _utc(value: str | None) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _age(value: str | None, now: datetime) -> int | None:
    parsed = _utc(value)
    if parsed is None:
        return None
    age = (now - parsed).total_seconds()
    return max(0, int(age)) if age >= -30 else None


def _duration(value: int | float | None) -> str:
    numeric = number(value)
    if numeric is None or numeric < 0:
        return "--:--"
    minutes, seconds = divmod(int(numeric), 60)
    return f"{minutes}:{seconds:02d}"


def _age_text(age: int | None) -> str:
    if age is None:
        return "SIN FECHA"
    if age < 60:
        return f"hace {age} s"
    if age < 3600:
        return f"hace {age // 60} min"
    if age < 172800:
        return f"hace {age // 3600} h"
    return f"hace {age // 86400} días"


def _public_text(value: Any, limit: int = 90) -> str:
    # Never render unexpected objects, control characters, URL credentials or
    # query strings. Real public track names and short source credits suffice.
    if not isinstance(value, str) or "://" in value or "\x00" in value:
        return ""
    return " ".join(value.split())[:limit]


def _clean_track(track: tuple) -> tuple[tuple[float, float], ...]:
    clean = []
    for point in track[-120:]:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            continue
        lat, lon = number(point[0]), number(point[1])
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            clean.append((lat, lon))
    return tuple(clean)


@lru_cache(maxsize=12)
def _image_digest(data: bytes) -> bytes:
    # Python memoizes bytes hashes; unchanged worker thumbnails are therefore
    # not SHA-256 hashed again at the camera's 30 FPS transport cadence.
    return hashlib.sha256(data).digest()


@lru_cache(maxsize=12)
def _thumbnail(data: bytes) -> bytes | None:
    """Decode bounded rasters only, returning an already fitted tiny PNG."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_CARD_BYTES:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    return None
                if image.width < 1 or image.height < 1 or image.width * image.height > MAX_CARD_PIXELS:
                    return None
                image.seek(0)
                rgb = image.convert("RGB")
            try:
                # Contain, never crop a dated solar disk or forecast legend.
                fitted = ImageOps.contain(rgb, (72, 72), Image.Resampling.LANCZOS)
                result = Image.new("RGB", (72, 72), "#02070d")
                result.paste(fitted, ((72 - fitted.width) // 2, (72 - fitted.height) // 2))
                buffer = io.BytesIO()
                result.save(buffer, "PNG", compress_level=1)
                return buffer.getvalue()
            finally:
                rgb.close()
                if "fitted" in locals():
                    fitted.close()
                if "result" in locals():
                    result.close()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


class StreamDashboard:
    """Thread-safe one-frame cache, with immediate source/freshness changes.

    The canonical design is 1280×144. Other sizes use one down/upscale per HUD
    refresh, not per camera frame. ``enabled=False`` returns ``None`` without
    loading maps or images, allowing an inexpensive rollback.
    """

    def __init__(self, width: int = 1280, height: int = 144, *, enabled: bool = True):
        if (isinstance(width, bool) or isinstance(height, bool)
                or not isinstance(width, int) or not isinstance(height, int)
                or not 640 <= width <= 3840 or not 72 <= height <= 432):
            raise ValueError("Dashboard dimensions outside the bounded display range")
        self.width, self.height, self.enabled = width, height, bool(enabled)
        self._lock = threading.Lock()
        self._cache_key = None
        self._cache: DashboardFrame | None = None
        self.render_count = 0

    def render(
        self,
        state: dict[str, Any],
        track: tuple = (),
        now: datetime | None = None,
        cards: tuple[SpaceCard, ...] = (),
    ) -> DashboardFrame | None:
        if not self.enabled:
            return None
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("Dashboard time must be timezone aware")
        now = now.astimezone(timezone.utc)
        quality = position_state(state, now)
        age = _age(state.get("position_updated_at"), now) if quality != "unavailable" else None
        source, source_note = _SOURCE_LABELS.get(state.get("video_mode"), ("FUENTE SIN CONFIRMAR", "Esperando una fuente de vídeo válida"))
        lat = number(state.get("latitude")) if quality != "unavailable" else None
        lon = number(state.get("longitude")) if quality != "unavailable" else None
        altitude, speed = number(state.get("altitude_km")), number(state.get("velocity_kmh"))
        altitude = altitude if altitude is not None and 0 <= altitude <= 2000 else None
        speed = speed if speed is not None and 0 <= speed <= 100000 else None
        progress_age = _age(state.get("last_progress_at"), now)
        music_active = state.get("music_playback_active") is True and progress_age is not None and progress_age <= 12
        track_name = _public_text(state.get("music_track")) if music_active else "Reproducción sin confirmar"
        track_name = track_name or "Sesión musical AstroLearner"
        elapsed = number(state.get("music_track_elapsed_seconds")) if music_active else None
        elapsed = float(int(elapsed)) if elapsed is not None else None
        duration = number(state.get("music_track_duration_seconds")) if music_active else None
        ratio = min(1., max(0., elapsed / duration)) if elapsed is not None and duration is not None and duration > 0 else None
        clean_track = _clean_track(track)
        # Unknown/duplicate slots and unbounded iterables are deliberately not
        # accepted. Thumbnail bytes never enter labels, keys, logs or outputs.
        if not isinstance(cards, (tuple, list)) or len(cards) > 4:
            raise ValueError("At most four explicit dashboard image cards are supported")
        card_by_key: dict[str, SpaceCard] = {}
        for card in cards:
            if not isinstance(card, SpaceCard) or card.key not in CARD_KEYS or card.key in card_by_key:
                raise ValueError("Unknown or duplicate dashboard image card")
            card_by_key[card.key] = card
        card_models = []
        for key in CARD_KEYS:
            card = card_by_key.get(key, SpaceCard(key, state="unavailable"))
            # Size-check before hashing or invoking Pillow. Use a fixed sentinel
            # for corrupt/oversized input so render loops stay bounded.
            payload = card.image if isinstance(card.image, bytes) and len(card.image) <= MAX_CARD_BYTES else b""
            digest = _image_digest(payload) if payload else b""
            observed_age = _age(card.observed_at, now)
            observed = _utc(card.observed_at) if observed_age is not None else None
            # NOAA valid-time forecasts are legitimately in the future. Do
            # not turn them into fake observations "hace 0 s", but do retain
            # their clearly labelled, bounded valid time. Other image sources
            # continue to reject dates more than 30 seconds into the future.
            forecast = _utc(card.observed_at) if key == "aurora" else None
            valid_forecast = forecast is not None and (forecast - now).total_seconds() <= 6 * 3600
            if valid_forecast:
                date_label = forecast.strftime("VÁLIDO %H:%M UTC")
                age_label = forecast.strftime("PRONÓSTICO VÁLIDO %d/%m %H:%M UTC")
            else:
                date_label = observed.strftime("%d/%m %H:%M") if observed else "SIN FECHA"
                age_label = _age_text(observed_age)
            if card.state == "stale":
                age_label = "ANTERIOR · " + age_label
            elif card.state == "unavailable" or not payload:
                age_label = "NO DISPONIBLE"
            credit = _public_text(card.credit, 22)
            card_models.append((key, digest, payload, date_label, age_label, credit))
        # Exclude continuously increasing FFmpeg frames and unrelated status,
        # URLs, errors, titles and credentials from the cache and image entirely.
        cache_key = (int(now.timestamp()), quality, source, source_note, lat, lon,
                     altitude, speed, age, track_name, ratio,
                     int(elapsed) if elapsed is not None and math.isfinite(elapsed) else None,
                     int(duration) if duration is not None and math.isfinite(duration) else None,
                     clean_track, tuple((k, digest, date, age_, credit) for k, digest, _, date, age_, credit in card_models))
        with self._lock:
            if cache_key == self._cache_key and self._cache is not None:
                return self._cache
            result = self._draw(now, quality, source, source_note, lat, lon, altitude, speed,
                                age, track_name, elapsed, duration, ratio, clean_track, card_models)
            self._cache_key, self._cache = cache_key, result
            self.render_count += 1
            return result

    def _draw(self, now, quality, source, source_note, lat, lon, altitude, speed,
              age, track_name, elapsed, duration, ratio, track, cards) -> DashboardFrame:
        image = Image.new("RGB", DEFAULT_SIZE, "#07111c")
        draw = ImageDraw.Draw(image)
        lines = []

        def text(x, y, value, size=14, fill="#e8f4fa", bold=False, max_width=None):
            font = _font(size, bold)
            if max_width is not None:
                while value and draw.textlength(value, font=font) > max_width:
                    value = value[:-2] + "…" if len(value) > 2 else ""
            draw.text((x, y), value, font=font, fill=fill)
            lines.append(value)

        draw.rectangle((0, 0, 1279, 2), fill="#277b94")
        for x in (326, 572, 944):
            draw.line((x, 12, x, 132), fill="#27404e", width=1)

        quality_label = {"fresh": "ACTUAL", "stale": "ANTERIOR", "unavailable": "SIN DATOS"}[quality]
        quality_color = "#85e0be" if quality == "fresh" else "#ffd08b"
        text(12, 9, "ASTROLEARNER / ISS", 14, bold=True)
        text(231, 11, quality_label, 11, quality_color)
        world = _world_background(302, 88).copy()
        world_draw = ImageDraw.Draw(world)
        if quality != "unavailable":
            previous = None
            for a, b in track:
                point = _xy(b, a, world.width, world.height)
                if previous is not None and abs(b - previous[0]) < 180:
                    world_draw.line((previous[1], point), fill="#4ed7e1", width=1)
                previous = (b, point)
            x, y = _xy(lon, lat, world.width, world.height)
            world_draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#ffffff", outline="#32d7e0", width=2)
        image.paste(world, (12, 32))
        world.close()
        text(12, 124, "Natural Earth · trayectoria reciente, no predicción", 9, "#97b1c0")

        text(341, 10, now.strftime("%d %b %Y  %H:%M:%S UTC"), 14, bold=True, max_width=220)
        if quality == "unavailable":
            text(341, 39, "Posición no disponible", 18, "#ffd08b", max_width=219)
            text(341, 69, "No se estima una ubicación", 12, "#a9c0cc")
            text(341, 91, "Esperando datos orbitales", 12, "#a9c0cc")
        else:
            text(341, 40, f"{lat:+.2f}°  /  {lon:+.2f}°", 19, max_width=220)
            alt = f"{altitude:.1f} km" if altitude is not None else "-- km"
            vel = f"{speed:,.0f} km/h" if speed is not None else "-- km/h"
            text(341, 72, f"{alt}   ·   {vel}", 15, max_width=220)
            text(341, 106, "Posición " + _age_text(age), 12, quality_color)

        source_color = "#85e0be" if source == "SEÑAL EXTERNA" else "#ffd08b"
        text(589, 9, source, 19, source_color, bold=True, max_width=338)
        text(589, 37, source_note, 11, "#a9c0cc", max_width=338)
        draw.line((589, 59, 927, 59), fill="#27404e")
        text(589, 68, "AHORA SUENA", 11, "#89cce1", bold=True)
        text(589, 88, track_name, 15, max_width=338)
        if ratio is not None:
            draw.rounded_rectangle((589, 115, 850, 121), radius=3, fill="#263b49")
            if ratio > 0:
                draw.rounded_rectangle((589, 115, 589 + max(1, int(261 * ratio)), 121), radius=3, fill="#5bbcc6")
            text(861, 109, f"{_duration(elapsed)} / {_duration(duration)}", 10, "#a9c0cc", max_width=68)
        else:
            text(589, 113, "Progreso pendiente de confirmar", 10, "#a9c0cc")

        text(958, 9, "IMÁGENES FECHADAS · UTC", 11, "#89cce1", bold=True)
        for index, (key, _, payload, date_label, age_label, credit) in enumerate(cards):
            x = 958 + index * 80
            title = "PRONÓSTICO" if key == "aurora" else _CARD_TITLES[key]
            text(x, 29, title, 10, "#e8f4fa", bold=True, max_width=75)
            thumbnail = _thumbnail(payload)
            if thumbnail is not None:
                with Image.open(io.BytesIO(thumbnail)) as thumb:
                    image.paste(thumb, (x, 45))
                text(x, 118, date_label, 7 if key == "aurora" else 8, "#bed1db", max_width=75)
            else:
                draw.rectangle((x, 45, x + 71, 116), fill="#0b1a28", outline="#27404e")
                text(x + 6, 72, "SIN DATOS", 9, "#a9c0cc", max_width=63)
                age_label = "NO DISPONIBLE"
            # Exact age is retained in text_lines for tests/API diagnostics; a
            # short visual cue preserves readability of the tiny source tiles.
            lines.append(f"{_CARD_TITLES[key]}: {age_label}")
            if age_label.startswith("ANTERIOR"):
                text(x, 128, "ANTERIOR", 8, "#ffd08b", max_width=75)
            else:
                text(x, 128, credit or ("NOAA" if key == "aurora" else ""), 8, "#97b1c0", max_width=75)

        if image.size != (self.width, self.height):
            resized = image.resize((self.width, self.height), Image.Resampling.LANCZOS)
            image.close()
            image = resized
        png, jpeg = io.BytesIO(), io.BytesIO()
        try:
            image.save(png, "PNG", compress_level=2)
            image.save(jpeg, "JPEG", quality=91, subsampling=0)
        finally:
            image.close()
        return DashboardFrame(png.getvalue(), jpeg.getvalue(), self.width, self.height,
                              quality, source, age, tuple(lines))


def render_dashboard(state: dict[str, Any], *, width: int = 1280, height: int = 144,
                     track: tuple = (), now: datetime | None = None,
                     cards: tuple[SpaceCard, ...] = ()) -> DashboardFrame:
    """Convenience helper; persistent encoders should keep a class instance."""
    result = StreamDashboard(width, height).render(state, track, now, cards)
    assert result is not None
    return result
