"""Read one fixed internal PNG endpoint; no browser tabs, OAuth or remote URLs."""
from __future__ import annotations

import asyncio
import base64
import struct
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

if __package__:
    from .browser_esa_map import HIDE_MAP, SHOW_MAP, _wait_with_stop
else:
    from browser_esa_map import HIDE_MAP, SHOW_MAP, _wait_with_stop

MAP_URLS = {"http://iss-live:8092/corner-map.png", "http://camera-staging:8092/corner-map.png"}
PRODUCTION_MAP_URL = "http://iss-live:8092/corner-map.png"
MAX_PNG_BYTES = 256 * 1024
SHOW_PNG = SHOW_MAP.replace("data:image/jpeg;base64,", "data:image/png;base64,")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Internal map redirects are forbidden")


def read_map(url: str) -> tuple[bytes, bool]:
    if url not in MAP_URLS:
        raise ValueError("Map URL is not an allowed internal endpoint")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(url, timeout=3) as response:
        if response.headers.get_content_type() != "image/png":
            raise ValueError("Map content type is not PNG")
        fresh = response.headers.get("X-ISS-Position-State") == "fresh"
        data = response.read(MAX_PNG_BYTES + 1)
    if (not 45 <= len(data) <= MAX_PNG_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n"
            or data[8:16] != b"\0\0\0\rIHDR" or struct.unpack(">II", data[16:24]) != (432, 304)
            or data[-12:] != b"\0\0\0\0IEND\xaeB`\x82"):
        raise ValueError("Map image is not a bounded orbital card")
    return data, fresh


async def monitor_local_map(output_page, on_status, stop, url: str = PRODUCTION_MAP_URL) -> None:
    try:
        while not stop.is_set():
            try:
                data, fresh = await asyncio.wait_for(asyncio.to_thread(read_map, url), timeout=4)
                if stop.is_set():
                    break
                shown = await asyncio.wait_for(output_page.evaluate(
                    SHOW_PNG, base64.b64encode(data).decode("ascii")), timeout=1)
                on_status(shown is True and fresh)
            except asyncio.CancelledError:
                raise
            except Exception:
                on_status(False)
                try:
                    await asyncio.wait_for(output_page.evaluate(HIDE_MAP), timeout=1)
                except Exception:
                    pass
            await _wait_with_stop(stop, 5)
    finally:
        on_status(False)
        try:
            await asyncio.wait_for(output_page.evaluate(HIDE_MAP), timeout=1)
        except Exception:
            pass
