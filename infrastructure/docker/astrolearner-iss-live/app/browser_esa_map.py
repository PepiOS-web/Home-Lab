"""Read-only ESA tracker capture for the local, non-publishing staging test.

Public retransmission rights remain a separate operator prerequisite. The whole
official 625x365 viewport, including ESA's logo, is preserved: no cropping,
asset extraction or changes to the provider's DOM, JavaScript or attribution.
The supplied ephemeral browser context is reused; this never launches Chrome.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import math
import re
import time
from urllib.parse import urlsplit

if __package__:
    from .browser_snapshot import MAX_JPEG_BYTES, capture_jpeg
else:  # The isolated sidecar executes its modules from /opt/camera.
    from browser_snapshot import MAX_JPEG_BYTES, capture_jpeg

ESA_MAP_URL = "https://isstracker.spaceflight.esa.int/"
VIEWPORT = {"width": 625, "height": 365}
CAPTURE_INTERVAL_SECONDS = 5.0
PROGRESS_GRACE_SECONDS = 15.0
MAX_CLOCK_AGE_SECONDS = 120.0
NO_HEALTHY_TIMEOUT_SECONDS = 60.0
RETRY_SECONDS = 30.0
MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}

# Provider DOM is inspected but never changed. In particular an HTTP-200 error
# screen or its loading cover is not accepted as a working orbital tracker.
READ_MAP_STATE = """() => {
 const visible = el => {
  if (!el) return false;
  const style = getComputedStyle(el), rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' &&
   rect.width > 0 && rect.height > 0;
 };
 const canvas = document.querySelector('#isst_map');
 const logo = document.querySelector('#overlay img');
 return {
  url: location.href, title: document.title,
  canvas_width: canvas instanceof HTMLCanvasElement ? canvas.width : 0,
  canvas_height: canvas instanceof HTMLCanvasElement ? canvas.height : 0,
  canvas_visible: visible(canvas),
  logo_loaded: !!(logo && logo.complete && logo.naturalWidth > 0),
  cover_visible: visible(document.querySelector('#cover')),
  error_visible: visible(document.querySelector('#errMsg')),
  telemetry: ['#isst_lat','#isst_lon','#isst_alt','#isst_spd'].map(
   id => (document.querySelector(id)?.textContent || '').trim()),
  gmt: (document.querySelector('#isst_tim')?.textContent || '').trim()
 };
}"""

# Only our dedicated capture page receives a bounded JPEG argument. No provider
# text, URL, HTML, credentials or browser error is copied into that page.
SHOW_MAP = """async encoded => {
 const image = document.getElementById('esa-map');
 const wrapper = document.getElementById('esa-map-wrap');
 if (!image || !wrapper) return false;
 const sequence = (window.esaMapSequence || 0) + 1;
 window.esaMapSequence = sequence;
 image.src = 'data:image/jpeg;base64,' + encoded;
 try { await image.decode(); } catch (_) { return false; }
 if (window.esaMapSequence !== sequence) return false;
 window.esaMapUpdated = performance.now();
 wrapper.style.opacity = '1';
 return true;
}"""
HIDE_MAP = """() => {
 window.esaMapSequence = (window.esaMapSequence || 0) + 1;
 const wrapper = document.getElementById('esa-map-wrap');
 if (wrapper) wrapper.style.opacity = '0';
 window.esaMapUpdated = 0;
}"""


def is_esa_origin(url: object) -> bool:
    """Reject redirects, credentials and lookalike hosts outside the fixed origin."""
    if not isinstance(url, str) or any(ord(char) < 33 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and
                parsed.hostname == "isstracker.spaceflight.esa.int" and
                parsed.port in (None, 443) and
                parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def parse_esa_gmt(value: object) -> float | None:
    """Parse the provider's English GMT label without the process's locale."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    normalized = " ".join(value.split())
    match = re.fullmatch(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{4}),\s*(\d{2}):(\d{2}):(\d{2})", normalized)
    if not match or match[2] not in MONTHS:
        return None
    try:
        return datetime(int(match[3]), MONTHS[match[2]], int(match[1]),
                        int(match[4]), int(match[5]), int(match[6]),
                        tzinfo=timezone.utc).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def valid_map_dom(state: object) -> bool:
    if not isinstance(state, dict) or not is_esa_origin(state.get("url")):
        return False
    telemetry = state.get("telemetry")
    return (state.get("title") == "ESA ISS Tracker" and
            state.get("canvas_width") == 625 and
            state.get("canvas_height") in (312, 313) and
            state.get("canvas_visible") is True and
            state.get("logo_loaded") is True and
            state.get("cover_visible") is False and
            state.get("error_visible") is False and
            isinstance(telemetry, list) and len(telemetry) == 4 and
            all(isinstance(value, str) and 0 < len(value) <= 48 and
                any(character.isdecimal() for character in value)
                for value in telemetry))


class MapReadinessGate:
    """Require fresh UTC and observed forward progress, independently of video."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last_clock: float | None = None
        self.last_observation: float | None = None
        self.last_progress: float | None = None

    def observe(self, state: object, monotonic_now: float, utc_now: float) -> bool:
        clock = parse_esa_gmt(state.get("gmt")) if isinstance(state, dict) else None
        if (not valid_map_dom(state) or clock is None or
                not math.isfinite(monotonic_now) or not math.isfinite(utc_now) or
                abs(utc_now - clock) > MAX_CLOCK_AGE_SECONDS):
            self.reset()
            return False
        if (self.last_observation is not None and monotonic_now < self.last_observation) or (
                self.last_clock is not None and clock < self.last_clock):
            self.reset()
        previous = self.last_clock
        self.last_clock, self.last_observation = clock, monotonic_now
        if previous is None:
            return False
        if clock > previous:
            self.last_progress = monotonic_now
        return (self.last_progress is not None and
                monotonic_now - self.last_progress <= PROGRESS_GRACE_SECONDS)


async def _wait_with_stop(stop, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.25, remaining))


async def _hide(output_page, on_status) -> None:
    try:
        on_status(False)
    except Exception:
        pass
    try:
        await asyncio.wait_for(output_page.evaluate(HIDE_MAP), timeout=1.0)
    except Exception:
        pass


async def _close(session, page) -> None:
    for resource, method in ((session, "detach"), (page, "close")):
        if resource is not None:
            try:
                await asyncio.wait_for(getattr(resource, method)(), timeout=2.0)
            except Exception:
                pass


async def monitor_esa_map(context, output_page, on_status, stop) -> None:
    """Update a small host-page image; map failures never escape into video capture.

    Navigation, DOM inspection, screenshotting and cleanup all have deadlines.
    Cancellation is deliberately propagated after cleanup. The callback accepts
    only a boolean; neither private URLs nor remote error messages are exposed.
    """
    try:
        await _hide(output_page, on_status)
        while not stop.is_set():
            page, session = None, None
            last_healthy = time.monotonic()
            try:
                page = await asyncio.wait_for(context.new_page(), timeout=3.0)
                await asyncio.wait_for(page.set_viewport_size(VIEWPORT), timeout=1.0)
                await asyncio.wait_for(
                    page.goto(ESA_MAP_URL, wait_until="domcontentloaded", timeout=20000),
                    timeout=20.0,
                )
                if not is_esa_origin(page.url):
                    raise ValueError("Map navigation left the permitted origin")
                session = await asyncio.wait_for(context.new_cdp_session(page), timeout=3.0)
                gate, last_capture = MapReadinessGate(), -math.inf
                while not stop.is_set():
                    if not is_esa_origin(page.url):
                        raise ValueError("Map navigation left the permitted origin")
                    state = await asyncio.wait_for(page.evaluate(READ_MAP_STATE), timeout=1.0)
                    current = time.monotonic()
                    if gate.observe(state, current, time.time()):
                        if current - last_capture >= CAPTURE_INTERVAL_SECONDS:
                            jpeg = await capture_jpeg(session)
                            if not (isinstance(jpeg, bytes) and 4 <= len(jpeg) <= MAX_JPEG_BYTES
                                    and jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")):
                                raise ValueError("Map snapshot is not a bounded JPEG")
                            if not is_esa_origin(page.url):
                                raise ValueError("Map navigation left the permitted origin")
                            if stop.is_set():
                                break
                            shown = await asyncio.wait_for(output_page.evaluate(
                                SHOW_MAP, base64.b64encode(jpeg).decode("ascii")), timeout=1.0)
                            if shown is not True:
                                raise ValueError("Map snapshot could not be displayed")
                            last_healthy = last_capture = time.monotonic()
                            try:
                                on_status(True)
                            except Exception:
                                pass
                    else:
                        await _hide(output_page, on_status)
                    if time.monotonic() - last_healthy >= NO_HEALTHY_TIMEOUT_SECONDS:
                        raise TimeoutError("Map has no recent validated snapshot")
                    await _wait_with_stop(stop, 1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                await _hide(output_page, on_status)
            finally:
                await _close(session, page)
            if not stop.is_set():
                await _wait_with_stop(stop, RETRY_SECONDS)
    finally:
        await _hide(output_page, on_status)
