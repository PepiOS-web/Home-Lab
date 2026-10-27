"""Small cached NASA/NOAA HUD images, fetched separately from the live encoder.

Only fixed public endpoints are allowed. No API keys, redirects, cookies,
environment proxies or caller-supplied URLs are used. Observation/product dates
are never replaced with download time, and unavailable sources retain their
last good, explicitly stale thumbnail. This module does not publish a stream.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import urlsplit
import warnings

import httpx
from PIL import Image, ImageOps

from .stream_dashboard import SpaceCard

SUN_URL = "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_0304.jpg"
EARTH_METADATA_URL = "https://epic.gsfc.nasa.gov/api/natural"
AURORA_METADATA_URL = "https://services.swpc.noaa.gov/products/animations/ovation_north_24h.json"
MOON_PREFIX = "https://svs.gsfc.nasa.gov/vis/a000000/a005500/a005587/frames/216x216_1x1_30p/"
KEYS = ("sun", "earth", "moon", "aurora")
CREDITS = {"sun": "NASA SDO", "earth": "NASA EPIC", "moon": "NASA SVS · modelo", "aurora": "NOAA SWPC"}
POLL_SECONDS = 300.0
INTERVALS = {"sun": 900.0, "earth": 3600.0, "moon": 3600.0, "aurora": 300.0}
MAX_AGES = {"sun": 6 * 3600, "earth": 72 * 3600, "moon": 90 * 60, "aurora": 2 * 3600}
REQUEST_TIMEOUT_SECONDS = 8.0
# Leave one second for cancellation/transport cleanup inside the 50 s budget.
REFRESH_TIMEOUT_SECONDS = 49.0
MAX_JSON_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_777_216


class SourceError(ValueError):
    """Fixed diagnostic code only; never include response bodies or URLs."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _date(value: object, *, epic: bool = False) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            if not epic:
                return None
            parsed = parsed.replace(tzinfo=timezone.utc)  # EPIC documents UTC.
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def allowed_url(url: object) -> bool:
    if not isinstance(url, str) or len(url) > 250:
        return False
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.port is not None
                or parsed.netloc != parsed.hostname):
            return False
    except ValueError:
        return False
    if url in {SUN_URL, EARTH_METADATA_URL, AURORA_METADATA_URL}:
        return True
    if parsed.hostname == "epic.gsfc.nasa.gov":
        return re.fullmatch(r"/archive/natural/\d{4}/\d{2}/\d{2}/jpg/epic_1b_\d{14}\.jpg", parsed.path) is not None
    if parsed.hostname == "services.swpc.noaa.gov":
        return re.fullmatch(r"/images/animations/ovation/north/aurora_N_\d{4}-\d{2}-\d{2}_\d{4}\.(?:jpg|png)", parsed.path) is not None
    if url.startswith(MOON_PREFIX):
        match = re.fullmatch(r"moon\.(\d{4})\.jpg", url[len(MOON_PREFIX):])
        return match is not None and 1 <= int(match[1]) <= 8760
    return False


def moon_url(now: datetime) -> tuple[str, str]:
    now = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if now.year != 2026:
        raise SourceError("moon_year_unavailable")
    hour = int((now - datetime(2026, 1, 1, tzinfo=timezone.utc)).total_seconds() // 3600) + 1
    return f"{MOON_PREFIX}moon.{hour:04d}.jpg", now.isoformat()


def _thumbnail(data: bytes) -> bytes:
    if not isinstance(data, bytes) or not 4 <= len(data) <= MAX_IMAGE_BYTES:
        raise SourceError("image_size")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if (image.format not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1
                        or image.width < 1 or image.height < 1
                        or image.width * image.height > MAX_IMAGE_PIXELS):
                    raise SourceError("image_format")
                rgb = image.convert("RGB")
            fitted = ImageOps.contain(rgb, (512, 512), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            fitted.save(output, "JPEG", quality=85, optimize=True)
            payload = output.getvalue()
        if not 4 <= len(payload) <= MAX_IMAGE_BYTES:
            raise SourceError("thumbnail_size")
        return payload
    except SourceError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise SourceError("image_invalid") from None


class DashboardSources:
    """One background worker; snapshot() never performs network or disk I/O."""

    def __init__(self, cache_dir: Path, stop_event: threading.Event):
        self.cache_dir = Path(cache_dir)
        self.stop_event = stop_event
        self._lock = threading.Lock()
        self._cards = {key: SpaceCard(key, state="unavailable", credit=CREDITS[key]) for key in KEYS}
        self._file_dates: dict[str, str | None] = {key: None for key in KEYS}
        self._attempted = {key: -float("inf") for key in KEYS}
        self._load()

    def snapshot(self) -> tuple[SpaceCard, ...]:
        now = _utcnow()
        with self._lock:
            result = []
            for key in KEYS:
                card = self._cards[key]
                dated = _date(self._file_dates[key] if key == "sun" else card.observed_at)
                if card.image and dated is not None and (now - dated).total_seconds() > MAX_AGES[key]:
                    card = replace(card, state="stale")
                # The 2026 visualization must not survive into another year
                # as if it were the current Moon, including a cached picture.
                if key == "moon" and now.year != 2026:
                    card = SpaceCard(key, state="unavailable", credit=CREDITS[key])
                result.append(card)
            return tuple(result)

    async def _download(self, client: httpx.AsyncClient, url: str, *, is_json=False) -> tuple[bytes, str | None]:
        if self.stop_event.is_set():
            raise SourceError("stopped")
        if not allowed_url(url):
            raise SourceError("url_not_allowed")
        limit = MAX_JSON_BYTES if is_json else MAX_IMAGE_BYTES

        async def request():
            async with client.stream("GET", url, follow_redirects=False) as response:
                if response.status_code != 200:
                    raise SourceError("http_status")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media_type not in ({"application/json"} if is_json else {"image/jpeg", "image/png"}):
                    raise SourceError("content_type")
                declared = response.headers.get("content-length")
                if declared is not None and (not declared.isdecimal() or int(declared) > limit):
                    raise SourceError("content_size")
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    if self.stop_event.is_set():
                        raise SourceError("stopped")
                    payload.extend(chunk)
                    if len(payload) > limit:
                        raise SourceError("content_size")
                modified = None
                if "last-modified" in response.headers:
                    try:
                        date = parsedate_to_datetime(response.headers["last-modified"])
                        if date.tzinfo is not None and date <= _utcnow() + timedelta(minutes=5):
                            modified = date.astimezone(timezone.utc).isoformat()
                    except (ValueError, TypeError, OverflowError):
                        pass
                return bytes(payload), modified

        try:
            return await asyncio.wait_for(request(), timeout=REQUEST_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, httpx.HTTPError):
            raise SourceError("network_unavailable") from None

    async def _json(self, client, url):
        payload, _ = await self._download(client, url, is_json=True)
        try:
            result = json.loads(payload)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise SourceError("json_invalid") from None
        if not isinstance(result, list) or len(result) > 1000:
            raise SourceError("metadata_invalid")
        return result

    async def _fetch(self, client, key: str) -> tuple[SpaceCard, str | None]:
        observed, file_date = None, None
        if key == "sun":
            url = SUN_URL  # Last-Modified is file freshness, NOT observation UTC.
        elif key == "moon":
            url, observed = moon_url(_utcnow())
        elif key == "earth":
            choices = []
            for item in await self._json(client, EARTH_METADATA_URL):
                if not isinstance(item, dict):
                    continue
                date = _date(item.get("date"), epic=True)
                name = item.get("image")
                if (date is not None and date <= _utcnow() + timedelta(minutes=5)
                        and isinstance(name, str) and re.fullmatch(r"epic_1b_\d{14}", name)):
                    choices.append((date, name))
            if not choices:
                raise SourceError("metadata_invalid")
            date, name = max(choices)
            observed = date.isoformat()
            url = f"https://epic.gsfc.nasa.gov/archive/natural/{date:%Y/%m/%d}/jpg/{name}.jpg"
        elif key == "aurora":
            choices = []
            for item in await self._json(client, AURORA_METADATA_URL):
                if not isinstance(item, dict):
                    continue
                date, path = _date(item.get("time_tag")), item.get("url")
                if not isinstance(path, str) or not path.startswith("/images/animations/ovation/north/"):
                    continue
                candidate = "https://services.swpc.noaa.gov" + path
                if (date is not None and date <= _utcnow() + timedelta(hours=6) and allowed_url(candidate)
                        and re.search(rf"aurora_N_{date:%Y-%m-%d_%H%M}\.(?:jpg|png)$", path)):
                    choices.append((date, candidate))
            if not choices:
                raise SourceError("metadata_invalid")
            date, url = max(choices)
            observed = date.isoformat()
        else:
            raise SourceError("unknown_card")
        image, file_date = await self._download(client, url)
        return SpaceCard(key, _thumbnail(image), observed, credit=CREDITS[key]), file_date

    def _failed(self, key):
        with self._lock:
            card = self._cards[key]
            self._cards[key] = replace(card, state="stale" if card.image else "unavailable")

    async def _refresh_due(self):
        client = httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS), follow_redirects=False,
                                   trust_env=False, limits=httpx.Limits(max_connections=1))
        try:
            for key in KEYS:
                if self.stop_event.is_set():
                    break
                now = time.monotonic()
                if now - self._attempted[key] < INTERVALS[key]:
                    continue
                self._attempted[key] = now
                try:
                    card, file_date = await self._fetch(client, key)
                    if self.stop_event.is_set():
                        break
                    with self._lock:
                        self._cards[key], self._file_dates[key] = card, file_date
                    try:
                        self._persist(card, file_date)
                    except OSError:
                        pass  # Read-only/full cache must not affect the encoder.
                except asyncio.CancelledError:
                    self._failed(key)
                    raise
                except (SourceError, OSError, ValueError, TypeError, KeyError):
                    self._failed(key)
        finally:
            await asyncio.wait_for(client.aclose(), timeout=1.0)

    def run(self) -> None:
        async def cycle():
            await asyncio.wait_for(self._refresh_due(), timeout=REFRESH_TIMEOUT_SECONDS)

        while not self.stop_event.is_set():
            try:
                asyncio.run(cycle())
            except (TimeoutError, httpx.HTTPError, OSError, ValueError):
                pass  # Fixed state cards communicate failures; never log remote data.
            self.stop_event.wait(POLL_SECONDS)

    def _persist(self, card: SpaceCard, file_date: str | None):
        if self.cache_dir.is_symlink():
            raise OSError("cache_path_invalid")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        metadata = {"version": 1, "key": card.key, "observed_at": card.observed_at,
                    "file_updated_at": file_date, "sha256": hashlib.sha256(card.image).hexdigest()}
        for suffix, payload in ((".jpg", card.image), (".json", json.dumps(metadata).encode())):
            target = self.cache_dir / (card.key + suffix)
            if target.is_symlink():
                raise OSError("cache_path_invalid")
            name = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.cache_dir, prefix=card.key + "-", suffix=".tmp", delete=False) as output:
                    name = output.name
                    output.write(payload)
                os.replace(name, target)
            finally:
                if name is not None:
                    try:
                        Path(name).unlink(missing_ok=True)
                    except OSError:
                        pass

    def _load(self):
        if self.cache_dir.is_symlink():
            return
        for key in KEYS:
            try:
                path, meta_path = self.cache_dir / (key + ".jpg"), self.cache_dir / (key + ".json")
                if path.is_symlink() or meta_path.is_symlink() or path.stat().st_size > MAX_IMAGE_BYTES or meta_path.stat().st_size > 8192:
                    continue
                image, metadata = path.read_bytes(), json.loads(meta_path.read_bytes())
                if (not isinstance(metadata, dict) or metadata.get("version") != 1 or metadata.get("key") != key
                        or metadata.get("sha256") != hashlib.sha256(image).hexdigest()):
                    continue
                observed = metadata.get("observed_at")
                file_date = metadata.get("file_updated_at")
                if ((observed is not None and _date(observed) is None)
                        or (file_date is not None and _date(file_date) is None)):
                    continue
                self._cards[key] = SpaceCard(key, _thumbnail(image), observed, state="stale", credit=CREDITS[key])
                self._file_dates[key] = file_date
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                continue
